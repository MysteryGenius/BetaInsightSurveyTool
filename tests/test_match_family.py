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
    """Round B task B2 gave `importance` three real per-vendor variants.
    PureSpectrum Q7's real labels (Not at all important / Not very
    important / Somewhat important / Very important) exactly equal
    `four_point_polar`'s folded_label_set, so identify_variant/
    classify_question_type resolve this unambiguously to that one variant.
    match_family's coarser count-based heuristic, however, also counts a
    partial touch against `five_point_gradated` (its "very important"
    pattern happens to overlap), so `ambiguous` is True here even though
    the real, single-variant resolution used by classify_question_type is
    not in question -- see test_scale_library.py's
    test_purespectrum_q7_five_point_gradated_importance and this file's own
    test_ambiguous_full_match_when_every_label_falls_in_the_winning_family
    pattern for the same count-based-ambiguity-without-real-ambiguity
    shape."""
    labels = _labels_for_question(_PURESPECTRUM_PATH, "Q7")
    result = match_family(labels)
    assert result.outcome is MatchOutcome.full
    assert result.family == "importance"
    assert result.variant == "four_point_polar"
    assert result.unmatched_labels == []
    assert result.ambiguous is True


@pytest.mark.skipif(not _PURESPECTRUM_PATH.exists(), reason="purespectrum fixture not present")
def test_purespectrum_d5_fluency_labels_are_full_match_on_current_scales_yaml():
    """PureSpectrum D5's real labels carry a descriptive suffix after a dash
    (e.g. "Basic — a few words or phrases"). Round B task B2's whole point
    was to give `fluency` a real variant that matches these dash-suffixed
    labels literally (four_point_suffixed) -- unlike the pre-B2 bare-word
    fluency family, D5 now DOES achieve a full match. fold_label folds the
    em dash to ASCII "-" on both sides (the pattern was written pre-folded,
    the vendor label gets folded at match time), so the folded strings line
    up exactly."""
    labels = _labels_for_question(_PURESPECTRUM_PATH, "D5")
    assert len(labels) == 4

    result = match_family(labels)
    assert result.outcome is MatchOutcome.full
    assert result.family == "fluency"
    assert result.variant == "four_point_suffixed"
    assert result.unmatched_labels == []
    assert not result.ambiguous


@pytest.mark.skipif(not _RAKUTEN_SUPPORT_PATH.exists(), reason="rakuten support-measures fixture not present")
def test_rakuten_q1_full_match_against_agreement():
    """Rakuten's rakuten_survey_support_measures_data.xlsx Q1 real labels —
    a clean 5-point Strongly Disagree..Strongly Agree scale — must be a
    full match against `agreement.five_point` (Round B task B2's real
    5-point variant, ranks 1-5, not B1's intermediate 3-point placeholder).

    Note on `ambiguous`: post-B2, bare "neutral" is unique to
    `agreement.five_point` -- no other family's variant declares it as a
    literal pattern any more (every other polar family uses a distinct
    combined literal like "neutral / neither important nor unimportant"),
    so this label set is no longer touched by more than one family and
    `ambiguous` is correctly False."""
    labels = _labels_for_question(_RAKUTEN_SUPPORT_PATH, "Q1")
    assert labels == ["Strongly Disagree", "Disagree", "Neutral", "Agree", "Strongly Agree"]

    result = match_family(labels)
    assert result.outcome is MatchOutcome.full
    assert result.family == "agreement"
    assert result.variant == "five_point"
    assert result.unmatched_labels == []
    assert result.matched_labels["Strongly Agree"] == (CodeRole.top, 5)
    assert result.matched_labels["Strongly Disagree"] == (CodeRole.bottom, 1)
    assert result.matched_labels["Neutral"] == (CodeRole.neutral, 3)
    assert set(result.matched_labels) == set(labels)
    assert not result.ambiguous


# ---------------------------------------------------------------------------
# Synthetic edge-case coverage
# ---------------------------------------------------------------------------


def test_full_match_no_ambiguity():
    """agreement.five_point (Round B task B2) is a real 5-point variant, so
    "strongly agree" is rank 5 (top) and "strongly disagree" is rank 1
    (bottom), not B1's intermediate 3-point placeholder's ranks."""
    result = match_family(["strongly agree", "agree", "disagree", "strongly disagree"])
    assert result.outcome is MatchOutcome.full
    assert result.family == "agreement"
    assert result.unmatched_labels == []
    assert not result.ambiguous
    assert result.matched_labels["strongly agree"] == (CodeRole.top, 5)
    assert result.matched_labels["strongly disagree"] == (CodeRole.bottom, 1)


def test_no_match_returns_none_outcome_and_all_labels_unmatched():
    result = match_family(["North", "South", "East", "West"])
    assert result.outcome is MatchOutcome.none
    assert result.family is None
    assert result.matched_labels == {}
    assert result.unmatched_labels == ["North", "South", "East", "West"]
    assert not result.ambiguous


def test_partial_match_records_matched_and_unmatched_labels():
    """agreement.five_point (Round B task B2) is a real 5-point variant --
    "agree" is rank 4 (top), "disagree" is rank 2 (bottom)."""
    result = match_family(["agree", "banana", "disagree"])
    assert result.outcome is MatchOutcome.partial
    assert result.family == "agreement"
    assert result.unmatched_labels == ["banana"]
    assert set(result.matched_labels) == {"agree", "disagree"}
    assert result.matched_labels["agree"] == (CodeRole.top, 4)
    assert result.matched_labels["disagree"] == (CodeRole.bottom, 2)
    assert not result.ambiguous


def test_ambiguous_match_reports_family_with_highest_matched_count():
    """"agree" and "strongly agree" match agreement's top patterns, but
    "agree" also matches nothing else; construct a label set that
    genuinely straddles two families: agreement's top ("strongly agree",
    "agree") plus likelihood's top ("very likely") — three labels total,
    two of which land in agreement and one in likelihood, so agreement
    should win by count and ambiguous must be True.

    Ranks reflect Round B task B2's real 5-point agreement.five_point
    variant (top = rank 4 for "agree", rank 5 for "strongly agree" -- both
    fall in the top half of a 5-point scale, not B1's intermediate 3-point
    placeholder's single top rank)."""
    result = match_family(["strongly agree", "agree", "very likely"])
    assert result.outcome is MatchOutcome.partial
    assert result.ambiguous is True
    assert result.family == "agreement"
    assert set(result.matched_labels) == {"strongly agree", "agree"}
    assert result.matched_labels["strongly agree"] == (CodeRole.top, 5)
    assert result.matched_labels["agree"] == (CodeRole.top, 4)
    assert result.unmatched_labels == ["very likely"]


# Round B task B2 deleted this file's
# test_ambiguous_full_match_when_every_label_falls_in_the_winning_family
# test. Its entire premise was that bare "neutral" is a literal pattern
# shared by many families (agreement, satisfaction, likelihood,
# effectiveness, ability, importance) in the old scales.yaml, creating a
# count-based tie to demonstrate. Post-B2, every family's real per-vendor
# variant except agreement.five_point uses a distinct combined literal for
# its neutral point (e.g. "neutral / neither important nor unimportant"),
# so bare "neutral" is now unique to agreement -- confirmed directly
# against _ALL_VARIANTS. The scenario this test existed to demonstrate no
# longer has any real label set to construct it from, so it is deleted
# rather than resurrected with a synthetic scales.yaml, following the same
# reasoning Task B1 used when it deleted
# test_purespectrum_q7_partial_match_against_pre_task3_importance_family
# for an analogous reason (see the comment above).


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


def test_strongly_satisfied_to_strongly_dissatisfied_now_only_partially_matches_agreement():
    """Round A prompt A3 originally reported this Rakuten housing-estate
    satisfaction question (Strongly dissatisfied / Dissatisfied / Neutral /
    Satisfied / Strongly satisfied) as unrecognised because `satisfaction`
    had `very satisfied`/`very dissatisfied` but no `strongly` variant.

    Round B task B2 deliberately leaves `satisfaction` with ZERO variants
    (`{}` in scales.yaml) -- no real vendor file has surfaced its actual
    label set yet, so per the plan it fails to match loudly rather than
    getting a placeholder invented for it. There is therefore nothing left
    for this label set to fully match against satisfaction; the only real
    signal left is that its bare "Neutral" label partially matches
    agreement.five_point's neutral point (the only family that still
    declares bare "neutral" post-B2 -- see the note on
    test_rakuten_q1_full_match_against_agreement)."""
    labels = ["Strongly dissatisfied", "Dissatisfied", "Neutral", "Satisfied", "Strongly satisfied"]
    result = match_family(labels)
    assert result.outcome is MatchOutcome.partial
    assert result.family == "agreement"
    assert result.unmatched_labels == ["Strongly dissatisfied", "Dissatisfied", "Satisfied", "Strongly satisfied"]
    assert result.matched_labels == {"Neutral": (CodeRole.neutral, 3)}
    assert not result.ambiguous
