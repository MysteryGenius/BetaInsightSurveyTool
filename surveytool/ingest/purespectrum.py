from __future__ import annotations

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
    ResponseState,
    ScaleCode,
    Survey,
)
from surveytool.core.nonsubstantive import classify_response, is_nonsubstantive_label
from surveytool.core.scale_library import classify_question_type
from surveytool.ingest.datamap_reader import Codebook, DatamapReader
from surveytool.ingest.overrides import QuestionOverride, resolve_with_override
from surveytool.ingest.validate_questions import AutoCategorical, assert_no_duplicate_codes, classify_or_collect
from surveytool.ingest.vendor_profile import PURESPECTRUM_PROFILE

_DEMOGRAPHIC_SOURCE_COLUMNS = declared_demographic_source_columns("purespectrum")


def _build_multi_response_questions(codebook: Codebook) -> list[Question]:
    """PureSpectrum's Datamap represents a multi-select "check all that
    apply" question group as a single unbracketed block whose code rows are
    option-definition rows (e.g. "[Q10r1]": "Loss of language / dialect
    itself") keyed to that option's own A1 data column, rather than a
    numeric code-to-label mapping (see DatamapReader.read_codebook, which
    separates these into the block's `options` list). One Question is built
    per such block, qid'd by the block's own qid (e.g. "Q10"), with one
    ScaleCode per option carrying the real vendor-supplied label — the
    option's own column name is stored as the code so load_respondents can
    map each option back to its A1 column.
    """
    questions: list[Question] = []
    for qid, (text, _codes, qtype_hint, options) in codebook.items():
        if qtype_hint is not None or not options:
            continue
        labels = [
            ScaleCode(code=column, label=normalize_label(label), role=CodeRole.excluded)
            for column, label in options
        ]
        questions.append(
            Question(
                qid=qid,
                text=text,
                qtype=QuestionType.multi_response,
                labels=labels,
                multi_response_delimiter="; ",
                base_eligible=True,
            )
        )
    return questions


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

    `a1_header` is accepted for backward compatibility with existing callers
    but is no longer used: multi-select question groups (e.g. Q10, D4) are
    now built directly from the Datamap's own option-definition rows (see
    _build_multi_response_questions), not inferred from the A1 header.

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
    for qid, (text, codes, qtype_hint, options) in codebook.items():
        if qid in PURESPECTRUM_PROFILE.quality_columns:
            continue
        if options:
            continue
        _build_question(
            qid, text, qtype_hint, codes, questions, overrides or {}, collected, nonsubstantive_labels
        )

    if collected:
        raise UnresolvedQuestionsError(collected)

    questions.extend(_build_multi_response_questions(codebook))
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

    assert_no_duplicate_codes(qid, codes)

    norm_labels = [normalize_label(label) for _, label in codes]
    ns_overrides: dict[str, CodeRole] = {
        nl: CodeRole.nonsubstantive for nl in norm_labels if is_nonsubstantive_label(nl, nonsubstantive_labels)
    }
    substantive_norm = [nl for nl in norm_labels if nl not in ns_overrides]
    is_declared_demographic = qid in _DEMOGRAPHIC_SOURCE_COLUMNS

    override_result = resolve_with_override(substantive_norm, overrides, qid)
    if override_result is not None:
        qtype, roles, family, variant_name = override_result
    else:
        classified = classify_question_type(substantive_norm)
        if classified is None:
            if is_declared_demographic:
                qtype, roles, family, variant_name = QuestionType.categorical, None, None, None
            else:
                # Round A prompt A4: still collect for the resolver if the
                # label set shows evidence of being ordinal; otherwise
                # classify as categorical outright with a recorded reason.
                outcome = classify_or_collect(qid, text, codes, substantive_norm, override=None)
                if isinstance(outcome, AutoCategorical):
                    out.append(
                        Question(
                            qid=qid, text=text, qtype=QuestionType.categorical,
                            labels=[
                                ScaleCode(code=code, label=normalize_label(label), role=CodeRole.excluded, numeric_value=code)
                                for code, label in codes
                            ],
                            base_eligible=True,
                            categorical_reason=outcome.reason,
                        )
                    )
                elif outcome is not None:
                    collected.append(outcome)
                return
        else:
            qtype, roles, family, variant_name = classified

    if qtype is QuestionType.excluded:
        out.append(Question(qid=qid, text=text, qtype=QuestionType.excluded, base_eligible=False))
        return

    if qtype is QuestionType.scale:
        for ns_label, ns_role in ns_overrides.items():
            roles[ns_label] = (ns_role, None)

        scale_codes = [
            ScaleCode(
                code=code,
                label=normalize_label(label),
                role=roles[normalize_label(label)][0],
                numeric_value=code,
                rank=roles[normalize_label(label)][1],
            )
            for code, label in codes
        ]

        substantive_ranked = sorted(
            (sc for sc in scale_codes if sc.rank is not None),
            key=lambda sc: sc.rank,
        )
        direction: str | None = None
        if substantive_ranked:
            # See rakuten.py's identical block for the full rationale:
            # direction here is informational-only provenance about
            # whether vendor code order agrees with rank order, never used
            # to derive rank/role/netting/mean.
            codes_by_rank_order = [sc.code for sc in substantive_ranked]
            codes_in_codebook_order = [c for c, lb in codes if normalize_label(lb) not in ns_overrides]
            if codes_in_codebook_order == codes_by_rank_order:
                direction = "ascending"
            elif codes_in_codebook_order == list(reversed(codes_by_rank_order)):
                direction = "descending"

        out.append(
            Question(
                qid=qid, text=text, qtype=QuestionType.scale, labels=scale_codes,
                scale_direction=direction, scale_family=family, scale_variant=variant_name,
                base_eligible=True,
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

    single_column_questions = [q for q in questions if q.qtype is not QuestionType.multi_response]
    multi_response_questions = [q for q in questions if q.qtype is QuestionType.multi_response]

    qid_to_col: dict[str, int] = {
        q.qid: col_index[q.qid] for q in single_column_questions if q.qid in col_index
    }
    q_by_qid: dict[str, Question] = {q.qid: q for q in single_column_questions}

    # Each multi-select ScaleCode.code is the option's own A1 column name
    # (see _build_multi_response_questions), so a group's flag columns are
    # read positionally per question rather than through a single qid->col
    # lookup.
    multi_option_cols: dict[str, list[tuple[str, int]]] = {
        q.qid: [(sc.code, col_index[sc.code]) for sc in q.labels if sc.code in col_index]
        for q in multi_response_questions
    }

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

        for qid, option_cols in multi_option_cols.items():
            flag_values = [row[col_idx] for _code, col_idx in option_cols]
            if all(v is None for v in flag_values):
                responses.append(
                    Response(respondent_id=respondent_id, qid=qid, raw_value=None, state=ResponseState.not_asked)
                )
                continue
            selected = [code for (code, col_idx), v in zip(option_cols, flag_values) if v]
            raw_value = "; ".join(selected)
            responses.append(
                Response(respondent_id=respondent_id, qid=qid, raw_value=raw_value, state=ResponseState.answered)
            )

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
    option columns (Q10r1..Q10r8, D4r1..D4r7) that the Datamap's own
    option-definition rows key to their group's qid (Q10, D4) — see
    DatamapReader.read_codebook's `options` field. Those map to the group's
    qid instead of their own column name, so the inventory attributes them
    to the Question that was actually built."""
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

    root_by_option_column: dict[str, str] = {
        column: qid
        for qid, (_text, _codes, _qtype_hint, options) in codebook.items()
        for column, _label in options
    }

    qid_by_column: dict[str, str] = {
        column: root_by_option_column.get(column, column) for column in columns
    }
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
