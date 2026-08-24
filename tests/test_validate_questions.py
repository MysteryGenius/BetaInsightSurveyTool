# tests/test_validate_questions.py
"""
Single-pass validation batches every unresolved question's override failure
into one UnresolvedQuestionsError, rather than raising on the first bad
override. See Task 15 for the override schema this validates against.

Task 5 changed validate_all_questions's contract: it used to only check
*incomplete overrides* (a stored override that doesn't cover the question's
current label set) and was silent on a fresh, override-free question that
simply didn't match any scale family — that was classify_question_type's
old silent-categorical-fallback behaviour, mirrored here. Task 5 deletes
that fallback everywhere it lived, including this module: a question with
no override that doesn't achieve a FULL match via match_family is now
collected too, on the same "collect every genuine miss, raise once" pass.
"""
from datetime import datetime, timezone

import pytest

from surveytool.charts.errors import UnresolvedQuestionsError
from surveytool.ingest.validate_questions import validate_all_questions


def test_three_unmatched_no_override_questions_batch_into_one_error():
    """Task 5: a question with no override and no full scale match is no
    longer silently treated as fine (the old categorical-fallback
    behaviour this test used to assert) — it's collected, same as an
    incomplete-override question, and the whole file raises once."""
    raw_questions = [
        ("Q3", "How often?", [(1, "Purple"), (2, "Green")]),
        ("Q7", "How able?", [(1, "Kinda"), (2, "Sorta")]),
        ("Q9", "How much?", [(1, "Bunches"), (2, "Loads")]),
    ]
    with pytest.raises(UnresolvedQuestionsError) as exc_info:
        validate_all_questions(raw_questions, overrides={})
    assert len(exc_info.value.detail_entries) == 3
    assert {e.variable for e in exc_info.value.detail_entries} == {"Q3", "Q7", "Q9"}


def test_incomplete_override_questions_batch_into_one_error():
    from surveytool.ingest.overrides import QuestionOverride

    raw_questions = [
        ("Q3", "How often?", [(1, "Purple"), (2, "Green")]),
        ("Q7", "How able?", [(1, "Kinda"), (2, "Sorta")]),
    ]
    now = datetime.now(timezone.utc)
    overrides = {
        "Q3": QuestionOverride(
            variable="Q3",
            question_type="scale",
            label_roles={"Purple": "top"},  # incomplete: Green unassigned
            resolved_at=now,
            library_version="1.0.0",
        ),
        "Q7": QuestionOverride(
            variable="Q7",
            question_type="scale",
            label_roles={},  # incomplete: both unassigned
            resolved_at=now,
            library_version="1.0.0",
        ),
    }
    with pytest.raises(UnresolvedQuestionsError) as exc_info:
        validate_all_questions(raw_questions, overrides=overrides)
    assert len(exc_info.value.detail_entries) == 2
    assert {e.variable for e in exc_info.value.detail_entries} == {"Q3", "Q7"}


def test_no_unresolved_questions_loads_cleanly():
    raw_questions = [("Q1", "Agreement?", [(1, "Agree"), (2, "Disagree")])]
    validate_all_questions(raw_questions, overrides={})  # must not raise


def test_partial_match_reason_names_family_and_failed_labels():
    """A question one label short of a known family must read differently
    from a genuine no-match — the analyst needs to know it's probably a
    scale, and which specific label broke it."""
    raw_questions = [("Q5", "How much?", [(1, "Agree"), (2, "Banana"), (3, "Disagree")])]
    with pytest.raises(UnresolvedQuestionsError) as exc_info:
        validate_all_questions(raw_questions, overrides={})
    entry = exc_info.value.detail_entries[0]
    assert "agreement" in entry.reason.lower()
    assert "Banana" in entry.reason


def test_no_match_reason_says_nothing_matched_plainly():
    """A genuinely non-scale list must not be described in scale-family
    terms — the analyst needs a plainly different message from a partial
    match."""
    raw_questions = [("Q6", "Which city?", [(1, "Singapore"), (2, "Tokyo"), (3, "Manila")])]
    with pytest.raises(UnresolvedQuestionsError) as exc_info:
        validate_all_questions(raw_questions, overrides={})
    entry = exc_info.value.detail_entries[0]
    assert "none" in entry.reason.lower()
    assert "match" in entry.reason.lower()
