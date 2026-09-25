"""Durable direct-SSH RFdiffusion job lifecycle."""

from __future__ import annotations

import json
import re
import shutil
import tarfile
import tempfile
import time
import uuid
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path, PurePosixPath

import yaml

from .cli import build_request
from .experiments import ExperimentStore, atomic_json, now
from .runner import build_command
from .transport import SSHTransport
from .trb import summarize_dir


class JobService:
    def __init__(self, cfg: dict, transport_factory=SSHTransport):
        self.cfg = cfg
        if cfg.get("ssh", {}).get("execution_mode") != "direct":
            raise ValueError("only explicit ssh.execution_mode: direct is supported")
        state = cfg["state"]
        repo = Path(cfg["repo_root"])
        self.jobs_root = (repo / state["jobs_dir"]).resolve()
        self.results_root = (repo / state["results_dir"]).resolve()
        self.store = ExperimentStore(
            repo / state["experiments_dir"],
            repo / state["inputs_dir"],
            cfg["limits"]["max_designs"],
            repo / state.get("examples_dir", "demo-api"),
        )
        self.transport_factory = transport_factory
        self.jobs_root.mkdir(parents=True, exist_ok=True)
        self.results_root.mkdir(parents=True, exist_ok=True)

    def _manifest_path(self, run_id: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", run_id):
            raise ValueError("invalid run ID")
        return self.jobs_root / run_id / "job.json"

    def load(self, run_id: str) -> dict:
        path = self._manifest_path(run_id)
        if not path.exists():
            raise FileNotFoundError(f"unknown job: {run_id}")
        return json.loads(path.read_text())

    def _write(self, manifest: dict) -> None:
        atomic_json(self._manifest_path(manifest["run_id"]), manifest)

    def preview(self, experiment_id: str, remote_dir: str | None = None) -> dict:
        exp = self.store.load(experiment_id)
        ssh = self.cfg["ssh"]
        fake_job = (
            PurePosixPath(remote_dir)
            if remote_dir
            else PurePosixPath(ssh["remote_root"]) / "jobs" / "<run-id>"
        )
        request = build_request(exp["spec"])
        command = build_command(
            request,
            fake_job / "outputs",
            cfg={
                "rfdiffusion_root": ssh["rfdiffusion_root"],
                "python_bin": ssh["python_bin"],
                "device": ssh["device"],
            },
            input_pdb=fake_job / "input" / PurePosixPath(request.input_pdb)
            if request.input_pdb
            else None,
        )
        return {
            "experiment_id": experiment_id,
            "digest": exp["digest"],
            "command": command,
        }

    def _archive(self, exp: dict, run_id: str, directory: Path) -> Path:
        stage = directory / "stage"
        package = stage / "src" / "agentic_design"
        package.mkdir(parents=True)
        repo = Path(self.cfg["repo_root"])
        for name in (
            "__init__.py",
            "cli.py",
            "config.py",
            "experiments.py",
            "paths.py",
            "runner.py",
            "trb.py",
            "cpu_shim.py",
            "remote_worker.py",
        ):
            (package / name).write_bytes(
                (repo / "src" / "agentic_design" / name).read_bytes()
            )
        (stage / "experiment.yaml").write_text(
            yaml.safe_dump(exp["spec"], sort_keys=True)
        )
        ssh = self.cfg["ssh"]
        worker = {key: ssh[key] for key in ("python_bin", "rfdiffusion_root", "device")}
        (stage / "worker.json").write_text(json.dumps(worker, indent=2))
        request = build_request(exp["spec"])
        if request.input_pdb:
            input_dir = stage / "input"
            input_dir.mkdir()
            source = self.store._path(exp["id"]).parent / "input" / request.input_pdb
            target = input_dir / request.input_pdb
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
        archive = directory / f"{run_id}.tar.gz"
        with tarfile.open(archive, "w:gz") as tf:
            for child in sorted(stage.rglob("*")):
                tf.add(child, arcname=child.relative_to(stage), recursive=False)
        return archive

    def submit(self, experiment_id: str, submission_key: str | None = None) -> dict:
        exp = self.store.require_approval(experiment_id)
        if submission_key is not None and not submission_key.strip():
            raise ValueError("submission_key must not be empty")
        key = submission_key if submission_key is not None else str(uuid.uuid4())
        # Validate local SSH configuration before reserving an idempotency key.
        transport = self.transport_factory(self.cfg["ssh"])
        run_id = f"{experiment_id}-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:8]}"
        reservation_dir = (
            self.jobs_root / "_submissions" / sha256(key.encode()).hexdigest()
        )
        try:
            reservation_dir.mkdir(parents=True)
            reservation = {
                "submission_key": key,
                "experiment_id": experiment_id,
                "experiment_digest": exp["digest"],
                "run_id": run_id,
                "created_at": now(),
            }
            atomic_json(reservation_dir / "reservation.json", reservation)
        except FileExistsError:
            path = reservation_dir / "reservation.json"
            for _ in range(20):
                if path.exists():
                    break
                time.sleep(0.01)
            if not path.exists():
                raise RuntimeError(
                    "submission with this key is being prepared; retry status shortly"
                )
            reservation = json.loads(path.read_text())
            if reservation["experiment_digest"] != exp["digest"]:
                raise ValueError(
                    "submission key already belongs to another experiment digest"
                )
            manifest_path = self._manifest_path(reservation["run_id"])
            if manifest_path.exists():
                return json.loads(manifest_path.read_text())
            return {
                **reservation,
                "state": "unknown",
                "error": "submission was reserved but its local manifest is missing; do not resubmit with a new key",
            }
        remote_dir = str(
            PurePosixPath(self.cfg["ssh"]["remote_root"]) / "jobs" / run_id
        )
        manifest = {
            "run_id": run_id,
            "experiment_id": experiment_id,
            "experiment_digest": exp["digest"],
            "submission_key": key,
            "backend": "ssh-direct",
            "remote_dir": remote_dir,
            "state": "prepared",
            "created_at": now(),
            "command": self.preview(experiment_id, remote_dir)["command"],
            "ssh": dict(self.cfg["ssh"]),
        }
        self._write(manifest)
        atomic_json(self._manifest_path(run_id).with_name("experiment.json"), exp)
        request = build_request(exp["spec"])
        if request.input_pdb:
            source = self.store._path(exp["id"]).parent / "input" / request.input_pdb
            target = self._manifest_path(run_id).parent / "input" / request.input_pdb
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
        try:
            with tempfile.TemporaryDirectory() as temp:
                archive = self._archive(exp, run_id, Path(temp))
                # Keep the exact small worker/input bundle used for this run.
                shutil.copyfile(archive, self._manifest_path(run_id).with_name("execution-bundle.tar.gz"))
                transport.run(["mkdir", "-p", remote_dir])
                remote_archive = f"{remote_dir}/stage.tar.gz"
                transport.upload(archive, remote_archive)
                transport.run(["tar", "-xzf", remote_archive, "-C", remote_dir])
            python = manifest["ssh"]["python_bin"]
            # sh is needed only for detachment and $!; every dynamic value is quoted.
            import shlex

            script = (
                f"cd {shlex.quote(remote_dir)} && "
                f"PYTHONPATH={shlex.quote(remote_dir + '/src')} "
                f"nohup {shlex.quote(python)} -m agentic_design.remote_worker "
                f"--job-dir {shlex.quote(remote_dir)} > worker-bootstrap.log 2>&1 < /dev/null & echo $!"
            )
            result = transport.run(["sh", "-c", script])
            manifest.update(
                {
                    "state": "submitted",
                    "submitted_at": now(),
                    "launcher_pid": result.stdout.strip(),
                }
            )
        except Exception as exc:
            manifest.update(
                {
                    "state": "unknown",
                    "error": f"submission outcome is ambiguous for {run_id}: {exc}",
                    "updated_at": now(),
                }
            )
            self._write(manifest)
            return manifest
        self._write(manifest)
        return manifest

    def status(self, run_id: str) -> dict:
        manifest = self.load(run_id)
        if manifest["state"] in ("completed", "failed"):
            return manifest
        transport = self.transport_factory(manifest["ssh"])
        result_path = f"{manifest['remote_dir']}/result.json"
        probe = transport.run(["cat", result_path], check=False)
        if probe.returncode == 255:
            manifest.update(
                {
                    "state": "unknown",
                    "error": "SSH transport failed while reading job state",
                    "updated_at": now(),
                }
            )
            self._write(manifest)
            return manifest
        if probe.returncode == 0:
            try:
                result = json.loads(probe.stdout)
            except json.JSONDecodeError:
                manifest.update(
                    {
                        "state": "unknown",
                        "error": "remote result manifest is temporarily unreadable",
                        "updated_at": now(),
                    }
                )
                self._write(manifest)
                return manifest
            manifest.update(
                {"state": result["state"], "result": result, "updated_at": now()}
            )
            manifest.pop("error", None)
        if manifest["state"] not in ("completed", "failed"):
            pid_probe = transport.run(
                ["cat", f"{manifest['remote_dir']}/worker-status.json"], check=False
            )
            if pid_probe.returncode == 255:
                manifest.update(
                    {
                        "state": "unknown",
                        "error": "SSH transport failed while reconciling worker PID",
                        "updated_at": now(),
                    }
                )
                self._write(manifest)
                return manifest
            if pid_probe.returncode == 0:
                try:
                    manifest["pid"] = str(json.loads(pid_probe.stdout)["pid"])
                except (json.JSONDecodeError, KeyError):
                    pass
            worker_pid = manifest.get("pid")
            pid = worker_pid or manifest.get("launcher_pid")
            if not pid:
                manifest.update(
                    {
                        "state": "unknown",
                        "error": "remote worker PID is not available",
                        "updated_at": now(),
                    }
                )
                self._write(manifest)
                return manifest
            alive = transport.run(["kill", "-0", str(pid)], check=False)
            if alive.returncode == 255:
                manifest.update(
                    {
                        "state": "unknown",
                        "error": "SSH transport failed while probing worker",
                        "updated_at": now(),
                    }
                )
            elif alive.returncode != 0 and worker_pid:
                final_probe = transport.run(["cat", result_path], check=False)
                if final_probe.returncode == 0:
                    try:
                        final_result = json.loads(final_probe.stdout)
                    except json.JSONDecodeError:
                        final_result = None
                    if final_result and final_result.get("state") in (
                        "completed",
                        "failed",
                    ):
                        manifest.update(
                            {
                                "state": final_result["state"],
                                "result": final_result,
                                "updated_at": now(),
                            }
                        )
                        manifest.pop("error", None)
                    else:
                        manifest.update(
                            {
                                "state": "unknown",
                                "error": "worker exited while its terminal result was still being reconciled",
                                "updated_at": now(),
                            }
                        )
                elif final_probe.returncode == 255:
                    manifest.update(
                        {
                            "state": "unknown",
                            "error": "SSH transport failed during terminal result reconciliation",
                            "updated_at": now(),
                        }
                    )
                else:
                    manifest.update(
                        {
                            "state": "failed",
                            "error": "remote worker exited without a terminal result manifest",
                            "updated_at": now(),
                        }
                    )
            elif alive.returncode != 0:
                manifest.update(
                    {
                        "state": "unknown",
                        "error": "launcher exited before the worker PID was reconciled",
                        "updated_at": now(),
                    }
                )
            else:
                manifest.update({"state": "running", "updated_at": now()})
                manifest.pop("error", None)
        self._write(manifest)
        return manifest

    def collect(self, run_id: str) -> dict:
        manifest = self.status(run_id)
        if manifest["state"] != "completed":
            raise RuntimeError(f"job is not complete (state={manifest['state']})")
        destination = self.results_root / run_id
        if not destination.exists():
            temporary = Path(
                tempfile.mkdtemp(prefix=f".{run_id}-", dir=self.results_root)
            )
            archive = temporary / "collected.tar.gz"
            transport = self.transport_factory(manifest["ssh"])
            with archive.open("wb") as output:
                transport.run(
                    [
                        "tar",
                        "-czf",
                        "-",
                        "-C",
                        manifest["remote_dir"],
                        "result.json",
                        "outputs",
                    ],
                    stdout=output,
                )
            try:
                with tarfile.open(archive, "r:gz") as tf:
                    for member in tf.getmembers():
                        target = (temporary / member.name).resolve()
                        if temporary not in target.parents and target != temporary:
                            raise ValueError("remote archive contains an unsafe path")
                        if not (member.isfile() or member.isdir()):
                            raise ValueError(
                                "remote archive contains a non-regular entry"
                            )
                        if member.isdir():
                            target.mkdir(parents=True, exist_ok=True)
                        else:
                            target.parent.mkdir(parents=True, exist_ok=True)
                            source = tf.extractfile(member)
                            if source is None:
                                raise ValueError("could not read archive member")
                            with target.open("wb") as output:
                                output.write(source.read())
                archive.unlink()
                self._validate_collection(temporary, manifest)
                temporary.replace(destination)
            except Exception:
                shutil.rmtree(temporary, ignore_errors=True)
                raise
        designs = self._validate_collection(destination, manifest)
        manifest.update({"collected_at": now(), "local_dir": str(destination)})
        self._write(manifest)
        return {"run_id": run_id, "directory": str(destination), "designs": designs}

    def _validate_collection(self, destination: Path, manifest: dict) -> list[dict]:
        result = json.loads((destination / "result.json").read_text())
        if (
            result.get("state") != "completed"
            or not result.get("success")
            or result.get("skipped_existing")
        ):
            raise ValueError(
                "remote result manifest does not record a fresh successful run"
            )
        designs = summarize_dir(destination / "outputs")
        snapshot = json.loads(
            self._manifest_path(manifest["run_id"])
            .with_name("experiment.json")
            .read_text()
        )
        request = build_request(snapshot["spec"])
        first_index = request.seed if request.seed is not None else 0
        expected_stems = {
            f"{request.name}_{index}" for index in range(first_index, first_index + request.num_designs)
        }
        output_dir = destination / "outputs"
        trbs = {path.stem for path in output_dir.glob("*.trb")}
        pdbs = {path.stem for path in output_dir.glob("*.pdb")}
        if (
            trbs != expected_stems
            or pdbs != expected_stems
            or len(designs) != request.num_designs
        ):
            raise ValueError(
                f"collected output is incomplete: expected {request.num_designs} named TRB/PDB pairs"
            )
        return designs

    def verified_outputs(self, run_id: str) -> tuple[dict, Path, list[dict]]:
        manifest = self.load(run_id)
        if not manifest.get("local_dir"):
            raise ValueError("job has not been collected")
        destination = Path(manifest["local_dir"])
        designs = self._validate_collection(destination, manifest)
        return manifest, destination / "outputs", designs

    def experiment_snapshot(self, run_id: str) -> tuple[dict, Path]:
        path = self._manifest_path(run_id).with_name("experiment.json")
        record = json.loads(path.read_text())
        return record, self._manifest_path(run_id).parent / "input"

    def list(self) -> list[dict]:
        return [
            json.loads(path.read_text())
            for path in sorted(self.jobs_root.glob("*/job.json"))
        ]
