from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class ManifestEntry:
    filename: str
    qid: str
    question_text: str
    breakdown_variable: str
    metric: str
    findings_row_keys: list[str]  # "{qid}/{breakdown_variable}/{breakdown_level}/{metric}"


def _row_key(qid: str, breakdown_variable: str, breakdown_level: str, metric: str) -> str:
    return f"{qid}/{breakdown_variable}/{breakdown_level}/{metric}"


def write_manifest(entries: list[ManifestEntry], path: Path) -> None:
    path.write_text(
        json.dumps([asdict(e) for e in entries], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
