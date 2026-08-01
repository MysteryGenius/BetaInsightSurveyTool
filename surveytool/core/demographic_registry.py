"""Demographic registry: canonical dimension definitions plus per-vendor mappings.

Loads and validates surveytool/core/demographics/canonical.yaml and the
vendor_*.yaml files against the rules in breaks-core-build-plan.md section 3:

1. Reachability (cheap, YAML-only): every canonical category must be
   reachable from every vendor mapping that declares the dimension.
2. Unmapped source values (needs loaded response data): a source value
   present in the actual data for a dimension's source column but absent
   from that vendor's value_map is a hard failure.

Rule 1 runs before rule 2 so cheap checks fail first. non_response
categories are ordinary categories throughout — never special-cased.
"""
from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from surveytool.charts.errors import (
    CanonicalCategoryUnreachableError,
    DimensionNotInCanonicalError,
    UnmappedSourceValueError,
)
from surveytool.core.model import Survey


class CanonicalCategory(BaseModel):
    value: str
    label: str
    order: int
    non_response: bool = False


class CanonicalDimension(BaseModel):
    label: str
    multi_select: bool = False
    categories: list[CanonicalCategory]


class CanonicalRegistry(BaseModel):
    dimensions: dict[str, CanonicalDimension]


class VendorDimensionMapping(BaseModel):
    source_column: str
    value_map: dict[str, str]
    multi_select: bool | None = None
    """Optional per-mapping override; the canonical dimension's multi_select
    flag is authoritative. Present in the vendor YAML only for the
    multi_select prototype case (Milieu car_ownership_reasons) as
    documentation at the point of use."""


class VendorMapping(BaseModel):
    vendor: str
    dimensions: dict[str, VendorDimensionMapping] = Field(default_factory=dict)


class ResolvedRegistry(BaseModel):
    """The canonical registry plus every vendor mapping, resolved and validated."""

    canonical: CanonicalRegistry
    vendors: dict[str, VendorMapping]

    def dimensions_for_vendor(self, vendor: str) -> dict[str, VendorDimensionMapping]:
        mapping = self.vendors.get(vendor)
        if mapping is None:
            return {}
        return mapping.dimensions


def _load_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def _check_reachability(canonical: CanonicalRegistry, vendor_mapping: VendorMapping) -> None:
    """Rule 1: every canonical category must be reachable from every vendor
    mapping that declares the dimension. Cheap, YAML-only. non_response
    categories participate like any other category."""
    for dimension_name, dim_mapping in vendor_mapping.dimensions.items():
        canonical_dim = canonical.dimensions.get(dimension_name)
        if canonical_dim is None:
            raise DimensionNotInCanonicalError(vendor_mapping.vendor, dimension_name)

        reached = set(dim_mapping.value_map.values())
        for category in canonical_dim.categories:
            if category.value not in reached:
                raise CanonicalCategoryUnreachableError(
                    vendor_mapping.vendor, dimension_name, category.value
                )


def _raw_values_for_column(
    survey: Survey, source_column: str, multi_select: bool
) -> set[str]:
    """Collect the distinct source values actually present in a survey's
    responses for a given source column (qid). For multi_select dimensions,
    splits on the module-level delimiter used by the multi-response ingest
    path (surveytool.ingest.milieu._MULTI_DELIMITER, "; ")."""
    values: set[str] = set()
    for response in survey.responses:
        if response.qid != source_column:
            continue
        if response.raw_value is None:
            continue
        raw = str(response.raw_value)
        if multi_select:
            for part in raw.split("; "):
                part = part.strip()
                if part:
                    values.add(part)
        else:
            values.add(raw)
    return values


def _check_unmapped_source_values(
    canonical: CanonicalRegistry,
    vendor_mapping: VendorMapping,
    survey: Survey,
) -> None:
    """Rule 2: a source value present in the actual loaded data for a
    dimension's source column but absent from that vendor's value_map is a
    hard failure. Never bucketed into "other", never dropped."""
    for dimension_name, dim_mapping in vendor_mapping.dimensions.items():
        canonical_dim = canonical.dimensions[dimension_name]
        multi_select = canonical_dim.multi_select
        raw_values = _raw_values_for_column(survey, dim_mapping.source_column, multi_select)
        for raw_value in raw_values:
            if raw_value not in dim_mapping.value_map:
                raise UnmappedSourceValueError(vendor_mapping.vendor, dimension_name, raw_value)


def load_registry(
    canonical_path: Path,
    vendor_paths: dict[str, Path],
    surveys: dict[str, Survey] | None = None,
) -> ResolvedRegistry:
    """Load and validate the demographic registry.

    Parameters
    ----------
    canonical_path:
        Path to canonical.yaml.
    vendor_paths:
        Map of vendor name -> path to that vendor's mapping YAML.
    surveys:
        Optional map of vendor name -> loaded Survey, used for the
        unmapped-source-value check (rule 2). If a vendor has no entry here,
        rule 2 is skipped for that vendor (rule 1 still runs for all vendors
        regardless).

    Raises
    ------
    DimensionNotInCanonicalError
        A vendor mapping declares a dimension not present in canonical.yaml.
    CanonicalCategoryUnreachableError
        A canonical category is unreachable from a vendor mapping that
        declares that dimension.
    UnmappedSourceValueError
        A source value present in the actual loaded data has no entry in
        that vendor's value_map.
    """
    canonical = CanonicalRegistry.model_validate(_load_yaml(canonical_path))

    vendor_mappings: dict[str, VendorMapping] = {}
    for vendor_name, path in vendor_paths.items():
        vendor_mappings[vendor_name] = VendorMapping.model_validate(_load_yaml(path))

    # Rule 1 first, for every vendor, before any rule 2 check runs.
    for vendor_mapping in vendor_mappings.values():
        _check_reachability(canonical, vendor_mapping)

    # Rule 2, only for vendors with loaded survey data available.
    surveys = surveys or {}
    for vendor_name, vendor_mapping in vendor_mappings.items():
        survey = surveys.get(vendor_name)
        if survey is None:
            continue
        _check_unmapped_source_values(canonical, vendor_mapping, survey)

    return ResolvedRegistry(canonical=canonical, vendors=vendor_mappings)
