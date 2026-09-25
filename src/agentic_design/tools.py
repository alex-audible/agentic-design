"""Shared, validated tools used by both the endpoint driver and MCP adapter."""

from __future__ import annotations

import json
from pathlib import Path

from .cli import build_request
from .jobs import JobService
from .validate import check_binder, check_motif

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "list_inputs",
            "description": "List PDB inputs available for experiments.",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_experiments",
            "description": "List saved experiment snapshots.",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_examples",
            "description": "List canonical example RFdiffusion specs that can be adapted.",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_experiment",
            "description": "Validate and save an immutable RFdiffusion experiment. Example spec: {name: ubq_binder, input_pdb: 1UBQ_clean.pdb, contigs: '[A1-76/0 50-65]', hotspot_res: '[A8,A44,A70]', num_designs: 1, diffuser_T: 20}.",
            "parameters": {
                "type": "object",
                "required": ["spec"],
                "properties": {
                    "spec": {
                        "type": "object",
                        "required": ["name", "contigs"],
                        "properties": {
                            "name": {"type": "string"},
                            "contigs": {"type": "string"},
                            "num_designs": {"type": "integer"},
                            "diffuser_T": {"type": "integer"},
                            "input_pdb": {"type": "string"},
                            "hotspot_res": {"type": "string"},
                            "seed": {"type": "integer"},
                        },
                        "additionalProperties": True,
                    },
                    "description": {"type": "string"},
                    "evaluation": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "preview_experiment",
            "description": "Show the exact remote RFdiffusion command for an experiment.",
            "parameters": {
                "type": "object",
                "required": ["experiment_id"],
                "properties": {"experiment_id": {"type": "string"}},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "submit_experiment",
            "description": "Submit an experiment previously approved at the human CLI. Cannot grant approval.",
            "parameters": {
                "type": "object",
                "required": ["experiment_id", "submission_key"],
                "properties": {
                    "experiment_id": {"type": "string"},
                    "submission_key": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "job_status",
            "description": "Get durable remote job state.",
            "parameters": {
                "type": "object",
                "required": ["run_id"],
                "properties": {"run_id": {"type": "string"}},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "collect_job",
            "description": "Collect and verify outputs for a completed job.",
            "parameters": {
                "type": "object",
                "required": ["run_id"],
                "properties": {"run_id": {"type": "string"}},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "inspect_results",
            "description": "Read authoritative TRB summaries from collected job outputs.",
            "parameters": {
                "type": "object",
                "required": ["run_id"],
                "properties": {"run_id": {"type": "string"}},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "validate_motif",
            "description": "Measure motif backbone RMSD for a collected job.",
            "parameters": {
                "type": "object",
                "required": ["run_id", "reference_pdb"],
                "properties": {
                    "run_id": {"type": "string"},
                    "reference_pdb": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "validate_binder",
            "description": "Measure target preservation and hotspot contacts for a collected binder job.",
            "parameters": {
                "type": "object",
                "required": ["run_id", "reference_pdb", "hotspot_res"],
                "properties": {
                    "run_id": {"type": "string"},
                    "reference_pdb": {"type": "string"},
                    "hotspot_res": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
    },
]

SCHEMAS = {
    item["function"]["name"]: item["function"]["parameters"] for item in TOOL_SCHEMAS
}


def _validate(schema: dict, value: dict) -> None:
    if not isinstance(value, dict):
        raise ValueError("tool arguments must be an object")
    required = schema.get("required", [])
    missing = [key for key in required if key not in value]
    if missing:
        raise ValueError(f"missing required arguments: {', '.join(missing)}")
    extra = set(value) - set(schema.get("properties", {}))
    if extra and schema.get("additionalProperties") is False:
        raise ValueError(f"unknown arguments: {', '.join(sorted(extra))}")
    types = {"string": str, "object": dict, "integer": int}
    for key, item in value.items():
        child = schema.get("properties", {}).get(key, {})
        expected = child.get("type")
        if expected and (
            not isinstance(item, types[expected])
            or (expected == "integer" and isinstance(item, bool))
        ):
            raise ValueError(f"{key} must be a {expected}")
        if expected == "object":
            _validate(child, item)


class ToolRegistry:
    def __init__(self, service: JobService, max_submissions: int = 1):
        self.service, self.max_submissions, self.submissions = (
            service,
            max_submissions,
            0,
        )

    def dispatch(self, name: str, arguments: dict) -> dict | list:
        if name not in SCHEMAS:
            raise ValueError(f"unknown tool: {name}")
        _validate(SCHEMAS[name], arguments)
        if name == "list_inputs":
            return self.service.store.list_inputs()
        if name == "list_experiments":
            return self.service.store.list()
        if name == "list_examples":
            return self.service.store.list_examples()
        if name == "save_experiment":
            return self.service.store.save(
                arguments["spec"],
                arguments.get("description", ""),
                arguments.get("evaluation", ""),
            )
        if name == "preview_experiment":
            return self.service.preview(arguments["experiment_id"])
        if name == "submit_experiment":
            if self.submissions >= self.max_submissions:
                raise PermissionError("agent submission limit reached")
            self.service.store.require_approval(arguments["experiment_id"])
            self.submissions += 1
            return self.service.submit(
                arguments["experiment_id"], arguments["submission_key"]
            )
        if name == "job_status":
            return self.service.status(arguments["run_id"])
        if name == "collect_job":
            return self.service.collect(arguments["run_id"])
        if name == "inspect_results":
            _, _, designs = self.service.verified_outputs(arguments["run_id"])
            return designs
        if name in ("validate_motif", "validate_binder"):
            _, outputs, _ = self.service.verified_outputs(arguments["run_id"])
            experiment, inputs = self.service.experiment_snapshot(arguments["run_id"])
            requested = Path(arguments["reference_pdb"])
            if requested.is_absolute() or ".." in requested.parts:
                raise ValueError("reference_pdb must name the approved input snapshot")
            ref = (inputs / requested).resolve()
            if inputs.resolve() not in ref.parents or not ref.is_file():
                raise ValueError("reference_pdb must name the approved input snapshot")
            expected = build_request(experiment["spec"]).input_pdb
            if expected != requested.as_posix():
                raise ValueError(
                    "reference_pdb does not match the experiment input snapshot"
                )
            if name == "validate_motif":
                return [
                    check_motif(p, p.with_suffix(".pdb"), ref)
                    for p in sorted(outputs.glob("*.trb"))
                ]
            return [
                check_binder(p, ref, arguments["hotspot_res"])
                for p in sorted(outputs.glob("*.pdb"))
            ]
        raise AssertionError(name)

    def safe_dispatch(self, name: str, raw_arguments: str) -> str:
        try:
            args = json.loads(raw_arguments)
            return json.dumps(
                {"ok": True, "result": self.dispatch(name, args)}, default=str
            )
        except Exception as exc:
            return json.dumps(
                {"ok": False, "error": type(exc).__name__, "message": str(exc)}
            )
