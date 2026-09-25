"""Researcher CLI for experiments, durable jobs, and endpoint conversations."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from .config import load_orchestrator
from .jobs import JobService
from .provider import run_agent
from .tools import ToolRegistry
from .notebook import Notebook


def emit(value):
    print(json.dumps(value, indent=2, default=str))


def parser():
    ap = argparse.ArgumentParser(prog="agentic-design")
    ap.add_argument("--config")
    groups = ap.add_subparsers(dest="group", required=True)
    exp = groups.add_parser("experiment").add_subparsers(dest="action", required=True)
    create = exp.add_parser("create")
    create.add_argument("spec")
    create.add_argument("--description", default="")
    create.add_argument("--evaluation", default="")
    for action in ("show", "preview", "approve"):
        command = exp.add_parser(action)
        command.add_argument("experiment_id")
    exp.add_parser("list")
    exp.add_parser("inputs")
    exp.add_parser("examples")
    job = groups.add_parser("job").add_subparsers(dest="action", required=True)
    submit = job.add_parser("submit")
    submit.add_argument("experiment_id")
    submit.add_argument("--submission-key")
    for action in ("status", "collect"):
        command = job.add_parser(action)
        command.add_argument("run_id")
    job.add_parser("list")
    notebook = groups.add_parser("notebook").add_subparsers(dest="action", required=True)
    notebook.add_parser("list")
    notebook.add_parser("show").add_argument("campaign_id")
    agent = groups.add_parser("agent")
    agent.add_argument("prompt", nargs="?")
    agent.add_argument("--prompt-file")
    agent.add_argument("--resume-job")
    return ap


def main(argv=None):
    args = parser().parse_args(argv)
    cfg = load_orchestrator(args.config)
    service = JobService(cfg)
    if args.group == "experiment":
        if args.action == "create":
            emit(
                service.store.save(
                    yaml.safe_load(Path(args.spec).read_text()),
                    args.description,
                    args.evaluation,
                )
            )
        elif args.action == "show":
            emit(service.store.load(args.experiment_id))
        elif args.action == "preview":
            emit(service.preview(args.experiment_id))
        elif args.action == "approve":
            emit(service.store.approve(args.experiment_id))
        elif args.action == "list":
            emit(service.store.list())
        elif args.action == "inputs":
            emit(service.store.list_inputs())
        elif args.action == "examples":
            emit(service.store.list_examples())
    elif args.group == "job":
        if args.action == "submit":
            emit(service.submit(args.experiment_id, args.submission_key))
        elif args.action == "status":
            emit(service.status(args.run_id))
        elif args.action == "collect":
            emit(service.collect(args.run_id))
        elif args.action == "list":
            emit(service.list())
    elif args.group == "notebook":
        notebook = Notebook(Path(cfg["repo_root"]) / cfg["state"].get("notebook_dir", "research/campaigns"))
        emit(notebook.list() if args.action == "list" else notebook.read(args.campaign_id))
    else:
        if args.prompt and args.prompt_file:
            raise ValueError("use either a prompt argument or --prompt-file, not both")
        prompt = (
            Path(args.prompt_file).read_text()
            if args.prompt_file
            else (args.prompt or "Help me define an RFdiffusion experiment.")
        )
        prompt += (
            f"\nResume by checking job {args.resume_job}." if args.resume_job else ""
        )
        emit(
            run_agent(
                cfg,
                ToolRegistry(service, cfg["limits"].get("max_agent_submissions", 1)),
                prompt,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
