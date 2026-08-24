from __future__ import annotations

import re
import zipfile
from pathlib import Path

import openpyxl
from openpyxl.utils.exceptions import InvalidFileException

from surveytool.charts.errors import ErrorCode, SurveyToolError, UnresolvedQuestion, UnresolvedQuestionsError
from surveytool.core.demographic_registry import declared_demographic_source_columns
from surveytool.core.hygiene import normalize_label
from surveytool.core.model import (
    CodeRole,
    Question,
    QuestionType,
    Response,
    ScaleCode,
    Survey,
)
from surveytool.core.nonsubstantive import classify_response, is_nonsubstantive_label
from surveytool.core.scale_library import classify_question_type
from surveytool.ingest.datamap_reader import Codebook, DatamapReader
from surveytool.ingest.overrides import QuestionOverride, resolve_with_override
from surveytool.ingest.validate_questions import collect_unresolved_question
from surveytool.ingest.vendor_profile import PURESPECTRUM_PROFILE

_DEMOGRAPHIC_SOURCE_COLUMNS = declared_demographic_source_columns("purespectrum")


_MULTISELECT_OE_RE = re.compile(r"^(?P<root>[A-Za-z0-9]+)r(?P<n>\d+)oe$")


def _build_multi_response_placeholders(codebook: Codebook, a1_header: list[str] | None) -> list[Question]:
    """PureSpectrum's Datamap documents a multi-select "check all that
    apply" group's other-specify tail (e.g. "Q10r8oe") but never declares
    the option columns themselves (Q10r1..Q10r7) — there is no codebook
    entry for them at all, so parse_codebook's normal per-codebook-entry
    loop can never build Questions for them, and they'd otherwise vanish
    from Survey.questions and the run summary's column inventory entirely.

    Detects any codebook qid shaped "<root>r<n>oe" (its accompanying
    open-text "Other, please specify" entry), derives the group's question
    text by stripping the " - Other ..." suffix, and — if the A1 header is
    available — builds one multi_response Question covering every
    "<root>r<k>" column present in the header for k < n (the oe suffix
    itself keeps its own separate text_open Question, already built
    normally). No option-level label text exists in the Datamap for these
    columns, so each placeholder label is the column name itself — visible
    and auditable in the run summary rather than silently absent, not
    fabricated text presented as if the vendor supplied it.
    """
    if not a1_header:
        return []
    header_set = {h for h in a1_header if h is not None}

    placeholders: list[Question] = []
    for qid in codebook:
        m = _MULTISELECT_OE_RE.match(qid)
        if m is None:
            continue
        root = m.group("root")
        oe_text = codebook[qid][0]
        group_text = oe_text.rsplit(" - ", 1)[0].strip()

        option_columns = sorted(
            (c for c in header_set if re.match(rf"^{re.escape(root)}r\d+$", c)),
            key=lambda c: int(re.search(r"\d+$", c).group()),
        )
        if not option_columns:
            continue

        labels = [
            ScaleCode(code=i, label=col, role=CodeRole.excluded)
            for i, col in enumerate(option_columns, start=1)
        ]
        placeholders.append(
            Question(
                qid=root,
                text=group_text,
                qtype=QuestionType.multi_response,
                labels=labels,
                base_eligible=True,
            )
        )
    return placeholders


def parse_codebook(
    ws_datamap,
    overrides: dict[str, QuestionOverride] | None = None,
    a1_header: list[str] | None = None,
    nonsubstantive_labels: list[str] | None = None,
) -> list[Question]:
    """Parse the PureSpectrum Datamap sheet. Structurally identical to the
    Rakuten adapter's parse_codebook (Task 5/12) — same DatamapReader, same
    classify_question_type path — parameterised by PURESPECTRUM_PROFILE.
    QC2/QC2Flag are excluded here via a direct quality_columns membership
    check, since DatamapReader's own skip (via reserved_metadata_columns)
    already handles record/uuid/date/status/etc — quality columns still
    need to appear in the run summary's classification map (Task 24), so
    they are filtered from *question* construction here specifically, not
    from column classification generally.

    `a1_header`, when supplied, also backfills multi-select option columns
    the Datamap never declares (see _build_multi_response_placeholders).
    Optional and defaults to None so existing Datamap-only callers are
    unaffected.

    Single-pass unresolved-question collection (Task 5): every analysis
    question that doesn't achieve a full scale match and isn't already
    covered by a stored override is collected, EXCEPT a qid PureSpectrum's
    demographic YAML (vendor_purespectrum.yaml) declares as a
    source_column (D1 ethnicity, D3 gender) — those are exempt regardless
    of match outcome, the same as Rakuten's S-prefixed demographics. D2
    (age) is deliberately NOT in that YAML (reachability gap, see the
    YAML's own comment) so it is NOT exempt here either — a genuine
    question column the tool can't silently guess about, same as any
    other unmatched question. If anything was collected, raises exactly
    one UnresolvedQuestionsError after every column has been seen.
    """
    reader = DatamapReader(PURESPECTRUM_PROFILE)
    codebook: Codebook = reader.read_codebook(ws_datamap)

    questions: list[Question] = []
    collected: list[UnresolvedQuestion] = []
    for qid, (text, codes, qtype_hint) in codebook.items():
        if qid in PURESPECTRUM_PROFILE.quality_columns:
            continue
        _build_question(
            qid, text, qtype_hint, codes, questions, overrides or {}, collected, nonsubstantive_labels
        )

    if collected:
        raise UnresolvedQuestionsError(collected)

    questions.extend(_build_multi_response_placeholders(codebook, a1_header))
    return questions


def _build_question(
    qid: str,
    text: str,
    qtype_hint: str | None,
    codes: list[tuple[int, str]],
    out: list[Question],
    overrides: dict[str, QuestionOverride],
    collected: list[UnresolvedQuestion],
    nonsubstantive_labels: list[str] | None = None,
) -> None:
    if qtype_hint == "open_numeric":
        out.append(Question(qid=qid, text=text, qtype=QuestionType.numeric_open, base_eligible=False))
        return
    if qtype_hint == "open_text":
        out.append(Question(qid=qid, text=text, qtype=QuestionType.text_open, base_eligible=False))
        return

    if not codes:
        return

    norm_labels = [normalize_label(label) for _, label in codes]
    ns_overrides: dict[str, CodeRole] = {
        nl: CodeRole.nonsubstantive for nl in norm_labels if is_nonsubstantive_label(nl, nonsubstantive_labels)
    }
    substantive_norm = [nl for nl in norm_labels if nl not in ns_overrides]
    is_declared_demographic = qid in _DEMOGRAPHIC_SOURCE_COLUMNS

    override_result = resolve_with_override(substantive_norm, overrides, qid)
    if override_result is not None:
        qtype, roles, family = override_result
    else:
        classified = classify_question_type(substantive_norm)
        if classified is None:
            if is_declared_demographic:
                qtype, roles, family = QuestionType.categorical, None, None
            else:
                unresolved = collect_unresolved_question(
                    qid, text, codes, substantive_norm, override=None
                )
                if unresolved is not None:
                    collected.append(unresolved)
                return
        else:
            qtype, roles, family = classified

    if qtype is QuestionType.excluded:
        out.append(Question(qid=qid, text=text, qtype=QuestionType.excluded, base_eligible=False))
        return

    if qtype is QuestionType.scale:
        for ns_label, ns_role in ns_overrides.items():
            roles[ns_label] = ns_role

        substantive_codes_sorted = [
            (code, normalize_label(label))
            for code, label in sorted(codes, key=lambda x: x[0])
            if normalize_label(label) not in ns_overrides
        ]
        direction: str | None = None
        if substantive_codes_sorted:
            lowest_role = roles.get(substantive_codes_sorted[0][1])
            if lowest_role is CodeRole.bottom:
                direction = "ascending"
            elif lowest_role is CodeRole.top:
                direction = "descending"

        scale_codes = [
            ScaleCode(code=code, label=normalize_label(label), role=roles[normalize_label(label)], numeric_value=code)
            for code, label in codes
        ]
        out.append(
            Question(
                qid=qid, text=text, qtype=QuestionType.scale, labels=scale_codes,
                scale_direction=direction, scale_family=family, base_eligible=True,
            )
        )
        return

    labels_out = [
        ScaleCode(
            code=code,
            label=normalize_label(label),
            role=CodeRole.nonsubstantive if normalize_label(label) in ns_overrides else CodeRole.excluded,
            numeric_value=code,
        )
        for code, label in codes
    ]
    out.append(Question(qid=qid, text=text, qtype=qtype, labels=labels_out, base_eligible=True))


def load_respondents(
    ws_a1, questions: list[Question], nonsubstantive_labels: list[str] | None = None
) -> tuple[list[Response], int]:
    """Identical shape to Rakuten's load_respondents (rakuten.py:201-271),
    parameterised by PURESPECTRUM_PROFILE instead of hardcoded column
    names. respondent_id resolution mirrors Rakuten's uuid-then-record
    fallback since PureSpectrum's reserved columns include both."""
    rows = ws_a1.iter_rows(values_only=True)
    header = next(rows)
    col_index: dict[str, int] = {str(h): i for i, h in enumerate(header) if h is not None}

    uuid_col = col_index.get("uuid")
    record_col = col_index.get("record")

    qid_to_col: dict[str, int] = {q.qid: col_index[q.qid] for q in questions if q.qid in col_index}
    q_by_qid: dict[str, Question] = {q.qid: q for q in questions}

    responses: list[Response] = []
    n_raw = 0

    for row in rows:
        if all(v is None for v in row):
            break

        respondent_id: str
        if uuid_col is not None and row[uuid_col] is not None:
            respondent_id = str(row[uuid_col])
        elif record_col is not None and row[record_col] is not None:
            respondent_id = str(row[record_col])
        else:
            continue

        n_raw += 1

        for qid, col_idx in qid_to_col.items():
            raw = row[col_idx]
            if isinstance(raw, float) and raw == int(raw):
                raw = int(raw)
            q = q_by_qid[qid]
            state = classify_response(raw, q, nonsubstantive_labels=nonsubstantive_labels)
            responses.append(Response(respondent_id=respondent_id, qid=qid, raw_value=raw, state=state))

    return responses, n_raw


def read_status_values(path: Path) -> list[str]:
    """Raw values of the 'status' column across all data rows, for the run
    summary's disposition counts (prompt 7). PureSpectrum's profile
    declares 'status' as reserved metadata (vendor_profile.py), so it's
    never built into a Question — this reads it directly."""
    try:
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    except (InvalidFileException, OSError, KeyError, zipfile.BadZipFile):
        return []
    try:
        ws = wb[PURESPECTRUM_PROFILE.data_sheet]
        rows = ws.iter_rows(values_only=True)
        header = next(rows, None)
        if header is None or "status" not in header:
            return []
        status_idx = header.index("status")
        values: list[str] = []
        for row in rows:
            if all(v is None for v in row):
                break
            if row[status_idx] is not None:
                values.append(str(row[status_idx]))
        return values
    finally:
        wb.close()


def column_qid_map(path: Path) -> tuple[list[str], dict[str, str]]:
    """Returns (header, qid_by_column) for the run summary's column
    inventory (prompt 7). Most PureSpectrum columns are an identity mapping
    (the qid is the literal A1 column name), except the multi-select
    "r<N>" option columns (Q10r1..Q10r8, D4r1..D4r7) that
    _build_multi_response_placeholders groups under one root qid (Q10, D4)
    — those map to the group's qid instead of their own column name, so
    the inventory attributes them to the Question that was actually built."""
    try:
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    except (InvalidFileException, OSError, KeyError, zipfile.BadZipFile) as exc:
        raise SurveyToolError(
            ErrorCode.FILE_UNREADABLE,
            "This file could not be opened as a PureSpectrum export.",
            detail=str(exc),
            next_action="Confirm the file is a complete, un-corrupted .xlsx export, or pick a different file.",
        ) from exc
    try:
        ws = wb[PURESPECTRUM_PROFILE.data_sheet]
        header = next(ws.iter_rows(max_row=1, values_only=True), None)
        ws_datamap = wb[PURESPECTRUM_PROFILE.codebook_sheet]
        codebook = DatamapReader(PURESPECTRUM_PROFILE).read_codebook(ws_datamap)
    finally:
        wb.close()
    if header is None:
        return [], {}
    columns = [str(h) for h in header if h is not None]

    multiselect_root_by_prefix: dict[str, str] = {}
    for qid in codebook:
        m = _MULTISELECT_OE_RE.match(qid)
        if m is not None:
            multiselect_root_by_prefix[m.group("root")] = m.group("root")

    qid_by_column: dict[str, str] = {}
    for column in columns:
        matched_root = next(
            (root for root in multiselect_root_by_prefix if re.match(rf"^{re.escape(root)}r\d+$", column)),
            None,
        )
        qid_by_column[column] = matched_root if matched_root is not None else column
    return columns, qid_by_column


def load(
    path: Path,
    survey_id: str,
    overrides: dict[str, QuestionOverride] | None = None,
    nonsubstantive_labels: list[str] | None = None,
) -> Survey:
    """Load a PureSpectrum xlsx file and return a canonical Survey.

    `nonsubstantive_labels`, when provided, is the project's configured
    non-substantive label list (Task 7); None falls back to the built-in
    defaults, preserving prior behavior for projects that haven't
    customized the list.
    """
    try:
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    except (InvalidFileException, OSError, KeyError, zipfile.BadZipFile) as exc:
        raise SurveyToolError(
            ErrorCode.FILE_UNREADABLE,
            "This file could not be opened as a PureSpectrum export.",
            detail=str(exc),
            next_action="Confirm the file is a complete, un-corrupted .xlsx export, or pick a different file.",
        ) from exc

    try:
        try:
            ws_datamap = wb[PURESPECTRUM_PROFILE.codebook_sheet]
        except KeyError as exc:
            raise SurveyToolError(
                ErrorCode.MISSING_SHEET,
                "This file does not look like a PureSpectrum export.",
                detail=f"No {PURESPECTRUM_PROFILE.codebook_sheet} sheet was found.",
                next_action="Check the vendor setting, or pick a different file.",
            ) from exc

        try:
            ws_respondents = wb[PURESPECTRUM_PROFILE.data_sheet]
        except KeyError as exc:
            raise SurveyToolError(
                ErrorCode.MISSING_SHEET,
                "This file does not look like a PureSpectrum export.",
                detail=f"No {PURESPECTRUM_PROFILE.data_sheet} respondent-data sheet was found.",
                next_action="Check the vendor setting, or pick a different file.",
            ) from exc

        a1_header_row = next(ws_respondents.iter_rows(max_row=1, values_only=True), None)
        a1_header = [str(h) if h is not None else None for h in a1_header_row] if a1_header_row else None
        questions = parse_codebook(ws_datamap, overrides, a1_header, nonsubstantive_labels)
        if not questions:
            raise SurveyToolError(
                ErrorCode.NO_QUESTIONS_FOUND,
                "This file was read but has no computable questions in it.",
                next_action="Check the Datamap sheet, or pick a different file.",
            )
        responses, n_raw = load_respondents(ws_respondents, questions, nonsubstantive_labels)
    finally:
        wb.close()

    return Survey(id=survey_id, n_raw=n_raw, n_analysis=n_raw, questions=questions, responses=responses)
