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


def test_demographic_columns_flagged_as_demographic():
    survey = _load()
    q5 = next(q for q in survey.questions if q.qid == "q5")
    q6 = next(q for q in survey.questions if q.qid == "q6")
    assert q5.is_demographic is True
    assert q6.is_demographic is True
    assert q5.qtype is QuestionType.single_choice
    assert q6.qtype is QuestionType.single_choice


def test_unresolvable_scale_label_is_collected_not_hard_failed_immediately():
    """Task 5: a Single-select column the adapter recognises as close to a
    scale (some labels match a family) but that also carries one
    unresolvable label used to hard-fail the whole file load immediately
    (UnresolvedScaleLabelsError from resolve_roles). It must now be
    collected into the single end-of-file UnresolvedQuestionsError instead,
    with a reason naming the family and the label that didn't fit —
    letting the analyst resolve it via the resolver rather than editing
    scales.yaml."""
    from surveytool.charts.errors import UnresolvedQuestionsError
    from surveytool.ingest.milieu import parse_header

    fieldnames = ["[q99]: Single-select - Some scale question"]
    rows = [
        {"[q99]: Single-select - Some scale question": "Agree"},
        {"[q99]: Single-select - Some scale question": "Disagree"},
        {"[q99]: Single-select - Some scale question": "Gobbledygook"},
    ]

    with pytest.raises(UnresolvedQuestionsError) as exc_info:
        parse_header(fieldnames, rows)

    entry = exc_info.value.detail_entries[0]
    assert entry.variable == "q99"
    assert "Gobbledygook" in entry.reason


def test_genuine_categorical_classifies_directly_not_queued_for_resolver():
    """Task 5 originally made a Single-select column where zero labels
    match any scale family (and whose qid is not a declared demographic)
    collect for the resolver rather than silently demote to single_choice
    (the any_label_matches_family gate that task deleted). Round A prompt
    A4 refines this further: a label set with no scale-pattern match AND no
    polarity pair (e.g. "not"/"un" counterpart) shows no evidence of being
    ordinal at all, so it is classified as `categorical` directly, with the
    reason recorded on the question — training an analyst to click through
    a resolver panel for questions that were never going to be scales is
    exactly what let the real A1/A3 defects hide. Contrast with
    test_toluna's/PureSpectrum's D5 fluency case, which does still queue
    for the resolver despite failing the same signals (a deliberate, named
    exception — see validate_questions._GRANDFATHERED_RESOLVER_CANDIDATES)."""
    from surveytool.core.model import QuestionType
    from surveytool.ingest.milieu import parse_header

    fieldnames = ["[q98]: Single-select - Favourite colour"]
    rows = [
        {"[q98]: Single-select - Favourite colour": "Red"},
        {"[q98]: Single-select - Favourite colour": "Blue"},
    ]

    questions = parse_header(fieldnames, rows)  # must not raise
    q98 = next(q for q in questions if q.qid == "q98")
    assert q98.qtype is QuestionType.categorical
    assert q98.categorical_reason is not None
    assert "no evidence" in q98.categorical_reason.lower()


def test_declared_demographic_still_demotes_to_single_choice_without_resolver():
    """A Single-select column whose qid is one of Milieu's declared
    demographic source_columns (q5, gender, per vendor_milieu.yaml) is
    exempt from the collector regardless of match outcome — Male/Female
    matches no scale family, but this must resolve straight to
    single_choice, not appear in the resolver."""
    from surveytool.ingest.milieu import parse_header

    fieldnames = ["[q5]: Single-select - Gender"]
    rows = [
        {"[q5]: Single-select - Gender": "Male"},
        {"[q5]: Single-select - Gender": "Female"},
    ]

    questions = parse_header(fieldnames, rows)
    assert len(questions) == 1
    assert questions[0].qtype is QuestionType.single_choice
