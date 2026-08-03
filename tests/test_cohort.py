"""cohort.py tests: apply_filter / resolve_cells semantics.

Section A: synthetic minimal registry+survey, exercising AND-across/OR-within
           filter semantics and cell resolution (empty-combo exclusion,
           key/label_path ordering).
Section B: real Milieu registry + a synthetic survey shaped like Milieu's
           real car_ownership_reasons dimension (the only real multi-select
           dimension available per Task 1's registry), exercising multi-select
           filter any-of matching through the real value_map.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from surveytool.core.cohort import apply_filter, resolve_cells, to_canonical_demographic_frame
from surveytool.core.demographic_registry import (
    CanonicalCategory,
    CanonicalDimension,
    CanonicalRegistry,
    ResolvedRegistry,
    VendorDimensionMapping,
    VendorMapping,
    load_registry,
)
from surveytool.core.model import Response, ResponseState, Survey
from surveytool.core.respondent_frame import to_respondent_frame

VENDOR = "acme"

ROOT = Path(__file__).parent.parent
DEMOGRAPHICS_DIR = ROOT / "surveytool" / "core" / "demographics"
CANONICAL_PATH = DEMOGRAPHICS_DIR / "canonical.yaml"
VENDOR_PATHS = {
    "rakuten": DEMOGRAPHICS_DIR / "vendor_rakuten.yaml",
    "milieu": DEMOGRAPHICS_DIR / "vendor_milieu.yaml",
    "toluna": DEMOGRAPHICS_DIR / "vendor_toluna.yaml",
}
MILIEU_PATH = ROOT / "milieu_survey_coe_data.csv"


# ── Section A: synthetic fixtures ────────────────────────────────────────────

def _registry() -> ResolvedRegistry:
    canonical = CanonicalRegistry(
        dimensions={
            "gender": CanonicalDimension(
                label="Gender",
                multi_select=False,
                categories=[
                    CanonicalCategory(value="male", label="Male", order=1),
                    CanonicalCategory(value="female", label="Female", order=2),
                ],
            ),
            "age_band": CanonicalDimension(
                label="Age band",
                multi_select=False,
                categories=[
                    CanonicalCategory(value="18_24", label="18-24", order=1),
                    CanonicalCategory(value="25_34", label="25-34", order=2),
                ],
            ),
            "reasons": CanonicalDimension(
                label="Reasons",
                multi_select=True,
                categories=[
                    CanonicalCategory(value="cost", label="Cost", order=1),
                    CanonicalCategory(value="time", label="Time", order=2),
                    CanonicalCategory(value="other", label="Other", order=3),
                ],
            ),
        }
    )
    vendor_mapping = VendorMapping(
        vendor=VENDOR,
        dimensions={
            "gender": VendorDimensionMapping(
                source_column="G1", value_map={"1": "male", "2": "female"}
            ),
            "age_band": VendorDimensionMapping(
                source_column="A1", value_map={"1": "18_24", "2": "25_34"}
            ),
            "reasons": VendorDimensionMapping(
                source_column="R1",
                multi_select=True,
                value_map={"1": "cost", "2": "time", "3": "other"},
            ),
        },
    )
    return ResolvedRegistry(canonical=canonical, vendors={VENDOR: vendor_mapping})


def _survey(rows: list[dict]) -> Survey:
    responses = []
    for row in rows:
        rid = row["respondent_id"]
        for qid in ("G1", "A1", "R1"):
            if qid in row:
                responses.append(
                    Response(respondent_id=rid, qid=qid, raw_value=row[qid], state=ResponseState.answered)
                )
    return Survey(id="s1", n_raw=len(rows), n_analysis=len(rows), responses=responses)


def test_and_across_or_within_filter_semantics():
    rows = [
        {"respondent_id": "r1", "G1": "1", "A1": "1"},  # male, 18_24
        {"respondent_id": "r2", "G1": "1", "A1": "2"},  # male, 25_34
        {"respondent_id": "r3", "G1": "2", "A1": "1"},  # female, 18_24
        {"respondent_id": "r4", "G1": "2", "A1": "2"},  # female, 25_34
        {"respondent_id": "r5", "G1": "1", "A1": "1"},  # male, 18_24 (dup combo)
    ]
    survey = _survey(rows)
    registry = _registry()
    frame = to_respondent_frame(survey)

    # OR within gender: male OR female is everyone -- sanity check first.
    matched_all = apply_filter(frame, {"gender": ["male", "female"]}, registry, survey, VENDOR)
    assert matched_all == {"r1", "r2", "r3", "r4", "r5"}

    # AND across gender + age_band: male AND 18_24 -> r1, r5 only.
    matched = apply_filter(
        frame, {"gender": ["male"], "age_band": ["18_24"]}, registry, survey, VENDOR
    )
    assert matched == {"r1", "r5"}

    # OR within age_band, AND with gender: male AND (18_24 OR 25_34) -> r1, r2, r5.
    matched2 = apply_filter(
        frame, {"gender": ["male"], "age_band": ["18_24", "25_34"]}, registry, survey, VENDOR
    )
    assert matched2 == {"r1", "r2", "r5"}


def test_empty_filter_spec_matches_everyone():
    rows = [{"respondent_id": f"r{i}", "G1": "1", "A1": "1"} for i in range(3)]
    survey = _survey(rows)
    registry = _registry()
    frame = to_respondent_frame(survey)

    matched = apply_filter(frame, {}, registry, survey, VENDOR)
    assert matched == {"r0", "r1", "r2"}


def test_multiselect_filter_any_of_matching_synthetic():
    rows = [
        {"respondent_id": "r1", "G1": "1", "A1": "1", "R1": "1; 2"},  # cost, time
        {"respondent_id": "r2", "G1": "1", "A1": "1", "R1": "2"},  # time only
        {"respondent_id": "r3", "G1": "1", "A1": "1", "R1": "3"},  # other only
    ]
    survey = _survey(rows)
    registry = _registry()
    frame = to_respondent_frame(survey)

    # Selecting "cost" should match r1 only (any-of, not all-of).
    matched = apply_filter(frame, {"reasons": ["cost"]}, registry, survey, VENDOR)
    assert matched == {"r1"}

    # Selecting "cost" or "other" should match r1 and r3.
    matched2 = apply_filter(frame, {"reasons": ["cost", "other"]}, registry, survey, VENDOR)
    assert matched2 == {"r1", "r3"}


def test_cell_resolution_never_produces_empty_combos():
    """3 respondents, one per gender/age combo present, but the full
    cartesian product of {male, female} x {18_24, 25_34} has 4 slots.
    cell_count must equal the number of distinct value-tuples actually
    present (2, not 4)."""
    rows = [
        {"respondent_id": "r1", "G1": "1", "A1": "1"},  # male, 18_24
        {"respondent_id": "r2", "G1": "1", "A1": "1"},  # male, 18_24 (same combo)
        {"respondent_id": "r3", "G1": "2", "A1": "2"},  # female, 25_34
        # note: no male/25_34, no female/18_24 -- those combos must not appear
    ]
    survey = _survey(rows)
    registry = _registry()
    frame = to_respondent_frame(survey)

    filtered_ids = apply_filter(frame, {}, registry, survey, VENDOR)
    cells = resolve_cells(frame, filtered_ids, ["gender", "age_band"], registry, survey, VENDOR)

    distinct_combos_present = {("male", "18_24"), ("female", "25_34")}
    assert len(cells) == len(distinct_combos_present) == 2
    cell_combos = {tuple(v for _, v in cell.key) for cell in cells}
    assert cell_combos == distinct_combos_present

    male_cell = next(c for c in cells if c.key == (("gender", "male"), ("age_band", "18_24")))
    assert male_cell.respondent_ids == frozenset({"r1", "r2"})
    assert male_cell.base_cell == 2


def test_key_and_label_path_ordering_matches_break_spec_order():
    rows = [
        {"respondent_id": "r1", "G1": "1", "A1": "1"},
        {"respondent_id": "r2", "G1": "2", "A1": "2"},
    ]
    survey = _survey(rows)
    registry = _registry()
    frame = to_respondent_frame(survey)
    filtered_ids = apply_filter(frame, {}, registry, survey, VENDOR)

    # break_spec = [age_band, gender] -- reversed order from the dims above.
    cells = resolve_cells(frame, filtered_ids, ["age_band", "gender"], registry, survey, VENDOR)
    for cell in cells:
        assert [dim for dim, _ in cell.key] == ["age_band", "gender"]
        # label_path must correspond 1:1 with key order.
        assert len(cell.label_path) == len(cell.key)

    # Confirm labels are the human-readable canonical labels, not raw codes.
    labels_seen = {label for cell in cells for label in cell.label_path}
    assert labels_seen <= {"18-24", "25-34", "Male", "Female"}


def test_base_total_base_filtered_base_cell_are_plain_lengths():
    rows = [
        {"respondent_id": "r1", "G1": "1", "A1": "1"},
        {"respondent_id": "r2", "G1": "1", "A1": "1"},
        {"respondent_id": "r3", "G1": "2", "A1": "2"},
    ]
    survey = _survey(rows)
    registry = _registry()
    frame = to_respondent_frame(survey)

    base_total = len(frame)
    assert base_total == 3

    filtered_ids = apply_filter(frame, {"gender": ["male"]}, registry, survey, VENDOR)
    base_filtered = len(filtered_ids)
    assert base_filtered == 2

    cells = resolve_cells(frame, filtered_ids, ["age_band"], registry, survey, VENDOR)
    assert len(cells) == 1
    assert cells[0].base_cell == 2


# ── Section B: real Milieu registry, real car_ownership_reasons dimension ───

@pytest.fixture(scope="module")
def milieu_registry_and_survey():
    if not MILIEU_PATH.exists():
        pytest.skip("HC file milieu_survey_coe_data.csv not found in project root")
    from surveytool.ingest.milieu import load

    survey = load(MILIEU_PATH, "coe")
    registry = load_registry(
        CANONICAL_PATH, {"milieu": VENDOR_PATHS["milieu"]}, surveys={"milieu": survey}
    )
    return registry, survey


def test_real_milieu_multiselect_dimension_any_of_matching(milieu_registry_and_survey):
    registry, survey = milieu_registry_and_survey
    frame = to_respondent_frame(survey)

    canonical_frame = to_canonical_demographic_frame(frame, survey, registry, "milieu")
    assert "car_ownership_reasons" in canonical_frame.columns

    # Pick a canonical value known to be reachable per vendor_milieu.yaml.
    matched = apply_filter(
        frame, {"car_ownership_reasons": ["cost_too_high"]}, registry, survey, "milieu"
    )
    # Every matched respondent's raw column, once translated, must actually
    # contain "cost_too_high" among its delimited canonical values.
    for rid in matched:
        value = canonical_frame.loc[rid, "car_ownership_reasons"]
        assert value is not None
        parts = [p.strip() for p in str(value).split("; ")]
        assert "cost_too_high" in parts

    # Respondents not matched must NOT have cost_too_high in their parts.
    non_matched = set(canonical_frame.index) - matched
    for rid in non_matched:
        value = canonical_frame.loc[rid, "car_ownership_reasons"]
        if value is None:
            continue
        parts = [p.strip() for p in str(value).split("; ")]
        assert "cost_too_high" not in parts


def test_real_milieu_cell_resolution_on_car_ownership(milieu_registry_and_survey):
    registry, survey = milieu_registry_and_survey
    frame = to_respondent_frame(survey)

    filtered_ids = apply_filter(frame, {}, registry, survey, "milieu")
    cells = resolve_cells(frame, filtered_ids, ["car_ownership"], registry, survey, "milieu")

    # cell_count must equal distinct canonical car_ownership values actually
    # present among filtered respondents, not the full canonical category count.
    canonical_frame = to_canonical_demographic_frame(frame, survey, registry, "milieu")
    present_values = set(canonical_frame.loc[list(filtered_ids), "car_ownership"].dropna())
    assert {cell.key[0][1] for cell in cells} == present_values

    total_in_cells = sum(cell.base_cell for cell in cells)
    # Respondents with a missing/unmapped car_ownership value are excluded
    # from cells (can't be placed in a cell tuple) -- so total_in_cells may
    # be <= len(filtered_ids), never more.
    assert total_in_cells <= len(filtered_ids)
