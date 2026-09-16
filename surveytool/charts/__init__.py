from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING, Iterator

from surveytool.charts.types import ChartSpec
from surveytool.core.model import QuestionType

if TYPE_CHECKING:
    from surveytool.core.model import Question
    from surveytool.findings.sheet import FindingsRow

__all__ = ["iter_chart_specs"]

_SCALE_TYPES = frozenset({QuestionType.scale, QuestionType.single_choice})


def iter_chart_specs(
    findings: list["FindingsRow"],
    survey_id: str,
    questions: list["Question"],
) -> Iterator[ChartSpec]:
    """Yield the ChartSpec for every chart that should exist for this survey.

    Emits:
    - One dist chart per (scale/single_choice question × breakdown_level for "total").
    - One xbreak chart per (scale question × non-total breakdown_variable).
    - One means chart per survey (all scale questions, total, mean metric).

    This is the single source of truth for "what charts exist" — both PNG
    rendering (chart_data.render_charts_plotly) and interactive chart data
    (chart_data.build_chart_data) consume it, so neither can drift from the
    other's selection rules.
    """
    q_by_id: dict[str, Question] = {q.qid: q for q in questions}

    # Group findings rows by (qid, breakdown_variable).
    groups: dict[tuple[str, str], list[FindingsRow]] = defaultdict(list)
    for row in findings:
        groups[(row.qid, row.breakdown_variable)].append(row)

    # Rows for the survey-wide means comparison chart.
    means_rows: list[FindingsRow] = []

    for (qid, bvar), rows in groups.items():
        question = q_by_id.get(qid)
        if question is None or not question.base_eligible:
            continue

        is_scale = question.qtype in _SCALE_TYPES
        q_text = rows[0].question_text

        if bvar == "total":
            yield ChartSpec(
                chart_type="dist",
                survey_id=survey_id,
                qid=qid,
                question_text=q_text,
                breakdown_variable=bvar,
                metric="pct",
                rows=rows,
            )

            if is_scale:
                for r in rows:
                    if r.metric == "mean" and r.value is not None:
                        means_rows.append(r)
                        break

        else:
            if not is_scale:
                continue
            has_t2b = any(r.metric == "t2b" for r in rows)
            has_mean = any(r.metric == "mean" for r in rows)
            if not has_t2b and not has_mean:
                continue
            metric = "t2b" if has_t2b else "mean"
            yield ChartSpec(
                chart_type="xbreak",
                survey_id=survey_id,
                qid=qid,
                question_text=q_text,
                breakdown_variable=bvar,
                metric=metric,
                rows=rows,
            )

    # Survey-wide means comparison chart.
    if means_rows:
        anchor = means_rows[0]
        yield _MeansSpec(
            chart_type="means",
            survey_id=survey_id,
            qid=anchor.qid,
            question_text=anchor.question_text,
            breakdown_variable="total",
            metric="mean",
            rows=means_rows,
            _override_filename=f"{survey_id}__all__means__total.png",
        )


class _MeansSpec(ChartSpec):
    """ChartSpec with an overridden filename for the survey-wide means chart."""

    def __init__(self, *args, _override_filename: str, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        object.__setattr__(self, "_override_filename", _override_filename)

    @property
    def filename(self) -> str:
        return self._override_filename  # type: ignore[attr-defined]
