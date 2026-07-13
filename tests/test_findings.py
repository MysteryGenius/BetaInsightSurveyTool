"""
Phase 3 findings-sheet and reconcile tests.

Section A: Unit tests over synthetic fixtures (no file I/O).
Section B: HC golden tests against real vendor files in the project root.
           Skipped automatically when vendor files are absent.
Section C: Negative-fixture reconcile tests — seed known-wrong values and assert
           reconcile() flags them. Each fixture carries a comment recording the source error.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from surveytool.core.model import (
    CodeRole,
    Question,
    QuestionType,
    Response,
    ResponseState,
    ScaleCode,
    Survey,
)
from surveytool.findings import FindingsRow, Mismatch, build_findings_sheet, reconcile

ROOT = Path(__file__).parent.parent
SUPPORT_MEASURES_PATH = ROOT / "rakuten_survey_support_measures_data.xlsx"


# ── Shared synthetic survey helpers ──────────────────────────────────────────

def _make_scale_question(qid: str, text: str = "Q") -> Question:
    return Question(
        qid=qid,
        text=text,
        qtype=QuestionType.scale,
        labels=[
            ScaleCode(code=1, label="Agree", role=CodeRole.top, numeric_value=1),
            ScaleCode(code=2, label="Neutral", role=CodeRole.neutral, numeric_value=2),
            ScaleCode(code=3, label="Disagree", role=CodeRole.bottom, numeric_value=3),
        ],
        scale_family="agreement",
    )


def _make_demo_question(qid: str, text: str, labels: list[ScaleCode]) -> Question:
    return Question(
        qid=qid,
        text=text,
        qtype=QuestionType.demographic,
        labels=labels,
        is_demographic=True,
        base_eligible=False,
    )


# ── Section A: unit tests ─────────────────────────────────────────────────────

def test_total_row_present():
    """findings sheet always contains a total-breakdown row for each substantive question."""
    q = _make_scale_question("Q1", "Social mobility question")
    survey = Survey(
        id="test",
        n_raw=3,
        n_analysis=3,
        questions=[q],
        responses=[
            Response(respondent_id="R1", qid="Q1", raw_value=1, state=ResponseState.answered),
            Response(respondent_id="R2", qid="Q1", raw_value=2, state=ResponseState.answered),
            Response(respondent_id="R3", qid="Q1", raw_value=3, state=ResponseState.answered),
        ],
    )
    sheet = build_findings_sheet(survey, banner=[])
    totals = [r for r in sheet if r.breakdown_variable == "total" and r.qid == "Q1"]
    assert len(totals) > 0
    t2b_rows = [r for r in totals if r.metric == "t2b"]
    assert len(t2b_rows) == 1
    assert t2b_rows[0].breakdown_level == "Total"
    assert t2b_rows[0].breakdown_level_label == "Total"


def test_breakdown_level_uses_label():
    """breakdown_level_label is always the ScaleCode.label string, never a raw code."""
    demo_labels = [
        ScaleCode(code=1, label="Chinese", role=CodeRole.top),
        ScaleCode(code=2, label="Malay", role=CodeRole.neutral),
        ScaleCode(code=3, label="Indian", role=CodeRole.bottom),
    ]
    demo_q = _make_demo_question("S1", "What is your ethnicity?", demo_labels)
    scale_q = _make_scale_question("Q1")
    survey = Survey(
        id="test",
        n_raw=3,
        n_analysis=3,
        questions=[demo_q, scale_q],
        responses=[
            Response(respondent_id="R1", qid="S1", raw_value=1, state=ResponseState.answered),
            Response(respondent_id="R2", qid="S1", raw_value=2, state=ResponseState.answered),
            Response(respondent_id="R3", qid="S1", raw_value=3, state=ResponseState.answered),
            Response(respondent_id="R1", qid="Q1", raw_value=1, state=ResponseState.answered),
            Response(respondent_id="R2", qid="Q1", raw_value=1, state=ResponseState.answered),
            Response(respondent_id="R3", qid="Q1", raw_value=3, state=ResponseState.answered),
        ],
    )
    sheet = build_findings_sheet(survey, banner=["ethnicity"])
    eth_rows = [r for r in sheet if r.breakdown_variable == "ethnicity" and r.qid == "Q1"]
    levels = {r.breakdown_level for r in eth_rows}
    # Real labels must be present, not raw codes
    assert "Chinese" in levels
    assert "Malay" in levels
    assert "Indian" in levels
    # Raw integer codes must NOT appear as levels
    assert 1 not in levels
    assert "1" not in levels
    # Every row's breakdown_level_label equals its breakdown_level
    for row in eth_rows:
        assert row.breakdown_level_label == row.breakdown_level


def test_cell_base_matches_filter():
    """cell_base for a breakdown level equals the count of respondents in that cell."""
    demo_labels = [
        ScaleCode(code=1, label="25-34", role=CodeRole.top),
        ScaleCode(code=2, label="35-44", role=CodeRole.bottom),
    ]
    demo_q = _make_demo_question("S1", "What is your age group?", demo_labels)
    scale_q = _make_scale_question("Q1")
    responses = []
    # 4 respondents in "25-34", 6 in "35-44"
    for i in range(1, 5):
        rid = f"R{i:02d}"
        responses.append(Response(respondent_id=rid, qid="S1", raw_value=1, state=ResponseState.answered))
        responses.append(Response(respondent_id=rid, qid="Q1", raw_value=1, state=ResponseState.answered))
    for i in range(5, 11):
        rid = f"R{i:02d}"
        responses.append(Response(respondent_id=rid, qid="S1", raw_value=2, state=ResponseState.answered))
        responses.append(Response(respondent_id=rid, qid="Q1", raw_value=3, state=ResponseState.answered))

    survey = Survey(id="test", n_raw=10, n_analysis=10, questions=[demo_q, scale_q], responses=responses)
    sheet = build_findings_sheet(survey, banner=["age"])
    young = [r for r in sheet if r.breakdown_variable == "age" and r.breakdown_level == "25-34" and r.qid == "Q1"]
    assert len(young) > 0
    assert young[0].cell_base == 4

    old = [r for r in sheet if r.breakdown_variable == "age" and r.breakdown_level == "35-44" and r.qid == "Q1"]
    assert old[0].cell_base == 6


def test_exclusion_set_reduces_base():
    """Excluding respondent IDs reduces the total base accordingly."""
    q = _make_scale_question("Q1")
    survey = Survey(
        id="test",
        n_raw=5,
        n_analysis=5,
        questions=[q],
        responses=[
            Response(respondent_id=f"R{i}", qid="Q1", raw_value=1, state=ResponseState.answered)
            for i in range(1, 6)
        ],
    )
    # Without exclusion: base 5
    sheet_full = build_findings_sheet(survey, banner=[])
    total_rows = [r for r in sheet_full if r.breakdown_variable == "total" and r.metric == "t2b"]
    assert total_rows[0].cell_base == 5

    # Exclude 2 respondents: base should drop to 3
    sheet_excl = build_findings_sheet(survey, banner=[], exclude_respondent_ids={"R1", "R2"})
    total_rows_excl = [r for r in sheet_excl if r.breakdown_variable == "total" and r.metric == "t2b"]
    assert total_rows_excl[0].cell_base == 3


def test_reconcile_passes_on_match():
    """reconcile() returns empty list when written value matches computed within tolerance."""
    q = _make_scale_question("Q1")
    survey = Survey(
        id="test",
        n_raw=2,
        n_analysis=2,
        questions=[q],
        responses=[
            Response(respondent_id="R1", qid="Q1", raw_value=1, state=ResponseState.answered),
            Response(respondent_id="R2", qid="Q1", raw_value=1, state=ResponseState.answered),
        ],
    )
    sheet = build_findings_sheet(survey, banner=[])
    # t2b should be 100.0; write 100.0 — exact match
    written = {"Q1|total|Total|t2b": 100.0}
    assert reconcile(sheet, written) == []


def test_reconcile_flags_mismatch():
    """reconcile() returns a Mismatch when written value differs by more than tolerance."""
    q = _make_scale_question("Q1")
    survey = Survey(
        id="test",
        n_raw=2,
        n_analysis=2,
        questions=[q],
        responses=[
            Response(respondent_id="R1", qid="Q1", raw_value=1, state=ResponseState.answered),
            Response(respondent_id="R2", qid="Q1", raw_value=1, state=ResponseState.answered),
        ],
    )
    sheet = build_findings_sheet(survey, banner=[])
    # Computed t2b is 100.0; write 99.0 — delta 1.0 > tolerance 0.05
    written = {"Q1|total|Total|t2b": 99.0}
    mismatches = reconcile(sheet, written)
    assert len(mismatches) == 1
    m = mismatches[0]
    assert m.qid == "Q1"
    assert m.metric == "t2b"
    assert m.written_value == pytest.approx(99.0)
    assert m.computed_value == pytest.approx(100.0)
    assert m.delta == pytest.approx(-1.0)


def test_reconcile_missing_key():
    """reconcile() flags a key that does not appear in the findings sheet."""
    sheet: list[FindingsRow] = []
    written = {"Q99|total|Total|t2b": 50.0}
    mismatches = reconcile(sheet, written)
    assert len(mismatches) == 1
    m = mismatches[0]
    assert m.computed_value is None
    assert m.delta is None
    assert "not found" in m.note


def test_reconcile_empty_written_returns_empty():
    """reconcile() with an empty written dict always returns []."""
    q = _make_scale_question("Q1")
    survey = Survey(
        id="test", n_raw=1, n_analysis=1,
        questions=[q],
        responses=[Response(respondent_id="R1", qid="Q1", raw_value=1, state=ResponseState.answered)],
    )
    sheet = build_findings_sheet(survey, banner=[])
    assert reconcile(sheet, {}) == []


# ── Section B: HC golden tests ────────────────────────────────────────────────

@pytest.fixture(scope="module")
def support_measures_sheet():
    """Build findings sheet for support-measures once per test session."""
    from surveytool.ingest.rakuten import load
    survey = load(SUPPORT_MEASURES_PATH, "support-measures")
    return build_findings_sheet(survey)


@pytest.mark.skipif(
    not SUPPORT_MEASURES_PATH.exists(),
    reason="HC file rakuten_survey_support_measures_data.xlsx not found in project root",
)
def test_support_measures_q1_total(support_measures_sheet):
    """Q1 concern: T2B 87.3%, B2B 2.3%, mean 4.27 (build plan golden fixture)."""
    idx = {
        (r.qid, r.breakdown_variable, r.breakdown_level, r.metric): r
        for r in support_measures_sheet
    }
    assert idx[("Q1", "total", "Total", "t2b")].value == pytest.approx(87.3, abs=0.05)
    assert idx[("Q1", "total", "Total", "b2b")].value == pytest.approx(2.3, abs=0.05)
    assert idx[("Q1", "total", "Total", "mean")].value == pytest.approx(4.27, abs=0.005)
    assert idx[("Q1", "total", "Total", "t2b")].cell_base == 1000
    assert idx[("Q1", "total", "Total", "t2b")].convention == "T2B"


@pytest.mark.skipif(
    not SUPPORT_MEASURES_PATH.exists(),
    reason="HC file rakuten_survey_support_measures_data.xlsx not found in project root",
)
def test_support_measures_q1_age_mean_rises(support_measures_sheet):
    """Q1 concern mean rises with age: youngest 3.90, oldest 4.48."""
    from surveytool.ingest.rakuten import load
    survey = load(SUPPORT_MEASURES_PATH, "support-measures")

    # Find the age demographic question to get actual label strings
    age_q = next(
        (q for q in survey.questions if q.is_demographic and "age" in q.text.lower()),
        None,
    )
    assert age_q is not None, "Age demographic question not found in support-measures survey"

    # Use labels that actually appear as mean rows in the findings sheet (bands with n>0)
    age_mean_levels = [
        r.breakdown_level for r in support_measures_sheet
        if r.qid == "Q1" and r.breakdown_variable == "age" and r.metric == "mean"
    ]
    # Sort preserves codebook order because ScaleCode ordering matches survey order
    all_age_labels = [
        sc.label for sc in age_q.labels
        if sc.role in {CodeRole.top, CodeRole.neutral, CodeRole.bottom, CodeRole.excluded}
    ]
    populated_labels = [lb for lb in all_age_labels if lb in age_mean_levels]
    assert len(populated_labels) >= 2, "Expected at least 2 age bands with respondents"

    idx = {
        (r.qid, r.breakdown_variable, r.breakdown_level, r.metric): r
        for r in support_measures_sheet
    }

    youngest_label = populated_labels[0]   # "18 - 24 years old"
    oldest_label = populated_labels[-1]    # "65 years old and above"

    youngest_mean = idx[("Q1", "age", youngest_label, "mean")].value
    oldest_mean = idx[("Q1", "age", oldest_label, "mean")].value

    assert youngest_mean == pytest.approx(3.90, abs=0.005)
    assert oldest_mean == pytest.approx(4.48, abs=0.005)
    assert oldest_mean > youngest_mean


@pytest.mark.skipif(
    not SUPPORT_MEASURES_PATH.exists(),
    reason="HC file rakuten_survey_support_measures_data.xlsx not found in project root",
)
def test_support_measures_q2_q3_q4_q5(support_measures_sheet):
    """Q2–Q5 total figures match build plan golden fixtures."""
    idx = {
        (r.qid, r.breakdown_variable, r.breakdown_level, r.metric): r
        for r in support_measures_sheet
    }
    # Q2 vouchers
    assert idx[("Q2", "total", "Total", "t2b")].value == pytest.approx(74.9, abs=0.05)
    assert idx[("Q2", "total", "Total", "mean")].value == pytest.approx(3.93, abs=0.005)

    # Q3 insufficiency (inverted scale: B2B is the high-concern net)
    assert idx[("Q3", "total", "Total", "t2b")].value == pytest.approx(23.7, abs=0.05)
    assert idx[("Q3", "total", "Total", "b2b")].value == pytest.approx(41.5, abs=0.05)
    assert idx[("Q3", "total", "Total", "mean")].value == pytest.approx(2.73, abs=0.005)

    # Q4 reaching-vulnerable
    assert idx[("Q4", "total", "Total", "t2b")].value == pytest.approx(49.9, abs=0.05)
    assert idx[("Q4", "total", "Total", "mean")].value == pytest.approx(3.39, abs=0.005)

    # Q5 government-confidence
    assert idx[("Q5", "total", "Total", "t2b")].value == pytest.approx(53.1, abs=0.05)
    assert idx[("Q5", "total", "Total", "mean")].value == pytest.approx(3.44, abs=0.005)


# ── Section C: negative-fixture reconcile tests ───────────────────────────────
# Each fixture seeds a known-wrong value and asserts reconcile() flags it.
# Comments record the source error documented in the build plan.

@pytest.fixture(scope="module")
def _sup_sheet_and_idx(support_measures_sheet):
    idx = {
        (r.qid, r.breakdown_variable, r.breakdown_level, r.metric): r
        for r in support_measures_sheet
    }
    return support_measures_sheet, idx


@pytest.mark.skipif(
    not SUPPORT_MEASURES_PATH.exists(),
    reason="HC file rakuten_survey_support_measures_data.xlsx not found in project root",
)
def test_reconcile_flags_gov_confidence_wrong(support_measures_sheet):
    """Source error: AI decks reported 42% government confidence (dropped 11.1% strongly agree).
    Correct value is 53.1%. reconcile() must flag the seeded wrong value.
    """
    written = {"Q5|total|Total|t2b": 42.0}
    mismatches = reconcile(support_measures_sheet, written)
    assert len(mismatches) == 1
    m = mismatches[0]
    assert m.qid == "Q5"
    assert m.metric == "t2b"
    assert m.written_value == pytest.approx(42.0)
    assert m.computed_value == pytest.approx(53.1, abs=0.05)


@pytest.mark.skipif(
    not SUPPORT_MEASURES_PATH.exists(),
    reason="HC file rakuten_survey_support_measures_data.xlsx not found in project root",
)
def test_reconcile_flags_reaching_vulnerable_wrong(support_measures_sheet):
    """Source error: AI decks said 'one in two' (50.0%) for reaching-vulnerable.
    Correct value is 49.9%. Delta 0.1 > tolerance 0.05 — must flag.
    """
    written = {"Q4|total|Total|t2b": 50.0}
    mismatches = reconcile(support_measures_sheet, written)
    assert len(mismatches) == 1
    m = mismatches[0]
    assert m.qid == "Q4"
    assert m.written_value == pytest.approx(50.0)
    assert m.computed_value == pytest.approx(49.9, abs=0.05)


@pytest.mark.skipif(
    not SUPPORT_MEASURES_PATH.exists(),
    reason="HC file rakuten_survey_support_measures_data.xlsx not found in project root",
)
def test_reconcile_flags_oldest_age_wrong(support_measures_sheet):
    """Source error: AI decks attributed highest concern to 'middle-aged' rather than 65+.
    65+ mean is 4.48; seeding 4.30 must trigger a mismatch.
    TODO: replace '<oldest_label>' with the actual 65+ band label from the survey once confirmed.
    """
    from surveytool.ingest.rakuten import load
    survey = load(SUPPORT_MEASURES_PATH, "support-measures")
    age_q = next(
        (q for q in survey.questions if q.is_demographic and "age" in q.text.lower()),
        None,
    )
    assert age_q is not None
    substantive = [
        sc for sc in age_q.labels
        if sc.role in {CodeRole.top, CodeRole.neutral, CodeRole.bottom, CodeRole.excluded}
    ]
    oldest_label = substantive[-1].label

    written = {f"Q1|age|{oldest_label}|mean": 4.30}
    mismatches = reconcile(support_measures_sheet, written)
    assert len(mismatches) == 1
    m = mismatches[0]
    assert m.breakdown_level == oldest_label
    assert m.written_value == pytest.approx(4.30)
    assert m.computed_value == pytest.approx(4.48, abs=0.005)
