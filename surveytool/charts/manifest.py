"""manifest.json: one record per exported file in an export folder.

Both the Charts tab and the Cross-tab export into the same folder, so the
manifest is cumulative and shared: `{"files": [...]}`, one entry per
filename, merged on every export rather than rewritten. An older flat-list
manifest (the Charts tab's previous format) is read as Charts entries.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from surveytool.charts.errors import ErrorCode, SurveyToolError

MANIFEST_FILENAME = "manifest.json"


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


def charts_manifest_record(entry: ManifestEntry, export_id: str) -> dict:
    """A Charts tab entry in the shared manifest shape."""
    return {"source": "charts", "export_id": export_id, **asdict(entry)}


def _unreadable(path: Path, detail: str) -> SurveyToolError:
    return SurveyToolError(
        ErrorCode.INTERNAL,
        "The export folder's manifest.json can't be read, so the export was stopped to avoid overwriting files.",
        detail=f"{path}: {detail}",
        next_action="Move or delete manifest.json in the export folder, or choose a different export folder, then export again.",
    )


def load_manifest(out_dir: Path) -> dict[str, dict]:
    """Return the folder's manifest as {filename: record}; {} if there is none.

    A manifest that exists but can't be parsed is a loud error, never a
    silent reset -- resetting would forget which files earlier exports wrote
    and let a later export overwrite them.
    """
    path = Path(out_dir) / MANIFEST_FILENAME
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _unreadable(path, str(exc)) from exc

    if isinstance(data, list):  # previous Charts-tab-only format
        records = [{"source": "charts", **r} for r in data]
    elif isinstance(data, dict) and isinstance(data.get("files"), list):
        records = data["files"]
    else:
        raise _unreadable(path, "unexpected structure")

    if not all(isinstance(r, dict) and isinstance(r.get("filename"), str) for r in records):
        raise _unreadable(path, "an entry has no filename")
    return {r["filename"]: r for r in records}


def merge_manifest(out_dir: Path, records: list[dict]) -> None:
    """Upsert `records` (by filename) into the folder's manifest and write it
    atomically, so an interrupted write never leaves a half-written file."""
    out_dir = Path(out_dir)
    existing = load_manifest(out_dir)
    written_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for record in records:
        existing[record["filename"]] = {**record, "written_at": written_at}

    path = out_dir / MANIFEST_FILENAME
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(
        json.dumps({"files": list(existing.values())}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    os.replace(tmp, path)


def write_manifest(entries: list[ManifestEntry], path: Path) -> None:
    """Merge Charts entries into the manifest at `path` (kept for callers of
    the old API; no longer overwrites other exports' entries)."""
    import uuid

    export_id = uuid.uuid4().hex
    merge_manifest(Path(path).parent, [charts_manifest_record(e, export_id) for e in entries])
