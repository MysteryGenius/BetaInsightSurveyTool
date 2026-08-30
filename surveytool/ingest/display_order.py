"""Manual response-option display order (Round C3).

A DisplayOrder is orthogonal to a QuestionOverride: it never changes a
question's classification, role, or rank -- only how its scale points are
DISPLAYED in a chart. Netting and mean always use rank regardless of
display order (see breaks_compute.py's use of this module).

Keyed by survey_id exactly like ProjectOverrides (surveytool/ingest/
overrides.py) -- one YAML file per survey, so a survey rename (Round C5)
must migrate this file alongside the overrides file.

Scope note (Round C final review): manual display order is currently
consumed only by the newer breaks/crosstab pipeline (the ``post_crosstab``/
``post_breaks_export`` endpoints and ``plotly_renderer.py``). It is not
read by the legacy ``dist``/``xbreak``/``means`` chart system
(``surveytool/charts/renderer.py`` and ``surveytool/charts/chart_data.py``)
-- that is a deliberate scope boundary, not an oversight, and wiring it
through is out of scope for this fix wave.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, ValidationError

from surveytool.charts.errors import ErrorCode, SurveyToolError


class DisplayOrder(BaseModel):
    variable: str
    label_order: list[str]
    is_manual: bool
    saved_at: datetime


class ProjectDisplayOrders(BaseModel):
    orders: dict[str, DisplayOrder] = Field(default_factory=dict)


class CorruptedDisplayOrderFileError(SurveyToolError):
    """Mirrors CorruptedOverridesFileError (overrides.py) -- a corrupted
    display-order file must never be silently treated as 'no manual order
    exists', since that would silently revert an analyst's saved reorder
    with no explanation."""

    def __init__(self, path: Path, reason: str) -> None:
        self.path = path
        detail = f"The display order file at {path} could not be read: {reason}"
        super().__init__(
            ErrorCode.CONFIG_INVALID,
            "This project's saved response-option order could not be read.",
            detail=detail,
            next_action=(
                "The display order file may be corrupted. Check it at the path above, "
                "restore it from a backup, or delete it to reset every question to its default order."
            ),
        )


def load_display_orders(path: Path) -> ProjectDisplayOrders:
    if not path.exists():
        return ProjectDisplayOrders()
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise CorruptedDisplayOrderFileError(path, str(exc)) from exc
    try:
        return ProjectDisplayOrders.model_validate(raw)
    except ValidationError as exc:
        raise CorruptedDisplayOrderFileError(path, str(exc)) from exc


def write_display_order(path: Path, order: DisplayOrder) -> None:
    existing = load_display_orders(path) if path.exists() else ProjectDisplayOrders()
    existing.orders[order.variable] = order
    path.write_text(yaml.dump(existing.model_dump(mode="json")), encoding="utf-8")


def delete_display_order(path: Path, variable: str) -> None:
    """Remove a variable's saved order entirely (reset to default rank
    order). A no-op if no order was saved for this variable."""
    if not path.exists():
        return
    existing = load_display_orders(path)
    existing.orders.pop(variable, None)
    path.write_text(yaml.dump(existing.model_dump(mode="json")), encoding="utf-8")
