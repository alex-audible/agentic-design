"""Opt-in test of the installed harness against a local fake model endpoint.

RUN_OPENCODE_SMOKE=1 python -m pytest tests/test_opencode.py -q
No provider credentials or remote experiment execution are used.
"""

import json
import os
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest
import yaml

from agentic_design.config import load_orchestrator


@pytest.mark.skipif(os.environ.get("RUN_OPENCODE_SMOKE") != "1", reason="requires installed OpenCode and localhost sockets")
def test_opencode_prepares_seeded_experiment_through_mcp(tmp_path):
    repo = Path(__file__).resolve().parents[1]
    cfg = load_orchestrator(repo / "config/orchestrator.yaml")
    cfg["state"] = {key: str(tmp_path / value) for key, value in cfg["state"].items()}
    cfg["provider"]["model"] = "offline-research-test"
    cfg["provider"]["api_key_env"] = "RESEARCH_TEST_KEY"
    requests = []
    actions = [
        ("research_start_campaign", {"campaign_id": "offline-pilot", "title": "Offline pilot", "question": "Does tool preparation work?"}),
        ("research_save_experiment", {"campaign_id": "offline-pilot", "spec": {"name": "offline-seeded", "contigs": "[4-4]", "seed": 123},
                                      "purpose": "Test harness wiring", "evaluation": "Inspect saved command, no scientific claim"}),
        ("research_preview_experiment", {"campaign_id": "offline-pilot", "experiment_id": "offline-seeded"}),
        ("research_read_notebook", {"campaign_id": "offline-pilot"}),
    ]

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(body)
            tools = {tool["function"]["name"] for tool in body.get("tools", [])}
            previous = sum(m["role"] == "tool" for m in body["messages"])
            delta = {"role": "assistant", "content": "Offline preparation complete."}
            reason = "stop"
            if "research_start_campaign" in tools and previous < len(actions):
                name, arguments = actions[previous]
                delta = {"role": "assistant", "tool_calls": [{"index": 0, "id": f"offline-{previous}", "type": "function",
                         "function": {"name": name, "arguments": json.dumps(arguments)}}]}
                reason = "tool_calls"
            base = {"id": "offline-completion", "created": 1, "model": "offline-research-test"}
            self.send_response(200)
            if body.get("stream"):
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                for choice in ({"index": 0, "delta": delta, "finish_reason": None},
                               {"index": 0, "delta": {}, "finish_reason": reason}):
                    self.wfile.write(("data: " + json.dumps({**base, "object": "chat.completion.chunk", "choices": [choice]}) + "\n\n").encode())
                self.wfile.write(b"data: [DONE]\n\n")
            else:
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({**base, "choices": [{"index": 0, "message": delta, "finish_reason": reason}]}).encode())

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    cfg["provider"]["base_url"] = f"http://127.0.0.1:{server.server_port}/v1"
    path = tmp_path / "orchestrator.yaml"
    path.write_text(yaml.safe_dump(cfg))
    environment = {**os.environ, "AGENTIC_DESIGN_CONFIG": str(path), "RESEARCH_TEST_KEY": "offline-fixture"}
    # Keep test conversations out of the user's real OpenCode history.
    for variable in ("XDG_DATA_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME"):
        environment[variable] = str(tmp_path / variable.lower())
    try:
        result = subprocess.run([sys.executable, str(repo / "scripts/co_scientist.py"), "run", "--format", "json",
                                 "Prepare an offline seeded experiment using research tools. Do not submit."],
                                env=environment, capture_output=True, text=True, timeout=55, cwd=repo)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    assert result.returncode == 0, result.stderr[-4000:]
    saved = Path(cfg["state"]["experiments_dir"]) / "offline-seeded/experiment.json"
    assert saved.exists(), result.stdout[-6000:] + result.stderr[-3000:]
    assert json.loads(saved.read_text())["spec"]["seed"] == 123
    assert not saved.with_name("approval.json").exists()
    assert not list(Path(cfg["state"]["jobs_dir"]).glob("*/job.json"))
    scientific = [r for r in requests if any(t["function"]["name"] == "research_save_experiment" for t in r.get("tools", []))]
    assert scientific
    for request in scientific:
        names = {t["function"]["name"] for t in request["tools"]}
        assert not {"bash", "apply_patch", "task", "edit", "write"} & names
        assert not any("approve" in name for name in names)
        assert request["provider"] == cfg["provider"]["parameters"]["provider"]
    notes = list((Path(cfg["state"]["notebook_dir"]) / "offline-pilot/entries").glob("*.json"))
    entries = [json.loads(p.read_text()) for p in notes]
    commands = [e["data"]["result"]["command"] for e in entries if e["kind"] == "tool_result" and e["text"] == "preview_experiment"]
    assert commands and "inference.design_startnum=123" in commands[0]
