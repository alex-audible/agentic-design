import io
import json
import os
import pickle
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

import pytest

from agentic_design.experiments import ExperimentStore, atomic_json
from agentic_design.jobs import JobService
from agentic_design.provider import run_agent
from agentic_design.runner import DesignRequest, build_command
from agentic_design.tools import ToolRegistry
from agentic_design.transport import SSHTransport


def config(tmp_path):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "target.pdb").write_text("ATOM\n")
    return {
        "repo_root": str(tmp_path),
        "ssh": {
            "execution_mode": "direct",
            "host": "user@host",
            "key_path": str(tmp_path / "key"),
            "remote_root": "/remote root",
            "python_bin": "/venv/python",
            "rfdiffusion_root": "/RF diffusion",
            "device": "cuda",
            "connect_timeout": 2,
            "command_timeout": 2,
        },
        "state": {
            "experiments_dir": "state/experiments",
            "jobs_dir": "state/jobs",
            "audit_dir": "state/audit",
            "results_dir": "results",
            "inputs_dir": "inputs",
            "examples_dir": "examples",
        },
        "limits": {
            "max_designs": 3,
            "max_agent_submissions": 1,
            "max_agent_turns": 4,
            "max_tool_calls_per_turn": 4,
            "max_transcript_bytes": 10000,
        },
        "provider": {
            "model": "fake",
            "base_url": "http://invalid",
            "api_key_env": "NO_KEY",
        },
    }


def test_experiment_approval_binds_spec_and_input_bytes(tmp_path):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "target.pdb").write_bytes(b"first")
    store = ExperimentStore(tmp_path / "experiments", inputs, 2)
    store.save({"name": "binder", "contigs": "[A1-2/0 4-5]", "input_pdb": "target.pdb"})
    approval = store.approve("binder")
    (inputs / "target.pdb").write_bytes(b"changed")
    assert store.require_approval("binder")["digest"] == approval["digest"]
    snapshot = tmp_path / "experiments" / "binder" / "input" / "target.pdb"
    assert snapshot.read_bytes() == b"first"
    payload = json.loads(
        (tmp_path / "experiments" / "binder" / "experiment.json").read_text()
    )
    payload["spec"]["contigs"] = "[9-9]"
    (tmp_path / "experiments" / "binder" / "experiment.json").write_text(
        json.dumps(payload)
    )
    with pytest.raises(ValueError, match="corrupt"):
        store.require_approval("binder")


@pytest.mark.parametrize("bad", ["../target.pdb", "/tmp/target.pdb"])
def test_input_path_cannot_escape(tmp_path, bad):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    store = ExperimentStore(tmp_path / "experiments", inputs)
    with pytest.raises(ValueError, match="relative path"):
        store.save({"name": "x", "contigs": "[2-2]", "input_pdb": bad})


class FakeTransport:
    calls = []

    def __init__(self, cfg):
        self.cfg = cfg

    def upload(self, local, remote):
        self.calls.append(("upload", remote, local.read_bytes()[:2]))

    def run(self, argv, **kwargs):
        self.calls.append(("run", argv))
        return SimpleNamespace(returncode=0, stdout="4242\n", stderr="")


def copy_package(tmp_path):
    source = Path(__file__).resolve().parents[1] / "src"
    shutil.copytree(source, tmp_path / "src")


def test_submission_requires_approval_and_is_idempotent(tmp_path):
    copy_package(tmp_path)
    cfg = config(tmp_path)
    service = JobService(cfg, FakeTransport)
    service.store.save({"name": "smoke", "contigs": "[4-4]"})
    with pytest.raises(PermissionError):
        service.submit("smoke", "same")
    service.store.approve("smoke")
    first = service.submit("smoke", "same")
    second = service.submit("smoke", "same")
    assert first["run_id"] == second["run_id"]
    assert first["state"] == "submitted"
    assert "<run-id>" not in " ".join(first["command"])
    assert first["ssh"]["host"] == "user@host"


def test_tool_errors_do_not_execute_unknown_or_malformed_calls(tmp_path):
    copy_package(tmp_path)
    registry = ToolRegistry(JobService(config(tmp_path), FakeTransport))
    assert json.loads(registry.safe_dispatch("does_not_exist", "{}"))["ok"] is False
    result = json.loads(
        registry.safe_dispatch("save_experiment", '{"description":"missing spec"}')
    )
    assert result["ok"] is False


def test_submission_attempt_limit_counts_ambiguous_side_effect():
    class ApprovedStore:
        def require_approval(self, experiment_id):
            return {"id": experiment_id}

    class AmbiguousService:
        store = ApprovedStore()

        def submit(self, experiment_id, key):
            raise RuntimeError("reply lost after launch")

    registry = ToolRegistry(AmbiguousService(), max_submissions=1)
    with pytest.raises(RuntimeError, match="reply lost"):
        registry.dispatch(
            "submit_experiment", {"experiment_id": "x", "submission_key": "one"}
        )
    with pytest.raises(PermissionError, match="limit"):
        registry.dispatch(
            "submit_experiment", {"experiment_id": "x", "submission_key": "two"}
        )


class FakeClient:
    def __init__(self):
        self.step = 0

    def complete(self, messages, tools):
        self.step += 1
        if self.step == 1:
            return {
                "role": "assistant",
                "content": None,
                "reasoning_details": {"kept": True},
                "tool_calls": [
                    {
                        "id": "a",
                        "type": "function",
                        "function": {"name": "list_examples", "arguments": "{}"},
                    },
                    {
                        "id": "b",
                        "type": "function",
                        "function": {"name": "unknown", "arguments": "{}"},
                    },
                ],
            }
        return {"role": "assistant", "content": "done"}


def test_agent_correlates_multiple_tools_and_audits(tmp_path):
    copy_package(tmp_path)
    cfg = config(tmp_path)
    (tmp_path / "examples").mkdir()
    registry = ToolRegistry(JobService(cfg, FakeTransport))
    result = run_agent(cfg, registry, "prepare", client=FakeClient())
    audit = json.loads(Path(result["audit"]).read_text())
    assert result["content"] == "done"
    assert [m["tool_call_id"] for m in audit["messages"] if m["role"] == "tool"] == [
        "a",
        "b",
    ]
    assert audit["messages"][2]["reasoning_details"] == {"kept": True}


class BadClient:
    def complete(self, messages, tools):
        return {
            "role": "assistant",
            "tool_calls": [
                {"id": "", "function": {"name": "submit_experiment", "arguments": "{}"}}
            ],
        }


def test_malformed_provider_call_is_rejected_and_audited(tmp_path):
    copy_package(tmp_path)
    cfg = config(tmp_path)
    registry = ToolRegistry(JobService(cfg, FakeTransport))
    with pytest.raises(RuntimeError, match="tool-call IDs"):
        run_agent(cfg, registry, "x", client=BadClient())
    audits = list((tmp_path / "state" / "audit").glob("*.json"))
    assert (
        len(audits) == 1
        and json.loads(audits[0].read_text())["error"]["type"] == "RuntimeError"
    )


def test_remote_command_keeps_posix_paths_on_windows_client():
    command = build_command(
        DesignRequest(name="x", contigs="[A1-2/0 3-4]", input_pdb="nested/target.pdb"),
        PurePosixPath("/remote root/jobs/x/outputs"),
        cfg={
            "rfdiffusion_root": "/RF diffusion",
            "python_bin": "/venv/python",
            "device": "cuda",
        },
        input_pdb=PurePosixPath("/remote root/jobs/x/input/nested/target.pdb"),
    )
    assert all("\\" not in item for item in command)
    assert command[1] == "/RF diffusion/scripts/run_inference.py"


@pytest.mark.parametrize("seed", [None, 42])
def test_staged_worker_executes_and_requires_named_pairs(tmp_path, seed):
    copy_package(tmp_path)
    fake_modules = tmp_path / "fake_modules"
    (fake_modules / "torch").mkdir(parents=True)
    (fake_modules / "torch" / "__init__.py").write_text(
        "class cuda:\n    @staticmethod\n    def is_available(): return True\n"
    )
    rf_root = tmp_path / "rf"
    (rf_root / "scripts").mkdir(parents=True)
    (rf_root / "scripts" / "run_inference.py").write_text(
        "import pickle, sys\n"
        "from pathlib import Path\n"
        "args=dict(x.split('=',1) for x in sys.argv[1:])\n"
        "prefix=Path(args['inference.output_prefix'])\n"
        "start=int(args.get('inference.design_startnum',0))\n"
        "for i in range(start,start+int(args['inference.num_designs'])):\n"
        " p=Path(str(prefix)+'_'+str(i)); p.with_suffix('.pdb').write_text('END\\n'); "
        " pickle.dump({'mask_1d':[True]*4,'config':{'contigmap':{'contigs':args['contigmap.contigs']}}},p.with_suffix('.trb').open('wb'))\n"
    )
    cfg = config(tmp_path)
    cfg["ssh"].update(
        {
            "rfdiffusion_root": str(rf_root),
            "python_bin": sys.executable,
            "device": "cuda",
        }
    )
    service = JobService(cfg, FakeTransport)
    experiment = service.store.save(
        {"name": "smoke", "contigs": "[4-4]", "num_designs": 1, "seed": seed}
    )
    staging = tmp_path / "staging"
    staging.mkdir()
    archive = service._archive(experiment, "worker-test", staging)
    job = tmp_path / "job"
    job.mkdir()
    with tarfile.open(archive, "r:gz") as bundle:
        extraction_options = (
            {"filter": "data"} if hasattr(tarfile, "data_filter") else {}
        )
        bundle.extractall(job, **extraction_options)
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join([str(fake_modules), str(job / "src")])
    completed = subprocess.run(
        [sys.executable, "-m", "agentic_design.remote_worker", "--job-dir", str(job)],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads((job / "worker-status.json").read_text())["pid"] > 0
    result = json.loads((job / "result.json").read_text())
    assert result["state"] == "completed" and result["success"] is True
    assert (job / "outputs" / f"smoke_{seed or 0}.trb").exists()
    run_id = "worker-test"
    atomic_json(service._manifest_path(run_id).with_name("experiment.json"), experiment)
    assert len(service._validate_collection(job, {"run_id": run_id})) == 1


class NetworkFailureTransport:
    def __init__(self, cfg):
        pass

    def run(self, argv, **kwargs):
        return SimpleNamespace(returncode=255, stdout="", stderr="network")


def test_status_network_failure_is_unknown_not_cached_failed(tmp_path):
    copy_package(tmp_path)
    cfg = config(tmp_path)
    service = JobService(cfg, NetworkFailureTransport)
    manifest = {
        "run_id": "job-1",
        "state": "submitted",
        "remote_dir": "/remote/job-1",
        "ssh": cfg["ssh"],
        "launcher_pid": "10",
    }
    service._write(manifest)
    assert service.status("job-1")["state"] == "unknown"
    assert service.load("job-1")["state"] == "unknown"


class CompletingTransport:
    def __init__(self, cfg):
        self.result_reads = 0

    def run(self, argv, **kwargs):
        if argv[0] == "cat" and argv[1].endswith("result.json"):
            self.result_reads += 1
            state = "running" if self.result_reads == 1 else "completed"
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps({"state": state, "success": state == "completed"}),
                stderr="",
            )
        if argv[0] == "cat":
            return SimpleNamespace(
                returncode=0, stdout=json.dumps({"pid": 99}), stderr=""
            )
        return SimpleNamespace(returncode=1, stdout="", stderr="dead")


def test_status_rereads_terminal_result_after_worker_exit(tmp_path):
    copy_package(tmp_path)
    cfg = config(tmp_path)
    service = JobService(cfg, CompletingTransport)
    service._write(
        {
            "run_id": "job-race",
            "state": "unknown",
            "error": "old network error",
            "remote_dir": "/remote/job-race",
            "ssh": cfg["ssh"],
        }
    )
    recovered = service.status("job-race")
    assert recovered["state"] == "completed"
    assert "error" not in recovered


def test_reserved_hydra_aliases_are_rejected():
    from agentic_design.cli import build_request

    for key in ("+inference", "++contigmap", "hydra", "inference"):
        if key == "+inference":
            spec = {"name": "x", "contigs": "[2-2]", key: {"num_designs": 99}}
        elif key == "++contigmap":
            spec = {"name": "x", "contigs": "[2-2]", key: {"contigs": "[9-9]"}}
        elif key == "hydra":
            spec = {"name": "x", "contigs": "[2-2]", "hydra": {"job": {"chdir": True}}}
        else:
            spec = {
                "name": "x",
                "contigs": "[2-2]",
                "inference": {"design_startnum": 7},
            }
        with pytest.raises(ValueError, match="reserved"):
            build_request(spec)


def test_empty_explicit_submission_key_is_rejected(tmp_path):
    copy_package(tmp_path)
    cfg = config(tmp_path)
    service = JobService(cfg, FakeTransport)
    service.store.save({"name": "empty-key", "contigs": "[4-4]"})
    service.store.approve("empty-key")
    with pytest.raises(ValueError, match="must not be empty"):
        service.submit("empty-key", "  ")


class ArchiveTransport:
    archive = b""

    def __init__(self, cfg):
        pass

    def run(self, argv, stdout=None, **kwargs):
        if stdout is not None:
            stdout.write(self.archive)
        return SimpleNamespace(returncode=0, stdout="", stderr="")


def output_archive(include_outputs=True):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz") as tf:
        result = json.dumps(
            {"state": "completed", "success": True, "skipped_existing": 0}
        ).encode()
        info = tarfile.TarInfo("result.json")
        info.size = len(result)
        tf.addfile(info, io.BytesIO(result))
        if include_outputs:
            pdb = b"END\n"
            info = tarfile.TarInfo("outputs/smoke_0.pdb")
            info.size = len(pdb)
            tf.addfile(info, io.BytesIO(pdb))
            trb = pickle.dumps(
                {"mask_1d": [True] * 4, "config": {"contigmap": {"contigs": "[4-4]"}}}
            )
            info = tarfile.TarInfo("outputs/smoke_0.trb")
            info.size = len(trb)
            tf.addfile(info, io.BytesIO(trb))
    return stream.getvalue()


def test_corrupt_collection_is_atomic_and_retryable(tmp_path):
    copy_package(tmp_path)
    cfg = config(tmp_path)
    service = JobService(cfg, ArchiveTransport)
    experiment = service.store.save({"name": "smoke", "contigs": "[4-4]"})
    manifest = {
        "run_id": "job-collect",
        "experiment_id": "smoke",
        "state": "completed",
        "remote_dir": "/remote/job",
        "ssh": cfg["ssh"],
    }
    service._write(manifest)
    atomic_json(
        service._manifest_path("job-collect").with_name("experiment.json"), experiment
    )
    ArchiveTransport.archive = output_archive(include_outputs=False)
    with pytest.raises(ValueError, match="incomplete"):
        service.collect("job-collect")
    assert not (service.results_root / "job-collect").exists()
    ArchiveTransport.archive = output_archive(include_outputs=True)
    collected = service.collect("job-collect")
    assert collected["designs"][0]["design"] == "smoke_0"
    # Existing collections are verified again instead of trusted blindly.
    (Path(collected["directory"]) / "outputs" / "smoke_0.pdb").unlink()
    with pytest.raises(ValueError, match="incomplete"):
        service.collect("job-collect")


def test_ssh_transport_quotes_one_remote_shell_boundary(tmp_path, monkeypatch):
    key = tmp_path / "id key"
    key.write_text("not a real key")
    seen = []

    def fake_run(command, **kwargs):
        seen.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    transport = SSHTransport(
        {
            "host": "user@example",
            "key_path": str(key),
            "remote_root": "/r",
            "python_bin": "/p",
            "rfdiffusion_root": "/rf",
        }
    )
    transport.run(["mkdir", "-p", "/remote path/$literal"])
    assert seen[0][0][-1] == "mkdir -p '/remote path/$literal'"
