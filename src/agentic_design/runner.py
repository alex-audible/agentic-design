"""Build and execute RFdiffusion commands.

``build_command`` is deliberately pure.  Remote workers pass an explicit
configuration and resolved paths; local callers retain the historical defaults.
"""

import json
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePath, PurePosixPath

from .paths import REPO_ROOT, load_paths, results_dir
from .trb import summarize_dir


@dataclass
class DesignRequest:
    name: str
    contigs: str
    num_designs: int = 1
    diffuser_T: int = 50
    input_pdb: str | None = None
    hotspot_res: str | None = None
    extra: dict = field(default_factory=dict)
    seed: int | None = None


def build_command(
    req: DesignRequest,
    outdir: PurePath,
    *,
    cfg: Mapping | None = None,
    input_pdb: PurePath | None = None,
) -> list[str]:
    cfg = dict(cfg or load_paths())
    path_flavour = PurePosixPath if isinstance(outdir, PurePosixPath) else Path
    root = path_flavour(str(cfg["rfdiffusion_root"]))
    cmd = [cfg["python_bin"]]
    if cfg.get("device") == "cpu":
        # SE3Transformer's CUDA-only NVTX profiling calls crash a CPU build.
        cmd += ["-m", "agentic_design.cpu_shim"]
    cmd += [
        str(root / "scripts" / "run_inference.py"),
        f"inference.output_prefix={outdir}/{req.name}",
        f"contigmap.contigs={req.contigs}",
        f"inference.num_designs={req.num_designs}",
        f"diffuser.T={req.diffuser_T}",
    ]
    if req.input_pdb:
        resolved_input = (
            input_pdb if input_pdb is not None else REPO_ROOT / req.input_pdb
        )
        cmd.append(f"inference.input_pdb={resolved_input}")
    if req.hotspot_res:
        cmd.append(f"ppi.hotspot_res={req.hotspot_res}")
    if req.seed is not None:
        if (isinstance(req.seed, bool) or not isinstance(req.seed, int)
                or req.seed < 0 or req.seed + req.num_designs > 2**32):
            raise ValueError("seed range must fit unsigned 32-bit integers")
        # Upstream RFdiffusion seeds Python, NumPy, and torch with i_des.
        cmd += ["inference.deterministic=true", f"inference.design_startnum={req.seed}"]
    for k, v in req.extra.items():
        if req.seed is not None and k.lstrip("+") in ("inference.deterministic", "inference.design_startnum"):
            if k == "inference.deterministic" and v is True:
                continue
            raise ValueError("seed cannot be combined with conflicting randomness overrides")
        if isinstance(v, bool):
            encoded = str(v).lower()
        elif v is None:
            encoded = "null"
        elif isinstance(v, list):
            encoded = json.dumps(v, separators=(",", ":"))
        else:
            encoded = str(v)
        cmd.append(f"{k}={encoded}")
    return cmd


def require_device(cfg: dict) -> None:
    """Fail fast when a GPU run lands on a machine without one.

    Silently falling back to CPU turns a 20-minute job into a multi-hour one,
    so CPU has to be asked for explicitly rather than inferred.
    """
    device = cfg.get("device", "cuda")
    if device == "cpu":
        return
    import torch  # deferred: the test suite runs without torch installed

    if not torch.cuda.is_available():
        raise RuntimeError(
            f"config requests device: {device}, but no GPU is visible. "
            "Set 'device: cpu' in config/paths.local.yaml to run on CPU."
        )


def run_design(
    req: DesignRequest,
    *,
    outdir: Path | None = None,
    cfg: Mapping | None = None,
    input_pdb: Path | None = None,
) -> dict:
    """Execute a design job. Returns a JSON-safe result dict."""
    effective_cfg = dict(cfg or load_paths())
    require_device(effective_cfg)
    outdir = outdir or (results_dir() / req.name)
    outdir.mkdir(parents=True, exist_ok=True)
    existing = list(outdir.glob("*.trb")) + list(outdir.glob("*.pdb"))
    if existing:
        raise FileExistsError(
            f"refusing to reuse output directory containing design artifacts: {outdir}"
        )
    cmd = build_command(req, outdir, cfg=effective_cfg, input_pdb=input_pdb)

    # Stream to the log rather than buffering: RFdiffusion logs every timestep,
    # and a job that only reveals its output on exit cannot be monitored.
    log = outdir / "run.log"
    if log.exists():
        raise FileExistsError(f"refusing to truncate existing log: {log}")
    with log.open("x") as fh:
        proc = subprocess.run(
            cmd, stdout=fh, stderr=subprocess.STDOUT, text=True, check=False
        )

    text = log.read_text()
    designs = summarize_dir(outdir) if proc.returncode == 0 else []
    skipped = text.count("Skipping this design")
    first_index = req.seed if req.seed is not None else 0
    expected_stems = {f"{req.name}_{index}" for index in range(first_index, first_index + req.num_designs)}
    trbs = {p.stem for p in outdir.glob("*.trb")}
    pdbs = {p.stem for p in outdir.glob("*.pdb")}
    pairs = trbs & pdbs
    valid = (
        proc.returncode == 0
        and trbs == expected_stems
        and pdbs == expected_stems
        and pairs == expected_stems
        and skipped == 0
    )
    error = None
    if not valid:
        if proc.returncode:
            error = text[-2000:]
        elif skipped:
            error = f"RFdiffusion skipped {skipped} existing design(s)"
        else:
            error = (
                f"expected {req.num_designs} fresh TRB/PDB pair(s), found {len(pairs)}"
            )
    return {
        "name": req.name,
        "returncode": proc.returncode,
        "outdir": str(outdir),
        "log": str(log),
        "designs": designs,
        # RFdiffusion's cautious mode skips designs whose output already
        # exists, so a re-run can exit 0 having generated nothing new.
        "skipped_existing": skipped,
        "success": valid,
        "error": error,
    }
