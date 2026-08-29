from pathlib import Path

import pandas as pd
import pytest

from surveytool.charts.errors import UnresolvedQuestion, UnresolvedQuestionsError
from surveytool.core.scale_library import MatchOutcome, match_family
from surveytool.ingest.validate_questions import close_family_hint_for_match

_ROOT = Path(__file__).parent.parent
_PURESPECTRUM_PATH = _ROOT / "purespectrum_survey_wcs_data.xlsx"


def _labels_for_question(path: Path, tag: str) -> list[str]:
    """Extract a question's response labels straight from a vendor Datamap
    sheet, mirroring the helper in tests/test_match_family.py."""
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


def test_unresolved_questions_error_message_states_count():
    entries = [
        UnresolvedQuestion(variable="Q3", question_text="How often?", codes=[(1, "Purple")], reason="No family matched 'purple'."),
        UnresolvedQuestion(variable="Q7", question_text="How able?", codes=[(1, "Kinda")], reason="No family matched 'kinda'."),
        UnresolvedQuestion(variable="Q9", question_text="How much?", codes=[(1, "Bunches")], reason="No family matched 'bunches'."),
    ]
    err = UnresolvedQuestionsError(entries)
    assert "3" in err.message
    assert err.detail_entries == entries
    assert "scales.yaml" not in err.message.lower()
    assert "yaml" not in err.message.lower()
    assert "override" not in err.next_action.lower() or "resolver" in err.next_action.lower()


def test_unresolved_questions_error_next_action_is_plain_english():
    entries = [UnresolvedQuestion(variable="Q1", question_text="text", codes=[], reason="reason")]
    err = UnresolvedQuestionsError(entries)
    for forbidden in ("scales.yaml", ".yaml", "surveytool/", "repository"):
        assert forbidden not in err.next_action.lower()
        assert forbidden not in err.message.lower()


def test_unresolved_questions_error_to_response_serializes_detail_entries():
    entries = [
        UnresolvedQuestion(variable="Q3", question_text="How often?", codes=[(1, "Purple"), (2, "Green")], reason="No family matched 'purple'."),
        UnresolvedQuestion(variable="Q7", question_text="How able?", codes=[(1, "Kinda")], reason="No family matched 'kinda'."),
    ]
    err = UnresolvedQuestionsError(entries)
    response = err.to_response()

    assert response["error"]["code"] == "UNRESOLVED_SCALE_LABELS"
    assert response["error"]["message"] == err.message
    assert response["error"]["detail"] == err.detail
    detail_entries = response["error"]["detail_entries"]
    assert len(detail_entries) == 2
    assert detail_entries[0] == {
        "variable": "Q3",
        "question_text": "How often?",
        "codes": [[1, "Purple"], [2, "Green"]],
        "reason": "No family matched 'purple'.",
    }
    assert detail_entries[1]["variable"] == "Q7"


# ---------------------------------------------------------------------------
# close_family_hint regression coverage (Task 6 fix round 1)
#
# Task 6's original report demonstrated close_family_hint against
# PureSpectrum Q9, believing it to be a genuine partial match. A review
# investigation found that Q9's "partial match" is actually an artifact of
# a pre-existing DatamapReader parsing bug (Q10's un-bracketed header row
# is never recognised as a new question boundary, so Q9's code-parsing
# loop bleeds into Q10's rows and appends two stray labels). Verified
# independently: match_family on Q9's correct 4 labels alone returns
# MatchOutcome.full against 'worry', not partial — so Q9 exercises the
# parser bug, not this feature. That bug is out of scope here (flagged
# separately, not fixed in this file) — these tests replace the Q9 demo
# with a clean partial-match case built the same way
# test_purespectrum_q7_partial_match_against_pre_task3_importance_family
# in tests/test_match_family.py does: reconstructing the pre-Task-3
# `importance` family definition (verified against `git show
# e3215ae:surveytool/core/scales.yaml`) and matching it against Q7's real,
# correctly-parsed labels, which involves no datamap-parsing bug at all.
#
# These were previously only exercised by the implementer's one-off manual
# demonstration in the task-6 report, not by any test in tests/ — this
# closes that gap.
# ---------------------------------------------------------------------------

def _match_against_pre_task3_importance(labels: list[str]):
    """Build a synthetic FamilyMatch by hand for a hard-coded, historical
    (pre-Task-3) partial-match scenario over PureSpectrum Q7's real labels:
    "Very important" and "Not at all important" matched importance's
    top/bottom at that point in history, but "Somewhat important" and
    "Not very important" matched nothing yet (Task 3 later added them).

    Round B task B1 deleted the private per-family dict helpers
    (_label_in_family/_role_in_family) this used to call to derive the
    match generically -- that dict-shaped family concept no longer exists
    anywhere in the codebase. Since this is a fixed, known historical
    scenario over a fixed label list, the match is just asserted directly
    as literal (CodeRole, rank) tuples rather than re-derived from any
    library helper; the rank values mirror the current single 3-point
    `default` importance variant (bottom=1, neutral=2, top=3)."""
    from surveytool.core.model import CodeRole
    from surveytool.core.scale_library import FamilyMatch

    matched_ranks = {
        "Very important": (CodeRole.top, 3),
        "Not at all important": (CodeRole.bottom, 1),
    }
    matched_labels = {lb: matched_ranks[lb] for lb in labels if lb in matched_ranks}
    unmatched_labels = [lb for lb in labels if lb not in matched_ranks]

    outcome = MatchOutcome.partial if matched_labels and unmatched_labels else MatchOutcome.full
    return FamilyMatch(
        outcome=outcome,
        family="importance",
        variant="pre_task3_importance",
        matched_labels=matched_labels,
        unmatched_labels=unmatched_labels,
        missing_point_patterns=[],
        ambiguous=False,
    )


@pytest.mark.skipif(not _PURESPECTRUM_PATH.exists(), reason="purespectrum fixture not present")
def test_close_family_hint_present_for_genuine_partial_match():
    """A genuine partial match (no datamap-parsing bug involved) must
    produce a close_family_hint naming the family and the specific labels
    that didn't fit, and that hint must survive serialization via
    UnresolvedQuestionsError.to_response()."""
    labels = _labels_for_question(_PURESPECTRUM_PATH, "Q7")
    assert labels == [
        "Very important",
        "Somewhat important",
        "Not very important",
        "Not at all important",
    ]

    match = _match_against_pre_task3_importance(labels)
    assert match.outcome is MatchOutcome.partial
    assert set(match.unmatched_labels) == {"Somewhat important", "Not very important"}

    hint = close_family_hint_for_match(match)
    assert hint is not None
    assert "importance" in hint
    assert "Somewhat important" in hint
    assert "Not very important" in hint

    entry = UnresolvedQuestion(
        variable="Q7",
        question_text="How important is this to you?",
        codes=list(enumerate(labels, start=1)),
        reason="This looks close to the 'importance' scale, but these response(s) don't match it: "
        "Somewhat important, Not very important.",
        close_family_hint=hint,
    )
    response = UnresolvedQuestionsError([entry]).to_response()
    entry_dict = response["error"]["detail_entries"][0]
    assert "close_family_hint" in entry_dict
    assert entry_dict["close_family_hint"] == hint
    assert "importance" in entry_dict["close_family_hint"]
    assert "Somewhat important" in entry_dict["close_family_hint"]
    assert "Not very important" in entry_dict["close_family_hint"]


@pytest.mark.skipif(not _PURESPECTRUM_PATH.exists(), reason="purespectrum fixture not present")
def test_close_family_hint_absent_for_genuine_no_match():
    """PureSpectrum D5 is a real, current, non-buggy no-match (confirmed by
    Task 3/4/5's reports and tests/test_match_family.py): its labels carry
    a descriptive suffix that doesn't match any family in the CURRENT
    scales.yaml, no datamap-parsing bug involved. close_family_hint must be
    None from close_family_hint_for_match, and the 'close_family_hint' key
    must be entirely absent (not null, not empty string) from the
    serialized detail entry."""
    labels = _labels_for_question(_PURESPECTRUM_PATH, "D5")
    match = match_family(labels)
    assert match.outcome is MatchOutcome.none

    hint = close_family_hint_for_match(match)
    assert hint is None

    entry = UnresolvedQuestion(
        variable="D5",
        question_text="How fluent are you?",
        codes=list(enumerate(labels, start=1)),
        reason="None of this question's response labels match any known scale.",
        close_family_hint=hint,
    )
    response = UnresolvedQuestionsError([entry]).to_response()
    entry_dict = response["error"]["detail_entries"][0]
    assert "close_family_hint" not in entry_dict
    assert set(entry_dict.keys()) == {"variable", "question_text", "codes", "reason"}
