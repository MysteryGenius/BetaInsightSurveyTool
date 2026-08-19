from __future__ import annotations

import re
from typing import Iterator

from surveytool.charts.errors import ErrorCode, SurveyToolError
from surveytool.ingest.vendor_profile import VendorProfile

_QID_RE = re.compile(r"\[([^\]]+)\]")

# Maps variable name -> (question text, ordered code/label pairs, qtype_hint).
# qtype_hint is 'open_numeric', 'open_text', or None for a coded (scale/
# demographic) question. Role/family resolution is intentionally NOT done
# here — callers (vendor adapters) still do their own resolve_roles /
# identify_family step against the raw codes.
Codebook = dict[str, tuple[str, list[tuple[int, str]], str | None]]


class DatamapReaderError(SurveyToolError):
    """Raised when a datamap codebook entry has a Values: line but no code
    rows follow it — a malformed entry that must not silently resolve to an
    empty label set."""

    def __init__(self, qid: str) -> None:
        self.qid = qid
        detail = (
            f"Codebook entry {qid!r} declares a Values: range but no code/label "
            "rows follow it."
        )
        super().__init__(
            ErrorCode.NO_QUESTIONS_FOUND,
            f"This file's codebook has a malformed entry for {qid!r}.",
            detail=detail,
            next_action="Check the codebook sheet for this question, or pick a different file.",
        )


def _iter_until_blank(rows: Iterator[tuple]) -> Iterator[tuple]:
    for row in rows:
        if all(v is None for v in row):
            break
        yield row


class DatamapReader:
    """Parses a datamap-format codebook: '[variable]: question text' header
    rows, an optional 'Values: n-m' hint row, then rows of (code, label)
    pairs. Shared by any vendor whose codebook follows this convention."""

    def __init__(self, profile: VendorProfile) -> None:
        self.profile = profile

    def read_codebook(self, ws_codebook) -> Codebook:
        codebook: Codebook = {}
        current_qid: str | None = None
        current_text: str | None = None
        current_qtype_hint: str | None = None
        current_codes: list[tuple[int, str]] = []
        saw_values_line = False

        def _flush() -> None:
            if current_qid is None:
                return
            if current_qid in self.profile.reserved_metadata_columns:
                return
            if current_qtype_hint is None and saw_values_line and not current_codes:
                raise DatamapReaderError(current_qid)
            codebook[current_qid] = (current_text or "", current_codes, current_qtype_hint)

        for row in ws_codebook.iter_rows(values_only=True):
            col0, col1, col2 = (row[i] if i < len(row) else None for i in range(3))

            if col0 is None and col1 is None and col2 is None:
                continue

            if col0 and isinstance(col0, str) and col0.strip():
                cell = col0.strip()
                m = _QID_RE.match(cell)
                if m:
                    _flush()
                    current_qid = m.group(1)
                    current_text = cell[m.end():].lstrip(":").strip()
                    current_qtype_hint = None
                    current_codes = []
                    saw_values_line = False
                elif cell.startswith("Open numeric"):
                    current_qtype_hint = "open_numeric"
                elif cell.startswith("Open text"):
                    current_qtype_hint = "open_text"
                elif cell.startswith("Values:"):
                    saw_values_line = True
            elif col1 is not None and col2 is not None:
                try:
                    code = int(col1)
                except (TypeError, ValueError):
                    continue
                current_codes.append((code, str(col2)))

        _flush()
        return codebook

    def read_table(self, ws_data) -> tuple[list[str], list[tuple]]:
        rows = ws_data.iter_rows(values_only=True)
        header = list(next(rows))
        header_strs = [str(h) if h is not None else None for h in header]
        data_rows = list(_iter_until_blank(rows))
        return header_strs, data_rows
