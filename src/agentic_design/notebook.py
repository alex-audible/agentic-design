"""A small file-based research notebook, independent of the chat transcript."""

from __future__ import annotations

import json
import re
from pathlib import Path
from uuid import uuid4

from .experiments import atomic_json, now


class Notebook:
    def __init__(self, root: Path):
        self.root = Path(root)

    def directory(self, campaign_id: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", campaign_id):
            raise ValueError("campaign ID must contain 1-80 letters, digits, hyphens or underscores")
        return self.root / campaign_id

    def create(self, campaign_id: str, title: str, question: str) -> dict:
        if not title.strip() or not question.strip():
            raise ValueError("a campaign needs a title and research question")
        directory = self.directory(campaign_id)
        record = {"id": campaign_id, "title": title, "question": question, "created_at": now()}
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "campaign.json"
        # Exclusive creation prevents a later session from replacing the question.
        try:
            with path.open("x") as stream:
                json.dump(record, stream, indent=2)
                stream.write("\n")
        except FileExistsError:
            previous = json.loads(path.read_text())
            if previous["title"] != title or previous["question"] != question:
                raise ValueError("campaign already exists; use a new ID or append a note")
            record = previous
        self.read(campaign_id)
        return record

    def list(self) -> list[dict]:
        return [json.loads(p.read_text()) for p in sorted(self.root.glob("*/campaign.json"))]

    def read(self, campaign_id: str) -> dict:
        directory = self.directory(campaign_id)
        path = directory / "campaign.json"
        if not path.is_file():
            raise ValueError(f"unknown campaign: {campaign_id}")
        campaign = json.loads(path.read_text())
        entries = [json.loads(p.read_text()) for p in sorted((directory / "entries").glob("*.json"))]
        # Markdown is a readable view. The individual JSON entries are the record.
        lines = [f"# {campaign['title']}", "", campaign["question"], "",
                 "Generated from the saved entries. Add corrections as new notes.", ""]
        for entry in entries:
            lines += [f"## {entry['kind']} — {entry['at']}", "", entry["text"], ""]
            if entry["data"]:
                lines += ["```json", json.dumps(entry["data"], indent=2, ensure_ascii=False), "```", ""]
        (directory / "notebook.md").write_text("\n".join(lines))
        return {"campaign": campaign, "entries": entries, "notebook": str(directory / "notebook.md")}

    def append(self, campaign_id: str, kind: str, text: str, data: dict | None = None) -> dict:
        self.read(campaign_id)
        entry = {"at": now(), "kind": kind, "text": text, "data": data or {}}
        # One file per entry means concurrent appends cannot overwrite each other.
        name = entry["at"].replace(":", "-") + "-" + uuid4().hex + ".json"
        atomic_json(self.directory(campaign_id) / "entries" / name, entry)
        self.read(campaign_id)
        return entry
