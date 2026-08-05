"""Conformance cases over real vendor files (build plan section 13).

One test (or, where a case genuinely cannot run against real data, one
explicitly-labelled test plus a reported gap) per bullet in section 13's
conformance list. Everything here runs against the three real fixture files in
the project root and skips cleanly if a fixture is absent -- never silently
passes when the fixture is present but the case is untested.

Real-data facts this file depends on, all verified by inspection for Task 10
rather than assumed:

* Rakuten (support-measures, N=1000) declares 4 dimensions: gender, age_band,
  ethnicity, residential_status. ``residential_status`` is DEGENERATE on this
  fixture -- all 1000 respondents are Singapore Citizens -- so it is usable for
  VENDOR_MISMATCH and for validation cases but is useless as a break partner,
  and Rakuten's real depth-3 uses gender + age_band + ethnicity.
* Toluna (misinformation, N=1000) declares 4 dimensions: gender, ethnicity,
  income, education. It has NO age_band mapping at all -- 5 bands exist in the
  data but do not cover the canonical 7-band set (no "Below 18"; a single
  "55 and above" bucket that cannot be split into 55_64 / 65_plus without
  inventing a boundary). A genuine vendor gap, deliberate since Task 1.
* Milieu (COE, N=1000) declares 4 dimensions: gender, ethnicity,
  car_ownership, car_ownership_reasons. The last is the ONLY confirmed
  multi_select dimension across all three vendors, and being multi_select it
  is REJECTED in a break spec -- so Milieu's real depth-3 uses gender +
  ethnicity + car_ownership.
* No vendor demographic anywhere declares a non-response / declined category.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from surveytool.charts.errors import (
    ErrorCode,
    FilterZeroMatchError,
    MultiselectBreakRejectedError,
    SurveyToolError,
    UnmappedSourceValueError,
)
from surveytool.compute.breaks_compute import compute_breaks_crosstab
from surveytool.core.break_filter import BreakSpec, FilterSpec, validate_request
from surveytool.core.chart_validity import ChartType, evaluate_chart_permissions
from surveytool.core.cohort import apply_filter
from surveytool.core.config import ToolConfig
from surveytool.core.demographic_registry import load_registry
from surveytool.core.projection import project
from surveytool.core.respondent_frame import to_respondent_frame
from surveytool.core.suppression import Band

ROOT = Path(__file__).parent.parent
DEMOGRAPHICS_DIR = ROOT / "surveytool" / "core" / "demographics"
CANONICAL_PATH = DEMOGRAPHICS_DIR / "canonical.yaml"
VENDOR_PATHS = {
    "rakuten": DEMOGRAPHICS_DIR / "vendor_rakuten.yaml",
    "toluna": DEMOGRAPHICS_DIR / "vendor_toluna.yaml",
    "milieu": DEMOGRAPHICS_DIR / "vendor_milieu.yaml",
}
FIXTURES = {
    "rakuten": ROOT / "rakuten_survey_support_measures_data.xlsx",
    "toluna": ROOT / "toluna_survey_misinformation_data.xlsx",
    "milieu": ROOT / "milieu_survey_coe_data.csv",
}

# Break dimensions actually usable (non-degenerate, non-multi_select) per
# vendor, ordered so that any prefix of length 1/2/3 is a valid break spec.
BREAK_DIMENSIONS = {
    "rakuten": ["gender", "age_band", "ethnicity"],
    "toluna": ["gender", "ethnicity", "income"],
    "milieu": ["gender", "ethnicity", "car_ownership"],
}


def _load(vendor: str):
    path = FIXTURES[vendor]
    if not path.exists():
        pytest.skip(f"HC file {path.name} not found in project root")
    if vendor == "rakuten":
        from surveytool.ingest.rakuten import load
    elif vendor == "toluna":
        from surveytool.ingest.toluna import load
    else:
        from surveytool.ingest.milieu import load
    return load(path, f"{vendor}-conformance")


@pytest.fixture(scope="module")
def surveys():
    return {vendor: _load(vendor) for vendor in FIXTURES}


@pytest.fixture(scope="module")
def frames(surveys):
    return {vendor: to_respondent_frame(survey) for vendor, survey in surveys.items()}


@pytest.fixture(scope="module")
def registry(surveys):
    """The full three-vendor registry, validated against all three real files
    (so rule 2, unmapped source values, actually runs on real data)."""
    return load_registry(CANONICAL_PATH, VENDOR_PATHS, surveys=surveys)


def _scale_qids(survey, limit=2):
    from surveytool.core.model import QuestionType

    return [q.qid for q in survey.questions if q.qtype is QuestionType.scale][:limit]


# ── Depth 1, 2, 3 breaks, all three vendors ─────────────────────────────────

@pytest.mark.parametrize("vendor", ["rakuten", "toluna", "milieu"])
@pytest.mark.parametrize("depth", [1, 2, 3])
def test_depth_1_2_3_breaks_on_real_vendor_files(
    surveys, frames, registry, vendor, depth
):
    """Depth 1/2/3 breaks compute successfully on every real vendor file, with
    a payload that is internally consistent at every depth."""
    survey = surveys[vendor]
    frame = frames[vendor]
    break_spec = BREAK_DIMENSIONS[vendor][:depth]
    qids = _scale_qids(survey)
    assert qids, f"{vendor} fixture has no scale questions to compute"

    # The request must validate, not just compute.
    validate_request(
        BreakSpec(dimensions=break_spec), FilterSpec(), registry, survey, vendor, frame
    )

    results = compute_breaks_crosstab(
        frame, survey, break_spec, {}, qids, registry, vendor, ToolConfig()
    )

    assert len(results) == len(qids)
    for result in results:
        assert result.columns, f"{vendor} depth-{depth} produced no columns"
        assert result.base_total == len(frame)
        assert result.base_filtered == len(frame)
        # Cells partition the filtered set at every depth (single-select dims).
        assert sum(c.base_cell for c in result.columns) == result.base_filtered
        for column in result.columns:
            assert len(column.key) == depth
            assert [d for d, _ in column.key] == break_spec
            assert len(column.label_path) == depth
            assert column.base_cell > 0
        # Deeper breaks must produce at least as many columns as shallower.
        assert len(result.columns) >= depth


@pytest.mark.parametrize("vendor", ["rakuten", "toluna", "milieu"])
def test_deeper_breaks_strictly_subdivide_shallower_ones(
    surveys, frames, registry, vendor
):
    """Depth 2 is a refinement of depth 1 on every real file: each depth-2
    cell nests inside exactly one depth-1 cell, and the bases add up."""
    survey, frame = surveys[vendor], frames[vendor]
    d1, d2 = BREAK_DIMENSIONS[vendor][:1], BREAK_DIMENSIONS[vendor][:2]
    qid = _scale_qids(survey, limit=1)[0]

    r1 = compute_breaks_crosstab(
        frame, survey, d1, {}, [qid], registry, vendor, ToolConfig()
    )[0]
    r2 = compute_breaks_crosstab(
        frame, survey, d2, {}, [qid], registry, vendor, ToolConfig()
    )[0]

    rollup: dict[str, int] = {}
    for column in r2.columns:
        rollup[column.key[0][1]] = rollup.get(column.key[0][1], 0) + column.base_cell
    assert rollup == {c.key[0][1]: c.base_cell for c in r1.columns}


def test_toluna_has_no_age_band_dimension_at_all(registry):
    """Documents the real Toluna gap that constrains its break dimensions:
    age_band is absent from the mapping entirely (5 real bands do not cover
    the canonical 7-band set), so Toluna's depth-3 uses income instead."""
    assert "age_band" not in registry.dimensions_for_vendor("toluna")
    assert "age_band" in registry.dimensions_for_vendor("rakuten")


def test_rakuten_residential_status_is_degenerate_on_this_fixture(
    surveys, frames, registry
):
    """Documents why residential_status is not used as a break partner: every
    respondent on this fixture is a Singapore Citizen, so a break on it is a
    single column and proves nothing about nesting."""
    survey, frame = surveys["rakuten"], frames["rakuten"]
    result = compute_breaks_crosstab(
        frame, survey, ["residential_status"], {}, ["Q1"], registry, "rakuten", ToolConfig()
    )[0]
    assert len(result.columns) == 1
    assert result.columns[0].key[0][1] == "citizen"
    assert result.columns[0].base_cell == result.base_filtered


# ── Break on a dimension containing a non-response category ─────────────────

def test_no_real_vendor_demographic_declares_a_non_response_category(surveys, registry):
    """CONFORMANCE GAP, REPORTED NOT PAPERED OVER.

    Section 13 asks for a break on a dimension containing a non-response
    category. No such dimension exists in ANY real vendor file: this test
    asserts that absence directly, over the real parsed codebooks of every
    demographic source column of all three vendors, plus over the canonical
    registry itself. The positive behaviour (a non_response category forming
    its own cell) is therefore covered by a clearly-labelled SYNTHETIC
    fixture in
    ``tests/test_breaks_invariants.py::test_inv2_non_response_appears_as_its_own_cell_SYNTHETIC``.

    If a future vendor file DOES carry a non-response code, this test fails
    loudly -- which is the intended signal to replace the synthetic fixture
    with the real case.
    """
    # No canonical category is flagged non_response.
    flagged = [
        (name, category.value)
        for name, dimension in registry.canonical.dimensions.items()
        for category in dimension.categories
        if category.non_response
    ]
    assert flagged == [], f"canonical registry now declares non_response categories: {flagged}"

    # And no real vendor source column carries a declined/refused style code.
    markers = ("prefer not", "decline", "refus", "rather not", "don't know", "dont know")
    found = []
    for vendor, survey in surveys.items():
        source_columns = {
            mapping.source_column
            for mapping in registry.dimensions_for_vendor(vendor).values()
        }
        for question in survey.questions:
            if question.qid not in source_columns:
                continue
            for code in question.labels:
                if any(marker in code.label.lower() for marker in markers):
                    found.append((vendor, question.qid, code.label))
    assert found == [], f"a real vendor demographic now has a non-response code: {found}"


# ── Filters: one dimension, two dimensions, AND across / OR within ──────────

def test_filter_on_one_dimension_real(surveys, frames, registry):
    survey, frame = surveys["rakuten"], frames["rakuten"]
    males = apply_filter(frame, {"gender": ["male"]}, registry, survey, "rakuten")
    result = compute_breaks_crosstab(
        frame, survey, ["ethnicity"], {"gender": ["male"]}, ["Q1"], registry, "rakuten", ToolConfig()
    )[0]
    assert result.base_total == len(frame)
    assert result.base_filtered == len(males) < len(frame)
    assert sum(c.base_cell for c in result.columns) == result.base_filtered


def test_filter_or_within_a_dimension_is_a_union(surveys, frames, registry):
    """OR within: selecting both categories of a dimension matches the union,
    and on a dimension with no unmapped values that is everyone."""
    survey, frame = surveys["rakuten"], frames["rakuten"]
    male = apply_filter(frame, {"gender": ["male"]}, registry, survey, "rakuten")
    female = apply_filter(frame, {"gender": ["female"]}, registry, survey, "rakuten")
    both = apply_filter(frame, {"gender": ["male", "female"]}, registry, survey, "rakuten")

    assert male and female
    assert not (male & female)
    assert both == male | female
    assert len(both) == len(male) + len(female)

    three = apply_filter(
        frame, {"ethnicity": ["chinese", "malay", "indian"]}, registry, survey, "rakuten"
    )
    for single in ("chinese", "malay", "indian"):
        assert apply_filter(frame, {"ethnicity": [single]}, registry, survey, "rakuten") <= three


def test_filter_and_across_two_dimensions_is_an_intersection(surveys, frames, registry):
    """AND across: two filter dimensions intersect, never union."""
    survey, frame = surveys["rakuten"], frames["rakuten"]
    male = apply_filter(frame, {"gender": ["male"]}, registry, survey, "rakuten")
    chinese = apply_filter(frame, {"ethnicity": ["chinese"]}, registry, survey, "rakuten")
    both = apply_filter(
        frame, {"gender": ["male"], "ethnicity": ["chinese"]}, registry, survey, "rakuten"
    )

    assert both == male & chinese
    assert 0 < len(both) < min(len(male), len(chinese))

    # Same semantics end-to-end through the compute path.
    result = compute_breaks_crosstab(
        frame,
        survey,
        ["age_band"],
        {"gender": ["male"], "ethnicity": ["chinese"]},
        ["Q1"],
        registry,
        "rakuten",
        ToolConfig(),
    )[0]
    assert result.base_filtered == len(both)


def test_filter_combining_or_within_and_and_across(surveys, frames, registry):
    """The two rules together: (male OR female) AND (chinese OR malay)."""
    survey, frame = surveys["rakuten"], frames["rakuten"]
    matched = apply_filter(
        frame,
        {"gender": ["male", "female"], "ethnicity": ["chinese", "malay"]},
        registry,
        survey,
        "rakuten",
    )
    genders = apply_filter(frame, {"gender": ["male", "female"]}, registry, survey, "rakuten")
    ethnicities = apply_filter(
        frame, {"ethnicity": ["chinese", "malay"]}, registry, survey, "rakuten"
    )
    assert matched == genders & ethnicities


# ── Filter producing zero matches → FILTER_ZERO_MATCH ──────────────────────

def test_filter_zero_match_on_real_data(surveys, frames, registry):
    """A real, implausible-but-legal combination: Rakuten's codebook declares
    a "Below 18 years old" band, but zero respondents fall in it (the survey
    screened to adults), so filtering to it matches nobody."""
    survey, frame = surveys["rakuten"], frames["rakuten"]
    assert apply_filter(frame, {"age_band": ["under_18"]}, registry, survey, "rakuten") == set()

    with pytest.raises(FilterZeroMatchError) as exc_info:
        validate_request(
            BreakSpec(dimensions=["gender"]),
            FilterSpec(selections={"age_band": ["under_18"]}),
            registry,
            survey,
            "rakuten",
            frame,
        )
    assert exc_info.value.code is ErrorCode.FILTER_ZERO_MATCH

    # And in-band through the projection path, which never raises. The break
    # dimension must be disjoint from the filter dimensions, or the earlier
    # DIMENSION_IN_BREAK_AND_FILTER check fires first (first-failure-wins).
    projection = project(
        BreakSpec(dimensions=["ethnicity"]),
        FilterSpec(selections={"gender": ["male"], "age_band": ["under_18"]}),
        survey,
        frame,
        registry,
        "rakuten",
        ToolConfig(),
    )
    assert [e.code for e in projection.errors] == [ErrorCode.FILTER_ZERO_MATCH.value]
    assert projection.cell_count == 0


# ── Multi-select dimension in break spec → MULTISELECT_BREAK_REJECTED ──────

@pytest.mark.parametrize(
    "break_spec",
    [
        ["car_ownership_reasons"],
        ["gender", "car_ownership_reasons"],
        ["gender", "ethnicity", "car_ownership_reasons"],
    ],
)
def test_multiselect_dimension_in_break_spec_is_rejected(
    surveys, frames, registry, break_spec
):
    """Milieu's car_ownership_reasons (q8) is the only real multi_select
    dimension anywhere. It is rejected in a break spec at ANY position and
    any depth -- so it can never appear in a depth-3 break either."""
    survey, frame = surveys["milieu"], frames["milieu"]
    with pytest.raises(MultiselectBreakRejectedError) as exc_info:
        validate_request(
            BreakSpec(dimensions=break_spec),
            FilterSpec(),
            registry,
            survey,
            "milieu",
            frame,
        )
    assert exc_info.value.code is ErrorCode.MULTISELECT_BREAK_REJECTED
    assert "car_ownership_reasons" in (exc_info.value.detail or "") or "Car" in exc_info.value.message


# ── Multi-select dimension in filter spec → correct any-of matching ────────

def test_multiselect_dimension_in_filter_spec_is_any_of_matching(
    surveys, frames, registry
):
    """The same dimension IS legal in a filter, where it means any-of: a
    respondent matches if ANY of their selected reasons is in the list."""
    survey, frame = surveys["milieu"], frames["milieu"]

    validate_request(
        BreakSpec(dimensions=["gender"]),
        FilterSpec(selections={"car_ownership_reasons": ["coe_too_high"]}),
        registry,
        survey,
        "milieu",
        frame,
    )

    coe = apply_filter(
        frame, {"car_ownership_reasons": ["coe_too_high"]}, registry, survey, "milieu"
    )
    licence = apply_filter(
        frame, {"car_ownership_reasons": ["no_licence"]}, registry, survey, "milieu"
    )
    either = apply_filter(
        frame,
        {"car_ownership_reasons": ["coe_too_high", "no_licence"]},
        registry,
        survey,
        "milieu",
    )

    assert coe and licence
    assert either == coe | licence
    # Any-of, not all-of and not exactly-one: the two sets genuinely overlap,
    # so a union strictly smaller than the sum proves multi-membership.
    assert coe & licence
    assert len(either) < len(coe) + len(licence)

    result = compute_breaks_crosstab(
        frame,
        survey,
        ["gender"],
        {"car_ownership_reasons": ["coe_too_high"]},
        _scale_qids(survey, limit=1),
        registry,
        "milieu",
        ToolConfig(),
    )[0]
    assert result.base_filtered == len(coe)


# ── Dimension present in one vendor, absent in another → VENDOR_MISMATCH ───

@pytest.mark.parametrize(
    "vendor, dimension",
    [
        ("toluna", "residential_status"),
        ("milieu", "residential_status"),
        ("toluna", "age_band"),
        ("milieu", "age_band"),
        ("rakuten", "income"),
        ("rakuten", "car_ownership"),
    ],
)
def test_vendor_mismatch_for_dimension_absent_from_this_vendor(
    surveys, frames, registry, vendor, dimension
):
    """Each of these dimensions is real and mapped for at least one vendor but
    absent from the vendor under test, so requesting it raises VENDOR_MISMATCH
    with a plain-English message naming the problem.

    Single-vendor-per-session reading: a session loads exactly one vendor's
    file, so "present in one vendor and absent in another" is checked as
    "requested against a session whose loaded vendor does not declare it".
    """
    survey, frame = surveys[vendor], frames[vendor]
    # The dimension is genuinely available somewhere -- this is a vendor gap,
    # not a nonexistent dimension.
    assert any(dimension in registry.dimensions_for_vendor(v) for v in VENDOR_PATHS)
    assert dimension not in registry.dimensions_for_vendor(vendor)

    with pytest.raises(SurveyToolError) as exc_info:
        validate_request(
            BreakSpec(dimensions=[dimension]),
            FilterSpec(),
            registry,
            survey,
            vendor,
            frame,
        )
    assert exc_info.value.code is ErrorCode.VENDOR_MISMATCH
    assert dimension in (exc_info.value.detail or "")
    assert vendor in (exc_info.value.detail or "")


def test_vendor_mismatch_also_applies_to_filter_dimensions(surveys, frames, registry):
    """The same check covers a filter-only dimension, so an unavailable
    dimension can never reach apply_filter and raise a bare KeyError."""
    survey, frame = surveys["toluna"], frames["toluna"]
    with pytest.raises(SurveyToolError) as exc_info:
        validate_request(
            BreakSpec(dimensions=["gender"]),
            FilterSpec(selections={"residential_status": ["citizen"]}),
            registry,
            survey,
            "toluna",
            frame,
        )
    assert exc_info.value.code is ErrorCode.VENDOR_MISMATCH


# ── Unmapped source value present in data → hard failure ──────────────────

def test_unmapped_source_value_in_real_data_fails_naming_vendor_dimension_value(
    surveys, tmp_path
):
    """A deliberately-incomplete TEST-ONLY vendor mapping run against REAL
    Rakuten respondent data. Dropping the "3" (Indian) code from the ethnicity
    value_map must hard-fail, naming vendor, dimension and the offending
    value -- never bucketing it into "other" and never dropping it.

    The SHIPPED mappings have no such gap (Task 1's own conformance tests load
    all three real files cleanly, and the ``registry`` fixture in this module
    re-proves it on every run), so an incomplete mapping has to be constructed
    to exercise the failure path.

    Note the reported value is the resolved LABEL ("Indian"), not the raw code
    ("3"). ``demographic_registry._raw_values_for_column`` falls back from code
    to label when a code is not itself a value_map key -- the mechanism that
    makes Milieu's and Toluna's label-keyed value_maps work. For this error
    that fallback is a feature: an end user reading the message sees the
    ethnicity that is missing, not an opaque codebook integer.
    """
    survey = surveys["rakuten"]

    canonical = tmp_path / "canonical.yaml"
    canonical.write_text(
        "dimensions:\n"
        "  ethnicity:\n"
        "    label: Ethnicity\n"
        "    multi_select: false\n"
        "    categories:\n"
        "      - {value: chinese, label: Chinese, order: 1}\n"
        "      - {value: malay, label: Malay, order: 2}\n"
        "      - {value: other, label: Other, order: 3}\n",
        encoding="utf-8",
    )
    vendor = tmp_path / "vendor_rakuten_incomplete.yaml"
    vendor.write_text(
        "vendor: rakuten\n"
        "dimensions:\n"
        "  ethnicity:\n"
        '    source_column: "S4"\n'
        "    value_map:\n"
        '      "1": chinese\n'
        '      "2": malay\n'
        '      "4": other\n',  # "3" (Indian) deliberately missing
        encoding="utf-8",
    )

    with pytest.raises(UnmappedSourceValueError) as exc_info:
        load_registry(canonical, {"rakuten": vendor}, surveys={"rakuten": survey})

    error = exc_info.value
    assert error.code is ErrorCode.UNMAPPED_SOURCE_VALUE
    assert error.vendor == "rakuten"
    assert error.dimension == "ethnicity"
    assert error.raw_value == "Indian"
    # Plain English for a non-technical end user, naming all three.
    combined = f"{error.message} {error.detail or ''}"
    assert "rakuten" in combined and "ethnicity" in combined and "Indian" in combined


def test_shipped_registry_has_no_unmapped_values_on_any_real_file(registry):
    """The counterpart: the shipped mappings load cleanly against all three
    real files. (The ``registry`` fixture would have raised otherwise; this
    asserts the resolved result explicitly.)"""
    assert set(registry.vendors) == set(VENDOR_PATHS)
    for vendor in VENDOR_PATHS:
        assert registry.dimensions_for_vendor(vendor)


# ── Cell below hard threshold and cell in the low band ────────────────────

@pytest.mark.parametrize("vendor", ["rakuten", "toluna", "milieu"])
def test_real_depth3_break_produces_suppressed_and_low_base_cells(
    surveys, frames, registry, vendor
):
    """No config override needed: a real depth-3 break on every vendor file
    produces cells below the hard threshold (10) AND cells in the low band
    ([10, 20)) at the SHIPPED default config. Banding and nulling are both
    asserted against the payload."""
    survey, frame = surveys[vendor], frames[vendor]
    config = ToolConfig()
    assert config.cross_tab_suppress_threshold == 10
    assert config.suppression_low_base_multiplier == 2.0

    result = compute_breaks_crosstab(
        frame,
        survey,
        BREAK_DIMENSIONS[vendor],
        {},
        _scale_qids(survey, limit=1),
        registry,
        vendor,
        config,
    )[0]

    suppressed = [c for c in result.columns if c.band is Band.suppressed]
    low_base = [c for c in result.columns if c.band is Band.low_base]
    ok = [c for c in result.columns if c.band is Band.ok]
    assert suppressed, f"{vendor} depth-3 produced no sub-threshold cells"
    assert low_base, f"{vendor} depth-3 produced no low-band cells"
    assert ok, f"{vendor} depth-3 produced no ok cells"

    # Correct banding, read off the real base counts.
    for column in suppressed:
        assert column.base_cell < 10
    for column in low_base:
        assert 10 <= column.base_cell < 20
    for column in ok:
        assert column.base_cell >= 20

    # Correct nulling: suppressed cells lose figures but keep base and band;
    # low_base cells keep everything (they are a display warning, not a redaction).
    for column in suppressed:
        assert column.counts is None
        assert column.percentages is None
        assert column.nets is None
        assert column.base_valid is None
        assert column.n_invalid is None
        assert column.base_cell > 0
        assert column.band is Band.suppressed
    for column in low_base + ok:
        assert column.counts is not None
        assert column.percentages is not None
        assert column.nets is not None
        assert column.base_valid is not None
        assert column.base_valid + column.n_invalid == column.base_cell


def test_projection_counts_suppressed_and_low_base_cells_on_real_data(
    surveys, frames, registry
):
    """The projection path reports the same banding without computing figures."""
    survey, frame = surveys["rakuten"], frames["rakuten"]
    projection = project(
        BreakSpec(dimensions=BREAK_DIMENSIONS["rakuten"]),
        FilterSpec(),
        survey,
        frame,
        registry,
        "rakuten",
        ToolConfig(),
    )
    assert projection.errors == []
    assert projection.suppressed_count > 0
    assert projection.low_base_count > 0
    assert projection.cell_count == len(projection.cells)
    assert projection.suppressed_count == sum(
        1 for c in projection.cells if c.band is Band.suppressed
    )
    assert projection.low_base_count == sum(
        1 for c in projection.cells if c.band is Band.low_base
    )


# ── Column count above the render ceiling ─────────────────────────────────

def test_real_break_exceeding_render_ceiling_refuses_all_charts_but_table(
    surveys, frames, registry
):
    """No config override needed: a real depth-3 break on Toluna
    (gender x ethnicity x income) produces 54 columns against the shipped
    ceiling of 24. Every chart type is refused with a reason EXCEPT table,
    and the full result is still computed -- the ceiling governs rendering,
    never computation."""
    survey, frame = surveys["toluna"], frames["toluna"]
    config = ToolConfig()
    assert config.render_column_ceiling == 24

    qid = _scale_qids(survey, limit=1)[0]
    result = compute_breaks_crosstab(
        frame, survey, BREAK_DIMENSIONS["toluna"], {}, [qid], registry, "toluna", config
    )[0]

    assert len(result.columns) > config.render_column_ceiling

    permissions = evaluate_chart_permissions(result, len(result.columns), config)
    by_type = {p.chart_type: p for p in permissions}
    assert set(by_type) == set(ChartType)

    assert by_type[ChartType.table].permitted is True
    for chart_type, permission in by_type.items():
        if chart_type is ChartType.table:
            continue
        assert permission.permitted is False, f"{chart_type} should be refused above the ceiling"
        assert permission.reason == "COLUMN_COUNT_EXCEEDS_RENDER_LIMIT"

    # The full result is still computed: non-suppressed cells carry figures.
    populated = [c for c in result.columns if c.band is not Band.suppressed]
    assert populated
    for column in populated:
        assert column.counts and column.percentages and column.nets


def test_projection_reports_render_ceiling_breach_on_real_data(surveys, frames, registry):
    survey, frame = surveys["toluna"], frames["toluna"]
    projection = project(
        BreakSpec(dimensions=BREAK_DIMENSIONS["toluna"]),
        FilterSpec(),
        survey,
        frame,
        registry,
        "toluna",
        ToolConfig(),
    )
    assert projection.errors == []
    assert projection.cell_count > projection.render_ceiling
    assert projection.chart_render_permitted is False


def test_below_the_ceiling_charts_are_not_refused_for_column_count(
    surveys, frames, registry
):
    """Control case, so the test above is not vacuously true: a depth-1 break
    is well under the ceiling and charts are permitted on column-count
    grounds."""
    survey, frame = surveys["toluna"], frames["toluna"]
    config = ToolConfig()
    qid = _scale_qids(survey, limit=1)[0]
    result = compute_breaks_crosstab(
        frame, survey, ["gender"], {}, [qid], registry, "toluna", config
    )[0]

    assert len(result.columns) <= config.render_column_ceiling
    permissions = evaluate_chart_permissions(result, len(result.columns), config)
    reasons = {p.reason for p in permissions}
    assert "COLUMN_COUNT_EXCEEDS_RENDER_LIMIT" not in reasons
    assert all(p.permitted for p in permissions if p.chart_type is ChartType.table)


def test_lowered_ceiling_override_forces_a_breach_deterministically(
    surveys, frames, registry
):
    """The per-project config override pattern also works, for a UI that wants
    a tighter ceiling than the shipped default."""
    survey, frame = surveys["rakuten"], frames["rakuten"]
    config = ToolConfig(render_column_ceiling=1)
    result = compute_breaks_crosstab(
        frame, survey, ["gender"], {}, ["Q1"], registry, "rakuten", config
    )[0]
    assert len(result.columns) == 2 > config.render_column_ceiling

    permissions = evaluate_chart_permissions(result, len(result.columns), config)
    by_type = {p.chart_type: p for p in permissions}
    assert by_type[ChartType.table].permitted is True
    assert all(
        not p.permitted for t, p in by_type.items() if t is not ChartType.table
    )


# ── Depth-0 / empty break spec: the disclosed design gap ──────────────────

def test_empty_break_spec_yields_zero_columns_DISCLOSED_GAP(surveys, frames, registry):
    """DISCLOSED DESIGN GAP, asserted so it cannot change silently.

    An empty break_spec produces zero columns -- there is no "Total" /
    depth-0 column concept in this build. ``BreakSpec`` itself enforces
    ``min_length=1``, so the empty case is not even expressible through the
    validated request path; it is only reachable by calling
    ``compute_breaks_crosstab`` directly. This is why INV-4 is constructed
    against a non-empty break on a second dimension rather than the build
    plan's literal ``break_spec=[]``. Flagged as an open design question for
    the UI-facing follow-on work, not resolved here.
    """
    survey, frame = surveys["rakuten"], frames["rakuten"]
    result = compute_breaks_crosstab(
        frame, survey, [], {}, ["Q1"], registry, "rakuten", ToolConfig()
    )[0]
    assert result.columns == []
    # Bases are still correct -- only the column structure is missing.
    assert result.base_total == len(frame)
    assert result.base_filtered == len(frame)

    with pytest.raises(Exception):
        BreakSpec(dimensions=[])
