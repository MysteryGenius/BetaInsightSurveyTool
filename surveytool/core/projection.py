"""Projection: the cheap "shape of the request" check.

Build plan section 6: projection runs before compute and returns the shape
of a break/filter request — without computing any question. It groups the
filtered data by the break dimensions and counts. This is cheap relative to
computing every question and is what the (future) confirmation gate is built
on, and what the UI re-runs on every pill change (add/remove a break
dimension, change a filter selection).

`project()` therefore combines Tasks 2-4:
  - Task 2 (surveytool.core.break_filter): validate_request.
  - Task 3 (surveytool.core.cohort): apply_filter, resolve_cells.
  - Task 4 (surveytool.core.suppression): classify_band.

CRITICAL: this module must never import or call into per-question compute
(surveytool.compute.frequency's compute_question_stats or anything similar).
That per-question path is what projection exists to avoid running on every
pill change. Enforced by convention here and by
tests/test_projection.py::test_projection_module_does_not_import_frequency_compute.
"""
from __future__ import annotations

import pandas as pd
from pydantic import BaseModel

from surveytool.charts.errors import SurveyToolError
from surveytool.core.break_filter import BreakSpec, FilterSpec, validate_request
from surveytool.core.cohort import apply_filter, resolve_cells
from surveytool.core.config import ToolConfig
from surveytool.core.demographic_registry import ResolvedRegistry
from surveytool.core.model import Survey
from surveytool.core.suppression import Band, classify_band


class DimensionSummary(BaseModel):
    """A break dimension's identity, for display in the Projection payload.
    Pulled from the canonical registry — dimension name plus its label."""

    dimension: str
    label: str


class ErrorDetail(BaseModel):
    """Mirrors SurveyToolError's fields, so a validation failure can travel
    in-band inside Projection.errors rather than being raised."""

    code: str
    message: str
    detail: str | None = None
    next_action: str | None = None

    @classmethod
    def from_survey_tool_error(cls, exc: SurveyToolError) -> "ErrorDetail":
        return cls(
            code=exc.code.value,
            message=exc.message,
            detail=exc.detail,
            next_action=exc.next_action,
        )


class CellProjection(BaseModel):
    """Payload-shaped counterpart of cohort.Cell (build plan section 6)."""

    key: list[list[str]]
    label_path: list[str]
    base_cell: int
    band: Band


class Projection(BaseModel):
    """The shape of a break/filter request, per build plan section 6."""

    break_dimensions: list[DimensionSummary]
    base_total: int
    base_filtered: int
    cell_count: int
    cells: list[CellProjection]
    suppressed_count: int
    low_base_count: int
    render_ceiling: int
    chart_render_permitted: bool
    errors: list[ErrorDetail]


def project(
    break_spec: BreakSpec,
    filter_spec: FilterSpec,
    survey: Survey,
    respondent_frame: pd.DataFrame,
    registry: ResolvedRegistry,
    vendor: str,
    config: ToolConfig,
) -> Projection:
    """Compute the shape of a break/filter request without computing any
    question's figures. Never raises SurveyToolError — a validation failure
    is reported in Projection.errors instead, since this function is meant
    to run cheaply on every UI pill change (add/remove a break dimension or
    filter value), before the analyst has necessarily settled on a valid
    combination. A non-SurveyToolError exception is a genuine bug, not a
    user-triggerable validation state, and is left to propagate.

    base_total is always populated (len(respondent_frame) — doesn't depend
    on validation). base_filtered is only populated on validation success:
    on failure it isn't well-defined (e.g. an unknown filter dimension can't
    be run through apply_filter at all), so it's left at 0 alongside the
    other empty defaults, consistent with cell_count=0 / cells=[].
    """
    base_total = len(respondent_frame)

    try:
        validate_request(break_spec, filter_spec, registry, survey, vendor, respondent_frame)
    except SurveyToolError as exc:
        return Projection(
            break_dimensions=[],
            base_total=base_total,
            base_filtered=0,
            cell_count=0,
            cells=[],
            suppressed_count=0,
            low_base_count=0,
            render_ceiling=config.render_column_ceiling,
            chart_render_permitted=False,
            errors=[ErrorDetail.from_survey_tool_error(exc)],
        )

    filtered_ids = apply_filter(respondent_frame, filter_spec.selections, registry, survey, vendor)
    cells = resolve_cells(respondent_frame, filtered_ids, break_spec.dimensions, registry, survey, vendor)

    cell_projections: list[CellProjection] = []
    suppressed_count = 0
    low_base_count = 0
    for cell in cells:
        band = classify_band(cell.base_cell, config)
        if band is Band.suppressed:
            suppressed_count += 1
        elif band is Band.low_base:
            low_base_count += 1
        cell_projections.append(
            CellProjection(
                key=[[dimension, category] for dimension, category in cell.key],
                label_path=list(cell.label_path),
                base_cell=cell.base_cell,
                band=band,
            )
        )

    break_dimensions = [
        DimensionSummary(dimension=name, label=registry.canonical.dimensions[name].label)
        for name in break_spec.dimensions
    ]

    cell_count = len(cell_projections)
    render_ceiling = config.render_column_ceiling

    return Projection(
        break_dimensions=break_dimensions,
        base_total=base_total,
        base_filtered=len(filtered_ids),
        cell_count=cell_count,
        cells=cell_projections,
        suppressed_count=suppressed_count,
        low_base_count=low_base_count,
        render_ceiling=render_ceiling,
        chart_render_permitted=cell_count <= render_ceiling,
        errors=[],
    )
