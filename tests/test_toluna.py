"""
Phase 7 Toluna adapter tests, run against the real misinformation xlsx in the
project root.

Task 5: column "2" (age_band) is a genuine demographic by content, but
vendor_toluna.yaml deliberately does NOT declare it as a source_column (a
real reachability gap — see that YAML's comment), so it is not exempt from
the load-path collector. An override-free load of the real fixture now
correctly raises UnresolvedQuestionsError for it, same as PureSpectrum's D2.
_load() below supplies the categorical override an analyst would write via
the resolver so the rest of this module's tests can still load the fixture
cleanly and assert on its other columns.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from surveytool.core.model import CodeRole, QuestionType
from surveytool.ingest.overrides import QuestionOverride

ROOT = Path(__file__).parent.parent
MISINFO_PATH = ROOT / "toluna_survey_misinformation_data.xlsx"

pytestmark = pytest.mark.skipif(
    not MISINFO_PATH.exists(),
    reason="toluna_survey_misinformation_data.xlsx not found in project root",
)

_AGE_COLUMN_OVERRIDE = {
    "2": QuestionOverride(
        variable="2",
        question_type="categorical",
        label_roles={},
        resolved_at=datetime.now(timezone.utc),
        library_version="test",
    )
}


def _load(overrides=None):
    from surveytool.ingest.toluna import load

    merged = dict(_AGE_COLUMN_OVERRIDE)
    merged.update(overrides or {})
    return load(MISINFO_PATH, "misinformation", merged)


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
    """Gender/ethnicity (declared demographic source_columns in
    vendor_toluna.yaml, hence exempt from the collector) still resolve to
    single_choice with no override needed. Age (column "2") is a genuine
    demographic by content but is NOT declared in that YAML (a real
    reachability gap, see the YAML's own comment) — Task 5 means it's no
    longer exempt, so _load()'s categorical override for it is what lets
    this test's file load at all; it now surfaces as categorical, not
    single_choice, reflecting the classification the analyst actually
    chose via the resolver rather than an auto-detected default."""
    survey = _load()
    gender = next(q for q in survey.questions if q.qid == "1")
    age = next(q for q in survey.questions if q.qid == "2")
    ethnicity = next(q for q in survey.questions if q.qid == "3")

    assert gender.qtype is QuestionType.single_choice
    assert age.qtype is QuestionType.categorical
    assert ethnicity.qtype is QuestionType.single_choice

    assert gender.is_demographic is True
    assert age.is_demographic is True
    assert ethnicity.is_demographic is True


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


def test_unresolvable_scale_label_is_collected_not_hard_failed_immediately():
    """Task 5: a column the adapter recognises as close to a scale (some
    labels match a family) but that also carries one unresolvable label
    used to hard-fail the whole file load immediately
    (UnresolvedScaleLabelsError from resolve_roles). It must now be
    collected into the single end-of-file UnresolvedQuestionsError instead,
    with a reason naming the family and the label that didn't fit."""
    from surveytool.charts.errors import UnresolvedQuestionsError
    from surveytool.ingest.toluna import parse_header

    header = ("respid", "99 : Some scale question?")
    rows = [
        ("SG1", "Agree"),
        ("SG2", "Disagree"),
        ("SG3", "Gobbledygook"),
    ]

    with pytest.raises(UnresolvedQuestionsError) as exc_info:
        parse_header(header, rows)

    entry = exc_info.value.detail_entries[0]
    assert entry.variable == "99"
    assert "Gobbledygook" in entry.reason


def test_genuine_categorical_is_collected_not_silently_single_choice():
    """Task 5: a column where zero labels match any scale family, and whose
    qid is not a declared demographic, used to demote silently to
    single_choice. It must now be collected instead."""
    from surveytool.charts.errors import UnresolvedQuestionsError
    from surveytool.ingest.toluna import parse_header

    header = ("respid", "98 : Favourite city?")
    rows = [
        ("SG1", "Singapore"),
        ("SG2", "Tokyo"),
    ]

    with pytest.raises(UnresolvedQuestionsError) as exc_info:
        parse_header(header, rows)

    entry = exc_info.value.detail_entries[0]
    assert entry.variable == "98"
    assert "none" in entry.reason.lower()
