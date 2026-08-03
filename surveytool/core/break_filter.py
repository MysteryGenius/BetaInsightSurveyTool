"""BreakSpec/FilterSpec models plus request validation.

Runs the checks from breaks-core-build-plan.md section 4, in order,
first-failure-wins. The vendor-mismatch and multiselect checks are
YAML-only (cheap); the zero-match check is the only one requiring
Task 3's apply_filter, since it needs to actually run the filter to know
whether it matches zero respondents.
"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from surveytool.charts.errors import (
    DemographicNotInRegistryError,
    DimensionInBreakAndFilterError,
    DuplicateBreakDimensionError,
    ErrorCode,
    FilterZeroMatchError,
    MultiselectBreakRejectedError,
    SurveyToolError,
)
from surveytool.core.cohort import apply_filter
from surveytool.core.demographic_registry import ResolvedRegistry
from surveytool.core.model import Survey


class BreakSpec(BaseModel):
    """Ordered list of dimension names forming the column structure.
    Order matters (build plan section 2's Terms) — it is preserved
    verbatim, never sorted or deduplicated by this model.
    """

    dimensions: list[str] = Field(min_length=1)


class FilterSpec(BaseModel):
    """Map of dimension name -> list of selected canonical category values.
    OR within a dimension; combined with other dimensions via AND
    (enforced in cohort.apply_filter, not here).
    """

    selections: dict[str, list[str]] = Field(default_factory=dict)

    @field_validator("selections")
    @classmethod
    def _values_non_empty(cls, v: dict[str, list[str]]) -> dict[str, list[str]]:
        for dimension, values in v.items():
            if not values:
                raise ValueError(f"Filter selection for {dimension!r} must not be empty.")
        return v


def validate_request(
    break_spec: BreakSpec,
    filter_spec: FilterSpec,
    registry: ResolvedRegistry,
    survey: Survey,
    vendor: str,
    respondent_frame,
) -> None:
    """Validate a break/filter request against the registry and the single
    loaded vendor Survey. Raises on first failure, in build plan section 4's
    exact order. Returns None on success.

    `vendor` names which vendor's Survey is loaded. Survey carries no vendor
    field of its own (surveytool/core/model.py::Survey has no such field,
    and ingest adapters don't stamp one on), so the caller — the one place
    that knows which vendor's file was uploaded for this session — must
    pass it explicitly rather than have this function try to infer it.

    `respondent_frame` is the wide respondent_id x qid frame for `survey`
    (surveytool.core.respondent_frame.to_respondent_frame(survey)) — needed
    to actually run the filter for the FILTER_ZERO_MATCH check.
    """
    # 1. DEMOGRAPHIC_NOT_IN_REGISTRY — every named dimension must exist.
    all_dimensions = list(break_spec.dimensions) + list(filter_spec.selections.keys())
    for dimension in all_dimensions:
        if dimension not in registry.canonical.dimensions:
            raise DemographicNotInRegistryError(dimension)

    # 2. DUPLICATE_BREAK_DIMENSION — no dimension appears twice in break_spec.
    seen: set[str] = set()
    for dimension in break_spec.dimensions:
        if dimension in seen:
            raise DuplicateBreakDimensionError(dimension)
        seen.add(dimension)

    # 3. DIMENSION_IN_BREAK_AND_FILTER — break_spec and filter_spec disjoint.
    break_set = set(break_spec.dimensions)
    for dimension in filter_spec.selections:
        if dimension in break_set:
            raise DimensionInBreakAndFilterError(dimension)

    # 4. VENDOR_MISMATCH (reused code) — every break dimension resolves for
    #    the single loaded vendor.
    vendor_dims = registry.dimensions_for_vendor(vendor)
    missing = [d for d in break_spec.dimensions if d not in vendor_dims]
    if missing:
        detail = (
            f"Dimension(s) {missing!r} are not available for vendor {vendor!r}: "
            f"this vendor's mapping does not declare them."
        )
        raise SurveyToolError(
            ErrorCode.VENDOR_MISMATCH,
            "One or more Break by selections aren't available for this file's vendor.",
            detail=detail,
            next_action="Remove the unavailable demographic from Break by, or load a file from a vendor that collects it.",
        )

    # 5. MULTISELECT_BREAK_REJECTED — no break dimension may be multi_select.
    for dimension in break_spec.dimensions:
        canonical_dim = registry.canonical.dimensions[dimension]
        if canonical_dim.multi_select:
            raise MultiselectBreakRejectedError(dimension, canonical_dim.label)

    # 6. FILTER_ZERO_MATCH — the filter, once applied, must match >= 1 respondent.
    matched = apply_filter(respondent_frame, filter_spec.selections, registry, survey, vendor)
    if not matched:
        raise FilterZeroMatchError(filter_spec.selections)
