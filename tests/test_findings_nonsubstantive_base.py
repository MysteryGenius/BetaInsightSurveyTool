"""
exclude_nonsubstantive_from_base wiring test (UI build prompt 9).

Synthetic in-memory fixture (no vendor file needed) — confirms
build_findings_sheet actually threads the setting through to
compute_question_stats: toggling it produces a lower base and higher
percentages, with the base always present in both states.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from surveytool.core.config import ToolConfig
from surveytool.core.model import CodeRole, Question, QuestionType, Response, ResponseState, ScaleCode, Survey
from surveytool.core.nonsubstantive import DEFAULT_NONSUBSTANTIVE_LABELS, is_nonsubstantive_label
from surveytool.findings.sheet import build_findings_sheet
from surveytool.ingest.rakuten import load

ROOT = Path(__file__).parent.parent
SUPPORT_MEASURES_PATH = ROOT / "rakuten_survey_support_measures_data.xlsx"


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


# ── Regression guard: ToolConfig()'s real default must match labels=None ──
#
# Task 7 fix-round-1: the reviewer found that ToolConfig.nonsubstantive_labels
# defaulted to a stale 3-pattern literal while is_nonsubstantive_label's
# labels=None fallback used a 6-pattern default. Because a non-None list is
# authoritative (replace-not-union), every real pipeline run against an
# unmodified project (ToolConfig() with no per-project override) was silently
# using only 3 of the 6 intended patterns. Neither existing Rakuten fixture
# contains a response option matching any of the 6 patterns, so a plain
# before/after diff against fixture data can't catch this by luck of
# content -- this test instead exercises the REAL settings object
# (ToolConfig(), unmodified) through the REAL load() path and separately
# proves systematic parity against labels=None for every default pattern.


def test_default_tool_config_matches_hardcoded_defaults_for_every_pattern():
    """The test that should have caught the bug: for every one of the 6
    built-in default non-substantive patterns, classification through
    ToolConfig()'s real (unmodified) nonsubstantive_labels must be IDENTICAL
    to classification through labels=None (the pre-Task-7 hardcoded-only
    behavior). If ToolConfig's default ever drifts out of sync with the
    real default list again, this fails immediately."""
    settings = ToolConfig()
    # One representative label per default pattern. "Dont know" (no
    # apostrophe) is deliberately excluded here: it relies on the
    # labels=None path's fuzzy don.?t know regex, which is a documented,
    # pre-existing difference in matching semantics between the None
    # fallback (regex patterns) and a configured list (literal substring
    # match per label, see _compile_patterns) -- orthogonal to this fix,
    # which is about the default *list contents*, not per-label match
    # semantics.
    sample_labels = [
        "Prefer not to say",
        "Don't know",
        "Not Applicable",
        "N/A",
        "Refused",
        "No opinion",
    ]
    for label in sample_labels:
        via_config = is_nonsubstantive_label(label, settings.nonsubstantive_labels)
        via_none = is_nonsubstantive_label(label, None)
        assert via_config == via_none is True, (
            f"{label!r}: ToolConfig() default classified as {via_config} "
            f"but labels=None classifies as {via_none} -- ToolConfig's "
            "default has drifted out of sync with DEFAULT_NONSUBSTANTIVE_LABELS"
        )

    # And the list itself is exactly the shared canonical default, not a
    # second literal that happens to currently agree.
    assert settings.nonsubstantive_labels == list(DEFAULT_NONSUBSTANTIVE_LABELS)


@pytest.mark.skipif(
    not SUPPORT_MEASURES_PATH.exists(),
    reason=f"{SUPPORT_MEASURES_PATH.name} not found in project root",
)
def test_real_pipeline_path_with_unmodified_project_settings():
    """End-to-end: construct ToolConfig() exactly as
    _load_project_settings() does for any project that hasn't written
    custom settings (the common case), load a real Rakuten fixture through
    it exactly as app.py's real wiring does, and confirm behavior is
    identical to the pre-Task-7 hardcoded-only path (nonsubstantive_labels
    left as None). This fixture's real option set (checked directly)
    contains none of the 6 default patterns, so this alone doesn't
    numerically move the base -- the systematic parity test above is what
    proves the fix; this test proves the real object wiring end-to-end
    doesn't regress the no-match case either."""
    settings = ToolConfig()  # exactly what _load_project_settings returns for a fresh project

    survey_via_settings = load(SUPPORT_MEASURES_PATH, "probe-real-settings", None, settings.nonsubstantive_labels)
    survey_via_none = load(SUPPORT_MEASURES_PATH, "probe-real-settings-none", None, None)

    rows_via_settings = build_findings_sheet(survey_via_settings, banner=[], exclude_nonsubstantive_from_base=True)
    rows_via_none = build_findings_sheet(survey_via_none, banner=[], exclude_nonsubstantive_from_base=True)

    base_via_settings = next(
        r.cell_base for r in rows_via_settings if r.breakdown_variable == "total" and r.qid == "Q1"
    )
    base_via_none = next(r.cell_base for r in rows_via_none if r.breakdown_variable == "total" and r.qid == "Q1")
    assert base_via_settings == base_via_none
