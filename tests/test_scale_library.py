# tests/test_scale_library.py
from surveytool.core.model import CodeRole, QuestionType
from surveytool.core.scale_library import classify_question_type


def test_classify_full_scale_match_returns_scale():
    qtype, roles, family = classify_question_type(["strongly agree", "agree", "disagree", "strongly disagree"])
    assert qtype is QuestionType.scale
    assert family == "agreement"
    assert roles["strongly agree"] is CodeRole.top


def test_classify_binary_match_returns_binary_no_roles():
    qtype, roles, family = classify_question_type(["yes", "no"])
    assert qtype is QuestionType.binary
    assert roles is None
    assert family is None


def test_classify_no_match_falls_through_to_categorical():
    qtype, roles, family = classify_question_type(["North", "South", "East", "West"])
    assert qtype is QuestionType.categorical
    assert roles is None
    assert family is None


def test_classify_partial_match_falls_through_to_categorical_not_error():
    """A question where some labels match a family and others don't must
    demote cleanly to CATEGORICAL, not raise — this is the exact behaviour
    change from the old any_label_matches_family gate."""
    qtype, roles, family = classify_question_type(["agree", "banana", "disagree"])
    assert qtype is QuestionType.categorical
    assert roles is None
    assert family is None
