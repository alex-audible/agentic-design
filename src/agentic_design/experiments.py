"""Immutable experiment snapshots and human approvals."""

from __future__ import annotations

import json
import re
import tempfile
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

import yaml

from .cli import build_request


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False) as fh:
        json.dump(value, fh, indent=2, sort_keys=True)
        fh.write("\n")
        temporary = Path(fh.name)
    temporary.replace(path)


def digest_spec(spec: dict) -> str:
    encoded = json.dumps(spec, sort_keys=True, separators=(",", ":")).encode()
    return sha256(encoded).hexdigest()


class ExperimentStore:
    def __init__(
        self,
        root: str | Path,
        inputs_root: str | Path,
        max_designs: int = 100,
        examples_root: str | Path | None = None,
    ):
        self.root, self.inputs_root = Path(root).resolve(), Path(inputs_root).resolve()
        self.max_designs = max_designs
        self.examples_root = Path(examples_root).resolve() if examples_root else None
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, experiment_id: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", experiment_id):
            raise ValueError("invalid experiment ID")
        return self.root / experiment_id / "experiment.json"

    def validate_spec(self, spec: dict, require_source: bool = True) -> dict:
        request = build_request(spec)
        if request.num_designs > self.max_designs:
            raise ValueError(
                f"num_designs exceeds configured maximum {self.max_designs}"
            )
        if request.input_pdb:
            raw = Path(request.input_pdb)
            if raw.is_absolute() or ".." in raw.parts:
                raise ValueError(
                    "input_pdb must be a relative path inside the configured inputs directory"
                )
            candidate = (self.inputs_root / raw).resolve()
            try:
                candidate.relative_to(self.inputs_root)
            except ValueError as exc:
                raise ValueError(
                    "input_pdb must be inside the configured inputs directory"
                ) from exc
            if require_source and not candidate.is_file():
                raise ValueError(f"input PDB does not exist: {candidate}")
            spec = dict(spec)
            spec["input_pdb"] = raw.as_posix()
        return spec

    def save(self, spec: dict, description: str = "", evaluation: str = "") -> dict:
        spec = self.validate_spec(spec)
        experiment_id = spec["name"]
        path = self._path(experiment_id)
        input_digest = None
        input_bytes = None
        request = build_request(spec)
        if request.input_pdb:
            source = self.inputs_root / request.input_pdb
            input_bytes = source.read_bytes()
            input_digest = sha256(input_bytes).hexdigest()
        material = {"spec": spec, "input_sha256": input_digest}
        record = {
            "id": experiment_id,
            "description": description,
            "evaluation": evaluation,
            "spec": spec,
            "input_sha256": input_digest,
            "digest": digest_spec(material),
            "created_at": now(),
        }
        if path.exists():
            old = json.loads(path.read_text())
            if old["digest"] == record["digest"]:
                return old
            raise FileExistsError(
                f"experiment {experiment_id!r} already exists with a different spec"
            )
        if request.input_pdb:
            snapshot = path.parent / "input" / request.input_pdb
            snapshot.parent.mkdir(parents=True, exist_ok=True)
            snapshot.write_bytes(input_bytes)
        atomic_json(path, record)
        return record

    def load(self, experiment_id: str) -> dict:
        path = self._path(experiment_id)
        if not path.exists():
            raise FileNotFoundError(f"unknown experiment: {experiment_id}")
        record = json.loads(path.read_text())
        material = {"spec": record["spec"], "input_sha256": record.get("input_sha256")}
        if digest_spec(material) != record["digest"]:
            raise ValueError(f"experiment snapshot is corrupt: {experiment_id}")
        self.validate_spec(record["spec"], require_source=False)
        request = build_request(record["spec"])
        if request.input_pdb:
            snapshot = path.parent / "input" / request.input_pdb
            if (
                not snapshot.is_file()
                or sha256(snapshot.read_bytes()).hexdigest() != record["input_sha256"]
            ):
                raise ValueError(
                    f"experiment input snapshot is corrupt: {experiment_id}"
                )
        return record

    def approve(self, experiment_id: str) -> dict:
        record = self.load(experiment_id)
        approval = {
            "experiment_id": experiment_id,
            "digest": record["digest"],
            "approved_at": now(),
        }
        atomic_json(self._path(experiment_id).with_name("approval.json"), approval)
        return approval

    def require_approval(self, experiment_id: str) -> dict:
        record = self.load(experiment_id)
        path = self._path(experiment_id).with_name("approval.json")
        if not path.exists():
            raise PermissionError(
                f"experiment {experiment_id!r} has not been approved by a human"
            )
        approval = json.loads(path.read_text())
        if approval.get("digest") != record["digest"]:
            raise PermissionError(
                "approval does not match the current experiment digest"
            )
        return record

    def list(self) -> list[dict]:
        return [
            self.load(p.parent.name)
            for p in sorted(self.root.glob("*/experiment.json"))
        ]

    def list_inputs(self) -> list[dict]:
        return [
            {
                "name": p.relative_to(self.inputs_root).as_posix(),
                "bytes": p.stat().st_size,
            }
            for p in sorted(self.inputs_root.rglob("*.pdb"))
        ]

    def list_examples(self) -> list[dict]:
        if not self.examples_root or not self.examples_root.exists():
            return []
        return [
            {"name": p.name, "spec": yaml.safe_load(p.read_text())}
            for p in sorted(self.examples_root.glob("*.yaml"))
        ]
