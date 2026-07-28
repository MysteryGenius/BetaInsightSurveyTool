"""
Cross-tab compute path tests.

Section A: unit tests over synthetic fixtures (no file I/O) — config wiring,
           demographic detection/resolution, suppression thresholds, straightliner
           exclusion, significance stub.
Section B: HC golden tests against real vendor files in the project root.
           Skipped automatically when vendor files are absent.

Coverage note (see module bottom for full statement): golden hand-verified figures
exist only for Q1 x age (youngest mean 3.90, oldest mean 4.48), reused from
test_findings.py's existing hand-verified fixture. No hand-verified figures exist
for other question x demographic combinations, for gender/ethnicity breakdowns, or
for the second vendor file. Base-size suppression/greying is tested only against
synthetic fixtures — neither real vendor file has a demographic subgroup small
enough to exercise the default thresholds. Income has no real-file coverage at all;
"race" resolves only via the ethnicity alias.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from surveytool.compute.cross_tab import (
    CellStatus,
    DemographicNotFoundError,
    compute_cross_tab,
    detect_available_demographics,
    resolve_demographic_question,
)
from surveytool.core.config import ToolConfig, project_config
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

ROOT = Path(__file__).parent.parent
SUPPORT_MEASURES_PATH = ROOT / "rakuten_survey_support_measures_data.xlsx"


# ── Shared synthetic survey helpers ──────────────────────────────────────────

def _make_scale_question(qid: str = "Q1", text: str = "Q") -> Question:
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


_AGE_LABELS = [
    ScaleCode(code=1, label="18-34", role=CodeRole.top),
    ScaleCode(code=2, label="35-54", role=CodeRole.bottom),
]


def _survey_with_age_groups(n_young: int, n_old: int, *, straightliners: set[str] = frozenset()) -> Survey:
    """Build a survey with a scale question Q1 and an "age" demographic,
    n_young respondents coded 1 (young), n_old respondents coded 2 (old).
    Every response answered with code 1 (Agree) on Q1, unless respondent_id
    is in `straightliners`, in which case Q1 raw_value is still 1 (single-item
    straightlining is orthogonal here — straightliner detection needs >=2 scale
    items, so straightliner respondents get a second dummy scale question).
    """
    age_q = _make_demo_question("S1", "What is your age group?", _AGE_LABELS)
    scale_q = _make_scale_question("Q1")
    dummy_q = _make_scale_question("Q2", "dummy scale item for straightliner detection")
    questions = [age_q, scale_q, dummy_q]

    responses: list[Response] = []
    for i in range(n_young):
        rid = f"Y{i:03d}"
        responses.append(Response(respondent_id=rid, qid="S1", raw_value=1, state=ResponseState.answered))
        responses.append(Response(respondent_id=rid, qid="Q1", raw_value=1, state=ResponseState.answered))
        # straightliners: identical values across both scale items
        val = 1 if rid in straightliners else (1 + (i % 3))
        responses.append(Response(respondent_id=rid, qid="Q2", raw_value=1 if rid in straightliners else val, state=ResponseState.answered))
    for i in range(n_old):
        rid = f"O{i:03d}"
        responses.append(Response(respondent_id=rid, qid="S1", raw_value=2, state=ResponseState.answered))
        responses.append(Response(respondent_id=rid, qid="Q1", raw_value=1, state=ResponseState.answered))
        val = 1 if rid in straightliners else (1 + (i % 3))
        responses.append(Response(respondent_id=rid, qid="Q2", raw_value=1 if rid in straightliners else val, state=ResponseState.answered))

    return Survey(
        id="test", n_raw=n_young + n_old, n_analysis=n_young + n_old,
        questions=questions, responses=responses,
    )


# ── Section A: unit tests ─────────────────────────────────────────────────────

def test_cell_below_suppress_threshold_is_suppressed():
    """n below default suppress threshold (10) => suppressed, figures withheld, n still correct."""
    survey = _survey_with_age_groups(n_young=5, n_old=50)
    frame = to_respondent_frame(survey)
    q1 = next(q for q in survey.questions if q.qid == "Q1")

    result = compute_cross_tab(frame, survey, q1, "age")

    young_cell = next(c for c in result.cells if c.subgroup_label == "18-34")
    assert young_cell.n == 5
    assert young_cell.status == CellStatus.suppressed
    assert young_cell.t2b is None
    assert young_cell.b2b is None
    assert young_cell.mean is None


def test_cell_between_thresholds_is_greyed_but_values_present():
    """n between suppress (10) and grey (30) => greyed, values still populated."""
    survey = _survey_with_age_groups(n_young=20, n_old=50)
    frame = to_respondent_frame(survey)
    q1 = next(q for q in survey.questions if q.qid == "Q1")

    result = compute_cross_tab(frame, survey, q1, "age")

    young_cell = next(c for c in result.cells if c.subgroup_label == "18-34")
    assert young_cell.n == 20
    assert young_cell.status == CellStatus.grey
    assert young_cell.t2b is not None
    assert young_cell.mean is not None


def test_cell_above_grey_threshold_is_ok():
    survey = _survey_with_age_groups(n_young=50, n_old=50)
    frame = to_respondent_frame(survey)
    q1 = next(q for q in survey.questions if q.qid == "Q1")

    result = compute_cross_tab(frame, survey, q1, "age")

    for cell in result.cells:
        assert cell.status == CellStatus.ok
        assert cell.t2b is not None


def test_per_project_config_override_changes_threshold_outcome():
    """A project override of grey_threshold changes the same n=20 cell's status."""
    survey = _survey_with_age_groups(n_young=20, n_old=50)
    frame = to_respondent_frame(survey)
    q1 = next(q for q in survey.questions if q.qid == "Q1")

    base_config = ToolConfig(per_project={"proj-a": {"cross_tab_grey_threshold": 10}})
    project_cfg = project_config(base_config, "proj-a")

    result = compute_cross_tab(frame, survey, q1, "age", config=project_cfg)
    young_cell = next(c for c in result.cells if c.subgroup_label == "18-34")
    assert young_cell.status == CellStatus.ok


def test_n_always_populated_even_when_suppressed():
    survey = _survey_with_age_groups(n_young=3, n_old=50)
    frame = to_respondent_frame(survey)
    q1 = next(q for q in survey.questions if q.qid == "Q1")

    result = compute_cross_tab(frame, survey, q1, "age")
    young_cell = next(c for c in result.cells if c.subgroup_label == "18-34")
    assert young_cell.n == 3


def test_resolve_demographic_question_raises_when_unresolvable():
    survey = _survey_with_age_groups(n_young=20, n_old=20)
    with pytest.raises(DemographicNotFoundError, match="nonsense_field"):
        resolve_demographic_question(survey, "nonsense_field")


def test_compute_cross_tab_raises_when_demographic_unresolvable():
    survey = _survey_with_age_groups(n_young=20, n_old=20)
    frame = to_respondent_frame(survey)
    q1 = next(q for q in survey.questions if q.qid == "Q1")
    with pytest.raises(DemographicNotFoundError):
        compute_cross_tab(frame, survey, q1, "income")


def test_detect_available_demographics_standard_present_conditional_absent():
    survey = _survey_with_age_groups(n_young=20, n_old=20)
    availability = detect_available_demographics(survey)
    assert "age" in availability.standard
    assert availability.conditional == {}


def test_significance_true_raises_not_implemented_before_computation():
    survey = _survey_with_age_groups(n_young=20, n_old=20)
    frame = to_respondent_frame(survey)
    q1 = next(q for q in survey.questions if q.qid == "Q1")

    with pytest.raises(NotImplementedError, match="significance testing not yet implemented"):
        compute_cross_tab(frame, survey, q1, "age", significance=True)


def test_significance_true_short_circuits_even_for_unresolvable_demographic():
    """significance check happens before demographic resolution — fail fast, no partial work."""
    survey = _survey_with_age_groups(n_young=20, n_old=20)
    frame = to_respondent_frame(survey)
    q1 = next(q for q in survey.questions if q.qid == "Q1")

    with pytest.raises(NotImplementedError):
        compute_cross_tab(frame, survey, q1, "nonsense_field", significance=True)


def test_straightliner_exclusion_reduces_subgroup_n_and_figures():
    straightliners = {"Y000", "Y001"}
    survey = _survey_with_age_groups(n_young=20, n_old=20, straightliners=straightliners)
    frame = to_respondent_frame(survey)
    q1 = next(q for q in survey.questions if q.qid == "Q1")

    result_full = compute_cross_tab(frame, survey, q1, "age")
    result_excluded = compute_cross_tab(frame, survey, q1, "age", exclude_respondent_ids=straightliners)

    young_full = next(c for c in result_full.cells if c.subgroup_label == "18-34")
    young_excluded = next(c for c in result_excluded.cells if c.subgroup_label == "18-34")

    assert young_full.n == 20
    assert young_excluded.n == 18


# ── Section B: HC golden tests ────────────────────────────────────────────────

@pytest.fixture(scope="module")
def support_measures_survey():
    from surveytool.ingest.rakuten import load
    return load(SUPPORT_MEASURES_PATH, "support-measures")


@pytest.fixture(scope="module")
def support_measures_frame(support_measures_survey):
    return to_respondent_frame(support_measures_survey)


@pytest.mark.skipif(
    not SUPPORT_MEASURES_PATH.exists(),
    reason="HC file rakuten_survey_support_measures_data.xlsx not found in project root",
)
def test_q1_age_mean_matches_hand_verified_golden_figures(support_measures_survey, support_measures_frame):
    """Q1 concern mean by age band: youngest 3.90, oldest 4.48.

    Reused from test_findings.py::test_support_measures_q1_age_mean_rises, which
    hand-verifies these exact figures against the build plan golden fixture.
    """
    q1 = next(q for q in support_measures_survey.questions if q.qid == "Q1")
    result = compute_cross_tab(support_measures_frame, support_measures_survey, q1, "age")

    populated_cells = [c for c in result.cells if c.mean is not None]
    assert len(populated_cells) >= 2, "Expected at least 2 age bands with respondents"

    age_q = next(
        q for q in support_measures_survey.questions
        if q.is_demographic and "age" in q.text.lower()
    )
    ordered_labels = [
        sc.label for sc in age_q.labels
        if sc.role in {CodeRole.top, CodeRole.neutral, CodeRole.bottom, CodeRole.excluded}
    ]
    populated_labels = [lb for lb in ordered_labels if any(c.subgroup_label == lb for c in populated_cells)]

    youngest_label = populated_labels[0]
    oldest_label = populated_labels[-1]

    youngest_cell = next(c for c in result.cells if c.subgroup_label == youngest_label)
    oldest_cell = next(c for c in result.cells if c.subgroup_label == oldest_label)

    assert youngest_cell.mean == pytest.approx(3.90, abs=0.005)
    assert oldest_cell.mean == pytest.approx(4.48, abs=0.005)


@pytest.mark.skipif(
    not SUPPORT_MEASURES_PATH.exists(),
    reason="HC file rakuten_survey_support_measures_data.xlsx not found in project root",
)
def test_cross_tab_n_matches_findings_sheet_cell_base(support_measures_survey, support_measures_frame):
    """compute_cross_tab's per-cell n must equal build_findings_sheet's cell_base
    for the same (qid, demographic, level) — internal-consistency regression guard,
    not independent golden verification (both call compute_question_stats)."""
    from surveytool.findings.sheet import build_findings_sheet

    sheet = build_findings_sheet(support_measures_survey)
    q1 = next(q for q in support_measures_survey.questions if q.qid == "Q1")
    result = compute_cross_tab(support_measures_frame, support_measures_survey, q1, "age")

    sheet_bases = {
        (r.breakdown_level): r.cell_base
        for r in sheet
        if r.qid == "Q1" and r.breakdown_variable == "age" and r.metric == "t2b"
    }

    assert sheet_bases, "Expected age-breakdown t2b rows in findings sheet"
    for cell in result.cells:
        if cell.subgroup_label in sheet_bases:
            assert cell.n == sheet_bases[cell.subgroup_label]
