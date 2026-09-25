"""Thin CLI so runs are reproducible from a shell and from an agent.

python -m agentic_design.cli config/runs/smoke.yaml
"""

import argparse
import json
import shlex
import sys
from pathlib import Path

import yaml

from .paths import load_paths
from .runner import DesignRequest, run_design

# Spec keys that map to named DesignRequest fields. Everything else is passed
# through as a Hydra override, so a spec can reach any RFdiffusion config key
# without this file growing a branch for each one.
NAMED_KEYS = {
    "name",
    "contigs",
    "num_designs",
    "diffuser_T",
    "input_pdb",
    "hotspot_res",
    "seed",
}
RESERVED_OVERRIDES = {
    "inference.output_prefix",
    "inference.input_pdb",
    "inference.num_designs",
    "inference.design_startnum",
    "contigmap.contigs",
    "diffuser.T",
    "hydra.run.dir",
    "hydra.sweep.dir",
    "hydra.searchpath",
    "hydra.job.chdir",
    "device",
    "backend",
}


def flatten(spec: dict, prefix: str = "") -> dict:
    """{'denoiser': {'noise_scale_ca': 0}} -> {'denoiser.noise_scale_ca': 0}"""
    flat = {}
    for key, value in spec.items():
        if not isinstance(key, str):
            raise ValueError("all experiment keys must be strings")
        dotted = f"{prefix}{key}"
        if isinstance(value, dict):
            flat.update(flatten(value, f"{dotted}."))
        else:
            flat[dotted] = value
    return flat


def build_request(spec: dict) -> DesignRequest:
    if not isinstance(spec, dict):
        raise ValueError("experiment spec must be a mapping")
    name = spec.get("name")
    if (
        not isinstance(name, str)
        or not name
        or not all(c.isalnum() or c in "-_" for c in name)
    ):
        raise ValueError("name must contain only letters, numbers, '-' and '_'")
    if not isinstance(spec.get("contigs"), str) or not spec["contigs"].strip():
        raise ValueError("contigs must be a non-empty string")
    if spec.get("input_pdb") is not None and not isinstance(spec["input_pdb"], str):
        raise ValueError("input_pdb must be a string")
    if spec.get("hotspot_res") is not None and not isinstance(spec["hotspot_res"], str):
        raise ValueError("hotspot_res must be a string")
    for key in ("num_designs", "diffuser_T"):
        value = spec.get(key, 1 if key == "num_designs" else 50)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{key} must be a positive integer")
    extra = flatten({k: v for k, v in spec.items() if k not in NAMED_KEYS})
    seed = spec.get("seed")
    if seed is not None:
        if (isinstance(seed, bool) or not isinstance(seed, int)
                or seed < 0 or seed + spec.get("num_designs", 1) > 2**32):
            raise ValueError("seed range must fit unsigned 32-bit integers")
        for key, value in extra.items():
            if key.lstrip("+") == "inference.deterministic" and not (key == "inference.deterministic" and value is True):
                raise ValueError("seed cannot be combined with conflicting randomness overrides")
    normalized = {key.lstrip("+") for key in extra}
    forbidden = sorted(
        key
        for key in normalized
        if key in RESERVED_OVERRIDES
        or key.startswith("hydra.")
        or key.startswith("/")
        or "@" in key
    )
    if forbidden:
        raise ValueError(f"reserved overrides are not allowed: {', '.join(forbidden)}")
    for key, value in extra.items():
        if isinstance(value, (dict, tuple, set)) or not isinstance(
            value, (str, int, float, bool, list, type(None))
        ):
            raise ValueError(f"unsupported override value for {key}")
        if isinstance(value, list) and any(
            isinstance(item, (dict, list, tuple, set)) for item in value
        ):
            raise ValueError(f"override list for {key} must contain scalar values")
    return DesignRequest(
        name=spec["name"],
        contigs=spec["contigs"],
        num_designs=spec.get("num_designs", 1),
        diffuser_T=spec.get("diffuser_T", 50),
        input_pdb=spec.get("input_pdb"),
        hotspot_res=spec.get("hotspot_res"),
        extra=extra,
        seed=seed,
    )


def main(argv=None):
    ap = argparse.ArgumentParser(description="Run an RFdiffusion job from a YAML spec.")
    ap.add_argument("spec", help="path to a config/runs/*.yaml file")
    ap.add_argument("--dry-run", action="store_true", help="print the command only")
    args = ap.parse_args(argv)

    spec = yaml.safe_load(Path(args.spec).read_text())
    req = build_request(spec)

    if args.dry_run:
        from .paths import results_dir
        from .runner import build_command

        print(shlex.join(build_command(req, results_dir() / req.name)))
        return 0

    if load_paths().get("backend", "local") != "local":
        raise RuntimeError(
            "legacy YAML CLI only supports backend: local; use 'agentic-design job submit' for SSH execution"
        )
    result = run_design(req)
    json.dump(result, sys.stdout, indent=2)
    print()
    return 0 if result.get("success") else (result["returncode"] or 1)


if __name__ == "__main__":
    raise SystemExit(main())
