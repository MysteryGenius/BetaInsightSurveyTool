"""
Phase 7 Toluna adapter tests, run against the real misinformation xlsx in the
project root.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from surveytool.core.model import CodeRole, QuestionType

ROOT = Path(__file__).parent.parent
MISINFO_PATH = ROOT / "toluna_survey_misinformation_data.xlsx"

pytestmark = pytest.mark.skipif(
    not MISINFO_PATH.exists(),
    reason="toluna_survey_misinformation_data.xlsx not found in project root",
)


def _load():
    from surveytool.ingest.toluna import load

    return load(MISINFO_PATH, "misinformation")


def _responses_by_qid(survey):
    index: dict[str, list] = {}
    for r in survey.responses:
        index.setdefault(r.qid, []).append(r)
    return index


def test_n_raw_does_not_assume_contiguous_respids():
    survey = _load()
    assert survey.n_raw == 1000
    assert survey.n_analysis == 1000

    respondent_ids = {r.respondent_id for r in survey.responses}
    assert "SG100001" in respondent_ids
    assert "SG100003" not in respondent_ids  # screen-out gap
    assert "SG100004" in respondent_ids


def test_q7_grid_groups_by_shared_number():
    survey = _load()
    grid_questions = [q for q in survey.questions if q.grid_group == "grid_7"]
    other_questions = [q for q in survey.questions if q.grid_group != "grid_7"]

    assert len(grid_questions) == 3
    assert all(q.qtype is QuestionType.scale for q in grid_questions)
    assert all(q.grid_group == "grid_7" for q in grid_questions)
    assert all(q.grid_group is None for q in other_questions)

    texts = {q.text for q in grid_questions}
    assert texts == {"Local mainstream media", "Overseas mainstream media", "Online social media"}


def test_ability_scale_resolves_from_labels():
    survey = _load()
    q6 = next(q for q in survey.questions if q.qid == "6")
    assert q6.scale_family == "ability"

    roles_by_label = {sc.label: sc.role for sc in q6.labels}
    assert roles_by_label["Somewhat able to"] is CodeRole.top
    assert roles_by_label["Neutral / Neither able nor unable to"] is CodeRole.neutral


def test_likelihood_scale_resolves_top_neutral_bottom():
    survey = _load()
    q7 = next(q for q in survey.questions if q.grid_group == "grid_7" and q.text == "Local mainstream media")
    assert q7.scale_family == "likelihood"

    roles_by_label = {sc.label: sc.role for sc in q7.labels}
    assert roles_by_label["Very Likely"] is CodeRole.top
    assert roles_by_label["Likely"] is CodeRole.top
    assert roles_by_label["Neutral / Neither Likely nor Unlikely"] is CodeRole.neutral
    assert roles_by_label["Unlikely"] is CodeRole.bottom


def test_importance_scale_resolves_top_neutral_bottom():
    survey = _load()
    q8 = next(q for q in survey.questions if q.qid == "8")
    assert q8.scale_family == "importance"

    roles_by_label = {sc.label: sc.role for sc in q8.labels}
    assert roles_by_label["Very Important"] is CodeRole.top
    assert roles_by_label["Important"] is CodeRole.top
    assert roles_by_label["Neutral / Neither Important nor Unimportant"] is CodeRole.neutral


def test_effectiveness_scale_resolves_top_neutral_bottom():
    survey = _load()
    q9 = next(q for q in survey.questions if q.qid == "9")
    assert q9.scale_family == "effectiveness"

    roles_by_label = {sc.label: sc.role for sc in q9.labels}
    assert roles_by_label["Very Effective"] is CodeRole.top
    assert roles_by_label["Effective"] is CodeRole.top
    assert roles_by_label["Neutral / Neither Effective nor Ineffective"] is CodeRole.neutral
    assert roles_by_label["Ineffective"] is CodeRole.bottom


def test_demographic_columns_load_as_single_choice():
    survey = _load()
    gender = next(q for q in survey.questions if q.qid == "1")
    age = next(q for q in survey.questions if q.qid == "2")
    ethnicity = next(q for q in survey.questions if q.qid == "3")

    assert gender.qtype is QuestionType.single_choice
    assert age.qtype is QuestionType.single_choice
    assert ethnicity.qtype is QuestionType.single_choice


def test_no_scale_column_left_unresolved():
    """Every non-demographic column must resolve to a scale via the label
    library; none should silently fall back to single_choice."""
    survey = _load()
    scale_qids = {"6", "8", "9", "10"}
    grid_qids = {q.qid for q in survey.questions if q.grid_group == "grid_7"}

    for qid in scale_qids | grid_qids:
        q = next(qq for qq in survey.questions if qq.qid == qid)
        assert q.qtype is QuestionType.scale, f"{qid} did not resolve as scale"
        assert q.scale_family is not None, f"{qid} scale_family not identified"
