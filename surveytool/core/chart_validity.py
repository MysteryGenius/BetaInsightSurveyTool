"""Chart type validity for breaks-and-filters results (build plan section 9).

The core declares what a computed ``QuestionResult`` may legitimately be
drawn as; the frontend does not decide. This module never blocks or alters
computation -- ``evaluate_chart_permissions`` is a pure function of an
already-computed result's shape plus config, and every chart type is
evaluated and returned alongside the full result, permitted or not.

Only five chart types exist. Pie and donut are explicitly excluded by the
build plan and are not in the enum.

Polarity is looked up, never inferred: ``diverging_stacked_bar`` consults the
``scale_polarity.yaml`` registry keyed by ``scale_family`` (the same string
already carried as ``QuestionResult.scale_id``) and never looks at scale
point labels. A family absent from the registry is undeclared by design --
see ``scale_polarity.yaml`` for the reasoning behind each family's
declared/undeclared status.
"""
from __future__ import annotations

from enum import Enum
from pathlib import Path

import yaml
from pydantic import BaseModel

from surveytool.compute.breaks_compute import QuestionResult
from surveytool.core.config import ToolConfig

_POLARITY_PATH = Path(__file__).parent / "scale_polarity.yaml"

_REASON_SCALE_POLARITY_UNDECLARED = "SCALE_POLARITY_UNDECLARED"
_REASON_COLUMN_COUNT_EXCEEDS_RENDER_LIMIT = "COLUMN_COUNT_EXCEEDS_RENDER_LIMIT"


def _load_polarity_registry() -> dict[str, dict]:
    raw = yaml.safe_load(_POLARITY_PATH.read_text(encoding="utf-8"))
    return raw["scale_families"]


_POLARITY_REGISTRY: dict[str, dict] = _load_polarity_registry()


class ChartType(str, Enum):
    """The only chart types this tool can render. No pie, no donut."""

    stacked_bar_100 = "stacked_bar_100"
    diverging_stacked_bar = "diverging_stacked_bar"
    grouped_bar = "grouped_bar"
    net_bar = "net_bar"
    table = "table"


class ChartPermission(BaseModel):
    """One chart type's permitted/refused verdict for a computed result.

    ``reason`` is a plain informational string, not an ``ErrorCode`` -- this
    is never raised, only reported alongside the full result.
    """

    chart_type: ChartType
    permitted: bool
    reason: str | None = None


def _has_declared_polarity(scale_id: str | None) -> bool:
    return scale_id is not None and scale_id in _POLARITY_REGISTRY


def evaluate_chart_permissions(
    question_result: QuestionResult, column_count: int, config: ToolConfig
) -> list[ChartPermission]:
    """Evaluate every ``ChartType`` against one computed result.

    Per-type rules are computed first; the render-ceiling override is applied
    last so it can clobber any earlier ``permitted=True`` (build plan section
    9). ``table`` is exempt from the ceiling and stays permitted regardless
    of column count.
    """
    n_scale_points = len(question_result.scale_points)

    permissions = {
        ChartType.stacked_bar_100: ChartPermission(
            chart_type=ChartType.stacked_bar_100,
            permitted=n_scale_points >= 2,
        ),
        ChartType.diverging_stacked_bar: (
            ChartPermission(
                chart_type=ChartType.diverging_stacked_bar,
                permitted=True,
            )
            if _has_declared_polarity(question_result.scale_id)
            else ChartPermission(
                chart_type=ChartType.diverging_stacked_bar,
                permitted=False,
                reason=_REASON_SCALE_POLARITY_UNDECLARED,
            )
        ),
        ChartType.grouped_bar: ChartPermission(
            chart_type=ChartType.grouped_bar,
            permitted=column_count <= config.render_column_ceiling
            and n_scale_points <= 7,
        ),
        ChartType.net_bar: ChartPermission(
            chart_type=ChartType.net_bar,
            permitted=len(question_result.nets) >= 1,
        ),
        ChartType.table: ChartPermission(chart_type=ChartType.table, permitted=True),
    }

    if column_count > config.render_column_ceiling:
        for chart_type, permission in permissions.items():
            if chart_type is ChartType.table:
                continue
            permission.permitted = False
            permission.reason = _REASON_COLUMN_COUNT_EXCEEDS_RENDER_LIMIT

    return list(permissions.values())


def populate_permitted_charts(
    question_result: QuestionResult, config: ToolConfig
) -> QuestionResult:
    """Convenience wrapper: evaluate and assign onto the result in place.

    Column count is derived from ``len(question_result.columns)`` -- the
    result already carries its own computed columns, so no separate count
    needs to be threaded through by the caller.
    """
    question_result.permitted_charts = evaluate_chart_permissions(
        question_result, len(question_result.columns), config
    )
    return question_result
