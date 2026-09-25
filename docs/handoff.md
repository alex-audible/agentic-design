# Status

Updated 2026-09-25 for the simple OpenCode co-scientist.

## OpenCode co-scientist (current)

The researcher selected OpenCode and asked for a simple first version with a
persistent research notebook and explicit seeds for replication. The existing
experiment/job service is retained. Start with [the co-scientist guide](co-scientist.md).

- OpenCode **1.18.32** is installed locally under `harness/node_modules`, pinned
  by `harness/package-lock.json`. `.venv-research` contains the Python/MCP client.
  `./co-scientist` starts the research profile; Windows can use
  `py scripts/co_scientist.py`.
- The launcher reads the existing endpoint/model configuration and starts
  `agents/research.py`. OpenCode's actual MCP connection has been checked.
- `research/campaigns/<id>/campaign.json` stores the question; timestamped JSON
  entries store plans, tool requests/results/failures, and interpretations.
  `notebook.md` is a generated readable view. There is no notebook database,
  hash chain, or separate workspace/application.
- Specs saved through the research tools include `seed` (default 0). With
  `seed: 42` and two designs, RFdiffusion deterministic mode is enabled and
  design indices/seeds are 42 and 43. The runner and collector check those names.
  Legacy specs without a seed retain their previous behavior.
- Repeating an approved experiment uses the same spec/input snapshot and a new
  submission key. Retries use the original key. The small submitted worker/input
  bundle is retained with the job. Full runtime/checkpoint capture and automatic
  historical-bundle replay are not implemented; keep the compute environment
  fixed when evaluating replication.
- Notebook entries link existing experiment/input snapshots and job/results
  locations. Back up `research/campaigns/`, `.agentic-design/`, and `results/`
  together; all are ignored by Git.
- Human approval remains a CLI action. The research profile has no shell,
  file-editing, delegation, or approval tool. Existing submission limits remain.
- Analysis resumes when a researcher starts a session and asks to continue.
  There is no automatic wakeup or background agent.

Verification: **45 tests passed**, including a real OpenCode process connected
to a local fake model endpoint, MCP stdio, forbidden self-approval, saved input
reuse after the original file changes, seed propagation, seeded worker outputs,
and notebook persistence. Command: `RUN_OPENCODE_SMOKE=1 .venv-research/bin/python -m pytest tests -q`.
Compilation and `git diff --check` also passed. MCP is constrained to `<2` because
the existing server uses the v1 FastMCP API. The co-scientist changes are being
shared on `agentic-design-api` through
[upstream pull request #1](https://github.com/KristinaGagalova/agentic-design/pull/1).
GitHub Actions automation was removed at the researcher's request. Run tests
locally with `python -m pytest tests -q` after installing `.[mcp,test]`;
the optional OpenCode fixture uses `RUN_OPENCODE_SMOKE=1`. The notebook and
experiment service do not depend on GitHub Actions.

The main README now contains detailed fresh-machine installation instructions
for macOS/Linux/WSL and Windows cmd, model and SSH configuration, no-key fixture
checks, the first campaign, and research-record transfer limitations.
`docs/INSTALL.md` covers the separate CPU execution-host setup and manual
environment-version records. The client install was repeated in a clean temporary
source copy with a fresh venv and `npm ci`; all **45 tests passed** there as well.
README/document links, anchors, and code fences were checked.

No live model request or real SSH/RFdiffusion experiment was run. The current
environment has no configured model API key, SSH host, or SSH key. Configure
these before the first live run. Sequence design/refolding/filtering remain stubs.

## Earlier endpoint implementation (2026-09-16)

Start with [the demo walkthrough](../demo-api/README.md) and
[Astra’s design](../astra-design.md).

## Current work

Astra designed the system and Sol implemented the agent/job service. The
researcher selected direct SSH execution, human approval before submission,
configurable endpoint/model settings, and OpenRouter `openai/gpt-5.6-sol`
restricted to the OpenAI provider. The initial client is Windows `cmd`, with
WSL2 available as an alternative.

- A Chat Completions tool loop prepares immutable experiment specs and records
  conversation audits. Endpoint, model, key environment variable, and request
  parameters are operator-configurable.
- Approval is a human CLI action tied to the saved spec and input bytes. Models
  can submit approved experiments but cannot approve them.
- The job service stages a small worker and input snapshot automatically over
  SSH, starts detached jobs, records durable IDs, and retrieves checked outputs.
- MCP shares the same tool service and approval rules.
- Original YAML runs remain supported on the execution machine. The new
  orchestrator is the SSH path; the legacy CLI rejects non-local backends.
- `demo-api/` adapts the existing ubiquitin examples with portable input paths,
  a prompt file, data-fetch scripts, and a numbered Windows/WSL walkthrough.
- The upstream demo fetch update (`dcaf416`) was fast-forwarded into this checkout
  before integrating the API demo. No existing work was discarded.

The API implementation is on the `agentic-design-api` branch for review against
`main`. The earlier warning about all historical work being uncommitted was
stale; that work was already in Git.

## Verification

The researcher explicitly authorized mocked/unit tests locally and chose to
configure the cluster later. See the final verification entry below for the
suite result. No live OpenRouter request, real SSH submission, or new RFdiffusion
experiment has been run in this implementation session.

The updated fetcher downloaded public 1UBQ. The cleaned target was checked:
602 protein atoms, chain A, contiguous residues 1-76, and complete N/CA/C backbone
atoms. Generated target files are gitignored and reproducible with the fetcher.

The HTTP integration fixture exercises the API demo using a local fake endpoint:
input/example discovery, saving a motif experiment, command preview, rejection
of model self-approval and unapproved submission, tool-result correlation,
reasoning metadata preservation, and a key-free saved audit.

## Still required for a live demonstration

1. Follow `demo-api/README.md` on the Windows client (or entirely within WSL).
2. Set the local OpenRouter key; no key is present in source control.
3. Configure `config/orchestrator.local.yaml` with the SSH host/key and remote
   installation paths, then establish the verified host-key entry.
4. Review the saved motif experiment, approve it, submit it, and collect outputs.
5. Check motif RMSD. This is geometric verification, not candidate validation.

The native Windows commands and POSIX remote paths are implemented, but this
session runs on macOS; a native Windows/real-host acceptance run remains pending.
Slurm/PBS adapters are deferred because the researcher selected direct commands.

## Scientific scope and historical evidence

The historical CPU runs remain documented in [first-run.md](first-run.md):
`smoke`, `ubq_motif`, `ubq_monomer`, and `ubq_binder` ran end to end. Motif RMSDs
were 0.73 and 1.13 Å; binder target-preservation RMSDs were 0.117 and 0.114 Å.
Those binders contacted only A8, not the full intended patch.

ProteinMPNN, refolding, and downstream filtering are still explicit stubs in
`workflows/design_campaign.py`. No validated binder candidate has been produced.
The framework reports backbones and structural checks without claiming otherwise.

## Final verification (2026-09-16)

- Full local suite: **33 passed** (`.venv-sol/bin/python -m pytest tests -q`).
- Python compilation and `git diff --check`: passed.
- Console entry point, input/example discovery, demo import, and command preview:
  exercised successfully. The saved local demo remains unapproved and unsubmitted.
- Real localhost HTTP fixture: passed, with no paid provider request.
- Isolated staged worker: executed against fake inference/torch fixtures; no
  real protein design or GPU computation was performed.
- Regression coverage includes immutable input approval, protected overrides,
  job idempotency, output freshness, partial collection recovery, remote quoting,
  SSH failure handling, completion/PID race handling, and bounded submissions.
- CI configuration added for Windows/Linux with Python 3.10/3.12. It has not
  been run on GitHub in this session; native Windows acceptance is still pending.
