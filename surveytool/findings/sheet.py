from __future__ import annotations

import warnings
from dataclasses import dataclass

from surveytool.compute.frequency import compute_question_stats
from surveytool.core.model import CodeRole, Question, Response, ResponseState, ScaleCode, Survey

_DEFAULT_BANNER = ["age", "ethnicity"]
# Demographic ScaleCodes use CodeRole.excluded (they are not scale items).
# For crossbreak purposes, every demographic code that represents a real category
# (i.e. not a nonsubstantive sentinel) is a valid breakdown level.
_BANNER_LEVEL_ROLES = frozenset({
    CodeRole.top, CodeRole.neutral, CodeRole.bottom, CodeRole.excluded
})


@dataclass(frozen=True)
class FindingsRow:
    survey_id: str
    qid: str
    question_text: str
    breakdown_variable: str   # "total" | "age" | "ethnicity" | …
    breakdown_level: str      # "Total" | "25-34" | "Chinese" | …
    breakdown_level_label: str  # real label, never a bare code
    cell_base: int
    metric: str               # "pct_<label>" | "t2b" | "b2b" | "mean" | "n_<label>"
    value: float | None
    convention: str           # "T2B" | "B2B" | "mean" | "pct" | "n"
    role: CodeRole | None = None  # populated for pct_<label> rows; None for aggregates


def _find_banner_question(survey: Survey, name: str) -> Question | None:
    name_lower = name.lower()
    for q in survey.questions:
        if not q.is_demographic:
            continue
        if q.qid.lower() == name_lower:
            return q
        if name_lower in q.text.lower():
            return q
    return None


def _emit_rows(
    qs_result,
    survey_id: str,
    question: Question,
    breakdown_variable: str,
    breakdown_level: str,
    breakdown_level_label: str,
) -> list[FindingsRow]:
    rows: list[FindingsRow] = []
    base = qs_result.base

    for cs in qs_result.code_stats:
        rows.append(FindingsRow(
            survey_id=survey_id,
            qid=question.qid,
            question_text=question.text,
            breakdown_variable=breakdown_variable,
            breakdown_level=breakdown_level,
            breakdown_level_label=breakdown_level_label,
            cell_base=base,
            metric=f"pct_{cs.label}",
            value=cs.pct,
            convention="pct",
            role=cs.role,
        ))
        rows.append(FindingsRow(
            survey_id=survey_id,
            qid=question.qid,
            question_text=question.text,
            breakdown_variable=breakdown_variable,
            breakdown_level=breakdown_level,
            breakdown_level_label=breakdown_level_label,
            cell_base=base,
            metric=f"n_{cs.label}",
            value=float(cs.n),
            convention="n",
        ))

    if qs_result.t2b is not None:
        rows.append(FindingsRow(
            survey_id=survey_id,
            qid=question.qid,
            question_text=question.text,
            breakdown_variable=breakdown_variable,
            breakdown_level=breakdown_level,
            breakdown_level_label=breakdown_level_label,
            cell_base=base,
            metric="t2b",
            value=qs_result.t2b,
            convention="T2B",
        ))

    if qs_result.b2b is not None:
        rows.append(FindingsRow(
            survey_id=survey_id,
            qid=question.qid,
            question_text=question.text,
            breakdown_variable=breakdown_variable,
            breakdown_level=breakdown_level,
            breakdown_level_label=breakdown_level_label,
            cell_base=base,
            metric="b2b",
            value=qs_result.b2b,
            convention="B2B",
        ))

    if qs_result.mean is not None:
        rows.append(FindingsRow(
            survey_id=survey_id,
            qid=question.qid,
            question_text=question.text,
            breakdown_variable=breakdown_variable,
            breakdown_level=breakdown_level,
            breakdown_level_label=breakdown_level_label,
            cell_base=base,
            metric="mean",
            value=qs_result.mean,
            convention="mean",
        ))

    return rows


def build_findings_sheet(
    survey: Survey,
    banner: list[str] | None = None,
    exclude_respondent_ids: set[str] | None = None,
) -> list[FindingsRow]:
    """Build the long-format findings sheet.

    Returns one FindingsRow per (question, breakdown variable, breakdown level, metric).
    Every label field carries the real ScaleCode label, never a bare code.
    """
    if banner is None:
        banner = _DEFAULT_BANNER

    excluded = exclude_respondent_ids or set()

    # Index responses by qid, with exclusions applied
    response_index: dict[str, list[Response]] = {}
    for r in survey.responses:
        if r.respondent_id in excluded:
            continue
        response_index.setdefault(r.qid, []).append(r)

    # Resolve banner questions and build respondent→ScaleCode maps
    banner_questions: list[tuple[str, Question, dict[str, ScaleCode]]] = []
    for bname in banner:
        demo_q = _find_banner_question(survey, bname)
        if demo_q is None:
            warnings.warn(
                f"Banner variable {bname!r} not found in survey questions; skipping.",
                stacklevel=2,
            )
            continue
        # Build code→ScaleCode lookup from the demographic question's labels
        code_to_sc: dict[int | str, ScaleCode] = {sc.code: sc for sc in demo_q.labels}
        # Build respondent_id → ScaleCode map
        rid_to_sc: dict[str, ScaleCode] = {}
        for r in response_index.get(demo_q.qid, []):
            if r.state is ResponseState.answered and r.raw_value is not None:
                sc = code_to_sc.get(r.raw_value)
                if sc is not None:
                    rid_to_sc[r.respondent_id] = sc
        banner_questions.append((bname, demo_q, rid_to_sc))

    rows: list[FindingsRow] = []

    for question in survey.questions:
        if not question.base_eligible:
            continue

        q_responses = response_index.get(question.qid, [])

        # Total breakdown
        qs_total = compute_question_stats(question, q_responses)
        rows.extend(_emit_rows(
            qs_total, survey.id, question,
            breakdown_variable="total",
            breakdown_level="Total",
            breakdown_level_label="Total",
        ))

        # Per-banner breakdowns
        for bname, demo_q, rid_to_sc in banner_questions:
            # Emit a breakdown level for every demographic category.
            # Demographic codes are all CodeRole.excluded (they are not scale items),
            # so we include excluded but still skip nonsubstantive sentinel codes.
            substantive_scs = [
                sc for sc in demo_q.labels
                if sc.role in _BANNER_LEVEL_ROLES
            ]

            for sc in substantive_scs:
                # Filter question responses to respondents in this demographic cell
                cell_respondents = {
                    rid for rid, demo_sc in rid_to_sc.items() if demo_sc.code == sc.code
                }
                cell_responses = [r for r in q_responses if r.respondent_id in cell_respondents]
                qs_cell = compute_question_stats(question, cell_responses)
                rows.extend(_emit_rows(
                    qs_cell, survey.id, question,
                    breakdown_variable=bname,
                    breakdown_level=sc.label,
                    breakdown_level_label=sc.label,
                ))

    return rows
