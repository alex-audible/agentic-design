"""Co-scientist tools: the existing experiment service plus a simple notebook."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from .jobs import JobService
from .notebook import Notebook
from .tools import ToolRegistry


class ResearchService:
    def __init__(self, cfg: dict, service: JobService | None = None):
        self.service = service or JobService(cfg)
        self.registry = ToolRegistry(self.service, cfg["limits"].get("max_agent_submissions", 1))
        self.notebook = Notebook(Path(cfg["repo_root"]) / cfg["state"].get("notebook_dir", "research/campaigns"))

    def list_campaigns(self) -> list[dict]:
        """Find research campaigns to resume. Their notebooks survive new chats."""
        return self.notebook.list()

    def start_campaign(self, campaign_id: str, title: str, question: str) -> dict:
        """Start a notebook with a research question. Does not run an experiment."""
        return self.notebook.create(campaign_id, title, question)

    def read_notebook(self, campaign_id: str) -> dict:
        """Read the question, plans, tool results, and interpretations before continuing."""
        return self.notebook.read(campaign_id)

    def add_note(self, campaign_id: str, text: str, kind: str = "interpretation") -> dict:
        """Append an agent-authored hypothesis, interpretation, decision, or correction.

        This is commentary, not a measured result. Cite experiment/job IDs and
        distinguish observations, uncertainty, and proposed next steps.
        """
        if kind not in ("hypothesis", "interpretation", "decision", "correction"):
            raise ValueError("kind must be hypothesis, interpretation, decision, or correction")
        if not text.strip():
            raise ValueError("note must not be empty")
        return self.notebook.append(campaign_id, kind, text, {"source": "agent_note"})

    def list_inputs(self) -> list[dict]:
        """List PDB files already placed in the configured input directory."""
        return self.service.store.list_inputs()

    def list_examples(self) -> list[dict]:
        """Read working RFdiffusion example specifications."""
        return self.service.store.list_examples()

    def _experiments(self, campaign_id: str) -> dict:
        return {e["data"]["experiment"]["id"]: e["data"]["experiment"]
                for e in self.notebook.read(campaign_id)["entries"]
                if e["kind"] == "experiment_saved"}

    def _require_experiment(self, campaign_id: str, experiment_id: str) -> None:
        if experiment_id not in self._experiments(campaign_id):
            raise ValueError("experiment is not recorded in this campaign")

    def _require_job(self, campaign_id: str, run_id: str) -> None:
        self._require_experiment(campaign_id, self.service.load(run_id)["experiment_id"])

    @staticmethod
    def _public(value):
        # The job service's internal SSH settings include private key paths.
        if isinstance(value, dict):
            return {k: ResearchService._public(v) for k, v in value.items() if k != "ssh"}
        if isinstance(value, list):
            return [ResearchService._public(v) for v in value]
        return value

    def _call(self, campaign_id: str, action: str, arguments: dict):
        # Record intent before a side effect; keep the submission key even if a reply is lost.
        operation = uuid4().hex
        self.notebook.append(campaign_id, "tool_requested", action,
                             {"operation": operation, "arguments": arguments})
        try:
            # Reusing a submission key recovers the original job without spending
            # the session's submission allowance twice.
            existing = None
            if action == "submit_experiment":
                existing = next((j for j in self.service.list()
                                 if j.get("submission_key") == arguments["submission_key"]), None)
            if existing:
                if existing["experiment_id"] != arguments["experiment_id"]:
                    raise ValueError("submission key belongs to a different experiment")
                result = existing
            else:
                result = self.registry.dispatch(action, arguments)
            result = self._public(result)
        except Exception as exc:
            self.notebook.append(campaign_id, "tool_failed", action,
                                 {"operation": operation, "error": type(exc).__name__, "message": str(exc)})
            raise
        self.notebook.append(campaign_id, "tool_result", action,
                             {"operation": operation, "result": result})
        return result

    def save_experiment(self, campaign_id: str, spec: dict, purpose: str, evaluation: str) -> dict:
        """Save an immutable spec/input snapshot and record why it is being run and how to evaluate it.

        Reuse an existing ID only to recover the same saved experiment. For a new
        design, use a new ID. No approval or submission is performed here.
        """
        if not purpose.strip() or not evaluation.strip():
            raise ValueError("purpose and evaluation are required")
        spec = dict(spec)
        spec.setdefault("seed", 0)
        if spec["seed"] is None:
            raise ValueError("co-scientist experiments require an explicit integer seed")
        known = self._experiments(campaign_id)
        if spec.get("name") in known:
            record = known[spec["name"]]
            if record["spec"] != spec or record["description"] != purpose or record["evaluation"] != evaluation:
                raise ValueError("saved experiment differs; use a new experiment ID")
            return self.service.store.load(record["id"])
        record = self.service.store.save(spec, purpose, evaluation)
        if record["description"] != purpose or record["evaluation"] != evaluation:
            raise ValueError("existing experiment has different research notes; use a new experiment ID")
        self.notebook.append(campaign_id, "experiment_saved", purpose, {
            "experiment": record,
            "snapshot_directory": str(self.service.store._path(record["id"]).parent),
            "evaluation": evaluation,
            "design_seeds": list(range(spec["seed"], spec["seed"] + spec.get("num_designs", 1))),
        })
        return record

    def preview_experiment(self, campaign_id: str, experiment_id: str) -> dict:
        """Record the exact command preview for human review."""
        self._require_experiment(campaign_id, experiment_id)
        return self._call(campaign_id, "preview_experiment", {"experiment_id": experiment_id})

    def submit_experiment(self, campaign_id: str, experiment_id: str, submission_key: str) -> dict:
        """Submit a human-approved saved experiment. Reuse the key on retries.

        A new key intentionally repeats the same spec/input in a new job directory.
        Saved co-scientist specs include a starting seed. To sample new randomness,
        save a new experiment with a different seed and obtain approval for it.
        """
        self._require_experiment(campaign_id, experiment_id)
        return self._call(campaign_id, "submit_experiment", {
            "experiment_id": experiment_id, "submission_key": submission_key,
        })

    def list_jobs(self, campaign_id: str) -> list[dict]:
        """Find this campaign's jobs, including ones submitted from the human CLI."""
        experiments = self._experiments(campaign_id)
        return self._public([j for j in self.service.list() if j.get("experiment_id") in experiments])

    def job_status(self, campaign_id: str, run_id: str) -> dict:
        """Check and record job status. Completion alone does not validate a design."""
        self._require_job(campaign_id, run_id)
        return self._call(campaign_id, "job_status", {"run_id": run_id})

    def collect_job(self, campaign_id: str, run_id: str) -> dict:
        """Retrieve completed outputs, check fresh TRB/PDB pairs, and record their location."""
        self._require_job(campaign_id, run_id)
        return self._call(campaign_id, "collect_job", {"run_id": run_id})

    def inspect_results(self, campaign_id: str, run_id: str) -> list[dict]:
        """Record authoritative TRB summaries from collected results."""
        self._require_job(campaign_id, run_id)
        return self._call(campaign_id, "inspect_results", {"run_id": run_id})

    def validate_motif(self, campaign_id: str, run_id: str, reference_pdb: str) -> list[dict]:
        """Measure and record motif RMSD against the saved input snapshot."""
        self._require_job(campaign_id, run_id)
        return self._call(campaign_id, "validate_motif", {"run_id": run_id, "reference_pdb": reference_pdb})

    def validate_binder(self, campaign_id: str, run_id: str, reference_pdb: str, hotspot_res: str) -> list[dict]:
        """Record target preservation and hotspot contacts; these do not prove binding."""
        self._require_job(campaign_id, run_id)
        return self._call(campaign_id, "validate_binder", {
            "run_id": run_id, "reference_pdb": reference_pdb, "hotspot_res": hotspot_res,
        })
