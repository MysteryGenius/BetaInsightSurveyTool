from __future__ import annotations

import zipfile
from pathlib import Path

import openpyxl
from openpyxl.utils.exceptions import InvalidFileException

from surveytool.charts.errors import ErrorCode, SurveyToolError
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
from surveytool.ingest.vendor_profile import PURESPECTRUM_PROFILE


def parse_codebook(ws_datamap) -> list[Question]:
    """Parse the PureSpectrum Datamap sheet. Structurally identical to the
    Rakuten adapter's parse_codebook (Task 5/12) — same DatamapReader, same
    classify_question_type path — parameterised by PURESPECTRUM_PROFILE.
    QC2/QC2Flag are excluded here via a direct quality_columns membership
    check, since DatamapReader's own skip (via reserved_metadata_columns)
    already handles record/uuid/date/status/etc — quality columns still
    need to appear in the run summary's classification map (Task 24), so
    they are filtered from *question* construction here specifically, not
    from column classification generally."""
    reader = DatamapReader(PURESPECTRUM_PROFILE)
    codebook: Codebook = reader.read_codebook(ws_datamap)

    questions: list[Question] = []
    for qid, (text, codes, qtype_hint) in codebook.items():
        if qid in PURESPECTRUM_PROFILE.quality_columns:
            continue
        _build_question(qid, text, qtype_hint, codes, questions)
    return questions


def _build_question(
    qid: str,
    text: str,
    qtype_hint: str | None,
    codes: list[tuple[int, str]],
    out: list[Question],
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
        nl: CodeRole.nonsubstantive for nl in norm_labels if is_nonsubstantive_label(nl)
    }
    substantive_norm = [nl for nl in norm_labels if nl not in ns_overrides]

    qtype, roles, family = classify_question_type(substantive_norm)

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


def load_respondents(ws_a1, questions: list[Question]) -> tuple[list[Response], int]:
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
            state = classify_response(raw, q)
            responses.append(Response(respondent_id=respondent_id, qid=qid, raw_value=raw, state=state))

    return responses, n_raw


def load(path: Path, survey_id: str) -> Survey:
    """Load a PureSpectrum xlsx file and return a canonical Survey."""
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

        questions = parse_codebook(ws_datamap)
        if not questions:
            raise SurveyToolError(
                ErrorCode.NO_QUESTIONS_FOUND,
                "This file was read but has no computable questions in it.",
                next_action="Check the Datamap sheet, or pick a different file.",
            )
        responses, n_raw = load_respondents(ws_respondents, questions)
    finally:
        wb.close()

    return Survey(id=survey_id, n_raw=n_raw, n_analysis=n_raw, questions=questions, responses=responses)
