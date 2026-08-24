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
    NotCollectedConflictsWithValueMapError,
    NotCollectedReasonMissingError,
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


class NotCollectedDeclaration(BaseModel):
    """One canonical category a vendor's dimension mapping declares as a
    genuine content gap rather than a value_map omission (Task 9).

    ``reason`` is required free text explaining why (no silent placeholder).
    ``ambiguous_raw_values`` is only needed for the rarer case where the
    vendor's source column DOES contain real respondents whose raw value
    cannot be resolved to any single canonical category at the tool's
    granularity (e.g. Toluna's "55 years old and above" bucket covers both
    55_64 and 65_plus with no way to tell them apart) — listing the raw
    value here tells _check_unmapped_source_values it has been accounted
    for by a deliberate not-collected declaration, not missed by accident.
    Left empty (the common case, e.g. PureSpectrum's under_18) when the
    category simply has no respondents in the source data at all."""

    reason: str
    ambiguous_raw_values: list[str] = Field(default_factory=list)


class VendorDimensionMapping(BaseModel):
    source_column: str
    value_map: dict[str, str]
    multi_select: bool | None = None
    """Optional per-mapping override; the canonical dimension's multi_select
    flag is authoritative. Present in the vendor YAML only for the
    multi_select prototype case (Milieu car_ownership_reasons) as
    documentation at the point of use."""
    not_collected: dict[str, NotCollectedDeclaration] = Field(default_factory=dict)
    """Canonical category value -> declaration of why this vendor's source
    column genuinely has no data reaching that category (Task 9).

    A category listed here satisfies _check_reachability without needing a
    value_map entry: it is a real, investigated content gap (e.g. no
    under-18 band in a vendor's age codebook), not an authoring omission.
    Declaring a category here never removes it from view — build_run_summary
    turns it into a stated-gap sentence, and compute_breaks_crosstab attaches
    a matching note to any QuestionResult broken by a dimension carrying one,
    so an analyst always sees why a category never appears as a column."""


class VendorMapping(BaseModel):
    vendor: str
    dimensions: dict[str, VendorDimensionMapping] = Field(default_factory=dict)


class NotCollectedEntry(BaseModel):
    """One declared-not-collected category, resolved with its canonical
    label for display (run summary sentences, chart/table notes)."""

    dimension: str
    dimension_label: str
    category_value: str
    category_label: str
    reason: str


class ResolvedRegistry(BaseModel):
    """The canonical registry plus every vendor mapping, resolved and validated."""

    canonical: CanonicalRegistry
    vendors: dict[str, VendorMapping]

    def dimensions_for_vendor(self, vendor: str) -> dict[str, VendorDimensionMapping]:
        mapping = self.vendors.get(vendor)
        if mapping is None:
            return {}
        return mapping.dimensions

    def not_collected_for_vendor(self, vendor: str) -> list[NotCollectedEntry]:
        """Every declared-not-collected category across every dimension this
        vendor maps, resolved with canonical labels, in canonical dimension
        iteration order then category value order — used by build_run_summary
        (Task 1's always-present-statement pattern) and by
        compute_breaks_crosstab to attach a note to any result broken by a
        dimension carrying a not-collected category."""
        entries: list[NotCollectedEntry] = []
        for dimension_name, dim_mapping in self.dimensions_for_vendor(vendor).items():
            if not dim_mapping.not_collected:
                continue
            canonical_dim = self.canonical.dimensions.get(dimension_name)
            if canonical_dim is None:
                continue
            category_labels = {c.value: c.label for c in canonical_dim.categories}
            for category_value, declaration in dim_mapping.not_collected.items():
                entries.append(
                    NotCollectedEntry(
                        dimension=dimension_name,
                        dimension_label=canonical_dim.label,
                        category_value=category_value,
                        category_label=category_labels.get(category_value, category_value),
                        reason=declaration.reason,
                    )
                )
        return entries


def _load_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


_DEMOGRAPHICS_DIR = Path(__file__).parent / "demographics"


def declared_demographic_source_columns(vendor: str) -> frozenset[str]:
    """The set of source_column qids a vendor's demographic YAML declares
    (e.g. Rakuten's S1-S4, Milieu's q5-q8) — used by the load-path
    unresolved-question collector (Task 5) to exempt declared demographics
    from the resolver without waiting for a full Survey to exist, since
    ResolvedRegistry's own reachability/unmapped-value checks (above) need
    an already-built Survey and run after load(), not during it.

    Deliberately a plain source_column name lookup, not a full
    VendorMapping.model_validate — this only needs to answer "is this qid
    spoken for", not validate reachability, which load_registry still does
    separately, later, against the built Survey.
    """
    path = _DEMOGRAPHICS_DIR / f"vendor_{vendor}.yaml"
    if not path.exists():
        return frozenset()
    raw = _load_yaml(path) or {}
    dimensions = raw.get("dimensions") or {}
    return frozenset(
        str(dim["source_column"])
        for dim in dimensions.values()
        if isinstance(dim, dict) and "source_column" in dim
    )


def _check_reachability(canonical: CanonicalRegistry, vendor_mapping: VendorMapping) -> None:
    """Rule 1: every canonical category must be reachable from every vendor
    mapping that declares the dimension. Cheap, YAML-only. non_response
    categories participate like any other category.

    A category listed in a dimension mapping's `not_collected` (Task 9)
    counts as reachable here: it is a declared, reasoned content gap rather
    than a missing value_map entry, so it must not raise
    CanonicalCategoryUnreachableError. `not_collected` reasons are required
    to be non-empty free text (never a silent placeholder) and must not
    overlap with a category the value_map already reaches, since a category
    can't simultaneously be collected and not collected.
    """
    for dimension_name, dim_mapping in vendor_mapping.dimensions.items():
        canonical_dim = canonical.dimensions.get(dimension_name)
        if canonical_dim is None:
            raise DimensionNotInCanonicalError(vendor_mapping.vendor, dimension_name)

        reached = set(dim_mapping.value_map.values())

        for category_value, declaration in dim_mapping.not_collected.items():
            if not declaration.reason or not declaration.reason.strip():
                raise NotCollectedReasonMissingError(
                    vendor_mapping.vendor, dimension_name, category_value
                )
            if category_value in reached:
                raise NotCollectedConflictsWithValueMapError(
                    vendor_mapping.vendor, dimension_name, category_value
                )

        reachable = reached | set(dim_mapping.not_collected)
        for category in canonical_dim.categories:
            if category.value not in reachable:
                raise CanonicalCategoryUnreachableError(
                    vendor_mapping.vendor, dimension_name, category.value
                )


def _code_to_label_for_column(survey: Survey, source_column: str) -> dict[str, str]:
    """Build a {code: label} lookup (both as strings) from the Question
    matching source_column, if the survey carries parsed Question metadata.

    This exists because Milieu and Toluna have no fixed vendor codebook: their
    ingest adapters (surveytool.ingest.milieu / .toluna) assign numeric codes
    to labels purely by first-appearance order within the loaded rows (see
    _collect_single_values / _collect_multi_values). Those numbers are an
    artifact of a specific file's row order, not stable vendor codes, so
    those vendors' value_map YAML keys on the label text instead. Resolving
    a response's numeric raw_value back to its label here lets the same
    lookup logic work uniformly regardless of whether a vendor's value_map
    happens to key on codes (Rakuten, which has a genuine fixed Datamap
    codebook) or on labels (Milieu, Toluna).
    """
    for question in survey.questions:
        if question.qid == source_column:
            return {str(sc.code): sc.label for sc in question.labels}
    return {}


def _raw_values_for_column(
    survey: Survey, source_column: str, multi_select: bool, value_map: dict[str, str]
) -> set[str]:
    """Collect the distinct source values actually present in a survey's
    responses for a given source column (qid), resolved to whatever form
    that vendor's value_map expects. For multi_select dimensions, splits on
    the module-level delimiter used by the multi-response ingest path
    (surveytool.ingest.milieu._MULTI_DELIMITER, "; ").

    A response's raw_value is the code assigned by the ingest adapter. If
    that code isn't itself a value_map key but resolves (via the Question's
    ScaleCode.code -> .label) to a label that IS a value_map key, the label
    is used instead — this is what makes Milieu/Toluna's label-keyed
    value_map work, while leaving Rakuten's genuine code-keyed value_map
    (whose codes are already stable, from the Datamap codebook) unaffected.
    """
    code_to_label = _code_to_label_for_column(survey, source_column)
    values: set[str] = set()
    for response in survey.responses:
        if response.qid != source_column:
            continue
        if response.raw_value is None:
            continue
        raw = str(response.raw_value)
        if multi_select:
            parts = [p.strip() for p in raw.split("; ") if p.strip()]
        else:
            parts = [raw]
        for part in parts:
            if part in value_map:
                values.add(part)
            else:
                values.add(code_to_label.get(part, part))
    return values


def _check_unmapped_source_values(
    canonical: CanonicalRegistry,
    vendor_mapping: VendorMapping,
    survey: Survey,
) -> None:
    """Rule 2: a source value present in the actual loaded data for a
    dimension's source column but absent from that vendor's value_map is a
    hard failure. Never bucketed into "other", never dropped.

    A raw value listed in some category's `not_collected.ambiguous_raw_values`
    (Task 9) is the one deliberate exception: it has been explicitly
    investigated and declared as real respondent data that cannot be split
    across canonical categories at this tool's granularity (e.g. Toluna's
    "55 years old and above" spans both 55_64 and 65_plus with no finer
    breakdown in the source), so it is accounted for by that declaration
    rather than silently dropped — never an unnoticed omission.
    """
    for dimension_name, dim_mapping in vendor_mapping.dimensions.items():
        canonical_dim = canonical.dimensions[dimension_name]
        multi_select = canonical_dim.multi_select
        raw_values = _raw_values_for_column(
            survey, dim_mapping.source_column, multi_select, dim_mapping.value_map
        )
        ambiguous_raw_values = {
            raw for declaration in dim_mapping.not_collected.values()
            for raw in declaration.ambiguous_raw_values
        }
        for raw_value in raw_values:
            if raw_value in dim_mapping.value_map or raw_value in ambiguous_raw_values:
                continue
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
