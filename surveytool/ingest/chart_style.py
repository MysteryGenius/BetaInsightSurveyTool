"""Manual per-question chart style choice (chart style selector feature).

Structurally identical to display_order.py: one YAML file per survey_id,
keyed by qid, following the same load/write/round-trip and corrupted-file
handling pattern. A ChartStyleChoice is orthogonal to both classification
(overrides.py) and manual display order (display_order.py) -- it never
changes which points exist, their role/rank, or their display order, only
which ChartStyle (surveytool.charts.styles) a chart is rendered with.

style_name is validated against surveytool.charts.styles.STYLE_REGISTRY at
write time and rejected with a plain-English UnknownChartStyleError if
unrecognised -- never persisted unvalidated, since a bad style_name
written today would need get_style's silent fallback to mask it forever
after (get_style itself falls back for defense in depth on read, but this
module refuses to ever write a name get_style would have to fall back
from).

Scope note, mirroring display_order.py: chart style is consumed by BOTH
chart pipelines. The newer breaks/crosstab pipeline reads it via the
``post_crosstab``/``post_breaks_export`` endpoints, and the legacy
``dist``/``xbreak``/``means`` charts read it too (chart-parity work, Item
B) via ``get_charts``/``export_charts`` -> ``build_legacy_figure``. Both
now render through ``plotly_renderer.py``, the single chart-drawing engine;
the separate matplotlib renderer that once made the legacy charts a scope
boundary has been retired.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, ValidationError

from surveytool.charts.errors import (
    ErrorCode,
    InvalidResponseColourError,
    SurveyToolError,
    UnknownChartStyleError,
)
from surveytool.charts.styles import STYLE_REGISTRY


_HEX_COLOUR = re.compile(r"^#[0-9a-fA-F]{6}$")


class ChartStyleChoice(BaseModel):
    variable: str
    style_name: str
    saved_at: datetime
    response_colours: dict[str, str] = Field(default_factory=dict)


class ProjectChartStyles(BaseModel):
    styles: dict[str, ChartStyleChoice] = Field(default_factory=dict)


class CorruptedChartStyleFileError(SurveyToolError):
    """Mirrors CorruptedDisplayOrderFileError -- a corrupted chart-style
    file must never be silently treated as 'no style chosen', since that
    would silently revert an analyst's saved style with no explanation."""

    def __init__(self, path: Path, reason: str) -> None:
        self.path = path
        detail = f"The chart style file at {path} could not be read: {reason}"
        super().__init__(
            ErrorCode.CONFIG_INVALID,
            "This project's saved chart style choices could not be read.",
            detail=detail,
            next_action=(
                "The chart style file may be corrupted. Check it at the path above, "
                "restore it from a backup, or delete it to reset every question to the default (brand) style."
            ),
        )


def load_chart_styles(path: Path) -> ProjectChartStyles:
    if not path.exists():
        return ProjectChartStyles()
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise CorruptedChartStyleFileError(path, str(exc)) from exc
    try:
        return ProjectChartStyles.model_validate(raw)
    except ValidationError as exc:
        raise CorruptedChartStyleFileError(path, str(exc)) from exc


def write_chart_style(path: Path, choice: ChartStyleChoice) -> None:
    if choice.style_name not in STYLE_REGISTRY:
        raise UnknownChartStyleError(choice.style_name, sorted(STYLE_REGISTRY))
    for label, value in choice.response_colours.items():
        if not _HEX_COLOUR.match(value):
            raise InvalidResponseColourError(label, value)
    existing = load_chart_styles(path) if path.exists() else ProjectChartStyles()
    existing.styles[choice.variable] = choice
    path.write_text(yaml.dump(existing.model_dump(mode="json")), encoding="utf-8")


def delete_chart_style(path: Path, variable: str) -> None:
    """Remove a variable's saved style entirely (reset to brand). A no-op
    if no style was saved for this variable."""
    if not path.exists():
        return
    existing = load_chart_styles(path)
    existing.styles.pop(variable, None)
    path.write_text(yaml.dump(existing.model_dump(mode="json")), encoding="utf-8")
