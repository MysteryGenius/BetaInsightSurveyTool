from __future__ import annotations

import re
from pathlib import Path

import openpyxl

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
from surveytool.core.scale_library import identify_family, resolve_roles

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
) -> Question:
    ns_overrides: dict[str, CodeRole] = {
        v: CodeRole.nonsubstantive for v in values if is_nonsubstantive_label(v)
    }
    substantive_values = [v for v in values if v not in ns_overrides]

    roles = resolve_roles(substantive_values, override=ns_overrides)
    for label, role in ns_overrides.items():
        roles[label] = role

    direction: str | None = None
    if substantive_values:
        first_role = roles.get(substantive_values[0])
        last_role = roles.get(substantive_values[-1])
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
        qid=qid,
        text=text,
        qtype=QuestionType.scale,
        labels=labels,
        scale_direction=direction,
        scale_family=family,
        grid_group=grid_group,
        base_eligible=True,
    )


def _build_single_choice_question(qid: str, text: str, values: list[str]) -> Question:
    labels = [
        ScaleCode(
            code=i,
            label=v,
            role=CodeRole.nonsubstantive if is_nonsubstantive_label(v) else CodeRole.excluded,
        )
        for i, v in enumerate(values, start=1)
    ]
    return Question(
        qid=qid,
        text=text,
        qtype=QuestionType.single_choice,
        labels=labels,
        base_eligible=True,
    )


def parse_header(header: tuple, rows: list[tuple]) -> tuple[list[Question], dict[str, int]]:
    """Parse Toluna xlsx column headers into canonical Questions.

    Returns (questions, col_idx_by_qid).
    """
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

        try:
            question = _build_scale_question(qid, text, values, grid_group)
        except ValueError:
            question = _build_single_choice_question(qid, text, values)

        questions.append(question)
        col_idx_by_qid[qid] = idx

    return questions, col_idx_by_qid


def load_respondents(
    rows: list[tuple],
    questions: list[Question],
    col_idx_by_qid: dict[str, int],
    respid_col: int,
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


def load(path: Path, survey_id: str) -> Survey:
    """Load a Toluna xlsx file and return a canonical Survey."""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb[_SHEET_NAME]
        row_iter = ws.iter_rows(values_only=True)
        header = next(row_iter)

        rows: list[tuple] = []
        for row in row_iter:
            if all(v is None for v in row):
                break
            rows.append(row)

        respid_col = next(
            i for i, cell in enumerate(header) if cell is not None and str(cell).strip() == _RESPID_COLUMN
        )

        questions, col_idx_by_qid = parse_header(header, rows)
        responses, n_raw = load_respondents(rows, questions, col_idx_by_qid, respid_col)
    finally:
        wb.close()

    return Survey(
        id=survey_id,
        n_raw=n_raw,
        n_analysis=n_raw,
        questions=questions,
        responses=responses,
    )
