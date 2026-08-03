"""Cohort resolution: turn a respondent frame plus a filter/break spec into
respondent sets and cells.

This module stops at "which respondents are in which cell" — no
question-level computation happens here (that's compute/cross_tab.py's job,
unchanged by this work).

Demographic values used for filtering and grouping are always CANONICAL
values (translated through the vendor's value_map), never raw vendor codes.
`to_canonical_demographic_frame` does that translation once; `apply_filter`
and `resolve_cells` both operate on its output.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from surveytool.core.demographic_registry import ResolvedRegistry
from surveytool.core.model import Survey

_MULTI_DELIMITER = "; "
"""Same delimiter used by surveytool.ingest.milieu._MULTI_DELIMITER and
demographic_registry.py's _raw_values_for_column for splitting multi_select
raw values. Treated as a general property (build plan section 3, rule 4),
not a Milieu special case, but this is presently the only known delimiter
in use across vendors."""


@dataclass(frozen=True)
class Cell:
    """One column of the cross-tab: an ordered tuple of (dimension, category)
    pairs matching the break spec order, the respondents in it, and the
    human-readable label path for display."""

    key: tuple[tuple[str, str], ...]
    label_path: tuple[str, ...]
    respondent_ids: frozenset[str]

    @property
    def base_cell(self) -> int:
        return len(self.respondent_ids)


def _code_to_label_for_column(survey: Survey, source_column: str) -> dict[str, str]:
    """Mirrors demographic_registry.py::_code_to_label_for_column — build a
    {code: label} lookup from the Question matching source_column, so a
    raw_value that isn't itself a value_map key can be resolved via its
    label (the Milieu/Toluna label-keyed value_map case)."""
    for question in survey.questions:
        if question.qid == source_column:
            return {str(sc.code): sc.label for sc in question.labels}
    return {}


def _resolve_raw_to_canonical(
    raw: str, value_map: dict[str, str], code_to_label: dict[str, str]
) -> str | None:
    """Resolve a single raw token (already split, if multi_select) to its
    canonical value via value_map, falling back to the token's label first
    (same resolution pattern as demographic_registry.py::_raw_values_for_column,
    but here we want the canonical value itself, not just membership)."""
    if raw in value_map:
        return value_map[raw]
    label = code_to_label.get(raw)
    if label is not None and label in value_map:
        return value_map[label]
    return None


def to_canonical_demographic_frame(
    respondent_frame: pd.DataFrame, survey: Survey, registry: ResolvedRegistry, vendor: str
) -> pd.DataFrame:
    """Produce a frame indexed by respondent_id, one column per canonical
    dimension declared by `vendor`, with values translated to canonical
    category values (or a delimited string of canonical values, for
    multi_select dimensions, joined with the same delimiter used on ingest).

    Computed once per (frame, vendor) — callers such as apply_filter and
    resolve_cells should call this once and reuse the result rather than
    re-translating per request. A real caller (a future FastAPI session) is
    expected to cache this at upload time; this function itself is pure and
    does no caching.
    """
    dim_mappings = registry.dimensions_for_vendor(vendor)
    columns: dict[str, list[str | None]] = {}
    index = list(respondent_frame.index)

    for dimension_name, dim_mapping in dim_mappings.items():
        canonical_dim = registry.canonical.dimensions.get(dimension_name)
        multi_select = bool(canonical_dim and canonical_dim.multi_select)
        source_column = dim_mapping.source_column
        code_to_label = _code_to_label_for_column(survey, source_column)

        values: list[str | None] = []
        if source_column not in respondent_frame.columns:
            values = [None] * len(index)
        else:
            for raw_value in respondent_frame[source_column]:
                if raw_value is None or (isinstance(raw_value, float) and pd.isna(raw_value)):
                    values.append(None)
                    continue
                raw = str(raw_value)
                if multi_select:
                    parts = [p.strip() for p in raw.split(_MULTI_DELIMITER) if p.strip()]
                    resolved = [
                        _resolve_raw_to_canonical(p, dim_mapping.value_map, code_to_label)
                        for p in parts
                    ]
                    resolved = [r for r in resolved if r is not None]
                    values.append(_MULTI_DELIMITER.join(resolved) if resolved else None)
                else:
                    values.append(
                        _resolve_raw_to_canonical(raw, dim_mapping.value_map, code_to_label)
                    )
        columns[dimension_name] = values

    return pd.DataFrame(columns, index=index)


def _matches_dimension(
    value: str | None, selected: list[str], multi_select: bool
) -> bool:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return False
    if multi_select:
        parts = [p.strip() for p in value.split(_MULTI_DELIMITER) if p.strip()]
        return any(p in selected for p in parts)
    return value in selected


def apply_filter(
    respondent_frame: pd.DataFrame,
    filter_spec: dict[str, list[str]],
    registry: ResolvedRegistry,
    survey: Survey,
    vendor: str,
) -> set[str]:
    """AND across dimensions in filter_spec, OR within a dimension's selected
    value list. Returns the set of matching respondent_ids.

    An empty filter_spec matches every respondent in respondent_frame.
    """
    canonical_frame = to_canonical_demographic_frame(respondent_frame, survey, registry, vendor)

    if not filter_spec:
        return set(canonical_frame.index)

    matched = pd.Series(True, index=canonical_frame.index)
    for dimension_name, selected in filter_spec.items():
        canonical_dim = registry.canonical.dimensions[dimension_name]
        multi_select = canonical_dim.multi_select
        column = canonical_frame[dimension_name]
        dim_matches = column.apply(lambda v: _matches_dimension(v, selected, multi_select))
        matched &= dim_matches

    return set(canonical_frame.index[matched])


def resolve_cells(
    respondent_frame: pd.DataFrame,
    filtered_ids: set[str],
    break_spec: list[str],
    registry: ResolvedRegistry,
    survey: Survey,
    vendor: str,
) -> list[Cell]:
    """Group the filtered respondents by the break dimensions IN SPEC ORDER,
    using canonical demographic values. Groups over actual rows via
    DataFrame.groupby so combinations with zero respondents never appear as
    cells — never a cartesian product of category lists.
    """
    canonical_frame = to_canonical_demographic_frame(respondent_frame, survey, registry, vendor)
    subset = canonical_frame.loc[canonical_frame.index.isin(filtered_ids)]

    if not break_spec:
        return []

    # Drop rows with a missing (unmapped / absent) value in any break
    # dimension — such a respondent cannot be placed in a cell tuple.
    subset = subset.dropna(subset=break_spec)

    if subset.empty:
        return []

    label_lookup: dict[str, dict[str, str]] = {}
    for dimension_name in break_spec:
        canonical_dim = registry.canonical.dimensions[dimension_name]
        label_lookup[dimension_name] = {
            category.value: category.label for category in canonical_dim.categories
        }

    cells: list[Cell] = []
    grouped = subset.groupby(break_spec, dropna=True)
    for group_key, group_df in grouped:
        # pandas groupby with a list of column names always yields a tuple
        # key, including for a single-column list (verified against the
        # pandas version pinned in this repo) -- do not special-case length 1.
        values = group_key if isinstance(group_key, tuple) else (group_key,)

        key = tuple(zip(break_spec, values))
        label_path = tuple(
            label_lookup[dim].get(val, str(val)) for dim, val in key
        )
        respondent_ids = frozenset(group_df.index)
        cells.append(Cell(key=key, label_path=label_path, respondent_ids=respondent_ids))

    return cells
