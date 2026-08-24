from __future__ import annotations

import csv
import re
from pathlib import Path

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
from surveytool.ingest.validate_questions import collect_unresolved_question

_DEMOGRAPHIC_SOURCE_COLUMNS = declared_demographic_source_columns("milieu")

_HEADER_RE = re.compile(r"^\[(?P<qid>[^\]]+)\]:\s*(?P<qtype>.+?)\s+-\s+(?P<text>.*)$")
_MULTI_DELIMITER = "; "

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(text: str, max_len: int = 40) -> str:
    slug = _SLUG_RE.sub("_", text.lower()).strip("_")
    return slug[:max_len].rstrip("_")


class _HeaderInfo:
    __slots__ = ("qid", "qtype_token", "text", "grid_stem", "column")

    def __init__(self, qid: str, qtype_token: str, text: str, grid_stem: str | None, column: str) -> None:
        self.qid = qid
        self.qtype_token = qtype_token
        self.text = text
        self.grid_stem = grid_stem
        self.column = column


def _parse_header_cell(column: str) -> _HeaderInfo | None:
    m = _HEADER_RE.match(column.strip())
    if not m:
        return None
    qid = m.group("qid").strip()
    qtype_token = m.group("qtype").strip()
    text = normalize_label(m.group("text"))

    grid_stem: str | None = None
    if qtype_token == "Grid Single-select" and " - " in text:
        stem, _, sub_item = text.rpartition(" - ")
        grid_stem = stem.strip()
        text = sub_item.strip()

    return _HeaderInfo(qid=qid, qtype_token=qtype_token, text=text, grid_stem=grid_stem, column=column)


def _collect_single_values(rows: list[dict[str, str]], column: str) -> list[str]:
    seen: dict[str, None] = {}
    for row in rows:
        raw = row.get(column)
        if raw is None:
            continue
        value = normalize_label(raw)
        if not value:
            continue
        seen.setdefault(value, None)
    return list(seen.keys())


def _collect_multi_values(rows: list[dict[str, str]], column: str) -> list[str]:
    seen: dict[str, None] = {}
    for row in rows:
        raw = row.get(column)
        if raw is None:
            continue
        cell = raw.strip()
        if not cell:
            continue
        for part in cell.split(_MULTI_DELIMITER):
            value = normalize_label(part)
            if not value:
                continue
            seen.setdefault(value, None)
    return list(seen.keys())


def _build_scale_question(
    info: _HeaderInfo,
    values: list[str],
    grid_group: str | None,
    override: QuestionOverride | None = None,
) -> Question:
    """Builds a scale Question. Caller (parse_header) is responsible for
    only reaching this function once it already knows the substantive
    label set achieves a full match_family outcome (or an override says
    scale) — this function no longer calls resolve_roles/raises on its own
    (Task 5 removed the load-path raise), it just re-derives the same
    roles match_family already computed."""
    ns_overrides: dict[str, CodeRole] = {
        v: CodeRole.nonsubstantive for v in values if is_nonsubstantive_label(v)
    }
    substantive_values = [v for v in values if v not in ns_overrides]

    if override is not None:
        roles = apply_override(substantive_values, override)
    else:
        match = match_family(substantive_values)
        roles = dict(match.matched_labels)
    for label, role in ns_overrides.items():
        roles[label] = role

    ordered_substantive = [v for v in substantive_values]
    direction: str | None = None
    if ordered_substantive:
        first_role = roles.get(ordered_substantive[0])
        last_role = roles.get(ordered_substantive[-1])
        if first_role is CodeRole.top:
            direction = "descending"
        elif first_role is CodeRole.bottom:
            direction = "ascending"
        elif last_role is CodeRole.top:
            direction = "ascending"
        elif last_role is CodeRole.bottom:
            direction = "descending"

    family = identify_family(substantive_values)

    labels: list[ScaleCode] = []
    for i, value in enumerate(values, start=1):
        role = roles[value]
        numeric_value = i if role is not CodeRole.nonsubstantive else None
        labels.append(ScaleCode(code=i, label=value, role=role, numeric_value=numeric_value))

    return Question(
        qid=info.qid,
        text=info.text,
        qtype=QuestionType.scale,
        labels=labels,
        scale_direction=direction,
        scale_family=family,
        grid_group=grid_group,
        base_eligible=True,
    )


def _build_single_choice_question(
    info: _HeaderInfo,
    values: list[str],
    qtype: QuestionType = QuestionType.single_choice,
) -> Question:
    """Builds a non-scale question. `qtype` defaults to single_choice (the
    auto-detected shape), but a binary/categorical override passes its real
    question_type through here so the override's classification choice
    survives rather than collapsing to single_choice regardless of which
    the analyst actually picked (see resolve_with_override)."""
    labels = [
        ScaleCode(
            code=i,
            label=v,
            role=CodeRole.nonsubstantive if is_nonsubstantive_label(v) else CodeRole.excluded,
        )
        for i, v in enumerate(values, start=1)
    ]
    return Question(
        qid=info.qid,
        text=info.text,
        qtype=qtype,
        labels=labels,
        base_eligible=True,
        is_demographic=text_matches_demographic(info.text),
    )


def _build_multi_response_question(info: _HeaderInfo, values: list[str]) -> Question:
    labels = [
        ScaleCode(
            code=i,
            label=v,
            role=CodeRole.nonsubstantive if is_nonsubstantive_label(v) else CodeRole.excluded,
        )
        for i, v in enumerate(values, start=1)
    ]
    return Question(
        qid=info.qid,
        text=info.text,
        qtype=QuestionType.multi_response,
        labels=labels,
        multi_response_delimiter=_MULTI_DELIMITER,
        base_eligible=True,
    )


def _substantive_values(values: list[str]) -> list[str]:
    return [v for v in values if not is_nonsubstantive_label(v)]


def parse_header(
    fieldnames: list[str],
    rows: list[dict[str, str]],
    overrides: dict[str, QuestionOverride] | None = None,
) -> list[Question]:
    """Parse Milieu CSV column headers into canonical Questions.

    Single-pass unresolved-question collection (Task 5): a Single-select or
    Grid Single-select column with no override that doesn't achieve a full
    match_family outcome is collected instead of being silently demoted to
    single_choice (the old any_label_matches_family gate) or hard-failing
    the whole file (the old resolve_roles raise on a partial match). A
    column whose qid is one of Milieu's declared demographic source_columns
    (vendor_milieu.yaml — q5-q8 in the real fixture) is exempt regardless
    of match outcome, same as an override. If anything was collected across
    the whole file, raises exactly one UnresolvedQuestionsError after every
    column has been seen, not on the first miss.
    """
    overrides = overrides or {}
    questions: list[Question] = []
    grid_group_by_stem: dict[str, str] = {}
    collected: list[UnresolvedQuestion] = []

    for column in fieldnames:
        info = _parse_header_cell(column)
        if info is None:
            continue

        override = overrides.get(info.qid)
        if override is not None and override.question_type == "excluded":
            questions.append(Question(qid=info.qid, text=info.text, qtype=QuestionType.excluded, base_eligible=False))
            continue

        if info.qtype_token == "Multi-select":
            values = _collect_multi_values(rows, column)
            questions.append(_build_multi_response_question(info, values))
            continue

        values = _collect_single_values(rows, column)

        if info.qtype_token == "Grid Single-select":
            grid_group = grid_group_by_stem.setdefault(
                info.grid_stem or info.qid, f"grid_{_slugify(info.grid_stem or info.qid)}"
            )
            if override is not None and override.question_type == "scale":
                questions.append(_build_scale_question(info, values, grid_group, override=override))
                continue
            if override is not None:
                questions.append(_build_single_choice_question(info, values, qtype=QuestionType(override.question_type)))
                continue
            if info.qid in _DEMOGRAPHIC_SOURCE_COLUMNS:
                questions.append(_build_single_choice_question(info, values))
                continue
            match = match_family(_substantive_values(values))
            if match.outcome is MatchOutcome.full:
                questions.append(_build_scale_question(info, values, grid_group))
            else:
                unresolved = collect_unresolved_question(
                    info.qid, info.text, list(enumerate(values, start=1)), _substantive_values(values), override=None
                )
                if unresolved is not None:
                    collected.append(unresolved)
            continue

        if info.qtype_token == "Single-select":
            if override is not None and override.question_type == "scale":
                questions.append(_build_scale_question(info, values, None, override=override))
                continue
            if override is not None:
                questions.append(_build_single_choice_question(info, values, qtype=QuestionType(override.question_type)))
                continue
            if info.qid in _DEMOGRAPHIC_SOURCE_COLUMNS:
                questions.append(_build_single_choice_question(info, values))
                continue
            match = match_family(_substantive_values(values))
            if match.outcome is MatchOutcome.full:
                questions.append(_build_scale_question(info, values, None))
            else:
                unresolved = collect_unresolved_question(
                    info.qid, info.text, list(enumerate(values, start=1)), _substantive_values(values), override=None
                )
                if unresolved is not None:
                    collected.append(unresolved)
            continue

    if collected:
        raise UnresolvedQuestionsError(collected)

    return questions


def load_respondents(
    rows: list[dict[str, str]],
    questions: list[Question],
    header_by_qid: dict[str, str],
) -> tuple[list[Response], int]:
    """Load respondents from parsed CSV rows into canonical Responses."""
    q_by_qid: dict[str, Question] = {q.qid: q for q in questions}
    responses: list[Response] = []
    n_raw = 0

    for row in rows:
        respondent_id = row.get("profile_id")
        if not respondent_id:
            continue
        n_raw += 1

        for qid, question in q_by_qid.items():
            column = header_by_qid[qid]
            raw = row.get(column)
            cell = raw.strip() if raw is not None else ""

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

            if question.qtype is QuestionType.multi_response:
                parts = [normalize_label(p) for p in cell.split(_MULTI_DELIMITER) if normalize_label(p)]
                codes = [str(code_by_label[p]) for p in parts]
                value: str | int = _MULTI_DELIMITER.join(codes)
                state = ResponseState.answered
            else:
                label = normalize_label(cell)
                value = code_by_label.get(label, label)
                state = classify_response(value, question)

            responses.append(
                Response(
                    respondent_id=respondent_id,
                    qid=qid,
                    raw_value=value,
                    state=state,
                )
            )

    return responses, n_raw


def read_status_values(path: Path) -> list[str]:
    """Raw values of the 'status' column across all data rows, for the run
    summary's disposition counts (prompt 7). Milieu's real fixture carries
    a 'status' column even though it's not part of the vendor profile's
    reserved set — read directly from the CSV rows if present."""
    try:
        with path.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None or "status" not in reader.fieldnames:
                return []
            return [row["status"] for row in reader if row.get("status")]
    except (OSError, UnicodeDecodeError, csv.Error):
        return []


def column_qid_map(path: Path) -> tuple[list[str], dict[str, str]]:
    """Returns (header, qid_by_column) for the run summary's column
    inventory (prompt 7). Milieu's qid is embedded directly in each column's
    "[qid]: ..." header, so this only needs _parse_header_cell — no
    grid-synthesis logic to duplicate, unlike Toluna's column_qid_map."""
    try:
        with path.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            fieldnames = list(reader.fieldnames or [])
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        raise SurveyToolError(
            ErrorCode.FILE_UNREADABLE,
            "This file could not be read as a Milieu export.",
            detail=str(exc),
            next_action="Confirm the file is a complete, un-corrupted export, or pick a different file.",
        ) from exc

    qid_by_column: dict[str, str] = {}
    for column in fieldnames:
        info = _parse_header_cell(column)
        if info is not None:
            qid_by_column[column] = info.qid
    return fieldnames, qid_by_column


def load(path: Path, survey_id: str, overrides: dict[str, QuestionOverride] | None = None) -> Survey:
    """Load a Milieu CSV file and return a canonical Survey."""
    try:
        with path.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            fieldnames = list(reader.fieldnames or [])
            rows = list(reader)
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        raise SurveyToolError(
            ErrorCode.FILE_UNREADABLE,
            "This file could not be read as a Milieu export.",
            detail=str(exc),
            next_action="Confirm the file is a complete, un-corrupted export, or pick a different file.",
        ) from exc

    questions = parse_header(fieldnames, rows, overrides)
    if not questions:
        raise SurveyToolError(
            ErrorCode.NO_QUESTIONS_FOUND,
            "This file was read but has no computable questions in it.",
            next_action="Check the vendor setting, or pick a different file.",
        )

    header_by_qid: dict[str, str] = {}
    for column in fieldnames:
        info = _parse_header_cell(column)
        if info is not None:
            header_by_qid[info.qid] = column

    responses, n_raw = load_respondents(rows, questions, header_by_qid)

    return Survey(
        id=survey_id,
        n_raw=n_raw,
        n_analysis=n_raw,
        questions=questions,
        responses=responses,
    )
