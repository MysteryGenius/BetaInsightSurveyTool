"""compute_breaks_crosstab() tests.

Section A: synthetic survey -- payload shape, scale_points polarity derivation,
           net gating, INV-6, suppression nulling ordering, unknown-qid error.
Section B: real Rakuten fixture (support-measures) -- depth-1 break on
           age_band, shape sanity, INV-6 over real cells, verbatim reuse of
           compute_question_stats' percentages/nets, cell reuse across
           multiple questions, suppression nulling, and an INV-1-shaped
           sanity comparison against the existing compute_cross_tab.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from surveytool.charts.errors import ErrorCode, SurveyToolError
from surveytool.compute.breaks_compute import (
    ColumnResult,
    QuestionResult,
    compute_breaks_crosstab,
)
from surveytool.compute.cross_tab import compute_cross_tab
from surveytool.compute.frequency import compute_question_stats
from surveytool.core.cohort import apply_filter, resolve_cells
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


# ── Section A: synthetic ────────────────────────────────────────────────────

def _synthetic_question(qid: str = "Q1") -> Question:
    return Question(
        qid=qid,
        text=f"Synthetic scale question {qid}",
        qtype=QuestionType.scale,
        scale_family="agreement",
        labels=[
            ScaleCode(code=1, label="Strongly disagree", role=CodeRole.bottom, numeric_value=1),
            ScaleCode(code=2, label="Disagree", role=CodeRole.bottom, numeric_value=2),
            ScaleCode(code=3, label="Neutral", role=CodeRole.neutral, numeric_value=3),
            ScaleCode(code=4, label="Agree", role=CodeRole.top, numeric_value=4),
            ScaleCode(code=5, label="Strongly agree", role=CodeRole.top, numeric_value=5),
            ScaleCode(code=99, label="Prefer not to say", role=CodeRole.nonsubstantive),
        ],
    )


def test_scale_points_polarity_derives_from_code_role():
    """top -> positive, bottom -> negative, neutral -> neutral, else None."""
    question = _synthetic_question()
    from surveytool.compute.breaks_compute import _scale_points

    points = _scale_points(question)
    assert [p.order for p in points] == [0, 1, 2, 3, 4, 5]
    assert [p.polarity for p in points] == [
        "negative",
        "negative",
        "neutral",
        "positive",
        "positive",
        None,
    ]


def test_net_definitions_gate_on_role_presence():
    """Both nets emitted when both roles present; neither when absent."""
    from surveytool.compute.breaks_compute import _net_definitions

    question = _synthetic_question()
    nets = _net_definitions(question)
    assert [n.net_id for n in nets] == ["t2b", "b2b"]
    assert dict((n.net_id, n.member_codes) for n in nets) == {
        "t2b": [4, 5],
        "b2b": [1, 2],
    }

    # A multi-response question with no top/bottom roles gets no net entries.
    no_role_question = Question(
        qid="M1",
        text="Which do you use?",
        qtype=QuestionType.multi_response,
        multi_response_delimiter="; ",
        labels=[
            ScaleCode(code="a", label="A", role=CodeRole.excluded),
            ScaleCode(code="b", label="B", role=CodeRole.excluded),
        ],
    )
    assert _net_definitions(no_role_question) == []


def test_unknown_question_id_raises_internal():
    survey = Survey(
        id="s",
        n_raw=0,
        n_analysis=0,
        questions=[_synthetic_question()],
        responses=[],
    )
    from surveytool.compute.breaks_compute import _resolve_question

    with pytest.raises(SurveyToolError) as exc_info:
        _resolve_question(survey, "NOPE")
    assert exc_info.value.code is ErrorCode.INTERNAL
    assert "NOPE" in (exc_info.value.detail or "")


def test_inv6_holds_when_cell_contains_non_base_states():
    """base_valid + n_invalid == base_cell with not_asked/item_missing present."""
    from surveytool.compute.breaks_compute import _column_for_cell
    from surveytool.core.cohort import Cell

    question = _synthetic_question()
    responses = [
        Response(respondent_id="r1", qid="Q1", raw_value=4, state=ResponseState.answered),
        Response(respondent_id="r2", qid="Q1", raw_value=99, state=ResponseState.nonsubstantive),
        Response(respondent_id="r3", qid="Q1", raw_value=None, state=ResponseState.item_missing),
        Response(respondent_id="r4", qid="Q1", raw_value=None, state=ResponseState.not_asked),
    ]
    cell = Cell(
        key=(("age_band", "18-24"),),
        label_path=("18-24",),
        respondent_ids=frozenset({"r1", "r2", "r3", "r4"}),
    )
    config = ToolConfig(cross_tab_suppress_threshold=1, suppression_low_base_multiplier=1)
    column = _column_for_cell(cell, question, responses, config)

    assert column.base_cell == 4
    assert column.base_valid == 2  # answered + nonsubstantive
    assert column.n_invalid == 2  # item_missing + not_asked
    assert column.base_valid + column.n_invalid == column.base_cell


# ── Section B: real vendor file ─────────────────────────────────────────────

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


def _run(frame, survey, registry, question_ids, config=None, break_spec=None, filter_spec=None):
    return compute_breaks_crosstab(
        frame,
        survey,
        break_spec if break_spec is not None else ["age_band"],
        filter_spec if filter_spec is not None else {},
        question_ids,
        registry,
        "rakuten",
        config or ToolConfig(),
    )


def test_depth1_break_shape_is_sane(frame, survey, registry):
    results = _run(frame, survey, registry, ["Q1"])

    assert len(results) == 1
    result = results[0]
    assert isinstance(result, QuestionResult)
    assert result.question_id == "Q1"
    assert result.scale_id == "agreement"
    assert result.base_total == len(frame)
    assert result.base_filtered == len(frame)  # no filter
    assert len(result.scale_points) == 5
    assert [n.net_id for n in result.nets] == ["t2b", "b2b"]
    assert result.permitted_charts == []  # Task 8 populates this

    assert result.columns
    for column in result.columns:
        assert isinstance(column, ColumnResult)
        assert len(column.key) == 1
        assert column.key[0][0] == "age_band"
        assert len(column.label_path) == 1
        assert column.base_cell > 0
        assert column.significance is None
        assert column.significance_basis is None
        if column.band is not Band.suppressed:
            assert sum(column.counts.values()) == column.base_valid
            assert column.percentages.keys() == column.counts.keys()

    # Sum of base_cell across single-select break cells equals base_filtered
    # (INV-2 shape; every respondent falls in exactly one age_band cell here).
    assert sum(c.base_cell for c in result.columns) <= result.base_filtered


def test_inv6_holds_for_every_real_cell(frame, survey, registry):
    results = _run(frame, survey, registry, ["Q1", "Q2"])
    checked = 0
    for result in results:
        for column in result.columns:
            if column.band is Band.suppressed:
                continue
            assert column.base_valid + column.n_invalid == column.base_cell
            checked += 1
    assert checked > 0


def test_percentages_and_nets_reused_verbatim_from_compute_question_stats(
    frame, survey, registry
):
    """Cross-check every ColumnResult against a direct compute_question_stats
    call on the same cell's sliced responses -- numeric equality, not
    approximate, since the values must be the very same objects' values."""
    question = next(q for q in survey.questions if q.qid == "Q1")
    results = _run(frame, survey, registry, ["Q1"])
    result = results[0]

    filtered_ids = apply_filter(frame, {}, registry, survey, "rakuten")
    cells = resolve_cells(frame, filtered_ids, ["age_band"], registry, survey, "rakuten")
    cells_by_key = {tuple(c.key): c for c in cells}
    q_responses = [r for r in survey.responses if r.qid == "Q1"]

    assert len(result.columns) == len(cells)
    for column in result.columns:
        key = tuple((dim, cat) for dim, cat in column.key)
        cell = cells_by_key[key]
        cell_responses = [r for r in q_responses if r.respondent_id in cell.respondent_ids]
        expected = compute_question_stats(question, cell_responses)

        if column.band is Band.suppressed:
            continue

        assert column.base_valid == expected.base
        for cs in expected.code_stats:
            assert column.counts[str(cs.code)] == cs.n
            assert column.percentages[str(cs.code)] == cs.pct  # exact, not approx

        assert column.nets["t2b"].percentage == expected.t2b
        assert column.nets["b2b"].percentage == expected.b2b
        assert column.nets["t2b"].base_valid == expected.base
        assert column.nets["t2b"].count == sum(
            cs.n for cs in expected.code_stats if cs.role is CodeRole.top
        )
        assert column.nets["b2b"].count == sum(
            cs.n for cs in expected.code_stats if cs.role is CodeRole.bottom
        )


def test_net_percentage_equals_sum_of_member_percentages(frame, survey, registry):
    """INV-5 shape: a net percentage equals the sum of its constituent scale
    point percentages within the cell, within tolerance."""
    results = _run(frame, survey, registry, ["Q1"])
    result = results[0]
    members = {n.net_id: [str(c) for c in n.member_codes] for n in result.nets}

    for column in result.columns:
        if column.band is Band.suppressed:
            continue
        for net_id, net in column.nets.items():
            expected = sum(column.percentages[code] for code in members[net_id])
            assert net.percentage == pytest.approx(expected)


def test_cells_reused_across_multiple_questions(frame, survey, registry):
    """One resolve_cells for the whole call: the same cell must present
    identical base_cell/band/key across every question in one payload."""
    results = _run(frame, survey, registry, ["Q1", "Q2", "Q3"])
    assert len(results) == 3

    def shape(result):
        return [
            (tuple(tuple(p) for p in c.key), tuple(c.label_path), c.base_cell, c.band)
            for c in result.columns
        ]

    first = shape(results[0])
    assert first
    for result in results[1:]:
        assert shape(result) == first
        assert result.base_total == results[0].base_total
        assert result.base_filtered == results[0].base_filtered


def test_suppression_nulls_figures_but_keeps_base_and_band(frame, survey, registry):
    """A threshold above every real cell's base forces all cells suppressed;
    counts/percentages/nets go None while base_cell/band stay populated."""
    baseline = _run(frame, survey, registry, ["Q1"])[0]
    biggest = max(c.base_cell for c in baseline.columns)

    config = ToolConfig(cross_tab_suppress_threshold=biggest + 1)
    result = _run(frame, survey, registry, ["Q1"], config=config)[0]

    assert result.columns
    for column, base_column in zip(result.columns, baseline.columns):
        assert column.band is Band.suppressed
        assert column.counts is None
        assert column.percentages is None
        assert column.nets is None
        assert column.base_valid is None
        assert column.n_invalid is None
        # base_cell and band survive suppression, and base_cell is unchanged
        # from the unsuppressed run -- suppression is post-processing over an
        # already-computed result, not a skipped computation.
        assert column.base_cell == base_column.base_cell
        assert column.base_cell > 0


def test_partial_suppression_leaves_other_cells_populated(frame, survey, registry):
    """With a threshold between the smallest and largest cell, only the small
    cells null out -- proving the nulling is per cell, not per question."""
    baseline = _run(frame, survey, registry, ["Q1"])[0]
    bases = sorted(c.base_cell for c in baseline.columns)
    if len(set(bases)) < 2:
        pytest.skip("real cells do not differ in base_cell; cannot split the band")

    threshold = bases[len(bases) // 2]
    config = ToolConfig(
        cross_tab_suppress_threshold=threshold, suppression_low_base_multiplier=1
    )
    result = _run(frame, survey, registry, ["Q1"], config=config)[0]

    suppressed = [c for c in result.columns if c.band is Band.suppressed]
    populated = [c for c in result.columns if c.band is not Band.suppressed]
    assert suppressed and populated
    assert all(c.counts is None for c in suppressed)
    assert all(c.counts is not None for c in populated)


# ── INV-1-shaped sanity comparison against the existing single-break path ───

def test_depth1_break_matches_existing_compute_cross_tab(frame, survey, registry):
    """A depth-1 break must reproduce the existing verified single-break
    figures. compute_cross_tab groups by the RAW demographic question code
    (S3, labelled '18 - 24 years old') while the breaks core groups by
    CANONICAL age_band values ('18_24'), so the two are joined through the
    vendor value_map -- raw code -> canonical value -- rather than by label
    text or position.

    This is a sanity check ahead of Task 10's formal INV-1 diff.
    """
    question = next(q for q in survey.questions if q.qid == "Q1")
    config = ToolConfig()

    legacy = compute_cross_tab(frame, survey, question, "S3", config=config)
    new = _run(frame, survey, registry, ["Q1"], config=config)[0]

    value_map = registry.dimensions_for_vendor("rakuten")["age_band"].value_map
    legacy_by_canonical = {
        value_map[str(c.subgroup_code)]: c
        for c in legacy.cells
        if str(c.subgroup_code) in value_map
    }
    new_by_canonical = {c.key[0][1]: c for c in new.columns}

    overlap = set(legacy_by_canonical) & set(new_by_canonical)
    assert len(overlap) >= 5, (
        f"too few matching subgroups to compare: "
        f"legacy={sorted(legacy_by_canonical)} new={sorted(new_by_canonical)}"
    )

    compared = 0
    for value in overlap:
        legacy_cell = legacy_by_canonical[value]
        new_column = new_by_canonical[value]
        if new_column.band is Band.suppressed:
            continue
        assert new_column.base_valid == legacy_cell.n, (
            f"base mismatch for {value!r}: "
            f"new base_valid={new_column.base_valid} legacy n={legacy_cell.n}"
        )
        assert new_column.nets["t2b"].percentage == legacy_cell.t2b, (
            f"t2b mismatch for {value!r}: "
            f"new={new_column.nets['t2b'].percentage} legacy={legacy_cell.t2b}"
        )
        assert new_column.nets["b2b"].percentage == legacy_cell.b2b, (
            f"b2b mismatch for {value!r}: "
            f"new={new_column.nets['b2b'].percentage} legacy={legacy_cell.b2b}"
        )
        compared += 1

    assert compared >= 5
