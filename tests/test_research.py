"""Research records and seeded repetition, without a provider or compute host."""

import asyncio
import json
import os
import sys
import tarfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
import yaml

from agentic_design.cli import build_request
from agentic_design.jobs import JobService
from agentic_design.notebook import Notebook
from agentic_design.research import ResearchService
from agentic_design.runner import build_command
from test_orchestration import config, copy_package, FakeTransport


def research(tmp_path):
    copy_package(tmp_path)
    cfg = config(tmp_path)
    cfg["limits"]["max_agent_submissions"] = 2
    return ResearchService(cfg, JobService(cfg, FakeTransport)), cfg


def test_repetition_preserves_seed_input_and_notebook_after_restart(tmp_path):
    service, cfg = research(tmp_path)
    inputs = tmp_path / "inputs"
    inputs.mkdir(exist_ok=True)
    (inputs / "target.pdb").write_bytes(b"original input")
    service.start_campaign("pilot", "Pilot", "Does the motif survive?")
    spec = {"name": "motif", "contigs": "[A1-2/0 4-4]", "input_pdb": "target.pdb", "seed": 42, "num_designs": 2}
    record = service.save_experiment("pilot", spec, "Test preservation", "Measure motif RMSD")
    command = service.preview_experiment("pilot", "motif")["command"]
    assert "inference.deterministic=true" in command
    assert "inference.design_startnum=42" in command
    assert "seed=42" not in command
    with pytest.raises(PermissionError):
        service.submit_experiment("pilot", "motif", "first")
    service.service.store.approve("motif")  # external human action in this fixture
    (inputs / "target.pdb").write_bytes(b"changed original")
    first = service.submit_experiment("pilot", "motif", "first")
    second = service.submit_experiment("pilot", "motif", "repeat")
    assert first["run_id"] != second["run_id"]
    # Retrying a returned key is permitted even at the session limit.
    assert service.submit_experiment("pilot", "motif", "first")["run_id"] == first["run_id"]
    assert "ssh" not in first
    for run in (first, second):
        with tarfile.open(service.service._manifest_path(run["run_id"]).with_name("execution-bundle.tar.gz")) as archive:
            assert archive.extractfile("input/target.pdb").read() == b"original input"
            assert yaml.safe_load(archive.extractfile("experiment.yaml"))["seed"] == 42
    resumed = ResearchService(cfg, JobService(cfg, FakeTransport))
    assert len(resumed.list_jobs("pilot")) == 2
    notebook = resumed.read_notebook("pilot")
    saved = next(e for e in notebook["entries"] if e["kind"] == "experiment_saved")
    assert saved["data"]["experiment"]["digest"] == record["digest"]
    assert saved["data"]["design_seeds"] == [42, 43]
    assert any(e["kind"] == "tool_failed" for e in notebook["entries"])
    assert "Test preservation" in Path(notebook["notebook"]).read_text()


def test_default_seed_corrections_and_campaign_boundaries(tmp_path):
    service, cfg = research(tmp_path)
    service.start_campaign("one", "One", "Question one")
    service.start_campaign("two", "Two", "Question two")
    record = service.save_experiment("one", {"name": "x", "contigs": "[4-4]"}, "Pilot", "Check outputs")
    assert record["spec"]["seed"] == 0
    before = service.read_notebook("one")["entries"]
    service.add_note("one", "Earlier interpretation was inconclusive.", "correction")
    assert service.read_notebook("one")["entries"][:-1] == before
    with pytest.raises(ValueError, match="not recorded"):
        service.preview_experiment("two", "x")
    with pytest.raises(ValueError, match="new experiment ID"):
        service.save_experiment("one", {"name": "x", "contigs": "[4-4]"}, "Changed purpose", "Check outputs")
    with pytest.raises(ValueError):
        service.start_campaign("../outside", "No", "No")
    with pytest.raises(ValueError):
        service.add_note("one", "Invented number", "tool_result")


def test_parallel_notebook_notes_do_not_overwrite_entries(tmp_path):
    notebook = Notebook(tmp_path / "notes")
    notebook.create("pilot", "Pilot", "Question")
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda i: notebook.append("pilot", "interpretation", f"Note {i}"), range(12)))
    assert len(notebook.read("pilot")["entries"]) == 12


@pytest.mark.parametrize("seed", [-1, True, 0.5, "42", 2**32])
def test_invalid_seed_fails_before_submission(seed):
    with pytest.raises(ValueError, match="seed"):
        build_request({"name": "x", "contigs": "[4-4]", "seed": seed})


def test_seed_range_and_conflicting_overrides():
    with pytest.raises(ValueError, match="seed"):
        build_request({"name": "x", "contigs": "[4-4]", "seed": 2**32-1, "num_designs": 2})
    for key in ("inference.deterministic", "+inference.deterministic"):
        with pytest.raises(ValueError, match="conflicting"):
            build_request({"name": "x", "contigs": "[4-4]", "seed": 1, key: False})
    req = build_request({"name": "x", "contigs": "[4-4]", "seed": 7,
                         "inference": {"deterministic": True}})
    assert build_command(req, Path("/tmp/x")).count("inference.deterministic=true") == 1


def test_research_mcp_stdio_roundtrip(tmp_path):
    pytest.importorskip("mcp")
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    repo = Path(__file__).resolve().parents[1]
    cfg = config(tmp_path)
    # Absolute paths keep all fixture state out of the real research notebook.
    cfg["state"] = {key: str(tmp_path / value) for key, value in cfg["state"].items()}
    cfg["state"]["notebook_dir"] = str(tmp_path / "notebook")
    path = tmp_path / "orchestrator.yaml"
    path.write_text(yaml.safe_dump(cfg))

    async def exercise():
        params = StdioServerParameters(command=sys.executable, args=[str(repo / "agents/research.py")],
                                       env={**os.environ, "AGENTIC_DESIGN_CONFIG": str(path)})
        async with stdio_client(params) as streams:
            async with ClientSession(*streams) as session:
                await session.initialize()
                listing = await session.list_tools()
                names = {t.name for t in listing.tools}
                assert "save_experiment" in names and not any("approv" in name for name in names)
                assert "submit_experiment" in names
                started = await session.call_tool("start_campaign", {"campaign_id": "mcp-pilot", "title": "Pilot", "question": "Question"})
                assert not started.isError
                saved = await session.call_tool("save_experiment", {
                    "campaign_id": "mcp-pilot", "spec": {"name": "x", "contigs": "[4-4]", "seed": 73},
                    "purpose": "Transport test", "evaluation": "No scientific claim",
                })
                assert not saved.isError
                denied = await session.call_tool("submit_experiment", {
                    "campaign_id": "mcp-pilot", "experiment_id": "x", "submission_key": "unapproved",
                })
                assert denied.isError
                notebook = await session.call_tool("read_notebook", {"campaign_id": "mcp-pilot"})
                assert not notebook.isError
    asyncio.run(exercise())
    experiment = json.loads((tmp_path / "state/experiments/x/experiment.json").read_text())
    assert experiment["spec"]["seed"] == 73
    assert not (tmp_path / "state/experiments/x/approval.json").exists()
