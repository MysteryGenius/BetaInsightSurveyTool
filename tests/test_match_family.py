# tests/test_match_family.py
"""Direct unit tests for `match_family` (surveytool/core/scale_library.py),
the richer, non-raising sibling of `identify_family` added by Task 4 of the
state-audit remediation plan. `identify_family` itself is untouched — see
test_scale_library.py's existing coverage, which continues to pass
unmodified.

Real-fixture acceptance cases (PureSpectrum Q7/D5, Rakuten Q1) are checked
against label sets extracted directly from the vendor Datamap sheets in the
project root, not hand-typed. Small synthetic label lists are used only for
edge-case coverage (ambiguous match) per the task brief.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from surveytool.core.model import CodeRole
from surveytool.core.scale_library import (
    FamilyMatch,
    MatchOutcome,
    _FAMILIES_BY_NAME,
    match_family,
)

_ROOT = Path(__file__).parent.parent
_PURESPECTRUM_PATH = _ROOT / "purespectrum_survey_wcs_data.xlsx"
_RAKUTEN_SUPPORT_PATH = _ROOT / "rakuten_survey_support_measures_data.xlsx"


def _labels_for_question(path: Path, tag: str) -> list[str]:
    """Extract a question's response labels straight from a vendor Datamap
    sheet, mirroring how the audit script and the real adapters read the
    codebook: find the row whose column 0 contains "[tag]", then collect
    column 2 values from subsequent rows until a fully blank row."""
    df = pd.read_excel(path, sheet_name="Datamap", header=None)
    matches = df.index[df[0].astype(str).str.contains(rf"\[{tag}\]", na=False, regex=True)]
    assert len(matches) == 1, f"expected exactly one row tagged [{tag}], found {len(matches)}"
    idx = matches[0]
    labels: list[str] = []
    i = idx + 1
    while i < len(df) and not (pd.isna(df.loc[i, 0]) and pd.isna(df.loc[i, 1]) and pd.isna(df.loc[i, 2])):
        if not pd.isna(df.loc[i, 2]):
            labels.append(str(df.loc[i, 2]))
        i += 1
    return labels


# ---------------------------------------------------------------------------
# Real-fixture acceptance cases
# ---------------------------------------------------------------------------


# Round B task B1 removed this file's test_purespectrum_q7_partial_match_
# against_pre_task3_importance_family test, which reconstructed a
# historical (pre-existing-commit) dict-shaped `importance` family
# definition via the now-deleted private helpers `_label_in_family`/
# `_role_in_family` purely to demonstrate a partial-match scenario. That
# scenario is now covered by better mechanisms in the new variant-based
# test suite (tests/test_scale_library.py's load-time and match-time
# ambiguity/partial-match tests), and the dict-shaped family definition it
# reconstructed no longer exists as a concept anywhere in the codebase —
# resurrecting it here would just enshrine a dead code shape as a testing
# convention going forward.


@pytest.mark.skipif(not _PURESPECTRUM_PATH.exists(), reason="purespectrum fixture not present")
def test_purespectrum_q7_current_scales_yaml_is_full_match():
    """Sanity check documenting the CURRENT behaviour on this branch: Task 3
    already added "somewhat important"/"not very important" to importance,
    so against the CURRENT scales.yaml, Q7 is now a full match, not a
    partial one. This is expected and is why the partial-match acceptance
    case above reconstructs the pre-Task-3 family definition instead."""
    labels = _labels_for_question(_PURESPECTRUM_PATH, "Q7")
    result = match_family(labels)
    assert result.outcome is MatchOutcome.full
    assert result.family == "importance"
    assert result.unmatched_labels == []
    assert not result.ambiguous


@pytest.mark.skipif(not _PURESPECTRUM_PATH.exists(), reason="purespectrum fixture not present")
def test_purespectrum_d5_fluency_labels_are_no_match_on_current_scales_yaml():
    """PureSpectrum D5's real labels carry a descriptive suffix after a dash
    (e.g. "Basic — a few words or phrases"). scales.yaml's `fluency` family
    (added by Task 3) only has the bare words ("fluent", "conversational",
    "basic", "none", "not at all") — matching is exact normalised-label set
    membership, not substring/prefix matching (per fold_label's own
    docstring and the scales.yaml comment above the fluency family), so
    these dash-suffixed labels genuinely do not match anything in the
    CURRENT scales.yaml. This is the real, currently-true no-match case
    used in place of Q8/Q9, both of which Task 3 already gave matching
    families (concern, worry)."""
    labels = _labels_for_question(_PURESPECTRUM_PATH, "D5")
    assert len(labels) == 4

    result = match_family(labels)
    assert result.outcome is MatchOutcome.none
    assert result.family is None
    assert result.matched_labels == {}
    assert result.unmatched_labels == labels
    assert not result.ambiguous


@pytest.mark.skipif(not _RAKUTEN_SUPPORT_PATH.exists(), reason="rakuten support-measures fixture not present")
def test_rakuten_q1_full_match_against_agreement():
    """Rakuten's rakuten_survey_support_measures_data.xlsx Q1 real labels —
    a clean 5-point Strongly Disagree..Strongly Agree scale — must be a
    full match against `agreement`.

    Note on `ambiguous`: "Neutral" (folded to "neutral") is a literal
    neutral_pattern shared by several families in scales.yaml (agreement,
    satisfaction, likelihood, effectiveness, ability, importance), so by
    the count-based ambiguity rule this label set does touch more than one
    family — every other family only matches "Neutral" (count 1), while
    agreement also matches "Agree"/"Disagree"/"Strongly Agree"/"Strongly
    Disagree" (count 5) and wins outright. `family`/`outcome` are therefore
    unambiguous in effect even though the `ambiguous` flag is set; this is
    the intended, documented behaviour of the count-based tie-break, not a
    bug in this test's expectations."""
    labels = _labels_for_question(_RAKUTEN_SUPPORT_PATH, "Q1")
    assert labels == ["Strongly Disagree", "Disagree", "Neutral", "Agree", "Strongly Agree"]

    result = match_family(labels)
    assert result.outcome is MatchOutcome.full
    assert result.family == "agreement"
    assert result.unmatched_labels == []
    assert result.matched_labels["Strongly Agree"] == (CodeRole.top, 3)
    assert result.matched_labels["Strongly Disagree"] == (CodeRole.bottom, 1)
    assert result.matched_labels["Neutral"] == (CodeRole.neutral, 2)
    assert set(result.matched_labels) == set(labels)


# ---------------------------------------------------------------------------
# Synthetic edge-case coverage
# ---------------------------------------------------------------------------


def test_full_match_no_ambiguity():
    result = match_family(["strongly agree", "agree", "disagree", "strongly disagree"])
    assert result.outcome is MatchOutcome.full
    assert result.family == "agreement"
    assert result.unmatched_labels == []
    assert not result.ambiguous
    assert result.matched_labels["strongly agree"] == (CodeRole.top, 3)
    assert result.matched_labels["strongly disagree"] == (CodeRole.bottom, 1)


def test_no_match_returns_none_outcome_and_all_labels_unmatched():
    result = match_family(["North", "South", "East", "West"])
    assert result.outcome is MatchOutcome.none
    assert result.family is None
    assert result.matched_labels == {}
    assert result.unmatched_labels == ["North", "South", "East", "West"]
    assert not result.ambiguous


def test_partial_match_records_matched_and_unmatched_labels():
    result = match_family(["agree", "banana", "disagree"])
    assert result.outcome is MatchOutcome.partial
    assert result.family == "agreement"
    assert result.unmatched_labels == ["banana"]
    assert set(result.matched_labels) == {"agree", "disagree"}
    assert result.matched_labels["agree"] == (CodeRole.top, 3)
    assert result.matched_labels["disagree"] == (CodeRole.bottom, 1)
    assert not result.ambiguous


def test_ambiguous_match_reports_family_with_highest_matched_count():
    """"agree" and "strongly agree" match agreement's top_patterns, but
    "agree" also matches nothing else; construct a label set that
    genuinely straddles two families: agreement's top ("strongly agree",
    "agree") plus likelihood's top ("very likely") — three labels total,
    two of which land in agreement and one in likelihood, so agreement
    should win by count and ambiguous must be True."""
    result = match_family(["strongly agree", "agree", "very likely"])
    assert result.outcome is MatchOutcome.partial
    assert result.ambiguous is True
    assert result.family == "agreement"
    assert set(result.matched_labels) == {"strongly agree", "agree"}
    assert result.matched_labels["strongly agree"] == (CodeRole.top, 3)
    assert result.matched_labels["agree"] == (CodeRole.top, 3)
    assert result.unmatched_labels == ["very likely"]


def test_ambiguous_full_match_when_every_label_falls_in_the_winning_family():
    """Every label matches at least one family, but two different families
    are touched (agreement's "agree"/"disagree" pair plus a label that also
    happens to satisfy likelihood is not straightforward to construct from
    real patterns without also being a no-match elsewhere, so this uses a
    tie-breaking case instead: "neutral" is a literal neutral_pattern
    shared by multiple families, so a label set built entirely from
    literal "neutral" plus one family-specific label still only touches
    the count for families containing "neutral" once each, and the
    intended-family's other matched label breaks the tie by count."""
    result = match_family(["agree", "disagree", "neutral"])
    # "neutral" is a neutral_pattern in agreement, satisfaction, likelihood,
    # effectiveness, ability, and importance's families, but agreement is
    # the only family that also matches "agree"/"disagree", so it wins by
    # count (3) over every other family that only matches "neutral" (1).
    assert result.outcome is MatchOutcome.full
    assert result.family == "agreement"
    assert result.ambiguous is True
    assert result.unmatched_labels == []
    assert set(result.matched_labels) == {"agree", "disagree", "neutral"}
    assert result.matched_labels["agree"] == (CodeRole.top, 3)
    assert result.matched_labels["disagree"] == (CodeRole.bottom, 1)
    assert result.matched_labels["neutral"] == (CodeRole.neutral, 2)


def test_matched_and_unmatched_labels_preserve_original_input_casing_and_order():
    result = match_family(["Agree", "banana", "Disagree", "apple"])
    assert result.unmatched_labels == ["banana", "apple"]
    assert set(result.matched_labels) == {"Agree", "Disagree"}


def test_returns_family_match_dataclass_instance():
    """Round B task B1 removed 'binary' from scales.yaml entirely (it's now
    a hardcoded literal pair in classify_question_type, not a variant, so
    match_family — which only knows about variants — no longer recognises
    "yes"/"no" at all). Use a real remaining family instead to prove
    match_family still returns a genuine FamilyMatch instance."""
    result = match_family(["strongly agree", "agree", "disagree", "strongly disagree"])
    assert isinstance(result, FamilyMatch)
    assert result.family == "agreement"
    assert result.outcome is MatchOutcome.full


def test_every_family_name_reachable_via_match_family():
    """Smoke check that match_family can report every family defined in
    scales.yaml, not just a hardcoded subset — guards against the function
    silently ignoring families added after this task."""
    for name, family in _FAMILIES_BY_NAME.items():
        for variant in family.variants:
            sample = variant.points[0].patterns[:1]
            if not sample:
                continue
            result = match_family(list(sample))
            assert result.outcome in (MatchOutcome.full, MatchOutcome.partial)


def test_strongly_satisfied_to_strongly_dissatisfied_full_match_against_satisfaction():
    """Round A prompt A3: Leonard loaded a real Rakuten housing-estate
    satisfaction question labelled Strongly dissatisfied / Dissatisfied /
    Neutral / Satisfied / Strongly satisfied and it was flagged unrecognised
    — `satisfaction` had `very satisfied`/`very dissatisfied` but no
    `strongly` variant. Neither Rakuten fixture in this project root
    contains that question (see this file's fixture-vs-synthetic split
    above), so this is synthetic edge-case coverage of the exact reported
    label set, following this file's own documented convention for cases
    with no vendor file to extract from — not a claim that this label set
    was pulled from a real file."""
    labels = ["Strongly dissatisfied", "Dissatisfied", "Neutral", "Satisfied", "Strongly satisfied"]
    result = match_family(labels)
    assert result.outcome is MatchOutcome.full
    assert result.family == "satisfaction"
    assert result.unmatched_labels == []
    assert result.matched_labels["Strongly satisfied"] == (CodeRole.top, 3)
    assert result.matched_labels["Strongly dissatisfied"] == (CodeRole.bottom, 1)
    assert result.matched_labels["Neutral"] == (CodeRole.neutral, 2)
