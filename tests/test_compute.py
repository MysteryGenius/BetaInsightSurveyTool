"""
Phase 2 compute module tests.

Section A: Unit tests over synthetic fixtures (no file I/O).
Section B: HC golden tests against real vendor files in the project root.
           These are skipped automatically when the vendor files are absent.
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
)
from surveytool.compute import (
    CodeStat,
    QuestionStats,
    compute_question_stats,
    compute_survey_stats,
)

ROOT = Path(__file__).parent.parent
SOCIAL_MOBILITY_PATH = ROOT / "rakuten_survey_chn_clans_data.xlsx"
SUPPORT_MEASURES_PATH = ROOT / "rakuten_survey_support_measures_data.xlsx"


# ── Section A: unit tests ─────────────────────────────────────────────────────

def test_base_excludes_not_asked():
    """Routed respondents (not_asked) must not count in the base."""
    from tests.fixtures.routed_question import ROUTED_QUESTION, RESPONSES, EXPECTED_BASE

    stats = compute_question_stats(ROUTED_QUESTION, RESPONSES)
    assert stats.base == EXPECTED_BASE  # 6, not 10


def test_base_excludes_item_missing():
    """item_missing responses must not count in the base."""
    q = Question(
        qid="q_test",
        text="Test",
        qtype=QuestionType.scale,
        labels=[
            ScaleCode(code=1, label="Agree", role=CodeRole.top, numeric_value=1),
            ScaleCode(code=2, label="Disagree", role=CodeRole.bottom, numeric_value=2),
        ],
        scale_family="agreement",
    )
    responses = [
        Response(respondent_id="R1", qid="q_test", raw_value=1, state=ResponseState.answered),
        Response(respondent_id="R2", qid="q_test", raw_value=None, state=ResponseState.item_missing),
        Response(respondent_id="R3", qid="q_test", raw_value=1, state=ResponseState.answered),
    ]
    stats = compute_question_stats(q, responses)
    assert stats.base == 2  # R2 is item_missing, not in base


def test_nonsubstantive_in_base():
    """Non-substantive responses must be included in the base count."""
    from tests.fixtures.nonsubstantive import QUESTION, RESPONSES, EXPECTED_BASE

    stats = compute_question_stats(QUESTION, RESPONSES)
    assert stats.base == EXPECTED_BASE  # 5

    ns_code_stat = next(cs for cs in stats.code_stats if cs.role is CodeRole.nonsubstantive)
    assert ns_code_stat.n == 1


def test_mean_excludes_nonsubstantive():
    """Mean must be computed from substantive answered responses only."""
    from tests.fixtures.nonsubstantive import QUESTION, RESPONSES, EXPECTED_MEAN

    stats = compute_question_stats(QUESTION, RESPONSES)
    assert stats.mean == pytest.approx(EXPECTED_MEAN)  # 2.5


def test_t2b_none_when_no_top_codes():
    """T2B must be None for questions with no top-coded codes."""
    q = Question(
        qid="q_demo",
        text="What is your age group?",
        qtype=QuestionType.single_choice,
        labels=[
            ScaleCode(code=1, label="18-24", role=CodeRole.excluded),
            ScaleCode(code=2, label="25-34", role=CodeRole.excluded),
            ScaleCode(code=3, label="35-44", role=CodeRole.excluded),
        ],
        is_demographic=True,
    )
    responses = [
        Response(respondent_id="R1", qid="q_demo", raw_value=1, state=ResponseState.answered),
        Response(respondent_id="R2", qid="q_demo", raw_value=2, state=ResponseState.answered),
    ]
    stats = compute_question_stats(q, responses)
    assert stats.t2b is None
    assert stats.b2b is None


def test_multi_response_base_is_respondents():
    """Multi-response base is respondent count, and percentages can exceed 100% in aggregate."""
    from tests.fixtures.multi_response import QUESTION, SELECTIONS, RESPONDENT_BASE

    # Build Response objects from the fixture's SELECTIONS dict
    responses = []
    for rid, codes in SELECTIONS.items():
        responses.append(
            Response(
                respondent_id=rid,
                qid=QUESTION.qid,
                raw_value="; ".join(codes),
                state=ResponseState.answered,
            )
        )

    stats = compute_question_stats(QUESTION, responses)
    assert stats.base == RESPONDENT_BASE  # 10

    pct_by_label = {cs.label: cs.pct for cs in stats.code_stats}
    assert pct_by_label["Option A"] == pytest.approx(60.0)
    assert pct_by_label["Option B"] == pytest.approx(60.0)
    assert pct_by_label["Option C"] == pytest.approx(50.0)
    assert sum(pct_by_label.values()) == pytest.approx(170.0)  # exceeds 100%


def test_zero_base_returns_zero_pct():
    """When base is 0, all pct values are 0.0 and nets/mean are None."""
    q = Question(
        qid="q_empty",
        text="Empty question",
        qtype=QuestionType.scale,
        labels=[
            ScaleCode(code=1, label="Yes", role=CodeRole.top, numeric_value=1),
            ScaleCode(code=2, label="No", role=CodeRole.bottom, numeric_value=2),
        ],
        scale_family="agreement",
    )
    responses = [
        Response(respondent_id="R1", qid="q_empty", raw_value=None, state=ResponseState.not_asked),
    ]
    stats = compute_question_stats(q, responses)
    assert stats.base == 0
    assert all(cs.pct == 0.0 for cs in stats.code_stats)
    assert stats.t2b is None
    assert stats.b2b is None
    assert stats.mean is None


def test_compute_survey_stats_skips_non_eligible():
    """compute_survey_stats must skip questions where base_eligible=False."""
    from surveytool.core.model import Survey
    from datetime import date

    scale_q = Question(
        qid="q_scale",
        text="Scale question",
        qtype=QuestionType.scale,
        labels=[
            ScaleCode(code=1, label="Agree", role=CodeRole.top, numeric_value=1),
            ScaleCode(code=2, label="Disagree", role=CodeRole.bottom, numeric_value=2),
        ],
        scale_family="agreement",
        base_eligible=True,
    )
    demo_q = Question(
        qid="q_demo",
        text="Demographic",
        qtype=QuestionType.demographic,
        labels=[
            ScaleCode(code=1, label="Male", role=CodeRole.excluded),
            ScaleCode(code=2, label="Female", role=CodeRole.excluded),
        ],
        is_demographic=True,
        base_eligible=False,
    )
    survey = Survey(
        id="test",
        n_raw=2,
        n_analysis=2,
        questions=[scale_q, demo_q],
        responses=[
            Response(respondent_id="R1", qid="q_scale", raw_value=1, state=ResponseState.answered),
            Response(respondent_id="R1", qid="q_demo", raw_value=1, state=ResponseState.answered),
        ],
    )
    results = compute_survey_stats(survey)
    assert len(results) == 1
    assert results[0].qid == "q_scale"


# ── Section B: HC golden tests ────────────────────────────────────────────────
#
# These load the real vendor files and validate against human-verified HC counts.
# They are skipped when the vendor files are not present.

@pytest.mark.skipif(
    not SOCIAL_MOBILITY_PATH.exists(),
    reason="HC file rakuten_survey_chn_clans_data.xlsx not found in project root",
)
def test_social_mobility_hc_all_counts():
    """Every HC category count must match the compute output to the unit (base 1000).

    HC sheet values verified manually from the HC tab of rakuten_survey_chn_clans_data.xlsx.
    """
    from surveytool.ingest.rakuten import load

    survey = load(SOCIAL_MOBILITY_PATH, survey_id="social-mobility")
    stats_by_qid = {s.qid: s for s in compute_survey_stats(survey)}

    # ── A1 ────────────────────────────────────────────────────────────────────
    a1 = stats_by_qid["A1"]
    assert a1.base == 1000
    a1_counts = {cs.label: cs.n for cs in a1.code_stats}
    assert a1_counts["Not important at all"] == 78
    assert a1_counts["Slightly important"] == 202
    assert a1_counts["Moderately important"] == 361
    assert a1_counts["Very important"] == 270
    assert a1_counts["Extremely important"] == 89

    # ── A2 ────────────────────────────────────────────────────────────────────
    a2 = stats_by_qid["A2"]
    assert a2.base == 1000
    a2_counts = {cs.label: cs.n for cs in a2.code_stats}
    assert a2_counts["Not important at all"] == 105
    assert a2_counts["Slightly important"] == 247
    assert a2_counts["Moderately important"] == 367
    assert a2_counts["Very important"] == 206
    assert a2_counts["Extremely important"] == 75

    # ── A3 ────────────────────────────────────────────────────────────────────
    a3 = stats_by_qid["A3"]
    assert a3.base == 1000
    a3_counts = {cs.label: cs.n for cs in a3.code_stats}
    assert a3_counts["Not important at all"] == 117
    assert a3_counts["Slightly important"] == 234
    assert a3_counts["Moderately important"] == 342
    assert a3_counts["Very important"] == 229
    assert a3_counts["Extremely important"] == 78

    # ── A4 ────────────────────────────────────────────────────────────────────
    a4 = stats_by_qid["A4"]
    assert a4.base == 1000
    a4_counts = {cs.label: cs.n for cs in a4.code_stats}
    assert a4_counts["Strongly disagree"] == 34
    assert a4_counts["Disagree"] == 48
    assert a4_counts["Neutral"] == 385
    assert a4_counts["Agree"] == 405
    assert a4_counts["Strongly agree"] == 128

    # ── A5 — agree T2B = (463+186)/1000 = 64.9% ──────────────────────────────
    a5 = stats_by_qid["A5"]
    assert a5.base == 1000
    a5_counts = {cs.label: cs.n for cs in a5.code_stats}
    assert a5_counts["Strongly disagree"] == 26
    assert a5_counts["Disagree"] == 25
    assert a5_counts["Neutral"] == 300
    assert a5_counts["Agree"] == 463
    assert a5_counts["Strongly agree"] == 186
    # Build plan note: "Q1 agree 64.6%" — this question (A5) has T2B 64.9%.
    # The 64.6% figure in the build plan is from the straightliner-excluded run (base 927).
    # HC tab (base 1000, straightliners kept) gives 64.9%.
    assert a5.t2b == pytest.approx(64.9, abs=0.05)
    assert a5.b2b == pytest.approx(5.1, abs=0.05)  # (26+25)/1000

    # ── A6 ────────────────────────────────────────────────────────────────────
    a6 = stats_by_qid["A6"]
    assert a6.base == 1000
    a6_counts = {cs.label: cs.n for cs in a6.code_stats}
    assert a6_counts["Strongly disagree"] == 28
    assert a6_counts["Disagree"] == 47
    assert a6_counts["Neutral"] == 345
    assert a6_counts["Agree"] == 433
    assert a6_counts["Strongly agree"] == 147


@pytest.mark.skipif(
    not SUPPORT_MEASURES_PATH.exists(),
    reason="HC file rakuten_survey_support_measures_data.xlsx not found in project root",
)
def test_support_measures_hc_q1():
    """Support-measures Q1: T2B 87.3%, B2B 2.3%, mean 4.27 (build plan golden fixture)."""
    from surveytool.ingest.rakuten import load

    survey = load(SUPPORT_MEASURES_PATH, survey_id="support-measures")
    stats_by_qid = {s.qid: s for s in compute_survey_stats(survey)}

    q1 = stats_by_qid["Q1"]
    assert q1.base == 1000
    assert q1.t2b == pytest.approx(87.3, abs=0.05)
    assert q1.b2b == pytest.approx(2.3, abs=0.05)
    assert q1.mean == pytest.approx(4.27, abs=0.005)


@pytest.mark.skipif(
    not SUPPORT_MEASURES_PATH.exists(),
    reason="HC file rakuten_survey_support_measures_data.xlsx not found in project root",
)
def test_support_measures_hc_q5():
    """Support-measures Q5: T2B 53.1% (42.0 + 11.1), mean 3.44 (build plan golden fixture).

    The 42% error case (omitting the 11.1% strongly agree) is the flagship
    error class this tool is designed to prevent.
    """
    from surveytool.ingest.rakuten import load

    survey = load(SUPPORT_MEASURES_PATH, survey_id="support-measures")
    stats_by_qid = {s.qid: s for s in compute_survey_stats(survey)}

    q5 = stats_by_qid["Q5"]
    assert q5.base == 1000
    assert q5.t2b == pytest.approx(53.1, abs=0.05)
    assert q5.mean == pytest.approx(3.44, abs=0.005)
