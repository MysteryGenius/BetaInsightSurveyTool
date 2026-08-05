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

    Mirrors ``demographic_registry.CanonicalCategory`` field for field.
    Nothing is pruned — ``non_response`` categories are ordinary categories
    throughout this build and are emitted like any other.
    """

    value: str
    label: str
    order: int
    non_response: bool = False


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


class ExportRequest(BaseModel):
    """POST .../export body (build plan section 12).

    The renderer itself is a later task; this model pins the wire shape now.
    """

    break_spec: BreakSpec
    filter_spec: FilterSpec = Field(default_factory=FilterSpec)
    chart_type: ChartType
    question_id: str
