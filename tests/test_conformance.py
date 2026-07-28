"""
Phase 0 conformance suite.

Asserts the seven invariants the canonical model must satisfy.
Section A: synthetic fixtures only, no vendor files touched.
Section B: real Milieu and Toluna vendor files — a guard against the exact
           class of silent-degradation bug fixed in the v1 fix pass (role
           resolution succeeding while scale_family silently returns None,
           or a scale silently demoting to single_choice).
"""
from pathlib import Path

import pytest

from surveytool.core.model import CodeRole, QuestionType, ResponseState
from surveytool.core.scale_library import resolve_roles
from surveytool.core.straightliner import detect_straightliners


# ── Section A: synthetic fixtures ──────────────────────────────────────────────

# ── 1. Reversed-coded scale resolves roles from labels ────────────────────────

def test_reversed_scale_resolves_from_labels():
    """
    A scale where code 1 = top and code 5 = bottom must resolve roles
    from label meaning, not from code magnitude.
    """
    from tests.fixtures.reversed_scale import QUESTION

    roles_by_label = {sc.label: sc.role for sc in QUESTION.labels}
    assert roles_by_label["Strongly Agree"] is CodeRole.top
    assert roles_by_label["Agree"] is CodeRole.top
    assert roles_by_label["Neither Agree Nor Disagree"] is CodeRole.neutral
    assert roles_by_label["Disagree"] is CodeRole.bottom
    assert roles_by_label["Strongly Disagree"] is CodeRole.bottom

    # The reversed direction: code 1 is top, code 5 is bottom
    codes_by_role = {}
    for sc in QUESTION.labels:
        codes_by_role.setdefault(sc.role, []).append(sc.code)

    assert 1 in codes_by_role[CodeRole.top]
    assert 5 in codes_by_role[CodeRole.bottom]

    # High code is NOT top (direction is descending)
    assert QUESTION.scale_direction == "descending"


# ── 2. Multi-response bases on respondents, may exceed 100% ──────────────────

def test_multi_response_bases_on_respondents():
    """
    Multi-response percentage base = n respondents asked (not n selections).
    Individual code percentages can exceed 100% in aggregate.
    """
    from tests.fixtures.multi_response import (
        EXPECTED,
        EXPECTED_AGGREGATE_TOTAL,
        QUESTION,
        RESPONDENT_BASE,
        SELECTIONS,
    )

    assert QUESTION.qtype.value == "multi_response"

    # Compute code counts from the fixture selections
    counts: dict[str, int] = {"A": 0, "B": 0, "C": 0}
    for selections in SELECTIONS.values():
        for code in selections:
            counts[code] += 1

    base = RESPONDENT_BASE
    computed = {code: cnt / base * 100 for code, cnt in counts.items()}

    assert computed == pytest.approx(EXPECTED)
    assert sum(computed.values()) == pytest.approx(EXPECTED_AGGREGATE_TOTAL)
    assert EXPECTED_AGGREGATE_TOTAL > 100.0  # this is the key assertion


# ── 3. Non-substantive in base but excluded from mean ─────────────────────────

def test_nonsubstantive_in_base_not_mean():
    """
    A non-substantive response is counted in the percentage base
    (the respondent was asked) but excluded from the mean.
    """
    from tests.fixtures.nonsubstantive import (
        EXPECTED_BASE,
        EXPECTED_MEAN,
        QUESTION,
        RESPONSES,
    )

    all_asked = [r for r in RESPONSES if r.state is not ResponseState.not_asked]
    assert len(all_asked) == EXPECTED_BASE

    substantive = [
        r for r in RESPONSES
        if r.state is ResponseState.answered and r.raw_value is not None
    ]
    label_map = {sc.code: sc for sc in QUESTION.labels}
    numeric_values = [
        label_map[r.raw_value].numeric_value
        for r in substantive
        if r.raw_value in label_map and label_map[r.raw_value].numeric_value is not None
    ]

    mean = sum(numeric_values) / len(numeric_values)
    assert mean == pytest.approx(EXPECTED_MEAN)

    # Confirm the non-substantive respondent is in the base count
    ns_respondents = [r for r in RESPONSES if r.state is ResponseState.nonsubstantive]
    assert len(ns_respondents) == 1
    assert ns_respondents[0].respondent_id not in {r.respondent_id for r in substantive}


# ── 4. Routed question bases on those asked ───────────────────────────────────

def test_routed_question_bases_on_asked():
    """
    A question with an asked_base predicate must use a base of those
    who were asked, not the total sample N.
    """
    from tests.fixtures.routed_question import (
        EXPECTED_BASE,
        RESPONSES,
        ROUTED_QUESTION,
        TOTAL_N,
    )

    assert ROUTED_QUESTION.asked_base != "ALL"

    asked = [r for r in RESPONSES if r.state is not ResponseState.not_asked]
    not_asked = [r for r in RESPONSES if r.state is ResponseState.not_asked]

    assert len(asked) == EXPECTED_BASE
    assert len(not_asked) == TOTAL_N - EXPECTED_BASE
    assert EXPECTED_BASE < TOTAL_N


# ── 5. Unknown labels fail loudly ─────────────────────────────────────────────

def test_unknown_label_raises():
    """
    A label set containing a label that no scale family recognises
    must raise ValueError naming the unresolved label.
    """
    from tests.fixtures.unknown_labels import UNRESOLVABLE_LABEL, UNKNOWN_LABELS

    with pytest.raises(ValueError) as exc_info:
        resolve_roles(UNKNOWN_LABELS)

    assert UNRESOLVABLE_LABEL in str(exc_info.value)


# ── 6. Grids group by grid_group id ──────────────────────────────────────────

def test_grid_groups_by_stem():
    """
    Questions sharing a grid_group id are retrievable as a group.
    Questions without that id are excluded.
    """
    from tests.fixtures.grid_questions import ALL_QUESTIONS, GRID_GROUP_ID, GRID_QUESTIONS

    grouped = [q for q in ALL_QUESTIONS if q.grid_group == GRID_GROUP_ID]
    ungrouped = [q for q in ALL_QUESTIONS if q.grid_group != GRID_GROUP_ID]

    assert len(grouped) == len(GRID_QUESTIONS)
    assert all(q.grid_group == GRID_GROUP_ID for q in grouped)
    assert all(q.qid in {gq.qid for gq in GRID_QUESTIONS} for q in grouped)
    assert len(ungrouped) == 1
    assert ungrouped[0].grid_group is None


# ── 7. Straightliner reproduces known flagged set ─────────────────────────────

def test_straightliner_reproduces_known_set():
    """
    detect_straightliners returns exactly the respondents with zero variance
    across all scale items and no others.
    """
    from tests.fixtures.straightliner import EXPECTED_FLAGGED, QUESTIONS, RESPONSES

    flagged = detect_straightliners(RESPONSES, QUESTIONS)

    assert flagged == EXPECTED_FLAGGED


# ── Section B: real vendor file guard ──────────────────────────────────────────
#
# Every question an adapter treats as a scale must fully resolve: role
# resolution must succeed AND scale_family must not be None. This is the
# exact regression class of the two bugs this fix pass closed — resolve_roles
# succeeding while identify_family silently returned None (Toluna's compound
# "Neutral / Neither X nor Y" labels), and a scale silently demoting to
# single_choice when a label didn't resolve at all (Toluna Q6's missing
# ability-family gradations). This guard asserts loudly; it does not skip
# quietly the way the vendor adapters used to.

_ROOT = Path(__file__).parent.parent
_MILIEU_PATH = _ROOT / "milieu_survey_coe_data.csv"
_TOLUNA_PATH = _ROOT / "toluna_survey_misinformation_data.xlsx"
_RAKUTEN_PATH = _ROOT / "rakuten_survey_support_measures_data.xlsx"


def _assert_all_scales_fully_resolved(questions, vendor: str) -> None:
    for q in questions:
        if q.qtype is not QuestionType.scale:
            continue
        assert q.scale_family is not None, (
            f"{vendor} question {q.qid!r} resolved as a scale but "
            "scale_family is None — role resolution and family "
            "identification have diverged again."
        )
        roles = {sc.role for sc in q.labels}
        assert CodeRole.top in roles, f"{vendor} question {q.qid!r} scale has no top role"
        assert CodeRole.bottom in roles, f"{vendor} question {q.qid!r} scale has no bottom role"


@pytest.mark.skipif(
    not _RAKUTEN_PATH.exists(),
    reason="rakuten_survey_support_measures_data.xlsx not found in project root",
)
def test_rakuten_real_file_scales_fully_resolve():
    from surveytool.ingest.rakuten import load

    survey = load(_RAKUTEN_PATH, "support-measures")
    assert any(q.qtype is QuestionType.scale for q in survey.questions), (
        "Expected at least one scale question in the Rakuten fixture"
    )
    _assert_all_scales_fully_resolved(survey.questions, "rakuten")


@pytest.mark.skipif(
    not _MILIEU_PATH.exists(),
    reason="milieu_survey_coe_data.csv not found in project root",
)
def test_milieu_real_file_scales_fully_resolve():
    from surveytool.ingest.milieu import load

    survey = load(_MILIEU_PATH, "coe")
    assert any(q.qtype is QuestionType.scale for q in survey.questions), (
        "Expected at least one scale question in the Milieu fixture"
    )
    _assert_all_scales_fully_resolved(survey.questions, "milieu")


@pytest.mark.skipif(
    not _TOLUNA_PATH.exists(),
    reason="toluna_survey_misinformation_data.xlsx not found in project root",
)
def test_toluna_real_file_scales_fully_resolve():
    from surveytool.ingest.toluna import load

    survey = load(_TOLUNA_PATH, "misinformation")
    assert any(q.qtype is QuestionType.scale for q in survey.questions), (
        "Expected at least one scale question in the Toluna fixture"
    )
    _assert_all_scales_fully_resolved(survey.questions, "toluna")
