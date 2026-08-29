from __future__ import annotations

import re
import zipfile
from pathlib import Path

import openpyxl
from openpyxl.utils.exceptions import InvalidFileException

from surveytool.charts.errors import ErrorCode, SurveyToolError, UnresolvedQuestion, UnresolvedQuestionsError
from surveytool.core.demographic_registry import declared_demographic_source_columns
from surveytool.core.demographics import text_matches_demographic
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
from surveytool.core.scale_library import MatchOutcome, identify_family, match_family
from surveytool.ingest.overrides import QuestionOverride, apply_override
from surveytool.ingest.validate_questions import AutoCategorical, classify_or_collect

_DEMOGRAPHIC_SOURCE_COLUMNS = declared_demographic_source_columns("toluna")

_HEADER_RE = re.compile(r"^(?P<num>\d+)\s*:\s*(?P<rest>.+)$")
_RESPID_COLUMN = "respid"
_SHEET_NAME = "RespondentData.Text"

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(text: str, max_len: int = 40) -> str:
    slug = _SLUG_RE.sub("_", text.lower()).strip("_")
    return slug[:max_len].rstrip("_")


class _HeaderInfo:
    __slots__ = ("num", "stem", "sub_item", "column")

    def __init__(self, num: str, stem: str, sub_item: str | None, column: str) -> None:
        self.num = num
        self.stem = stem
        self.sub_item = sub_item
        self.column = column


def _parse_header_cell(column: str) -> _HeaderInfo | None:
    m = _HEADER_RE.match(column.strip())
    if not m:
        return None
    num = m.group("num").strip()
    rest = normalize_label(m.group("rest"))

    stem = rest
    sub_item: str | None = None
    if "?" in rest:
        stem_part, _, sub_part = rest.rpartition("?")
        sub_part = sub_part.strip()
        if sub_part:
            stem = stem_part.strip() + "?"
            sub_item = sub_part

    return _HeaderInfo(num=num, stem=stem, sub_item=sub_item, column=column)


def _collect_single_values(rows: list[tuple], col_idx: int) -> list[str]:
    seen: dict[str, None] = {}
    for row in rows:
        raw = row[col_idx] if col_idx < len(row) else None
        if raw is None:
            continue
        value = normalize_label(str(raw))
        if not value:
            continue
        seen.setdefault(value, None)
    return list(seen.keys())


def _build_scale_question(
    qid: str,
    text: str,
    values: list[str],
    grid_group: str | None,
    override: QuestionOverride | None = None,
    nonsubstantive_labels: list[str] | None = None,
) -> Question:
    """Builds a scale Question. Caller (parse_header) is responsible for
    only reaching this function once it already knows the substantive
    label set achieves a full match_family outcome (or an override says
    scale). Role and rank both come from the matched variant (Task B3) --
    `values`' own data-appearance order plays no part in role, rank,
    netting, or mean; it is used only as the ScaleCode.code join key
    (a synthesized 1-based sequential id, since Toluna has no real vendor
    numeric code) and, informationally, for `scale_direction`.
    """
    ns_overrides: dict[str, CodeRole] = {
        v: CodeRole.nonsubstantive for v in values if is_nonsubstantive_label(v, nonsubstantive_labels)
    }
    substantive_values = [v for v in values if v not in ns_overrides]

    variant_name: str | None = None
    if override is not None:
        roles: dict[str, tuple[CodeRole, int | None]] = apply_override(substantive_values, override)
        family = identify_family(substantive_values, qid=qid)
    else:
        match = match_family(substantive_values)
        roles = dict(match.matched_labels)
        variant_name = match.variant
        # match.outcome is guaranteed MatchOutcome.full here (the caller
        # only reaches this function once parse_header has confirmed that),
        # and full now means full coverage in both directions (every label
        # matched AND every variant point covered) -- so match.family and
        # identify_family(substantive_values) agree by construction. Using
        # match.family directly avoids a second, redundant full scan of the
        # library that could theoretically disagree with match.outcome.
        family = match.family
    for label, role in ns_overrides.items():
        roles[label] = (role, None)

    ranked_values = sorted(
        (v for v in substantive_values if roles[v][1] is not None),
        key=lambda v: roles[v][1],
    )
    direction: str | None = None
    if ranked_values:
        if substantive_values == ranked_values:
            direction = "ascending"
        elif substantive_values == list(reversed(ranked_values)):
            direction = "descending"

    labels: list[ScaleCode] = []
    for i, value in enumerate(values, start=1):
        role, rank = roles[value]
        numeric_value = i if role is not CodeRole.nonsubstantive else None
        labels.append(ScaleCode(code=i, label=value, role=role, numeric_value=numeric_value, rank=rank))

    return Question(
        qid=qid,
        text=text,
        qtype=QuestionType.scale,
        labels=labels,
        scale_direction=direction,
        scale_family=family,
        scale_variant=variant_name,
        grid_group=grid_group,
        base_eligible=True,
    )


def _build_single_choice_question(
    qid: str,
    text: str,
    values: list[str],
    qtype: QuestionType = QuestionType.single_choice,
    nonsubstantive_labels: list[str] | None = None,
    categorical_reason: str | None = None,
) -> Question:
    """Builds a non-scale question. `qtype` defaults to single_choice (the
    auto-detected shape), but a binary/categorical override passes its real
    question_type through here so the override's classification choice
    survives rather than collapsing to single_choice regardless of which
    the analyst actually picked. `categorical_reason` (Round A prompt A4)
    records why an auto-classified categorical question was classified that
    way."""
    labels = [
        ScaleCode(
            code=i,
            label=v,
            role=CodeRole.nonsubstantive if is_nonsubstantive_label(v, nonsubstantive_labels) else CodeRole.excluded,
        )
        for i, v in enumerate(values, start=1)
    ]
    return Question(
        qid=qid,
        text=text,
        qtype=qtype,
        labels=labels,
        base_eligible=True,
        is_demographic=text_matches_demographic(text),
        categorical_reason=categorical_reason,
    )


def _substantive_values(values: list[str], nonsubstantive_labels: list[str] | None = None) -> list[str]:
    return [v for v in values if not is_nonsubstantive_label(v, nonsubstantive_labels)]


def parse_header(
    header: tuple,
    rows: list[tuple],
    overrides: dict[str, QuestionOverride] | None = None,
    nonsubstantive_labels: list[str] | None = None,
) -> tuple[list[Question], dict[str, int]]:
    """Parse Toluna xlsx column headers into canonical Questions.

    Returns (questions, col_idx_by_qid).

    Single-pass unresolved-question collection (Task 5): a column with no
    override that doesn't achieve a full match_family outcome is collected
    instead of being silently demoted to single_choice (the old
    any_label_matches_family gate) or hard-failing the whole file (the old
    resolve_roles raise on a partial match). A column whose qid is one of
    Toluna's declared demographic source_columns (vendor_toluna.yaml —
    columns 1/3/4/5 in the real fixture) is exempt regardless of match
    outcome, same as an override. If anything was collected across the
    whole file, raises exactly one UnresolvedQuestionsError after every
    column has been seen, not on the first miss.
    """
    overrides = overrides or {}
    header_infos: list[_HeaderInfo] = []
    col_idx_by_column: dict[str, int] = {}
    cols_by_num: dict[str, list[int]] = {}

    for idx, cell in enumerate(header):
        if cell is None or str(cell).strip() == _RESPID_COLUMN:
            continue
        info = _parse_header_cell(str(cell))
        if info is None:
            continue
        header_infos.append(info)
        col_idx_by_column[info.column] = idx
        cols_by_num.setdefault(info.num, []).append(idx)

    questions: list[Question] = []
    col_idx_by_qid: dict[str, int] = {}
    collected: list[UnresolvedQuestion] = []

    for info in header_infos:
        idx = col_idx_by_column[info.column]
        is_grid = len(cols_by_num[info.num]) > 1

        if is_grid:
            sub_item = info.sub_item or info.stem
            qid = f"{info.num}_{_slugify(sub_item)}"
            text = sub_item
            grid_group = f"grid_{info.num}"
        else:
            qid = info.num
            text = info.stem
            grid_group = None

        values = _collect_single_values(rows, idx)
        override = overrides.get(qid)

        if override is not None and override.question_type == "excluded":
            question = Question(qid=qid, text=text, qtype=QuestionType.excluded, base_eligible=False)
        elif override is not None and override.question_type == "scale":
            question = _build_scale_question(
                qid, text, values, grid_group, override=override, nonsubstantive_labels=nonsubstantive_labels
            )
        elif override is not None:
            question = _build_single_choice_question(
                qid,
                text,
                values,
                qtype=QuestionType(override.question_type),
                nonsubstantive_labels=nonsubstantive_labels,
            )
        elif qid in _DEMOGRAPHIC_SOURCE_COLUMNS:
            question = _build_single_choice_question(qid, text, values, nonsubstantive_labels=nonsubstantive_labels)
        else:
            match = match_family(_substantive_values(values, nonsubstantive_labels))
            if match.outcome is MatchOutcome.full:
                question = _build_scale_question(qid, text, values, grid_group, nonsubstantive_labels=nonsubstantive_labels)
            else:
                outcome = classify_or_collect(
                    qid,
                    text,
                    list(enumerate(values, start=1)),
                    _substantive_values(values, nonsubstantive_labels),
                    override=None,
                )
                if isinstance(outcome, AutoCategorical):
                    question = _build_single_choice_question(
                        qid, text, values, qtype=QuestionType.categorical,
                        nonsubstantive_labels=nonsubstantive_labels, categorical_reason=outcome.reason,
                    )
                else:
                    if outcome is not None:
                        collected.append(outcome)
                    col_idx_by_qid[qid] = idx
                    continue

        questions.append(question)
        col_idx_by_qid[qid] = idx

    if collected:
        raise UnresolvedQuestionsError(collected)

    return questions, col_idx_by_qid


def load_respondents(
    rows: list[tuple],
    questions: list[Question],
    col_idx_by_qid: dict[str, int],
    respid_col: int,
    nonsubstantive_labels: list[str] | None = None,
) -> tuple[list[Response], int]:
    """Load respondents from parsed xlsx rows into canonical Responses."""
    q_by_qid: dict[str, Question] = {q.qid: q for q in questions}
    responses: list[Response] = []
    n_raw = 0

    for row in rows:
        raw_respid = row[respid_col] if respid_col < len(row) else None
        if raw_respid is None:
            continue
        respondent_id = str(raw_respid).strip()
        if not respondent_id:
            continue
        n_raw += 1

        for qid, question in q_by_qid.items():
            col_idx = col_idx_by_qid[qid]
            raw = row[col_idx] if col_idx < len(row) else None
            cell = str(raw).strip() if raw is not None else ""

            if not cell:
                responses.append(
                    Response(
                        respondent_id=respondent_id,
                        qid=qid,
                        raw_value=None,
                        state=ResponseState.not_asked,
                    )
                )
                continue

            code_by_label = {sc.label: sc.code for sc in question.labels}
            label = normalize_label(cell)
            value = code_by_label.get(label, label)
            state = classify_response(value, question, nonsubstantive_labels=nonsubstantive_labels)

            responses.append(
                Response(
                    respondent_id=respondent_id,
                    qid=qid,
                    raw_value=value,
                    state=state,
                )
            )

    return responses, n_raw


def column_qid_map(
    path: Path,
    overrides: dict[str, QuestionOverride] | None = None,
    nonsubstantive_labels: list[str] | None = None,
) -> tuple[list[str], dict[str, str]]:
    """Returns (header, qid_by_column) for the run summary's column
    inventory (prompt 7). A grid question's qid (e.g.
    "7_local_mainstream_media") is a synthesized slug, not the literal
    column text, so the inventory needs this mapping to attribute each raw
    column to the Question it became. Mirrors load()'s own header-reading
    path exactly (same sheet, same parse_header call) so the mapping can
    never drift from what load() actually parsed.
    """
    try:
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    except (InvalidFileException, OSError, KeyError, zipfile.BadZipFile) as exc:
        raise SurveyToolError(
            ErrorCode.FILE_UNREADABLE,
            "This file could not be opened as a Toluna export.",
            detail=str(exc),
            next_action="Confirm the file is a complete, un-corrupted .xlsx export, or pick a different file.",
        ) from exc

    try:
        ws = wb[_SHEET_NAME]
        row_iter = ws.iter_rows(values_only=True)
        header = next(row_iter, None)
        if header is None:
            return [], {}

        rows: list[tuple] = []
        for row in row_iter:
            if all(v is None for v in row):
                break
            rows.append(row)

        questions, _ = parse_header(header, rows, overrides, nonsubstantive_labels)

        # parse_header iterates header_infos (built in the same header
        # order, skipping None/respid cells) in lockstep with the
        # questions it appends — recomputing header_infos the same way
        # lets us zip them back together to recover each column's qid.
        header_infos = [
            info
            for info in (
                _parse_header_cell(str(cell))
                for cell in header
                if cell is not None and str(cell).strip() != _RESPID_COLUMN
            )
            if info is not None
        ]
        qid_by_column = {info.column: question.qid for info, question in zip(header_infos, questions)}

        return [str(c) if c is not None else None for c in header], qid_by_column
    finally:
        wb.close()


def load(
    path: Path,
    survey_id: str,
    overrides: dict[str, QuestionOverride] | None = None,
    nonsubstantive_labels: list[str] | None = None,
) -> Survey:
    """Load a Toluna xlsx file and return a canonical Survey.

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
            "This file could not be opened as a Toluna export.",
            detail=str(exc),
            next_action="Confirm the file is a complete, un-corrupted .xlsx export, or pick a different file.",
        ) from exc

    try:
        try:
            ws = wb[_SHEET_NAME]
        except KeyError as exc:
            raise SurveyToolError(
                ErrorCode.MISSING_SHEET,
                "This file does not look like a Toluna export.",
                detail=f"No {_SHEET_NAME!r} sheet was found.",
                next_action="Check the vendor setting, or pick a different file.",
            ) from exc

        row_iter = ws.iter_rows(values_only=True)
        header = next(row_iter, None)
        if header is None:
            raise SurveyToolError(
                ErrorCode.NO_QUESTIONS_FOUND,
                "This file was read but has no computable questions in it.",
                next_action="Check the vendor setting, or pick a different file.",
            )

        rows: list[tuple] = []
        for row in row_iter:
            if all(v is None for v in row):
                break
            rows.append(row)

        try:
            respid_col = next(
                i for i, cell in enumerate(header) if cell is not None and str(cell).strip() == _RESPID_COLUMN
            )
        except StopIteration as exc:
            raise SurveyToolError(
                ErrorCode.MISSING_COLUMNS,
                "This file is missing an expected column.",
                detail=f"No {_RESPID_COLUMN!r} column was found in the header row.",
                next_action="Check the vendor setting, or pick a different file.",
            ) from exc

        questions, col_idx_by_qid = parse_header(header, rows, overrides, nonsubstantive_labels)
        if not questions:
            raise SurveyToolError(
                ErrorCode.NO_QUESTIONS_FOUND,
                "This file was read but has no computable questions in it.",
                next_action="Check the vendor setting, or pick a different file.",
            )
        responses, n_raw = load_respondents(rows, questions, col_idx_by_qid, respid_col, nonsubstantive_labels)
    finally:
        wb.close()

    return Survey(
        id=survey_id,
        n_raw=n_raw,
        n_analysis=n_raw,
        questions=questions,
        responses=responses,
    )
