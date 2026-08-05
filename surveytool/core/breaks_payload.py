"""Payload assembly: join compute output to chart-type validity.

``compute_breaks_crosstab`` (build plan section 8) deliberately leaves
``QuestionResult.permitted_charts`` empty — it computes figures and knows
nothing about what those figures may be drawn as. ``chart_validity``
(section 9) decides what may be drawn but does not compute. This module is
the only place the two meet, producing the section 10 payload shape in full.

Column count comes from ``len(question_result.columns)``: the result already
carries its own computed columns, so no separate count is threaded through
by the caller and the two can never disagree.

``QuestionResult`` is a plain (non-frozen) pydantic ``BaseModel``, so
``permitted_charts`` is assigned in place rather than via ``model_copy`` —
the results are freshly built by ``compute_breaks_crosstab`` and are not
shared with any other caller.
"""
from __future__ import annotations

from surveytool.compute.breaks_compute import QuestionResult
from surveytool.core.chart_validity import evaluate_chart_permissions
from surveytool.core.config import ToolConfig


def attach_chart_permissions(
    question_results: list[QuestionResult], config: ToolConfig
) -> list[QuestionResult]:
    """Populate ``permitted_charts`` on every result, in place.

    Returns the same list it was given, so it reads naturally as the final
    step of an endpoint's compute pipeline.
    """
    for question_result in question_results:
        question_result.permitted_charts = evaluate_chart_permissions(
            question_result, len(question_result.columns), config
        )
    return question_results
