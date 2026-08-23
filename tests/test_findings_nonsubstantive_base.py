"""
exclude_nonsubstantive_from_base wiring test (UI build prompt 9).

Synthetic in-memory fixture (no vendor file needed) — confirms
build_findings_sheet actually threads the setting through to
compute_question_stats: toggling it produces a lower base and higher
percentages, with the base always present in both states.
"""
from __future__ import annotations

from surveytool.core.model import CodeRole, Question, QuestionType, Response, ResponseState, ScaleCode, Survey
from surveytool.findings.sheet import build_findings_sheet


def _make_survey_with_nonsubstantive_responses() -> Survey:
    question = Question(
        qid="Q1",
        text="How satisfied are you?",
        qtype=QuestionType.scale,
        labels=[
            ScaleCode(code=1, label="Satisfied", role=CodeRole.top),
            ScaleCode(code=2, label="Dissatisfied", role=CodeRole.bottom),
            ScaleCode(code=3, label="Prefer not to say", role=CodeRole.nonsubstantive),
        ],
        base_eligible=True,
    )
    responses = [
        Response(respondent_id="r1", qid="Q1", raw_value=1, state=ResponseState.answered),
        Response(respondent_id="r2", qid="Q1", raw_value=1, state=ResponseState.answered),
        Response(respondent_id="r3", qid="Q1", raw_value=2, state=ResponseState.answered),
        Response(respondent_id="r4", qid="Q1", raw_value=3, state=ResponseState.nonsubstantive),
    ]
    return Survey(id="probe", n_raw=4, n_analysis=4, questions=[question], responses=responses)


def test_exclude_toggle_off_keeps_nonsubstantive_in_base():
    survey = _make_survey_with_nonsubstantive_responses()
    rows = build_findings_sheet(survey, banner=[], exclude_nonsubstantive_from_base=False)
    base = next(r.cell_base for r in rows if r.breakdown_variable == "total")
    assert base == 4


def test_exclude_toggle_on_removes_nonsubstantive_from_base():
    survey = _make_survey_with_nonsubstantive_responses()
    rows = build_findings_sheet(survey, banner=[], exclude_nonsubstantive_from_base=True)
    base = next(r.cell_base for r in rows if r.breakdown_variable == "total")
    assert base == 3


def test_exclude_toggle_on_produces_higher_percentages():
    survey = _make_survey_with_nonsubstantive_responses()
    rows_off = build_findings_sheet(survey, banner=[], exclude_nonsubstantive_from_base=False)
    rows_on = build_findings_sheet(survey, banner=[], exclude_nonsubstantive_from_base=True)

    pct_off = next(r.value for r in rows_off if r.metric == "pct_Satisfied")
    pct_on = next(r.value for r in rows_on if r.metric == "pct_Satisfied")
    assert pct_on > pct_off


def test_base_is_present_in_both_toggle_states():
    survey = _make_survey_with_nonsubstantive_responses()
    for toggle in (False, True):
        rows = build_findings_sheet(survey, banner=[], exclude_nonsubstantive_from_base=toggle)
        assert all(r.cell_base is not None and r.cell_base > 0 for r in rows)


def test_default_matches_project_setting_default_of_false():
    survey = _make_survey_with_nonsubstantive_responses()
    rows_default = build_findings_sheet(survey, banner=[])
    rows_explicit_off = build_findings_sheet(survey, banner=[], exclude_nonsubstantive_from_base=False)
    base_default = next(r.cell_base for r in rows_default if r.breakdown_variable == "total")
    base_explicit_off = next(r.cell_base for r in rows_explicit_off if r.breakdown_variable == "total")
    assert base_default == base_explicit_off == 4
