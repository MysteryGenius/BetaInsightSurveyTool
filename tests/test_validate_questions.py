# tests/test_validate_questions.py
"""
Single-pass validation batches every unresolved question's override failure
into one UnresolvedQuestionsError, rather than raising on the first bad
override. See Task 15 for the override schema this validates against.
"""
from datetime import datetime, timezone

import pytest

from surveytool.charts.errors import UnresolvedQuestionsError
from surveytool.ingest.validate_questions import validate_all_questions


def test_three_unresolved_questions_produce_one_error_with_three_entries():
    raw_questions = [
        ("Q3", "How often?", [(1, "Purple"), (2, "Green")]),
        ("Q7", "How able?", [(1, "Kinda"), (2, "Sorta")]),
        ("Q9", "How much?", [(1, "Bunches"), (2, "Loads")]),
    ]
    # No overrides supplied — each falls to CATEGORICAL cleanly under
    # classify_question_type, so with no override requirement in force,
    # zero of these are "unresolved" in the override sense.
    validate_all_questions(raw_questions, overrides={})  # must not raise


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
