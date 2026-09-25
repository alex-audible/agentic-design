# Protein-design co-scientist with OpenCode

This first version combines OpenCode, the existing RFdiffusion experiment tools,
and a file-based research notebook. You discuss a question, review an experiment,
let it run, and ask the co-scientist to interpret the results.

## Start on this machine

OpenCode is installed locally under `harness/`; Python dependencies are in
`.venv-research/`. From the repository root:

```bash
export OPENROUTER_API_KEY='your-key'
./co-scientist
```

The launcher reads the model, endpoint, and key-environment-variable name from
`config/orchestrator.yaml` and the optional `config/orchestrator.local.yaml`.
Credentials are passed through the environment, not written into the notebook.
Use OpenCode's model selector or `--model provider/model` to choose another
configured OpenCode provider. Do not paste API keys into the chat.

Try:

> Start a campaign called ubq-pilot. Use the existing ubiquitin motif example to
> prepare two backbones with starting seed 42. Record why we are running it and
> how we will check motif preservation. Stop after the command preview.

Inputs must already be in `data/inputs/`. The existing public demo fetcher is:

```bash
.venv-research/bin/python demo-api/fetch_demo_target.py
```

The co-scientist can prepare a notebook and experiment before compute is
configured. To execute it, configure the SSH host, key, installation paths, and
device in `config/orchestrator.local.yaml`; see [orchestration](orchestration.md).
There is no host or model API key shipped with the project.

## Review and run

In another terminal, activate the environment and review the ID the agent gives:

```bash
source .venv-research/bin/activate
agentic-design experiment show EXPERIMENT_ID
agentic-design experiment preview EXPERIMENT_ID
agentic-design experiment approve EXPERIMENT_ID
```

Then tell the co-scientist to submit that approved experiment. The service keeps
the existing human approval rule. The OpenCode research profile has no shell,
file-editing, or agent-delegation tools and cannot run the approval command.
This is a configured tool boundary, not an operating-system sandbox.

The existing `limits.max_agent_submissions` defaults to one new submission per
MCP process. Set it deliberately in local configuration if a session needs more
runs. Retrying an existing recorded submission key retrieves that job without
launching another. Failed or ambiguous new submissions consume the allowance.

## Notebook and resuming

Open `research/campaigns/<campaign-id>/notebook.md` whenever you want to read the
record. The tools automatically record saved specs, command previews, submission
requests, returned job IDs, status checks, output locations, and measured checks.
The agent separately appends hypotheses, interpretations, decisions, and corrections.

The saved spec includes the starting seed. The existing input snapshot and its
SHA-256 identify the actual PDB bytes. Each remote submission also retains its
small worker/input archive at `.agentic-design/jobs/<run-id>/execution-bundle.tar.gz`.

You can inspect the notebook without an LLM:

```bash
agentic-design notebook list
agentic-design notebook show ubq-pilot
```

Close OpenCode whenever needed. Remote jobs continue. Open a new session and say:

> Resume ubq-pilot. Read the notebook, find its jobs, collect completed outputs,
> perform the motif check, and record what the results do and do not establish.

There is no always-running agent or automatic wakeup in this version. Actions
performed outside the research tools are not automatically notebook entries;
`list_jobs` discovers CLI-submitted jobs belonging to recorded experiments.

## Repeating an experiment

Every experiment saved through the co-scientist has an explicit integer `seed`
(default `0`). For `seed: 42` and `num_designs: 2`, the command enables
`inference.deterministic=true` and `inference.design_startnum=42`; RFdiffusion
uses seeds 42 and 43, and outputs are named `<experiment>_42` and `_43`.
The [upstream inference code](https://github.com/RosettaCommons/RFdiffusion/blob/main/scripts/run_inference.py)
seeds Python, NumPy, and torch by design index in deterministic mode.

To repeat, ask:

> Repeat experiment EXPERIMENT_ID using its saved input and seed. Use a new
> submission key and record that this is a replication of RUN_ID.

Reuse the **same experiment ID** with a **new submission key** for an intentional
repeat. Reuse the same key only to recover a submission whose reply was lost.
To explore different randomness or settings, save and approve a new experiment
with a different seed or spec. Legacy CLI/YAML experiments without `seed` keep
their previous behavior and are not automatically deterministic.

These records preserve inputs, parameters, and seeds. Matching outputs also
requires matching RFdiffusion code, checkpoint weights, dependencies, and hardware.
This first version does not capture those entire environments or promise bitwise
reproducibility. Keep the execution environment fixed when assessing replication.
The retained worker bundle is evidence of the submitted code/input; automatic
execution of historical bundles and automatic comparison of repeats are not implemented.

RFdiffusion backbones and geometric checks are the current scientific scope.
ProteinMPNN, refolding, and candidate filtering are not implemented. A successful
run does not establish a validated binder.

## Install on another machine

Follow the [main README](../README.md) for the complete fresh-machine setup:
source version, prerequisites, macOS/Linux/WSL and Windows commands, pinned
OpenCode installation, model credentials, SSH configuration, acceptance tests,
and transferring experiment records. It is the canonical installation guide.
