"""Formal invariant tests INV-1 .. INV-6 (build plan section 13).

Every test in this file is named ``test_inv<N>_...`` so the six invariant IDs
stay individually identifiable in pytest output.

Grounding, per the build plan: golden values for NESTED breaks do not exist in
any hand-verified report and are deliberately not constructed here. What
grounds this file instead is (a) equivalence to already-verified output --
INV-1 diffs the new depth-1 break against the existing, verified
``compute_cross_tab`` -- and (b) invariants that need no external ground truth
at all (INV-2 .. INV-6).

All six run against the real Rakuten support-measures fixture, except the
non-response half of INV-2, which is explicitly SYNTHETIC: no real vendor
demographic in any of the three fixture files declares a non-response /
declined-to-answer category (verified in Task 1 and re-verified for this task
-- see the module docstring of ``tests/test_breaks_conformance.py`` and the
task-10 report). That gap is reported rather than papered over, and the
synthetic fixture is labelled as such at the point of use.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from surveytool.compute.breaks_compute import compute_breaks_crosstab
from surveytool.compute.cross_tab import compute_cross_tab
from surveytool.core.cohort import Cell, apply_filter, resolve_cells
from surveytool.core.config import ToolConfig
from surveytool.core.demographic_registry import load_registry
from surveytool.core.model import (
    CodeRole,
    Question,
    QuestionType,
    Response,
    ResponseState,
    ScaleCode,
    Survey,
)
from surveytool.core.respondent_frame import to_respondent_frame
from surveytool.core.suppression import Band

ROOT = Path(__file__).parent.parent
DEMOGRAPHICS_DIR = ROOT / "surveytool" / "core" / "demographics"
CANONICAL_PATH = DEMOGRAPHICS_DIR / "canonical.yaml"
VENDOR_RAKUTEN_PATH = DEMOGRAPHICS_DIR / "vendor_rakuten.yaml"
SUPPORT_MEASURES_PATH = ROOT / "rakuten_survey_support_measures_data.xlsx"


@pytest.fixture(scope="module")
def survey():
    if not SUPPORT_MEASURES_PATH.exists():
        pytest.skip("HC file rakuten_survey_support_measures_data.xlsx not found in project root")
    from surveytool.ingest.rakuten import load

    return load(SUPPORT_MEASURES_PATH, "support-measures")


@pytest.fixture(scope="module")
def frame(survey):
    return to_respondent_frame(survey)


@pytest.fixture(scope="module")
def registry(survey):
    return load_registry(
        CANONICAL_PATH,
        {"rakuten": VENDOR_RAKUTEN_PATH},
        surveys={"rakuten": survey},
    )


def _run(frame, survey, registry, break_spec, filter_spec, question_ids, config=None):
    return compute_breaks_crosstab(
        frame,
        survey,
        break_spec,
        filter_spec,
        question_ids,
        registry,
        "rakuten",
        config or ToolConfig(),
    )


# ── INV-1 ───────────────────────────────────────────────────────────────────

def test_inv1_depth1_break_reproduces_verified_single_break_figures_exactly(
    frame, survey, registry
):
    """INV-1 (the go/no-go gate for the whole build).

    A break of depth 1 must reproduce the EXISTING verified single-break
    golden figures exactly -- nesting has to degrade to the already-verified
    case, or nothing downstream is trustworthy.

    The two paths are joined through the vendor value_map, NOT by label text
    or column position. ``compute_cross_tab`` groups Rakuten's S3 by RAW
    Datamap codebook code (subgroup_code 1..7, labelled e.g.
    "18 - 24 years old"); ``compute_breaks_crosstab`` groups by CANONICAL
    registry value (e.g. "18_24" from vendor_rakuten.yaml's value_map).
    Matching on label text or position would produce a FALSE mismatch.

    Equality is asserted EXACTLY (``==``, never ``pytest.approx``) on
    base/n and on both nets, for every subgroup present on both sides, for
    every scale question in the survey -- not just one.

    Expected asymmetry, which is correct on both sides and must not be
    flagged as a mismatch: the legacy path emits an ``under_18`` subgroup
    because Rakuten's Datamap declares a "Below 18 years old" code, while the
    break path omits it -- zero real respondents fall in that band and
    ``resolve_cells`` never materialises an empty combination. So 6 of the 7
    codebook bands are comparable, and the test asserts on that overlap.
    """
    config = ToolConfig()
    value_map = registry.dimensions_for_vendor("rakuten")["age_band"].value_map

    scale_qids = [q.qid for q in survey.questions if q.qtype is QuestionType.scale]
    assert scale_qids, "fixture must contain at least one scale question"

    total_compared = 0
    for qid in scale_qids:
        question = next(q for q in survey.questions if q.qid == qid)

        legacy = compute_cross_tab(frame, survey, question, "S3", config=config)
        new = _run(frame, survey, registry, ["age_band"], {}, [qid], config=config)[0]

        legacy_by_canonical = {
            value_map[str(c.subgroup_code)]: c
            for c in legacy.cells
            if str(c.subgroup_code) in value_map
        }
        new_by_canonical = {c.key[0][1]: c for c in new.columns}

        # The legacy path's extra under_18 subgroup (zero real respondents) is
        # the ONLY permitted asymmetry; assert that explicitly rather than
        # letting an arbitrary set difference pass silently.
        legacy_only = set(legacy_by_canonical) - set(new_by_canonical)
        new_only = set(new_by_canonical) - set(legacy_by_canonical)
        assert not new_only, f"{qid}: break path produced subgroups the legacy path lacks: {new_only}"
        for value in legacy_only:
            assert legacy_by_canonical[value].n == 0, (
                f"{qid}: legacy subgroup {value!r} is missing from the break path "
                f"but has {legacy_by_canonical[value].n} respondents -- a real mismatch, "
                f"not the known empty-band asymmetry."
            )

        overlap = set(legacy_by_canonical) & set(new_by_canonical)
        assert len(overlap) >= 6, (
            f"{qid}: expected >= 6 comparable age bands, got {len(overlap)}: "
            f"legacy={sorted(legacy_by_canonical)} new={sorted(new_by_canonical)}"
        )

        for value in sorted(overlap):
            legacy_cell = legacy_by_canonical[value]
            new_column = new_by_canonical[value]
            assert new_column.band is not Band.suppressed, (
                f"{qid}/{value}: cell unexpectedly suppressed at default config; "
                f"INV-1 cannot compare a nulled cell."
            )
            assert new_column.base_valid == legacy_cell.n, (
                f"{qid}/{value}: base mismatch -- "
                f"new base_valid={new_column.base_valid} legacy n={legacy_cell.n}"
            )
            assert new_column.nets["t2b"].percentage == legacy_cell.t2b, (
                f"{qid}/{value}: t2b mismatch -- "
                f"new={new_column.nets['t2b'].percentage} legacy={legacy_cell.t2b}"
            )
            assert new_column.nets["b2b"].percentage == legacy_cell.b2b, (
                f"{qid}/{value}: b2b mismatch -- "
                f"new={new_column.nets['b2b'].percentage} legacy={legacy_cell.b2b}"
            )
            total_compared += 1

    # 5 scale questions x 6 comparable bands on this fixture.
    assert total_compared >= 30, f"only {total_compared} subgroup comparisons ran"


# ── INV-2 ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "break_spec, filter_spec",
    [
        (["age_band"], {}),
        (["gender"], {}),
        (["gender", "ethnicity"], {}),
        (["age_band"], {"gender": ["male"]}),
        (["gender"], {"ethnicity": ["chinese", "malay"]}),
    ],
)
def test_inv2_sum_of_base_cell_equals_base_filtered(
    frame, survey, registry, break_spec, filter_spec
):
    """INV-2: for single-select breaks, sum(base_cell) across all cells
    equals base_filtered -- empty and non-empty filter alike.

    This holds on this fixture because every respondent carries a mapped
    value for every Rakuten break dimension. Where a respondent had an
    unmapped/absent value, resolve_cells would (correctly) drop them and the
    sum would fall short; the registry's rule-2 check makes that
    unreachable for a successfully loaded vendor file.
    """
    result = _run(frame, survey, registry, break_spec, filter_spec, ["Q1"])[0]
    assert result.columns
    assert sum(c.base_cell for c in result.columns) == result.base_filtered


def test_inv2_every_respondent_lands_in_exactly_one_cell(frame, survey, registry):
    """The stronger form behind INV-2's arithmetic: single-select break cells
    partition the filtered set -- disjoint, and jointly exhaustive."""
    filtered = apply_filter(frame, {}, registry, survey, "rakuten")
    cells = resolve_cells(frame, filtered, ["gender", "age_band"], registry, survey, "rakuten")

    seen: set[str] = set()
    for cell in cells:
        assert not (seen & cell.respondent_ids), "cells overlap; break is not a partition"
        seen |= cell.respondent_ids
    assert seen == filtered


def test_inv2_non_response_appears_as_its_own_cell_SYNTHETIC(tmp_path):
    """INV-2, second half: a non-response category must appear as its own
    cell and be counted in the sum, never silently dropped or folded in.

    *** SYNTHETIC FIXTURE, DELIBERATELY. ***

    No real vendor demographic in any of the three fixture files declares a
    non-response / declined / "prefer not to say" category -- verified in
    Task 1 (canonical.yaml says so in its own header comment) and re-verified
    for Task 10 by inspecting the parsed codebooks of every demographic
    question across all three vendors (Rakuten S1-S4, Toluna 1-5, Milieu
    q5-q8): none contains such a code. The real-data gap is reported in the
    task-10 report rather than papered over; this synthetic registry exists
    only to prove the code path treats a ``non_response: true`` category as
    an ordinary category, exactly as the build plan requires.
    """
    canonical = tmp_path / "canonical.yaml"
    canonical.write_text(
        "dimensions:\n"
        "  gender:\n"
        "    label: Gender\n"
        "    multi_select: false\n"
        "    categories:\n"
        "      - {value: male, label: Male, order: 1}\n"
        "      - {value: female, label: Female, order: 2}\n"
        "      - {value: declined, label: Prefer not to say, order: 3, non_response: true}\n",
        encoding="utf-8",
    )
    vendor = tmp_path / "vendor_acme.yaml"
    vendor.write_text(
        "vendor: acme\n"
        "dimensions:\n"
        "  gender:\n"
        '    source_column: "G1"\n'
        "    value_map:\n"
        '      "1": male\n'
        '      "2": female\n'
        '      "99": declined\n',
        encoding="utf-8",
    )

    question = Question(
        qid="Q1",
        text="Synthetic scale question",
        qtype=QuestionType.scale,
        scale_family="agreement",
        labels=[
            ScaleCode(code=1, label="Strongly disagree", role=CodeRole.bottom, numeric_value=1),
            ScaleCode(code=2, label="Disagree", role=CodeRole.bottom, numeric_value=2),
            ScaleCode(code=3, label="Neutral", role=CodeRole.neutral, numeric_value=3),
            ScaleCode(code=4, label="Agree", role=CodeRole.top, numeric_value=4),
            ScaleCode(code=5, label="Strongly agree", role=CodeRole.top, numeric_value=5),
        ],
    )
    demographic = Question(
        qid="G1",
        text="Gender",
        qtype=QuestionType.demographic,
        labels=[
            ScaleCode(code=1, label="Male", role=CodeRole.excluded),
            ScaleCode(code=2, label="Female", role=CodeRole.excluded),
            ScaleCode(code=99, label="Prefer not to say", role=CodeRole.excluded),
        ],
    )

    # 4 male, 3 female, 2 declined -- the declined respondents are real people
    # with real answers to Q1, so they must form their own cell.
    assignment = [
        ("r1", 1), ("r2", 1), ("r3", 1), ("r4", 1),
        ("r5", 2), ("r6", 2), ("r7", 2),
        ("r8", 99), ("r9", 99),
    ]
    responses: list[Response] = []
    for rid, gender_code in assignment:
        responses.append(
            Response(respondent_id=rid, qid="G1", raw_value=gender_code, state=ResponseState.answered)
        )
        responses.append(
            Response(respondent_id=rid, qid="Q1", raw_value=4, state=ResponseState.answered)
        )

    synthetic = Survey(
        id="synthetic-non-response",
        n_raw=len(assignment),
        n_analysis=len(assignment),
        questions=[demographic, question],
        responses=responses,
    )
    registry = load_registry(canonical, {"acme": vendor}, surveys={"acme": synthetic})
    frame = to_respondent_frame(synthetic)

    # Threshold of 1 so no synthetic cell is suppressed for smallness.
    config = ToolConfig(cross_tab_suppress_threshold=1, suppression_low_base_multiplier=1)
    result = compute_breaks_crosstab(
        frame, synthetic, ["gender"], {}, ["Q1"], registry, "acme", config
    )[0]

    by_value = {c.key[0][1]: c for c in result.columns}
    assert set(by_value) == {"male", "female", "declined"}, (
        "the non_response category must appear as its own cell, not be dropped or folded in"
    )
    assert by_value["declined"].base_cell == 2
    assert by_value["declined"].label_path == ["Prefer not to say"]
    # INV-2 proper, with the non-response cell participating like any other.
    assert sum(c.base_cell for c in result.columns) == result.base_filtered == 9


# ── INV-3 ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "spec_a, spec_b",
    [
        (["gender", "ethnicity"], ["ethnicity", "gender"]),
        (["age_band", "gender"], ["gender", "age_band"]),
    ],
)
def test_inv3_swapping_pill_order_changes_structure_only(
    frame, survey, registry, spec_a, spec_b
):
    """INV-3: swapping break-spec pill order changes column structure and
    ordering only. The SET of cells and their figures are unchanged.

    Note ``residential_status`` is deliberately NOT used as a partner
    dimension here: on this fixture all 1000 respondents are Singapore
    Citizens, so it is degenerate (a single category) and would make the
    swap structurally trivial -- it could pass without proving anything.
    """
    result_a = _run(frame, survey, registry, spec_a, {}, ["Q1"])[0]
    result_b = _run(frame, survey, registry, spec_b, {}, ["Q1"])[0]

    assert len(result_a.columns) == len(result_b.columns)
    assert result_a.base_filtered == result_b.base_filtered

    def figures(column):
        """Order-independent identity of a cell plus everything computed for
        it. The key is normalised to a frozenset of (dimension, category)
        pairs, so the same cohort matches across the two orderings even
        though its ordered key tuple and label_path differ."""
        return (
            frozenset((dim, cat) for dim, cat in column.key),
            column.base_cell,
            column.base_valid,
            column.n_invalid,
            column.band,
            None if column.counts is None else tuple(sorted(column.counts.items())),
            None if column.percentages is None else tuple(sorted(column.percentages.items())),
            None
            if column.nets is None
            else tuple(
                (net_id, net.count, net.percentage, net.base_valid)
                for net_id, net in sorted(column.nets.items())
            ),
        )

    set_a = {figures(c) for c in result_a.columns}
    set_b = {figures(c) for c in result_b.columns}
    assert set_a == set_b, "cell set or figures changed when pill order was swapped"

    # ... and the ordered structure genuinely DID change, so the equality
    # above is a real result and not a vacuous one.
    keys_a = [tuple(tuple(p) for p in c.key) for c in result_a.columns]
    keys_b = [tuple(tuple(p) for p in c.key) for c in result_b.columns]
    assert keys_a != keys_b, "pill order swap did not change column ordering at all"
    assert [c.key[0][0] for c in result_a.columns] == [spec_a[0]] * len(result_a.columns)
    assert [c.key[0][0] for c in result_b.columns] == [spec_b[0]] * len(result_b.columns)
    # label_path ordering follows the spec order too.
    for column in result_a.columns:
        assert [d for d, _ in column.key] == spec_a
    for column in result_b.columns:
        assert [d for d, _ in column.key] == spec_b


# ── INV-4 ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "dimension, category, other_dimension",
    [
        ("gender", "male", "ethnicity"),
        ("gender", "female", "age_band"),
        ("ethnicity", "chinese", "gender"),
        ("age_band", "25_34", "gender"),
    ],
)
def test_inv4_filtering_to_one_category_equals_that_cell_of_a_depth1_break(
    frame, survey, registry, dimension, category, other_dimension
):
    """INV-4: filtering to a single category of dimension D produces the same
    figures as selecting that cell from a depth-1 break on D.

    The build plan states this as ``filter_spec={D:[catX]}, break_spec=[]``
    vs ``filter_spec={}, break_spec=[D]``. A literal depth-0 break_spec is
    not expressible in this implementation -- an empty break_spec yields zero
    columns (``resolve_cells`` returns [] for an empty spec) and there is no
    Total/depth-0 column concept, a disclosed design gap carried in the
    task-10 report. So the equivalence is constructed a different, genuinely
    equivalent way rather than being weakened:

        filtered side:  filter={D: [catX]}, break=[E]   (E != D)
        unfiltered side: filter={},          break=[D, E]

    Every cell of the filtered side must have an exact counterpart in the
    unfiltered side's D=catX slice, with identical figures. This is a
    STRICTLY STRONGER statement than the build plan's version: it asserts
    filter/break equivalence across a whole family of sub-cells at once, and
    the plan's depth-0 case is the E-collapsed special case of it. Summing
    the filtered side's base_cell back to base_filtered (also asserted)
    recovers the plan's total-level claim.
    """
    filtered = _run(
        frame, survey, registry, [other_dimension], {dimension: [category]}, ["Q1"]
    )[0]
    broken = _run(frame, survey, registry, [dimension, other_dimension], {}, ["Q1"])[0]

    # The unfiltered depth-2 break's slice where D == catX.
    slice_of_break = {
        tuple(tuple(p) for p in c.key if p[0] != dimension): c
        for c in broken.columns
        if dict((d, v) for d, v in c.key)[dimension] == category
    }
    filtered_by_key = {tuple(tuple(p) for p in c.key): c for c in filtered.columns}

    assert filtered_by_key, "filtered side produced no columns"
    assert set(filtered_by_key) == set(slice_of_break), (
        f"cell sets differ between filter={dimension}:{category} and the matching "
        f"slice of a break on [{dimension}, {other_dimension}]"
    )

    for key, filtered_column in filtered_by_key.items():
        break_column = slice_of_break[key]
        assert filtered_column.base_cell == break_column.base_cell
        assert filtered_column.base_valid == break_column.base_valid
        assert filtered_column.n_invalid == break_column.n_invalid
        assert filtered_column.band == break_column.band
        assert filtered_column.counts == break_column.counts
        assert filtered_column.percentages == break_column.percentages
        if filtered_column.nets is None:
            assert break_column.nets is None
        else:
            assert set(filtered_column.nets) == set(break_column.nets)
            for net_id, net in filtered_column.nets.items():
                other = break_column.nets[net_id]
                assert net.count == other.count
                assert net.percentage == other.percentage
                assert net.base_valid == other.base_valid

    # Total-level form of the plan's original claim: the filtered cohort is
    # exactly the depth-1 break's catX cell.
    depth1 = _run(frame, survey, registry, [dimension], {}, ["Q1"])[0]
    depth1_cell = next(c for c in depth1.columns if c.key[0][1] == category)
    assert filtered.base_filtered == depth1_cell.base_cell
    assert sum(c.base_cell for c in filtered.columns) == depth1_cell.base_cell


# ── INV-5 ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("break_spec", [["age_band"], ["gender", "ethnicity"]])
def test_inv5_net_percentage_equals_sum_of_constituent_scale_point_percentages(
    frame, survey, registry, break_spec
):
    """INV-5: a net percentage equals the sum of its constituent scale point
    percentages within the cell, within tolerance. Real data, every scale
    question on the fixture (all of which carry both a top and a bottom
    role, so both nets are exercised)."""
    qids = [q.qid for q in survey.questions if q.qtype is QuestionType.scale]
    results = _run(frame, survey, registry, break_spec, {}, qids)

    checked = 0
    for result in results:
        assert {n.net_id for n in result.nets} == {"t2b", "b2b"}, (
            f"{result.question_id}: expected both nets present for INV-5"
        )
        members = {n.net_id: [str(c) for c in n.member_codes] for n in result.nets}
        for column in result.columns:
            if column.band is Band.suppressed:
                continue
            for net_id, net in column.nets.items():
                expected = sum(column.percentages[code] for code in members[net_id])
                assert net.percentage == pytest.approx(expected, abs=1e-6), (
                    f"{result.question_id}/{column.label_path}/{net_id}: "
                    f"net={net.percentage} sum_of_points={expected}"
                )
                # The count side of the same identity, which is exact.
                assert net.count == sum(column.counts[code] for code in members[net_id])
                checked += 1
    assert checked > 0


# ── INV-6 ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "break_spec",
    [["age_band"], ["gender"], ["gender", "ethnicity"], ["gender", "age_band", "ethnicity"]],
)
def test_inv6_base_valid_plus_n_invalid_equals_base_cell_payload_level(
    frame, survey, registry, break_spec
):
    """INV-6, payload level: ``base_valid + n_invalid == base_cell`` for every
    cell, read off the actual ``ColumnResult`` fields returned by
    ``compute_breaks_crosstab`` -- not by calling internal helpers.

    Necessarily restricted to ``ok``/``low_base`` cells: a suppressed cell has
    ``base_valid``/``n_invalid`` nulled in the payload BY DESIGN, so the
    identity is not expressible there at payload level. Suppressed cells are
    covered by the internal runtime assertion in ``_column_for_cell``, which
    runs before nulling on every cell including suppressed ones (see
    ``tests/test_breaks_compute.py::test_inv6_assertion_fires_on_suppressed_cell``).
    This split is the INV-6 departure recorded in the task-10 report.

    The depth-3 spec is included because it produces genuinely suppressed and
    low-base cells on this real fixture, exercising both halves of the split.
    """
    qids = [q.qid for q in survey.questions if q.qtype is QuestionType.scale]
    results = _run(frame, survey, registry, break_spec, {}, qids)

    checked = 0
    suppressed_seen = 0
    for result in results:
        assert result.columns
        for column in result.columns:
            if column.band is Band.suppressed:
                # Payload-level identity is not expressible: fields are nulled.
                assert column.base_valid is None
                assert column.n_invalid is None
                assert column.base_cell > 0
                suppressed_seen += 1
                continue
            assert column.base_valid is not None
            assert column.n_invalid is not None
            assert column.base_valid + column.n_invalid == column.base_cell
            assert column.n_invalid >= 0
            checked += 1
    assert checked > 0

    if len(break_spec) == 3:
        assert suppressed_seen > 0, (
            "depth-3 break on this fixture is expected to produce suppressed cells; "
            "if it no longer does, the suppressed half of INV-6 is going untested here"
        )


def test_inv6_holds_under_a_filter_and_across_bands(frame, survey, registry):
    """INV-6 again with a non-empty filter and a raised threshold, so ok,
    low_base and suppressed cells all occur in one payload."""
    config = ToolConfig(cross_tab_suppress_threshold=40, suppression_low_base_multiplier=2.0)
    result = _run(
        frame, survey, registry, ["age_band", "ethnicity"], {"gender": ["male"]}, ["Q1"], config
    )[0]

    bands = {c.band for c in result.columns}
    assert len(bands) >= 2, f"expected multiple bands in one payload, saw {bands}"

    for column in result.columns:
        if column.band is Band.suppressed:
            assert column.base_valid is None and column.n_invalid is None
        else:
            assert column.base_valid + column.n_invalid == column.base_cell
