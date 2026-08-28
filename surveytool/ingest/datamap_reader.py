from __future__ import annotations

import re
from typing import Iterator

from surveytool.charts.errors import ErrorCode, SurveyToolError
from surveytool.ingest.vendor_profile import VendorProfile

_QID_RE = re.compile(r"\[([^\]]+)\]")
_ITEM_REF_RE = re.compile(r"^\[([^\]]+)\]$")

# Maps variable name -> (question text, ordered code/label pairs, qtype_hint,
# ordered option-definition pairs). qtype_hint is 'open_numeric', 'open_text',
# or None for a coded (scale/demographic/multi-select) question. Option
# definitions are (data_column_name, label) pairs for a multi-select block
# whose Datamap rows key each option to its own A1 column via a bracketed
# item reference (e.g. "[Q10r1]") rather than a numeric code — PureSpectrum's
# format for "check all that apply" question groups. Role/family resolution
# is intentionally NOT done here — callers (vendor adapters) still do their
# own resolve_roles / identify_family step against the raw codes.
Codebook = dict[str, tuple[str, list[tuple[int, str]], str | None, list[tuple[str, str]]]]


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


class DatamapMalformedLineError(SurveyToolError):
    """Raised when a Datamap sheet contains a column A line, or a code-column
    row, that the reader cannot classify as any recognised shape. Silently
    absorbing such a line into the preceding block (the historical bug this
    guards) loses whole questions without any sign in the output."""

    def __init__(self, sheet_name: str, row_number: int, content: str) -> None:
        self.sheet_name = sheet_name
        self.row_number = row_number
        self.content = content
        detail = (
            f"Sheet {sheet_name!r}, row {row_number}: unrecognised content {content!r}. "
            "Expected a '[qid]: text' or 'qid: text' block header, a 'Values:' or "
            "open-response continuation marker, a numeric code/label row, or a "
            "bracketed option-definition row."
        )
        super().__init__(
            ErrorCode.NO_QUESTIONS_FOUND,
            "This file's codebook has a line that could not be read.",
            detail=detail,
            next_action="Check the codebook sheet at the given row, or pick a different file.",
        )


def _is_continuation_marker(cell: str) -> bool:
    return cell.startswith("Values:") or cell.startswith("Open numeric") or cell.startswith("Open text")


def _extract_qid_and_text(cell: str) -> tuple[str, str] | None:
    m = _QID_RE.match(cell)
    if m:
        return m.group(1), cell[m.end():].lstrip(":").strip()
    if ":" in cell:
        qid, _, text = cell.partition(":")
        qid = qid.strip()
        if qid:
            return qid, text.strip()
    return None


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
        sheet_name = getattr(ws_codebook, "title", "Datamap")
        rows = list(ws_codebook.iter_rows(values_only=True))

        # Column A lines, in order, each paired with the row number they came
        # from — used for the one-line lookahead the header rule needs
        # ("is the *next* non-blank column A line a continuation marker?"),
        # and for pinpointing a malformed line in the raised error.
        col0_lines: list[tuple[int, str]] = []
        for row_number, row in enumerate(rows, start=1):
            col0 = row[0] if len(row) > 0 else None
            if col0 is not None and isinstance(col0, str) and col0.strip():
                col0_lines.append((row_number, col0.strip()))
        next_col0_by_row: dict[int, str] = {}
        for i, (row_number, _cell) in enumerate(col0_lines):
            next_col0_by_row[row_number] = col0_lines[i + 1][1] if i + 1 < len(col0_lines) else ""

        codebook: Codebook = {}
        current_qid: str | None = None
        current_text: str | None = None
        current_qtype_hint: str | None = None
        current_codes: list[tuple[int, str]] = []
        current_options: list[tuple[str, str]] = []
        saw_values_line = False

        def _flush() -> None:
            if current_qid is None:
                return
            if current_qid in self.profile.reserved_metadata_columns:
                return
            if current_qtype_hint is None and saw_values_line and not current_codes and not current_options:
                raise DatamapReaderError(current_qid)
            codebook[current_qid] = (current_text or "", current_codes, current_qtype_hint, current_options)

        for row_number, row in enumerate(rows, start=1):
            col0, col1, col2 = (row[i] if i < len(row) else None for i in range(3))

            if col0 is None and col1 is None and col2 is None:
                continue

            if col0 and isinstance(col0, str) and col0.strip():
                cell = col0.strip()
                if _is_continuation_marker(cell):
                    if cell.startswith("Open numeric"):
                        current_qtype_hint = "open_numeric"
                    elif cell.startswith("Open text"):
                        current_qtype_hint = "open_text"
                    else:
                        saw_values_line = True
                    continue

                next_cell = next_col0_by_row.get(row_number, "")
                if _is_continuation_marker(next_cell):
                    extracted = _extract_qid_and_text(cell)
                    if extracted is None:
                        raise DatamapMalformedLineError(sheet_name, row_number, cell)
                    _flush()
                    current_qid, current_text = extracted
                    current_qtype_hint = None
                    current_codes = []
                    current_options = []
                    saw_values_line = False
                    continue

                raise DatamapMalformedLineError(sheet_name, row_number, cell)

            item_ref = _ITEM_REF_RE.match(col1) if isinstance(col1, str) else None
            if item_ref is not None and col2 is not None:
                current_options.append((item_ref.group(1), str(col2)))
                continue

            if col1 is not None and col2 is not None:
                try:
                    code = int(col1)
                except (TypeError, ValueError):
                    raise DatamapMalformedLineError(
                        sheet_name, row_number, f"{col1!r}, {col2!r}"
                    ) from None
                current_codes.append((code, str(col2)))
                continue

            if col1 is not None or col2 is not None:
                raise DatamapMalformedLineError(sheet_name, row_number, f"{col1!r}, {col2!r}")

        _flush()
        return codebook

    def read_table(self, ws_data) -> tuple[list[str], list[tuple]]:
        rows = ws_data.iter_rows(values_only=True)
        header = list(next(rows))
        header_strs = [str(h) if h is not None else None for h in header]
        data_rows = list(_iter_until_blank(rows))
        return header_strs, data_rows
