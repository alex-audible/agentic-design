# agentic-design

A reusable framework for automating protein binder design against a target PDB,
built on RFdiffusion. Experiments execute on a remote CPU VM.

**For current status, open tasks, and next steps, read [docs/handoff.md](docs/handoff.md).**
This file holds only what stays true between sessions.

## Co-scientist interface

`./co-scientist` launches the pinned OpenCode research profile via
`agents/research.py`. `src/agentic_design/research.py` adds a simple file-based
notebook to the existing experiment tools. Read [docs/co-scientist.md](docs/co-scientist.md)
for launch, approval, and replication instructions. Keep this first version simple:
campaign questions, append-only entries, and a generated Markdown view.

Co-scientist specs require an explicit `seed` (default 0). RFdiffusion's design
index is also its deterministic seed, so both the runner and collection checks
must use `seed + i` for output names. Preserve the original input snapshots when
repeating a saved experiment. Never claim bitwise replication across changed
software, weights, or hardware.

## Goals

Build a **reusable framework that automates designing high-quality proteins that
bind to a given target PDB**, with experiments executing on a remote VM.

Three horizons, deliberately ordered:

1. **Test the framework** — prove it runs end to end.
2. **Extract what is reusable** from that run.
3. **Make it drivable by any AI** over an OpenAI-compatible endpoint. Claude is
   the first driver; `agents/tools.py` (an MCP server) is the intended seam.

The reusable framework is the deliverable; an experiment is the forcing function
that proves it.

**Ordering matters.** Extraction comes *after* a working run, never before. Do
not build the generic multi-backend abstraction ahead of evidence — three of the
four defects found so far were invisible until something actually ran.

## Environment

RFdiffusion jobs run on the execution machine, not locally. The orchestration
client supports Windows cmd and WSL2 with Python 3.10+ and OpenSSH; it does not
need a GPU, torch, or rsync. Mocked/unit tests can run on the client; real
RFdiffusion integration tests require the execution machine.

**The API/job service reads `config/orchestrator.yaml` plus gitignored
`config/orchestrator.local.yaml`.** This config holds the endpoint/model, SSH
host/key path, installation paths, and limits. API keys are read from environment
variables. The legacy `env/sync.sh` workflow still reads gitignored `project.env`
(copy `project.env.example`). Authentication is SSH key only.

Do not take connection details from `~/.ssh/config`. Its entries for this
project are stale: one is a rebuilt host that fails key verification, another
times out, and the correct host is not listed there at all.

RFdiffusion, its venv (Python 3.10.12), and ~3.7 GB of checkpoints live under
`/mnt/src/`. The repo deploys to `$REMOTE_ROOT`.

## Commands

```bash
bash env/sync.sh push                                  # local tree -> VM
bash env/sync.sh run config/runs/<spec>.yaml           # execute on the VM
bash env/sync.sh run config/runs/<spec>.yaml --dry-run # print command only
bash env/sync.sh progress <run>                        # status of a running job
bash env/sync.sh watch <run>                           # follow its log
bash env/sync.sh pull                                  # results -> ./results
bash env/sync.sh test                                  # run the test suite on the VM
```

Run mocked/unit tests with `python -m pytest tests -q` after installing `.[test]`.
For tests on the VM through the legacy workflow, `push` first. The new reviewed
API/job workflow is documented in `demo-api/README.md`.

## Architecture

```
config/runs/*.yaml   declarative run specs, one per job type
      |
   cli.py            build_request(): named fields + nested blocks -> Hydra overrides
      |
 runner.py           build_command()  PURE, testable, no execution
                     run_design()     executes, streams log, summarizes
      |
   trb.py            parse .trb — the authoritative record of what was designed
validate.py          motif backbone RMSD (Kabsch) — verification, not reporting
      |
agents/tools.py      MCP adapter: save / preview / submit / status / validate
```

**Execution model.** `app.py` is the researcher CLI. `provider.py` drives a
bounded Chat Completions tool loop; `tools.py` is shared with the MCP adapter.
`experiments.py` saves immutable specs/input snapshots and human approval.
`jobs.py` dispatches detached SSH workers, with one isolated directory per job;
`transport.py` owns SSH quoting and `remote_worker.py` runs the existing local
runner. `build_command()` remains the pure construction seam. No manual sync is
needed for this path. The legacy YAML CLI and `sync.sh` remain for local execution
on the VM; they are not the endpoint orchestration workflow.

Use POSIX paths for remote commands even on Windows. Contig strings contain
spaces/brackets and must remain one argument across the SSH shell boundary.
Retrieve outputs before local TRB inspection. Never infer success from a
scheduler/process exit alone. Do not add a model-accessible approval tool.

## Invariants

- **`build_command()` stays pure.** It constructs the RFdiffusion invocation;
  `run_design()` executes it. That separation is what keeps the execution target
  swappable — the remote job service depends on it. Keep execution concerns out.
- **Workarounds live in this repo, never as edits to the RFdiffusion checkout
  under `/mnt/src`.** A previous session hand-ran a target-prep step that was
  never captured; it had to be reconstructed from the output file. Anything done
  to make a run work belongs in version control.
- **GPU is the default and failures are loud.** `config/paths.yaml` sets
  `device: cuda` and a run aborts if no GPU is visible, rather than silently
  running 50-100x slower. CPU is an explicit opt-in in `config/paths.local.yaml`
  (gitignored), or `ssh.device: cpu` in `config/orchestrator.local.yaml` for
  the job service. Both enable `cpu_shim`.
- **Trust the `.trb`, not the PDB text and not the exit code.** The `.trb` is the
  authoritative record of what was designed.
- **A backbone that has not been refolded and checked is not a candidate.**

## Failure modes that present as success

Exit code 0 means little here. Of the four defects found so far, three looked
like success:

1. **Cautious mode silently skips.** RFdiffusion refuses to overwrite an existing
   output PDB — it logs `(cautious mode) Skipping this design`, exits 0, and the
   stale designs can look fresh. The runner now requires fresh TRB/PDB pairs
   and zero skips. Use a new job directory for a new run; preserve prior logs.
2. **Nested config blocks were dropped without error**, so runs completed with
   settings the YAML claimed were applied. Fixed, but confirm with `--dry-run`
   that a spec produces the overrides you expect.
3. **`summarize_dir()` reads `.trb` from a local path.** The job service now
   collects remote outputs before inspection and checks the expected pairs.
   Never remove this check: an absent local directory otherwise returns `[]`.
4. **CPU-only hosts crash inside the forward pass**, not at import:
   SE3Transformer imports `torch.cuda.nvtx.range` unguarded, raising
   `NVTX functions not installed` partway through inference, which reads like a
   model bug. `cpu_shim.py` handles it. This is the only genuine GPU-hardcoding
   in the inference path; everything else is properly guarded.

## Gotchas

- Runtime estimates in `demo/demo_configs.yaml` assume ~12 cores and are roughly
  20x pessimistic on this 32-core VM. Do not size decisions off them.
- Existing logs/artifacts are now refused rather than overwritten. The job
  service uses isolated run IDs; never delete a run just to force regeneration.
