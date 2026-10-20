"""Request/response models for the breaks-and-filters API surface.

This module is the single import point for the payload models the
breaks endpoints in ``surveytool/desktop/app.py`` speak in. Models that
already exist elsewhere are RE-EXPORTED here, never redefined — one
definition per model, per build plan section 10:

- ``BreakSpec`` / ``FilterSpec``  -> surveytool.core.break_filter
- ``Projection`` / ``CellProjection`` / ``DimensionSummary`` / ``ErrorDetail``
                                  -> surveytool.core.projection
- ``QuestionResult`` / ``ColumnResult`` / ``ScalePoint`` / ``NetDefinition``
  / ``NetResult``                 -> surveytool.compute.breaks_compute
- ``ChartType`` / ``ChartPermission`` -> surveytool.core.chart_validity

What is genuinely NEW here are the FastAPI request-body models. FastAPI
treats each Pydantic parameter as its own top-level body key, so a
single combined model per endpoint keeps the wire shape explicit and
matches build plan section 12's ``{break_spec, filter_spec, ...}``
objects exactly rather than depending on ``Body(embed=True)`` behaviour.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from surveytool.compute.breaks_compute import (
    ColumnResult,
    NetDefinition,
    NetResult,
    QuestionResult,
    ScalePoint,
)
from surveytool.core.break_filter import BreakSpec, FilterSpec
from surveytool.core.chart_validity import ChartPermission, ChartType
from surveytool.core.projection import (
    CellProjection,
    DimensionSummary,
    ErrorDetail,
    Projection,
)

__all__ = [
    "BreakSpec",
    "FilterSpec",
    "Projection",
    "CellProjection",
    "DimensionSummary",
    "ErrorDetail",
    "QuestionResult",
    "ColumnResult",
    "ScalePoint",
    "NetDefinition",
    "NetResult",
    "ChartType",
    "ChartPermission",
    "RegistryCategory",
    "RegistryDimension",
    "RegistryPayload",
    "ProjectionRequest",
    "CrosstabRequest",
    "ExportRequest",
]


# --- Registry payload (GET .../demographics/registry) ----------------------


class RegistryCategory(BaseModel):
    """One canonical category, as the UI's pill list needs it.

    Mirrors ``demographic_registry.CanonicalCategory`` field for field, plus
    ``not_collected_reason`` (Task 9): non-null when this session's vendor
    has declared this category as a genuine content gap rather than mapping
    it, so the UI's pill list can show the note at the point the analyst
    would otherwise wonder why the category is empty. Nothing is pruned —
    ``non_response`` categories are ordinary categories throughout this
    build and are emitted like any other.
    """

    value: str
    label: str
    order: int
    non_response: bool = False
    not_collected_reason: str | None = None


class RegistryDimension(BaseModel):
    """One canonical dimension as resolved for the loaded file's vendor.

    ``available`` records whether this session's vendor mapping actually
    declares the dimension. Unavailable dimensions are still emitted (with
    their full category list) so the UI can show them as disabled rather
    than silently having a different pill list per vendor — this endpoint
    is the UI's sole pill-list source, so it must be complete.
    """

    dimension: str
    label: str
    multi_select: bool
    available: bool
    source_column: str | None = None
    categories: list[RegistryCategory]


class RegistryPayload(BaseModel):
    vendor: str
    dimensions: list[RegistryDimension]


# --- Request bodies --------------------------------------------------------


class ProjectionRequest(BaseModel):
    """POST .../projection body."""

    break_spec: BreakSpec
    filter_spec: FilterSpec = Field(default_factory=FilterSpec)


class CrosstabRequest(BaseModel):
    """POST .../crosstab body.

    ``question_ids`` is optional: omitted (or null) means every
    base-eligible non-demographic question, the same set the existing
    ``GET .../demographics`` endpoint offers in its ``questions`` list.
    """

    break_spec: BreakSpec
    filter_spec: FilterSpec = Field(default_factory=FilterSpec)
    question_ids: list[str] | None = None


class BreaksFigureRequest(BaseModel):
    """POST .../breaks-figure body: one question's chart, as drawn on screen.

    `swap_axes` mirrors the Cross-tab "Swap axes" control; build_figure
    ignores it for chart types that cannot swap.
    """

    break_spec: BreakSpec
    filter_spec: FilterSpec = Field(default_factory=FilterSpec)
    chart_type: ChartType
    question_id: str
    swap_axes: bool = False


class ExportRequest(BreaksFigureRequest):
    """POST .../breaks-export body (build plan section 12): the same chart
    the screen shows, so the export can match it exactly."""


class BulkExportRequest(BaseModel):
    """POST .../breaks-export-bulk body. Unlike ExportRequest (single
    question_id, streamed FileResponse), this accepts a list and writes to
    out_dir, returning a manifest -- matching the legacy Charts tab's
    existing bulk /export response shape for UI consistency (Item D)."""

    break_spec: BreakSpec
    filter_spec: FilterSpec = Field(default_factory=FilterSpec)
    chart_type: ChartType
    question_ids: list[str]
    out_dir: str
    swap_axes: bool = False
