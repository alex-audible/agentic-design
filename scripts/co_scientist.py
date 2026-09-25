#!/usr/bin/env python3
"""Launch the pinned OpenCode install with the local research MCP server."""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    python = ROOT / ".venv-research" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python.exists():
        raise SystemExit("Run setup from docs/co-scientist.md first (.venv-research is missing).")
    # Use the environment containing the project's dependencies, even if invoked
    # with the operating system's Python.
    if sys.prefix != str(ROOT / ".venv-research"):
        return subprocess.call([str(python), str(Path(__file__).resolve()), *sys.argv[1:]])
    sys.path.insert(0, str(ROOT / "src"))
    from agentic_design.config import load_orchestrator
    cfg = load_orchestrator(os.environ.get("AGENTIC_DESIGN_CONFIG"))
    binary = ROOT / "harness/node_modules/.bin" / ("opencode.cmd" if os.name == "nt" else "opencode")
    if not binary.exists():
        raise SystemExit("OpenCode is missing. Run: npm ci --prefix harness")
    config = json.loads((ROOT / "opencode.json").read_text())
    config["mcp"] = {"research": {
        "type": "local", "command": [str(python), str(ROOT / "agents/research.py")],
        "enabled": True, "timeout": 120000,
    }}
    # Credentials remain environment references, never serialized key values.
    provider = cfg["provider"]
    model = provider["model"]
    config["model"] = f"research-endpoint/{model}"
    config["provider"] = {"research-endpoint": {
        "npm": "@ai-sdk/openai-compatible", "name": "Research model endpoint",
        "options": {"baseURL": provider["base_url"],
                    "apiKey": "{env:" + provider.get("api_key_env", "OPENROUTER_API_KEY") + "}"},
        "models": {model: {"name": model, "options": provider.get("parameters", {})}},
    }}
    environment = dict(os.environ)
    environment["OPENCODE_CONFIG_CONTENT"] = json.dumps(config)
    # Pin the default behavior; no external plugins are needed for this profile.
    return subprocess.call([str(binary), "--pure", *sys.argv[1:]], cwd=ROOT, env=environment)


if __name__ == "__main__":
    raise SystemExit(main())
