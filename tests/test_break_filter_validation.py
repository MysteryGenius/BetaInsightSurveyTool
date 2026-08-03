"""break_filter.validate_request tests.

Section A: synthetic minimal canonical+vendor registry (built in-process via
           the pydantic models, no YAML files needed) exercising each
           failure code in build plan section 4's exact order, a
           first-failure-wins ordering test, and a success case.
"""
from __future__ import annotations

import pandas as pd
import pytest

from surveytool.charts.errors import (
    DemographicNotInRegistryError,
    DimensionInBreakAndFilterError,
    DuplicateBreakDimensionError,
    FilterZeroMatchError,
    MultiselectBreakRejectedError,
    SurveyToolError,
)
from surveytool.core.break_filter import BreakSpec, FilterSpec, validate_request
from surveytool.core.demographic_registry import (
    CanonicalCategory,
    CanonicalDimension,
    CanonicalRegistry,
    ResolvedRegistry,
    VendorDimensionMapping,
    VendorMapping,
)
from surveytool.core.model import Response, ResponseState, Survey
from surveytool.core.respondent_frame import to_respondent_frame

VENDOR = "acme"


def _registry(*, include_multiselect: bool = False, vendor_has_age: bool = True) -> ResolvedRegistry:
    categories = {
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
    }
    if include_multiselect:
        categories["reasons"] = CanonicalDimension(
            label="Reasons",
            multi_select=True,
            categories=[
                CanonicalCategory(value="cost", label="Cost", order=1),
                CanonicalCategory(value="time", label="Time", order=2),
            ],
        )

    canonical = CanonicalRegistry(dimensions=categories)

    vendor_dims = {
        "gender": VendorDimensionMapping(
            source_column="G1", value_map={"1": "male", "2": "female"}
        ),
    }
    if vendor_has_age:
        vendor_dims["age_band"] = VendorDimensionMapping(
            source_column="A1", value_map={"1": "18_24", "2": "25_34"}
        )
    if include_multiselect:
        vendor_dims["reasons"] = VendorDimensionMapping(
            source_column="R1",
            multi_select=True,
            value_map={"1": "cost", "2": "time"},
        )

    vendor_mapping = VendorMapping(vendor=VENDOR, dimensions=vendor_dims)
    return ResolvedRegistry(canonical=canonical, vendors={VENDOR: vendor_mapping})


def _survey(rows: list[dict]) -> Survey:
    """rows: list of {respondent_id, G1, A1, R1 (optional)} raw values."""
    responses = []
    for row in rows:
        rid = row["respondent_id"]
        for qid in ("G1", "A1", "R1"):
            if qid in row:
                responses.append(
                    Response(respondent_id=rid, qid=qid, raw_value=row[qid], state=ResponseState.answered)
                )
    return Survey(id="s1", n_raw=len(rows), n_analysis=len(rows), responses=responses)


def _default_rows(n_each: int = 3) -> list[dict]:
    rows = []
    i = 0
    for gender_code in ("1", "2"):
        for age_code in ("1", "2"):
            for _ in range(n_each):
                rows.append({"respondent_id": f"r{i}", "G1": gender_code, "A1": age_code})
                i += 1
    return rows


def test_demographic_not_in_registry_raises():
    registry = _registry()
    survey = _survey(_default_rows())
    frame = to_respondent_frame(survey)

    with pytest.raises(DemographicNotInRegistryError) as exc_info:
        validate_request(
            BreakSpec(dimensions=["not_a_real_dimension"]),
            FilterSpec(),
            registry,
            survey,
            VENDOR,
            frame,
        )
    assert exc_info.value.dimension == "not_a_real_dimension"


def test_duplicate_break_dimension_raises():
    registry = _registry()
    survey = _survey(_default_rows())
    frame = to_respondent_frame(survey)

    with pytest.raises(DuplicateBreakDimensionError) as exc_info:
        validate_request(
            BreakSpec(dimensions=["gender", "gender"]),
            FilterSpec(),
            registry,
            survey,
            VENDOR,
            frame,
        )
    assert exc_info.value.dimension == "gender"


def test_dimension_in_break_and_filter_raises():
    registry = _registry()
    survey = _survey(_default_rows())
    frame = to_respondent_frame(survey)

    with pytest.raises(DimensionInBreakAndFilterError) as exc_info:
        validate_request(
            BreakSpec(dimensions=["gender"]),
            FilterSpec(selections={"gender": ["male"]}),
            registry,
            survey,
            VENDOR,
            frame,
        )
    assert exc_info.value.dimension == "gender"


def test_vendor_mismatch_raises_when_break_dimension_unavailable_for_vendor():
    registry = _registry(vendor_has_age=False)
    survey = _survey([{"respondent_id": "r0", "G1": "1"}])
    frame = to_respondent_frame(survey)

    with pytest.raises(SurveyToolError) as exc_info:
        validate_request(
            BreakSpec(dimensions=["age_band"]),
            FilterSpec(),
            registry,
            survey,
            VENDOR,
            frame,
        )
    assert exc_info.value.code.value == "VENDOR_MISMATCH"
    assert "age_band" in exc_info.value.detail


def test_multiselect_break_rejected_raises_with_plain_english_message():
    registry = _registry(include_multiselect=True)
    rows = _default_rows(1)
    for row in rows:
        row["R1"] = "1; 2"
    survey = _survey(rows)
    frame = to_respondent_frame(survey)

    with pytest.raises(MultiselectBreakRejectedError) as exc_info:
        validate_request(
            BreakSpec(dimensions=["reasons"]),
            FilterSpec(),
            registry,
            survey,
            VENDOR,
            frame,
        )
    assert exc_info.value.dimension == "reasons"
    # Message shown verbatim to non-technical analysts: must name the
    # column and plainly state a respondent may hold more than one value.
    assert "Reasons" in str(exc_info.value)
    assert "more than one" in str(exc_info.value)


def test_filter_zero_match_raises_disjoint_dims():
    registry = _registry()
    # Every respondent is gender=male; filter for female should match nobody.
    rows = [{"respondent_id": f"r{i}", "G1": "1", "A1": "1"} for i in range(5)]
    survey = _survey(rows)
    frame = to_respondent_frame(survey)

    with pytest.raises(FilterZeroMatchError) as exc_info:
        validate_request(
            BreakSpec(dimensions=["age_band"]),
            FilterSpec(selections={"gender": ["female"]}),
            registry,
            survey,
            VENDOR,
            frame,
        )
    assert "gender" in exc_info.value.detail


def test_success_case_raises_nothing():
    registry = _registry()
    survey = _survey(_default_rows())
    frame = to_respondent_frame(survey)

    validate_request(
        BreakSpec(dimensions=["age_band"]),
        FilterSpec(selections={"gender": ["male"]}),
        registry,
        survey,
        VENDOR,
        frame,
    )


# ── Ordering test: first-failure-wins ────────────────────────────────────────

def test_first_failure_wins_duplicate_before_break_and_filter_overlap():
    """Construct a request that simultaneously triggers check 2
    (DUPLICATE_BREAK_DIMENSION: 'gender' appears twice in break_spec) and
    check 3 (DIMENSION_IN_BREAK_AND_FILTER: 'gender' also in filter_spec).
    Check 2 is earlier in build plan section 4's order, so it must win."""
    registry = _registry()
    survey = _survey(_default_rows())
    frame = to_respondent_frame(survey)

    with pytest.raises(DuplicateBreakDimensionError):
        validate_request(
            BreakSpec(dimensions=["gender", "gender"]),
            FilterSpec(selections={"gender": ["male"]}),
            registry,
            survey,
            VENDOR,
            frame,
        )


def test_first_failure_wins_unknown_dimension_before_vendor_mismatch():
    """A break spec with an unknown dimension name would also (if it were
    real) trigger VENDOR_MISMATCH, but DEMOGRAPHIC_NOT_IN_REGISTRY (check 1)
    must win since it runs first."""
    registry = _registry(vendor_has_age=False)
    survey = _survey([{"respondent_id": "r0", "G1": "1"}])
    frame = to_respondent_frame(survey)

    with pytest.raises(DemographicNotInRegistryError):
        validate_request(
            BreakSpec(dimensions=["nonexistent_dim"]),
            FilterSpec(),
            registry,
            survey,
            VENDOR,
            frame,
        )
