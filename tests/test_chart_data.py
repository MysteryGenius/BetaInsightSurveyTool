"""
Phase 3 interactive chart-data tests.

Mirrors tests/test_charts.py's fixture style. Asserts build_chart_data()
produces the same values/n that the PNG renderer would use, and that the
real-fixture golden figures already proven in tests/test_findings.py are
reproduced exactly — no new computation is introduced.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from surveytool.charts.chart_data import build_chart_data
from surveytool.charts.errors import MissingFindingsRow
from surveytool.core.model import CodeRole, Question, QuestionType, Response, ResponseState, ScaleCode, Survey
from surveytool.findings.sheet import FindingsRow, build_findings_sheet

ROOT = Path(__file__).parent.parent
SUPPORT_MEASURES_PATH = ROOT / "rakuten_survey_support_measures_data.xlsx"


# ── Shared helpers (mirrors tests/test_charts.py) ────────────────────────────

def _agreement_question(qid: str = "Q1", text: str = "How much do you agree?") -> Question:
    return Question(
        qid=qid,
        text=text,
        qtype=QuestionType.scale,
        scale_family="agreement",
        labels=[
            ScaleCode(code=1, label="Strongly Agree", role=CodeRole.top, numeric_value=5),
            ScaleCode(code=2, label="Agree", role=CodeRole.top, numeric_value=4),
            ScaleCode(code=3, label="Neither Agree Nor Disagree", role=CodeRole.neutral, numeric_value=3),
            ScaleCode(code=4, label="Disagree", role=CodeRole.bottom, numeric_value=2),
            ScaleCode(code=5, label="Strongly Disagree", role=CodeRole.bottom, numeric_value=1),
        ],
    )


def _demo_age_question() -> Question:
    return Question(
        qid="age",
        text="What is your age group?",
        qtype=QuestionType.demographic,
        is_demographic=True,
        base_eligible=False,
        labels=[
            ScaleCode(code=1, label="18-24", role=CodeRole.excluded),
            ScaleCode(code=2, label="25-34", role=CodeRole.excluded),
            ScaleCode(code=3, label="35-44", role=CodeRole.excluded),
        ],
    )


def _make_survey(n: int, scale_q: Question, demo_questions: list[Question] | None = None) -> Survey:
    """Build a synthetic survey with n respondents cycling through scale codes 1-5."""
    questions = [scale_q] + (demo_questions or [])
    responses: list[Response] = []
    codes = [sc.code for sc in scale_q.labels if sc.role is not CodeRole.nonsubstantive]
    for i in range(n):
        rid = f"R{i+1:03d}"
        code = codes[i % len(codes)]
        responses.append(Response(respondent_id=rid, qid=scale_q.qid, raw_value=code, state=ResponseState.answered))
    return Survey(id="test-survey", n_raw=n, n_analysis=n, questions=questions, responses=responses)


def _make_survey_with_age(n: int) -> tuple[Survey, Question, Question]:
    scale_q = _agreement_question()
    age_q = _demo_age_question()
    scale_codes = [sc.code for sc in scale_q.labels]
    age_codes = [sc.code for sc in age_q.labels]
    responses: list[Response] = []
    for i in range(n):
        rid = f"R{i+1:03d}"
        responses.append(Response(respondent_id=rid, qid="Q1", raw_value=scale_codes[i % len(scale_codes)], state=ResponseState.answered))
        responses.append(Response(respondent_id=rid, qid="age", raw_value=age_codes[i % len(age_codes)], state=ResponseState.answered))
    survey = Survey(
        id="test-survey", n_raw=n, n_analysis=n,
        questions=[scale_q, age_q], responses=responses,
    )
    return survey, scale_q, age_q


# ── Test 1: dist chart data matches findings values/n ────────────────────────

def test_dist_chart_data_matches_findings_values_and_n() -> None:
    q = _agreement_question()
    survey = _make_survey(10, q)
    findings = build_findings_sheet(survey, banner=[])

    charts = build_chart_data(findings, survey.id, survey.questions)
    dist = next(c for c in charts if c.chart_type == "dist" and c.qid == "Q1")

    idx = {(r.metric): r for r in findings if r.breakdown_variable == "total" and r.qid == "Q1"}

    for label, value, n in zip(dist.trace["labels"], dist.trace["values"], dist.trace["n"]):
        pct_row = idx[f"pct_{label}"]
        n_row = idx[f"n_{label}"]
        assert value == pct_row.value
        assert n == int(n_row.value)

    assert dist.trace["cell_base"] == idx["pct_Strongly Agree"].cell_base


# ── Test 2: xbreak chart data matches findings values/n ──────────────────────

def test_xbreak_chart_data_matches_findings_values_and_n() -> None:
    survey, scale_q, age_q = _make_survey_with_age(30)
    findings = build_findings_sheet(survey, banner=["age"])

    charts = build_chart_data(findings, survey.id, survey.questions)
    xbreak = next(c for c in charts if c.chart_type == "xbreak" and c.qid == "Q1")

    metric = xbreak.trace["metric"]
    idx = {
        r.breakdown_level: r
        for r in findings
        if r.qid == "Q1" and r.breakdown_variable == "age" and r.metric == metric
    }

    for level, value, n in zip(xbreak.trace["levels"], xbreak.trace["values"], xbreak.trace["n"]):
        row = idx[level]
        assert value == row.value
        assert n == row.cell_base


# ── Test 3: missing row still raises MissingFindingsRow ──────────────────────

def test_missing_pct_row_raises_missing_findings_row() -> None:
    q = _agreement_question()
    survey = _make_survey(10, q)
    findings = build_findings_sheet(survey, banner=[])

    incomplete = [r for r in findings if not (r.qid == "Q1" and r.metric == "pct_Strongly Agree")]

    with pytest.raises(MissingFindingsRow):
        build_chart_data(incomplete, survey.id, survey.questions)


# ── Test 4: golden real-fixture values reproduced exactly, no recomputation ──

@pytest.fixture(scope="module")
def support_measures_findings():
    if not SUPPORT_MEASURES_PATH.exists():
        pytest.skip(f"{SUPPORT_MEASURES_PATH.name} not found in project root")
    from surveytool.ingest.rakuten import load
    survey = load(SUPPORT_MEASURES_PATH, "support-measures")
    return build_findings_sheet(survey), survey


@pytest.mark.skipif(
    not SUPPORT_MEASURES_PATH.exists(),
    reason="HC file rakuten_survey_support_measures_data.xlsx not found in project root",
)
def test_support_measures_q1_dist_chart_data_matches_golden_figures(support_measures_findings) -> None:
    """Q1 concern: T2B 87.3%, mean 4.27, base 1000 (build plan golden fixture)."""
    findings, survey = support_measures_findings
    charts = build_chart_data(findings, survey.id, survey.questions)
    dist = next(c for c in charts if c.chart_type == "dist" and c.qid == "Q1")

    assert dist.trace["t2b"] == pytest.approx(87.3, abs=0.05)
    assert dist.trace["mean"] == pytest.approx(4.27, abs=0.005)
    assert dist.trace["cell_base"] == 1000
