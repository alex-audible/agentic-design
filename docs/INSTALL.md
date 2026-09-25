# RFdiffusion execution-host installation

This guide is for the **Linux machine running RFdiffusion**, not the computer
running OpenCode. Complete the client setup in the [main README](../README.md)
separately. An already configured RFdiffusion host does not need reinstallation.

The repository's `env/install.sh` installs **CPU builds** of PyTorch and DGL for
development. It does not install CUDA. For GPU production use, follow the
[upstream RFdiffusion installation](https://github.com/RosettaCommons/RFdiffusion#installation)
and your host operator's CUDA/driver requirements, then set the actual installation
paths and `device: cuda` in the client's `ssh` configuration.

## Before installing

- Use Linux with Git, `wget`, Python **3.10** with `venv`, and sudo access for
  creating the installation directory. The historical CPU environment used
  Python 3.10.12. Client Python 3.12 is a separate environment.
- Choose a **fresh dedicated directory on a large disk**. The example below is
  `/mnt/src/agentic-design-runtime`; change every occurrence together if needed.
  Allow space for Python packages, download caches, several GB of checkpoint
  weights, and experiment outputs.
- Get a checkout of the same framework version as the client. The installer
  needs this repository on the execution host; subsequent co-scientist jobs stage
  their own small worker/input bundles automatically.
- This host must permit direct detached jobs over SSH. Slurm/PBS execution is
  not supported by the current job service.

The installer recursively changes ownership inside `SRC` and replaces
`SRC/RFdiffusion/models` with a symlink to `SRC/models`. Use a new dedicated
installation, not an existing shared RFdiffusion checkout or shared disk root.

## CPU development installation

Run these on the **execution host** from the framework repository root. Install
Python 3.10 and its `venv` support using your distribution's supported method
first; confirm `python3.10 --version` works.

```bash
git --version
wget --version
python3.10 --version
sudo mkdir -p /mnt/src/agentic-design-runtime
sudo chown "$USER" /mnt/src/agentic-design-runtime
python3.10 -m venv /mnt/src/agentic-design-runtime/bootstrap
```

The installer invokes `python3`, so put the Python 3.10 bootstrap environment
first on PATH for that command:

```bash
PATH="/mnt/src/agentic-design-runtime/bootstrap/bin:$PATH" SRC=/mnt/src/agentic-design-runtime MINIMAL=1 bash env/install.sh
```

`MINIMAL=1` downloads `Base_ckpt.pt` and `Complex_base_ckpt.pt`, used for common
unconditional/motif and binder examples. Omit `MINIMAL=1` if you need every
checkpoint. Downloads can be resumed separately:

```bash
SRC=/mnt/src/agentic-design-runtime MINIMAL=1 bash env/fetch_weights.sh
```

The installer pins PyTorch 2.0.1 (CPU), DGL 1.1.2, and e3nn 0.3.3, but some
dependencies and the RFdiffusion checkout are not locked. This is a starting
recipe, not a captured environment guaranteed to reproduce an older run.
When reproducing an existing campaign, use the recorded RFdiffusion commit and
dependency versions instead of assuming a new install matches. Do not change
the software environment in the middle of a replication comparison.

If you see NumPy ABI/import errors with this older PyTorch stack, check the NumPy
version against the working environment's recorded versions before running jobs.
Keep installation fixes in the framework or installation records, not as
unrecorded edits to RFdiffusion.

## Check the installation

```bash
source /mnt/src/agentic-design-runtime/rfdiff-venv/bin/activate
python --version
python -c "import torch, dgl, rfdiffusion; print('torch:', torch.__version__); print('DGL:', dgl.__version__); print('CUDA:', torch.cuda.is_available())"
ls /mnt/src/agentic-design-runtime/RFdiffusion/scripts/run_inference.py
ls -lh /mnt/src/agentic-design-runtime/RFdiffusion/models/*.pt
```

For this CPU installation, `CUDA: False` is expected. A CUDA-configured job on
this environment will fail; CPU execution requires explicit `device: cpu`.
Import and file checks are preparation checks, not an RFdiffusion acceptance run.
The live acceptance run is the small reviewed campaign in the main README.

## Point the client at this host

On the **client**, edit `config/orchestrator.local.yaml`:

```yaml
ssh:
  execution_mode: direct
  host: your-user@your-compute-host
  key_path: /local/path/to/private-key
  remote_root: /mnt/src/agentic-design-jobs
  python_bin: /mnt/src/agentic-design-runtime/rfdiff-venv/bin/python
  rfdiffusion_root: /mnt/src/agentic-design-runtime/RFdiffusion
  device: cpu
```

The SSH user must be able to create `remote_root`. If needed, have the operator
create that directory and give the user access. Establish the verified host-key
entry and SSH-key login as described in the README. Do not copy the remote
Python environment to the client.

`config/paths.local.yaml` only controls the legacy local YAML workflow; it does
not configure OpenCode's SSH job service. If deliberately running the legacy CLI
directly on this host, set all relevant paths as well as the CPU selection:

```yaml
rfdiffusion_root: /mnt/src/agentic-design-runtime/RFdiffusion
python_bin: /mnt/src/agentic-design-runtime/rfdiff-venv/bin/python
models_dir: /mnt/src/agentic-design-runtime/models
device: cpu
```

Both CPU paths enable the repository's NVTX compatibility shim. No RFdiffusion
source patch is needed for that workaround.

## Record the execution environment

For each environment used to generate results, retain the following output with
the campaign's installation notes. Run these on the execution host:

```bash
git rev-parse HEAD
git -C /mnt/src/agentic-design-runtime/RFdiffusion rev-parse HEAD
git -C /mnt/src/agentic-design-runtime/RFdiffusion status --short
/mnt/src/agentic-design-runtime/rfdiff-venv/bin/python --version
/mnt/src/agentic-design-runtime/rfdiff-venv/bin/python -m pip freeze
sha256sum /mnt/src/agentic-design-runtime/models/*.pt
uname -a
```

Run `nvidia-smi` as well for GPU experiments. The first Git command records the
framework checkout and should be run from its root. The second records
RFdiffusion. Preserve any local source modifications alongside the version
record; a commit hash alone does not describe a modified checkout. Save this
information with the notebook before comparing results from another host.

Matching a saved experiment's PDB snapshot, spec, and seeds is only part of
replication. Matching weights, code, dependencies, and compute environment is
also required for a meaningful comparison, and cross-platform floating-point
differences can still occur. Full environment capture and verification are not
automated in this first version.

## Verification status

Historical CPU runs are described in [first-run.md](first-run.md). The current
co-scientist implementation has been tested with local fixture workers, not by
rebuilding this execution environment or running a new real RFdiffusion job.
Complete the reviewed live pilot before treating a fresh host as ready.
