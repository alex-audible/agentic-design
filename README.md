# agentic-design: a protein-design co-scientist

Use OpenCode to discuss a protein-design question, prepare an experiment, run it
on a remote machine, and interpret the results. A simple research notebook keeps
the question, saved experiment settings, seeds, job records, results, and decisions
across conversations. You approve each saved experiment before it can run.

RFdiffusion currently generates **backbones, not validated binder candidates**.
Sequence design, refolding, and downstream candidate filtering are not implemented.

## What is installed where?

| Your computer: the client | Linux execution machine |
| --- | --- |
| This repository, Python, Node/npm, OpenSSH | RFdiffusion, its Python environment, and checkpoint weights |
| OpenCode, installed locally from the pinned npm lockfile | CPU or a correctly configured CUDA GPU |
| Model-provider API key, notebook, experiment snapshots, collected results | Detached design jobs and their outputs |

You do **not** need PyTorch, RFdiffusion weights, or a GPU on the client. You can
install and test the client, prepare experiments, and use the notebook before
configuring the execution machine. Model conversations need a provider key;
configuration checks and fixture tests do not.

## 1. Get the correct project version

Ask the person sharing this system for the **repository URL and commit or branch
containing the co-scientist implementation**. Replace `REPOSITORY_URL` and
`CO_SCIENTIST_REF` below with those values before running the commands:

```bash
git clone REPOSITORY_URL agentic-design
cd agentic-design
git checkout CO_SCIENTIST_REF
git rev-parse HEAD
```

An upstream/default branch may not yet contain this work. The checkout must
include `co-scientist`, `scripts/co_scientist.py`, `agents/research.py`,
`opencode.json`, `.opencode/agents/co-scientist.md`, and
`harness/package-lock.json`. The person sharing local changes must first commit
and publish them, or supply a source archive that includes the hidden `.opencode`
directory. Do not copy their virtual environment or `node_modules`; install your own.

Run all following commands **from the repository root**. If using a source archive
without Git history, retain the version/commit information supplied with it.

## 2. Install client prerequisites

Install [Git](https://git-scm.com/downloads), [Python](https://www.python.org/downloads/),
[Node.js with npm](https://nodejs.org/en/download), and an OpenSSH client.
Use Python **3.12** for the client to match the tested Python series. The package
declares Python 3.10+, but the remote RFdiffusion environment has separate requirements.
Use a supported Node LTS release with npm. No global OpenCode install is needed.

### macOS, Linux, or WSL2

Open a terminal and confirm:

```bash
git --version
python3 --version
node --version
npm --version
ssh -V
```

On Ubuntu/WSL, Python's `venv` package and `openssh-client` may need to be installed
with your system package manager. On macOS, Git may prompt to install Command
Line Tools. Fix missing commands before continuing.

For Windows, WSL2 is the [OpenCode-recommended environment](https://opencode.ai/docs/).
If using WSL, install Python, Node/npm, Git, and SSH **inside WSL**, clone into
your Linux home directory, and use the POSIX instructions throughout. Do not mix
Windows virtual environments or SSH key paths with WSL ones.

### Native Windows: Command Prompt (`cmd`)

Install Python with its launcher, Node.js/npm, Git, and Windows OpenSSH Client.
Open a new Command Prompt after installation so PATH changes are available:

```bat
git --version
py -3.12 --version
node --version
npm --version
ssh -V
```

The Windows blocks below are for **cmd**, not PowerShell. The repository includes
Windows/Linux CI configuration; this co-scientist installation was exercised on
macOS, not on a native Windows machine.

## 3. Install the project and pinned OpenCode runtime

### macOS, Linux, or WSL2

Confirm `python3 --version` reports your intended client Python, then run:

```bash
python3 -m venv .venv-research
source .venv-research/bin/activate
python -m pip install -e '.[mcp,test]'
npm ci --prefix harness
./co-scientist --version
```

If your Python 3.12 command is `python3.12`, use it instead of `python3` when
creating the environment. If an extracted source archive lost executable bits,
run `chmod +x co-scientist`, or use `python scripts/co_scientist.py`.

### Native Windows cmd

```bat
py -3.12 -m venv .venv-research
call .venv-research\Scripts\activate.bat
python -m pip install -e ".[mcp,test]"
npm ci --prefix harness
python scripts\co_scientist.py --version
```

Expected OpenCode version: **1.18.32**. `npm ci` installs the version recorded in
`harness/package-lock.json`; do not substitute a global/latest OpenCode install.
The launcher supplies the research tools and model configuration automatically.
It does not require OpenCode `/init` or manual MCP registration.

Python dependencies are specified in `pyproject.toml`; MCP is constrained to
version 1.x because the server uses FastMCP. Python dependency versions are not
fully locked. To record the exact client environment you installed:

```bash
python -m pip freeze
```

Keep that output with your installation notes if another user needs the same
client dependency versions. Do not reuse this client environment for RFdiffusion.

## 4. Check the installation without a model key or compute host

With `.venv-research` activated:

```bash
agentic-design --help
agentic-design notebook list
python -m pytest tests -q
```

An empty notebook list (`[]`) is normal on a fresh installation. The suite uses
local fixtures and never submits a real RFdiffusion job. The optional OpenCode
end-to-end test is skipped unless explicitly enabled.

Check OpenCode's connection to the local Python tools:

| macOS / Linux / WSL2 | Windows cmd |
| --- | --- |
| `./co-scientist mcp list` | `python scripts\co_scientist.py mcp list` |
| `./co-scientist debug agent co-scientist` | `python scripts\co_scientist.py debug agent co-scientist` |

Expect `research connected`. The profile should have research tools available
and shell/edit/delegation tools disabled. These checks use no model credits;
OpenCode may initialize local caches or fetch its provider catalog.

To test the actual OpenCode → local fake model → MCP → notebook path:

```bash
# macOS / Linux / WSL2
RUN_OPENCODE_SMOKE=1 python -m pytest tests/test_opencode.py -q
```

```bat
rem Windows cmd
set "RUN_OPENCODE_SMOKE=1"
python -m pytest tests/test_opencode.py -q
set "RUN_OPENCODE_SMOKE="
```

This test needs permission to open a localhost socket. It uses a fake credential,
temporary research data, and no external model API or SSH host.

## 5. Configure the model

Create the local settings file **once**; do not overwrite it on subsequent starts:

```bash
# macOS / Linux / WSL2
cp config/orchestrator.yaml config/orchestrator.local.yaml
```

```bat
rem Windows cmd
copy config\orchestrator.yaml config\orchestrator.local.yaml
notepad config\orchestrator.local.yaml
```

Edit the `provider` section in that file. The supplied example uses:

```yaml
provider:
  base_url: https://openrouter.ai/api/v1
  api_key_env: OPENROUTER_API_KEY
  model: openai/gpt-5.6-sol
  timeout: 120
  parameters:
    provider:
      only: [openai]
      allow_fallbacks: false
      require_parameters: true
```

Choose a model identifier available to your account that supports Chat Completions
tool calls. The default identifier is a project setting, not a guarantee of
provider availability. The `parameters.provider` fields restrict OpenRouter's
model routing; the launcher carries those settings into OpenCode.

Set your own API key in the **terminal that will launch OpenCode**:

```bash
export OPENROUTER_API_KEY='replace-with-your-own-key'
```

```bat
set "OPENROUTER_API_KEY=replace-with-your-own-key"
```

These settings last for that terminal session. Never put a key in the notebook,
experiment spec, chat prompt, or committed file. If your organisation supplies a
different endpoint, use its URL, model ID, and key variable. To remove
OpenRouter-only fields, use a **complete** alternate config and set
`AGENTIC_DESIGN_CONFIG` to its absolute path before launching. See
[endpoint configuration](docs/orchestration.md#endpoint-and-provider): local
overrides merge dictionaries, so simply omitting a field does not remove it.
When using an alternate config, also pass `--config /absolute/path/to/config.yaml`
to human CLI commands, for example
`agentic-design --config /absolute/path/to/config.yaml experiment show EXPERIMENT_ID`.
The `AGENTIC_DESIGN_CONFIG` variable configures the co-scientist launcher and MCP
server; the human CLI uses its explicit `--config` option.

## 6. Prepare a first campaign

Download the existing public ubiquitin example, or copy your own PDB into
`data/inputs/`:

```bash
python demo-api/fetch_demo_target.py
agentic-design experiment inputs
```

Expect `1UBQ_clean.pdb` in the listing. The fetcher needs internet access.
Now start the co-scientist:

```bash
./co-scientist
```

```bat
python scripts\co_scientist.py
```

Try this prompt:

> Start a campaign called ubq-pilot. Use the existing ubiquitin motif example to
> prepare an experiment called ubq-pilot-42 with two backbones and starting seed
> 42. Record the hypothesis and how we will check motif preservation. Save the
> experiment and preview the command. Stop before submission.

Check `research/campaigns/ubq-pilot/notebook.md`. You should see the research
question, experiment purpose, saved settings, seeds, input snapshot reference,
and command preview. This step uses the model API but does not need SSH or run
RFdiffusion. It can be your first installation acceptance check.

## 7. Configure the execution machine

For a new machine, follow [RFdiffusion execution-host installation](docs/INSTALL.md).
The supplied installer is a **CPU development setup**; it is not a CUDA installer.
A GPU host needs a compatible RFdiffusion/PyTorch/CUDA environment prepared by its
operator. Use a compute machine that permits direct detached commands. Scheduler
adapters such as Slurm/PBS are not implemented; do not target a scheduler login node.

Update `ssh` in `config/orchestrator.local.yaml`:

```yaml
ssh:
  execution_mode: direct
  host: your-user@your-compute-host
  key_path: /absolute/path/to/your/ssh/private-key
  remote_root: /mnt/src/agentic-design-jobs
  python_bin: /mnt/src/agentic-design-runtime/rfdiff-venv/bin/python
  rfdiffusion_root: /mnt/src/agentic-design-runtime/RFdiffusion
  device: cpu
  connect_timeout: 15
  command_timeout: 60
```

These installation paths match the CPU guide. Replace them with the host's actual
paths. Use `device: cuda` for a configured GPU environment; it fails if no GPU is
visible. CPU must be selected explicitly. `remote_root` must be writable by the
SSH user. Keys use **local** paths, for example `C:/Users/you/.ssh/id_ed25519` in
Windows or `/home/you/.ssh/id_ed25519` in WSL. All remote paths are POSIX paths.

Establish SSH access from the same environment that runs the client:

```bash
ssh -i "/absolute/path/to/your/ssh/private-key" your-user@your-compute-host
```

Use your local Windows key path for that command in cmd. Verify a new host's
fingerprint with its operator before accepting it. Authentication is by SSH key;
load a passphrase-protected key into your SSH agent. The service uses strict host
checking and noninteractive authentication, so an interactive password login
alone is insufficient. Configure the actual host here rather than relying on
this project's historical SSH aliases.

On the remote host, check the selected interpreter and installation:

```bash
/mnt/src/agentic-design-runtime/rfdiff-venv/bin/python -c "import torch, rfdiffusion; print(torch.__version__); print('CUDA available:', torch.cuda.is_available())"
ls /mnt/src/agentic-design-runtime/RFdiffusion/scripts/run_inference.py
ls /mnt/src/agentic-design-runtime/RFdiffusion/models/*.pt
exit
```

The orchestrator stages its worker and input files automatically on submission;
no manual `rsync` or `env/sync.sh push` is needed for the co-scientist workflow.

## 8. Review, approve, run, and resume

In a second client terminal, activate `.venv-research` again. Substitute the actual
experiment ID returned by the agent:

```bash
agentic-design experiment show ubq-pilot-42
agentic-design experiment preview ubq-pilot-42
agentic-design experiment approve ubq-pilot-42
```

Review the input, settings, seed, design count, and command before the approval
command. Approval is tied to the saved spec/input digest. It does not launch a job.
Then ask the co-scientist to submit the approved experiment and record the job ID.
The default limit is one new submission per MCP process; an operator can set
`limits.max_agent_submissions` in local config for a session needing more runs.

Close OpenCode whenever needed: remote jobs continue. To resume, start it again
and ask it to read `ubq-pilot`'s notebook, list jobs, check status, collect outputs,
run the motif check, and record its interpretation. There is no automatic agent
wakeup in this first version.

The CLI can inspect state without a model request:

```bash
agentic-design notebook show ubq-pilot
agentic-design job list
agentic-design job status JOB_ID
agentic-design job collect JOB_ID
```

Collection checks fresh expected TRB/PDB pairs. An exit code alone does not prove
success. Notebook logging is automatic for research-tool actions; actions taken
directly through the CLI are not automatically notebook entries.

## 9. Repeat or transfer an experiment

All co-scientist experiments have an explicit starting `seed` (default `0`). With
seed 42 and two designs, RFdiffusion uses design indices/seeds **42 and 43**, with
output names ending `_42` and `_43`. The command enables deterministic mode;
the [upstream inference script](https://github.com/RosettaCommons/RFdiffusion/blob/main/scripts/run_inference.py)
seeds Python, NumPy, and torch by design index. The saved PDB snapshot is reused
even if the original file in `data/inputs/` later changes.

Ask the agent to repeat the **same saved experiment ID** with a **new submission
key** and note which prior run it replicates. Reuse a previous submission key only
to recover that existing job after a lost reply. A different seed, input, or
parameter set is a new experiment requiring its own ID and approval.

To transfer records to another user, copy these directories with their relative
layout intact, after jobs have been collected and tools are no longer writing:

| Directory | What must be retained |
| --- | --- |
| `research/campaigns/` | Questions, timestamped JSON entries, readable notebooks |
| `.agentic-design/experiments/` | Exact specs, input snapshots, input checksums, approvals |
| `.agentic-design/jobs/` | Job IDs, commands, submission keys, retained worker/input bundles |
| `results/` | Collected TRB/PDB files, run logs, result records |

These directories are **ignored by Git**. A code checkout alone does not transfer
experiments. Notebook links and older job manifests can contain the original
machine's absolute paths; job manifests also retain the original SSH settings.
This version does not automatically relocate old job records. Keep transferred
records as evidence, configure the recipient's own SSH settings, and submit a new
job from the saved experiment for replication. Re-review and approve the saved
experiment on the recipient machine before submitting. Do not use an old run ID
to assume that a moved result directory or different SSH host will be discovered.

Transfer data with the researcher's permission; use each recipient's own API
credentials and SSH key. Recreate their `config/orchestrator.local.yaml` instead
of distributing your private key or copying machine-specific paths unchanged.

Seeds and input snapshots are necessary but do not guarantee bitwise-identical
outputs. Match the RFdiffusion revision, checkpoint files, Python/PyTorch and
dependencies, device, and hardware when comparing replications. Full runtime
capture is not automated in this version; record the execution-host versions as
described in [the host guide](docs/INSTALL.md#record-the-execution-environment).

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| Missing co-scientist files after cloning | Obtain the branch/commit or source archive containing this implementation. |
| `python3`, `py`, `npm`, or `ssh` not found | Install the prerequisite, reopen the terminal, and repeat the version checks. |
| `.venv-research` missing | Create the environment with the documented name; the launcher looks for it. |
| `agentic-design` not found | Activate `.venv-research`, or use `python -m agentic_design.app`. |
| `No module named mcp.server.fastmcp` | Re-run `python -m pip install -e ".[mcp,test]"` in the correct environment; MCP 2.x is incompatible. |
| OpenCode missing or wrong version | Run `npm ci --prefix harness`, then use this project's launcher. |
| `research` MCP server fails to connect | Run `python agents/research.py` with the venv active to see import/config errors; a healthy stdio server waits for input, so exit it with Ctrl-C. |
| Model authentication or model-not-found error | Set the correct environment key in the launching terminal and choose an available tool-capable model in local config. |
| Input PDB missing | Run the demo fetcher or place the PDB under the configured `state.inputs_dir`. |
| Saved experiment already exists with different settings | Use a new experiment ID; do not overwrite the old snapshot. |
| Experiment is not approved | Review it and run the human `experiment approve` command. |
| Submission limit reached | Recover an existing key, or deliberately adjust the operator's session limit for future work. |
| SSH/host-key failure | Test the same explicit host and key manually; confirm known-hosts and SSH-agent setup. |
| Job state is `unknown` | Inspect the recorded job before retrying; reuse its original submission key. |
| No GPU visible | Fix the CUDA environment or explicitly select `device: cpu` for intended CPU runs. |
| Local HTTP test cannot open a socket | Allow localhost networking for the test process; it does not need remote compute. |

## Verification and further documentation

The implementation was tested on macOS arm64 with Python 3.12.13, Node 23.9.0,
npm 10.9.2, and OpenCode 1.18.32. **45 tests passed**, including the actual
OpenCode/MCP path against a fake endpoint and seeded staged-worker fixtures.
The documented client installation was also repeated in a clean temporary source
copy with a newly created virtual environment and `npm ci`; all 45 tests passed
there with no pre-existing credentials, OpenCode runtime, or research state.
No live model call or real remote RFdiffusion run was performed for this setup;
native Windows and a fresh execution host still need acceptance runs.

- [Research workflow and notebook](docs/co-scientist.md)
- [RFdiffusion execution-host installation](docs/INSTALL.md)
- [Current status and remaining live checks](docs/handoff.md)
- [Earlier endpoint CLI workflow](docs/orchestration.md)
- [Existing API demo](demo-api/README.md)
- [Historical CPU experiment report](docs/first-run.md)

The earlier `agentic-design agent` endpoint loop and local YAML CLI remain
available. `agents/tools.py` is the original MCP adapter;
`agents/research.py` adds campaign/notebook tools for OpenCode.
