from __future__ import annotations

import zipfile
from pathlib import Path

import openpyxl
from openpyxl.utils.exceptions import InvalidFileException

from surveytool.charts.errors import ErrorCode, SurveyToolError, UnresolvedQuestion, UnresolvedQuestionsError
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
from surveytool.ingest.vendor_profile import RAKUTEN_PROFILE


def parse_codebook(
    ws_datamap,
    overrides: dict[str, QuestionOverride] | None = None,
    nonsubstantive_labels: list[str] | None = None,
) -> list[Question]:
    """Parse the Rakuten Datamap sheet into a list of Questions.

    Single-pass unresolved-question collection (Task 5): every analysis
    question that doesn't achieve a full scale match via the shared scale
    library, and isn't already covered by a stored override, is collected
    here rather than silently demoted to categorical. S1-S4 demographics
    never reach _build_question's classification branch at all (handled by
    their own qid.startswith("S") path below), so they can never appear in
    the collected set. If anything was collected across the whole file,
    raises exactly one UnresolvedQuestionsError after every column has been
    seen, not on the first miss.

    `nonsubstantive_labels`, when provided, is the project's configured
    non-substantive label list (Task 7) and is authoritative for
    classifying option labels as non-substantive; None falls back to the
    built-in defaults.
    """
    reader = DatamapReader(RAKUTEN_PROFILE)
    codebook: Codebook = reader.read_codebook(ws_datamap)

    questions: list[Question] = []
    collected: list[UnresolvedQuestion] = []
    for qid, (text, codes, qtype_hint) in codebook.items():
        _build_question(
            qid, text, qtype_hint, codes, questions, overrides or {}, collected, nonsubstantive_labels
        )

    if collected:
        raise UnresolvedQuestionsError(collected)

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
        out.append(
            Question(
                qid=qid,
                text=text,
                qtype=QuestionType.numeric_open,
                base_eligible=False,
                is_demographic=qid.startswith("S"),
            )
        )
        return

    if qtype_hint == "open_text":
        out.append(
            Question(
                qid=qid,
                text=text,
                qtype=QuestionType.text_open,
                base_eligible=False,
                is_demographic=qid.startswith("S"),
            )
        )
        return

    if qid.startswith("S"):
        labels = [
            ScaleCode(code=code, label=label, role=CodeRole.excluded)
            for code, label in codes
        ]
        out.append(
            Question(
                qid=qid,
                text=text,
                qtype=QuestionType.demographic,
                labels=labels,
                base_eligible=False,
                is_demographic=True,
            )
        )
        return

    # Analysis question: classify as scale, binary, or categorical
    if not codes:
        return

    norm_labels = [normalize_label(label) for _, label in codes]

    ns_overrides: dict[str, CodeRole] = {}
    for nl in norm_labels:
        if is_nonsubstantive_label(nl, nonsubstantive_labels):
            ns_overrides[nl] = CodeRole.nonsubstantive

    substantive_norm = [nl for nl in norm_labels if nl not in ns_overrides]

    override_result = resolve_with_override(substantive_norm, overrides, qid)
    if override_result is not None:
        qtype, roles, family = override_result
    else:
        classified = classify_question_type(substantive_norm)
        if classified is None:
            # No override and no full scale/binary match: this is not this
            # function's call to make silently (Task 5) — collect it for
            # the resolver instead of demoting to categorical.
            unresolved = collect_unresolved_question(
                qid, text, codes, substantive_norm, override=None
            )
            if unresolved is not None:
                collected.append(unresolved)
            return
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
            ScaleCode(
                code=code,
                label=normalize_label(label),
                role=roles[normalize_label(label)],
                numeric_value=code,
            )
            for code, label in codes
        ]

        out.append(
            Question(
                qid=qid,
                text=text,
                qtype=QuestionType.scale,
                labels=scale_codes,
                scale_direction=direction,
                scale_family=family,
                base_eligible=True,
            )
        )
        return

    # BINARY (full match) or CATEGORICAL (only ever reached via an override
    # here, since the no-match/no-override case returned above): no
    # role/family resolution, no netting.
    labels_out = [
        ScaleCode(
            code=code,
            label=normalize_label(label),
            role=CodeRole.nonsubstantive if normalize_label(label) in ns_overrides else CodeRole.excluded,
            numeric_value=code,
        )
        for code, label in codes
    ]
    out.append(
        Question(
            qid=qid,
            text=text,
            qtype=qtype,
            labels=labels_out,
            base_eligible=True,
        )
    )


def load_respondents(
    ws_a1,
    questions: list[Question],
    nonsubstantive_labels: list[str] | None = None,
) -> tuple[list[Response], int]:
    """
    Load respondents from the A1 sheet.

    Returns (responses, n_raw) where n_raw is the number of data rows processed.
    Stops at the first all-None row.
    """
    rows = ws_a1.iter_rows(values_only=True)

    header = next(rows)
    col_index: dict[str, int] = {
        str(h): i for i, h in enumerate(header) if h is not None
    }

    flag_col: int | None = col_index.get(RAKUTEN_PROFILE.quality_flag_column)
    uuid_col: int | None = col_index.get("uuid")
    record_col: int | None = col_index.get("record")

    qid_to_col: dict[str, int] = {}
    for q in questions:
        if q.qid in col_index:
            qid_to_col[q.qid] = col_index[q.qid]

    q_by_qid: dict[str, Question] = {q.qid: q for q in questions}

    responses: list[Response] = []
    n_raw = 0

    for row in rows:
        # Stop on all-None row
        if all(v is None for v in row):
            break

        # Determine respondent_id
        respondent_id: str
        if uuid_col is not None and row[uuid_col] is not None:
            respondent_id = str(row[uuid_col])
        elif record_col is not None and row[record_col] is not None:
            respondent_id = str(row[record_col])
        else:
            continue

        n_raw += 1

        vendor_flag: str | None = None
        if flag_col is not None and row[flag_col] is not None:
            vendor_flag = str(row[flag_col])

        for qid, col_idx in qid_to_col.items():
            raw = row[col_idx]
            # Coerce float with no fractional part to int (Excel sometimes gives 4.0)
            if isinstance(raw, float) and raw == int(raw):
                raw = int(raw)

            q = q_by_qid[qid]
            state = classify_response(raw, q, nonsubstantive_labels=nonsubstantive_labels)

            responses.append(
                Response(
                    respondent_id=respondent_id,
                    qid=qid,
                    raw_value=raw,
                    state=state,
                    vendor_flag=vendor_flag,
                )
            )

    return responses, n_raw


def column_qid_map(path: Path) -> tuple[list[str], dict[str, str]]:
    """Returns (header, qid_by_column) for the run summary's column
    inventory (prompt 7). Rakuten's qid is the literal A1 sheet column
    name, so this is an identity mapping over the header row."""
    try:
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    except (InvalidFileException, OSError, KeyError, zipfile.BadZipFile) as exc:
        raise SurveyToolError(
            ErrorCode.FILE_UNREADABLE,
            "This file could not be opened as a Rakuten export.",
            detail=str(exc),
            next_action="Confirm the file is a complete, un-corrupted .xlsx export, or pick a different file.",
        ) from exc
    try:
        ws = wb[RAKUTEN_PROFILE.data_sheet]
        header = next(ws.iter_rows(max_row=1, values_only=True), None)
    finally:
        wb.close()
    if header is None:
        return [], {}
    columns = [str(h) for h in header if h is not None]
    return columns, {c: c for c in columns}


def load(
    path: Path,
    survey_id: str,
    overrides: dict[str, QuestionOverride] | None = None,
    nonsubstantive_labels: list[str] | None = None,
) -> Survey:
    """Load a Rakuten xlsx file and return a canonical Survey.

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
            "This file could not be opened as a Rakuten export.",
            detail=str(exc),
            next_action="Confirm the file is a complete, un-corrupted .xlsx export, or pick a different file.",
        ) from exc

    try:
        try:
            ws_datamap = wb[RAKUTEN_PROFILE.codebook_sheet]
        except KeyError as exc:
            raise SurveyToolError(
                ErrorCode.MISSING_SHEET,
                "This file does not look like a Rakuten export.",
                detail=f"No {RAKUTEN_PROFILE.codebook_sheet} sheet was found.",
                next_action="Check the vendor setting, or pick a different file.",
            ) from exc

        try:
            ws_respondents = wb[RAKUTEN_PROFILE.data_sheet]
        except KeyError as exc:
            raise SurveyToolError(
                ErrorCode.MISSING_SHEET,
                "This file does not look like a Rakuten export.",
                detail=f"No {RAKUTEN_PROFILE.data_sheet} respondent-data sheet was found.",
                next_action="Check the vendor setting, or pick a different file.",
            ) from exc

        questions = parse_codebook(ws_datamap, overrides, nonsubstantive_labels)
        if not questions:
            raise SurveyToolError(
                ErrorCode.NO_QUESTIONS_FOUND,
                "This file was read but has no computable questions in it.",
                next_action="Check the Datamap sheet, or pick a different file.",
            )
        responses, n_raw = load_respondents(ws_respondents, questions, nonsubstantive_labels)
    finally:
        wb.close()

    return Survey(
        id=survey_id,
        n_raw=n_raw,
        n_analysis=n_raw,
        questions=questions,
        responses=responses,
    )
