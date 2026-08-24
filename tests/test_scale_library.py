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


def test_classify_no_match_returns_none_not_categorical():
    """Task 5 deleted classify_question_type's categorical fallback: a
    label set matching no family no longer silently demotes to
    CATEGORICAL here — it returns None, and it's the caller's (the vendor
    adapter's) job to collect it as an unresolved question for the
    resolver rather than infer categorical from a failed match. Categorical
    is only ever produced now as the outcome of a stored override."""
    result = classify_question_type(["North", "South", "East", "West"])
    assert result is None


def test_classify_partial_match_returns_none_not_error_not_categorical():
    """A question where some labels match a family and others don't must
    return None (collected by the caller), not raise and not silently
    demote to CATEGORICAL — this is the exact behaviour Task 5 changes
    from both the old any_label_matches_family gate (which raised) and the
    old classify_question_type fallback (which silently demoted)."""
    result = classify_question_type(["agree", "banana", "disagree"])
    assert result is None


from surveytool.core.scale_library import identify_family


def test_en_dash_age_range_matches_ascii_hyphen_pattern():
    """This test needs a library pattern containing a hyphen to prove the
    fold — none of the existing families have one, so this test adds a
    throwaway direct check against fold_label + a literal comparison rather
    than routing through identify_family (which needs a full family match).
    """
    from surveytool.core.hygiene import fold_label
    assert fold_label("18–24") == fold_label("18-24") == "18-24"


def test_binary_family_added_to_scales_yaml():
    qtype, roles, family = classify_question_type(["yes", "no"])
    assert qtype is QuestionType.binary


def test_calendar_frequency_family():
    family = identify_family(["daily", "weekly", "monthly", "rarely", "never"])
    assert family == "calendar_frequency"


def test_intensity_family():
    family = identify_family(["a lot", "somewhat", "not at all"])
    assert family == "intensity"


def test_partial_intensity_match_returns_none_not_categorical():
    """Task 5: a partial intensity match is no longer silently demoted to
    categorical by classify_question_type — it returns None so the caller
    collects it as unresolved."""
    result = classify_question_type(["a lot", "somewhat", "purple"])
    assert result is None
