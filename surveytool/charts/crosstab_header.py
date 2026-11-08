"""The plain-English description shown above a Cross-tab chart on screen
(v4 feedback F4): break-by, filter, chart type, bases and the manual-reorder
warning. Kept out of the figure itself so exported PNGs carry none of it;
exports record the same facts in manifest.json.

Built here, on the server, from the demographic registry's labels, so the
screen never shows an internal identifier (`age_band`, `stacked_bar_100`)
and never composes its own wording.
"""
from __future__ import annotations

from surveytool.compute.breaks_compute import QuestionResult
from surveytool.core.demographic_registry import ResolvedRegistry

REORDERED_WARNING = "⚠ Response options manually reordered"


def _dimension_label(registry: ResolvedRegistry, dimension: str) -> str:
    return registry.canonical.dimensions[dimension].label


def _category_label(registry: ResolvedRegistry, dimension: str, value: str) -> str:
    for category in registry.canonical.dimensions[dimension].categories:
        if category.value == value:
            return category.label
    return value


def crosstab_header_lines(
    question_result: QuestionResult,
    break_dims: list[str],
    filters: dict[str, list[str]],
    registry: ResolvedRegistry,
) -> list[str]:
    """Break-by, filter, bases and (if any) the manual-reorder warning. The
    chart type is added by the screen as the label of the chart-type button
    currently selected (CHART_TYPE_LABELS, mirrored in breaks.js), since the
    same result is shown as several chart types."""
    break_text = ", then ".join(_dimension_label(registry, d) for d in break_dims) or "None"
    active = {dim: values for dim, values in filters.items() if values}
    if active:
        filter_text = "; ".join(
            f"{_dimension_label(registry, dim)}: "
            + ", ".join(_category_label(registry, dim, v) for v in values)
            for dim, values in active.items()
        )
    else:
        filter_text = "None"

    lines = [
        f"Break by: {break_text}  |  Filter by: {filter_text}",
        f"Base total: {question_result.base_total:,}  |  Base filtered: {question_result.base_filtered:,}",
    ]
    if question_result.display_order_is_manual:
        lines.append(REORDERED_WARNING)
    return lines
