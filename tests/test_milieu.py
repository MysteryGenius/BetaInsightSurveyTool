"""
Phase 6 Milieu adapter tests, run against the real COE CSV in the project root.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from surveytool.core.model import CodeRole, QuestionType, ResponseState
from surveytool.compute.frequency import compute_question_stats

ROOT = Path(__file__).parent.parent
COE_PATH = ROOT / "milieu_survey_coe_data.csv"

pytestmark = pytest.mark.skipif(
    not COE_PATH.exists(),
    reason="milieu_survey_coe_data.csv not found in project root",
)


def _load():
    from surveytool.ingest.milieu import load

    return load(COE_PATH, "coe")


def _responses_by_qid(survey):
    index: dict[str, list] = {}
    for r in survey.responses:
        index.setdefault(r.qid, []).append(r)
    return index


def test_n_raw_is_1000():
    survey = _load()
    assert survey.n_raw == 1000
    assert survey.n_analysis == 1000


def test_q8_multi_response_bases_on_routed_567_not_1000():
    survey = _load()
    resp_by_qid = _responses_by_qid(survey)
    q8 = next(q for q in survey.questions if q.qid == "q8")

    assert q8.qtype is QuestionType.multi_response

    asked = [r for r in resp_by_qid["q8"] if r.state is not ResponseState.not_asked]
    not_asked = [r for r in resp_by_qid["q8"] if r.state is ResponseState.not_asked]
    assert len(asked) == 567
    assert len(not_asked) == 433

    stats = compute_question_stats(q8, resp_by_qid["q8"])
    assert stats.base == 567


def test_q7_trailing_space_label_trimmed():
    survey = _load()
    q7 = next(q for q in survey.questions if q.qid == "q7")
    labels = [sc.label for sc in q7.labels]
    assert "Yes, I own a car" in labels
    assert "Yes, I own a car " not in labels


def test_q7_base_is_full_sample():
    survey = _load()
    resp_by_qid = _responses_by_qid(survey)
    q7 = next(q for q in survey.questions if q.qid == "q7")
    stats = compute_question_stats(q7, resp_by_qid["q7"])
    assert stats.base == 1000

    by_label = {cs.label: cs.n for cs in stats.code_stats}
    assert by_label["No, I do not drive or have access to a car"] == 567
    assert by_label["Yes, I own a car"] == 213
    assert by_label["Yes, I share a car with others (e.g. family, friends)"] == 151
    assert by_label["Yes, I use car rental or car-sharing services"] == 69


def test_grid_items_share_group_and_resolve_from_labels():
    survey = _load()
    grid_qids = {"q10", "q11", "q12", "q13", "q14"}
    grid_questions = [q for q in survey.questions if q.qid in grid_qids]

    assert len(grid_questions) == 5
    group_ids = {q.grid_group for q in grid_questions}
    assert len(group_ids) == 1
    assert None not in group_ids

    other_questions = [q for q in survey.questions if q.qid not in grid_qids]
    assert all(q.grid_group is None for q in other_questions)

    for q in grid_questions:
        assert q.qtype is QuestionType.scale
        roles_by_label = {sc.label: sc.role for sc in q.labels}
        assert roles_by_label["Strongly Agree"] is CodeRole.top
        assert roles_by_label["Agree"] is CodeRole.top
        assert roles_by_label["Neutral"] is CodeRole.neutral
        assert roles_by_label["Disagree"] is CodeRole.bottom
        assert roles_by_label["Strongly Disagree"] is CodeRole.bottom


def test_grid_question_stats_compute_cleanly():
    survey = _load()
    resp_by_qid = _responses_by_qid(survey)
    q10 = next(q for q in survey.questions if q.qid == "q10")
    stats = compute_question_stats(q10, resp_by_qid["q10"])

    assert stats.base == 1000
    assert stats.mean is not None
    assert stats.t2b is not None
    assert stats.b2b is not None


def test_demographic_columns_not_flagged_as_demographic():
    survey = _load()
    q5 = next(q for q in survey.questions if q.qid == "q5")
    q6 = next(q for q in survey.questions if q.qid == "q6")
    assert q5.is_demographic is False
    assert q6.is_demographic is False
    assert q5.qtype is QuestionType.single_choice
    assert q6.qtype is QuestionType.single_choice
