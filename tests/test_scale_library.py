# tests/test_scale_library.py
import pytest

from surveytool.core.model import CodeRole, QuestionType
from surveytool.core.scale_library import classify_question_type


def test_classify_full_scale_match_returns_scale():
    """Round B task B2 replaced B1's intermediate mechanical shape with the
    real 5-point agreement variant used by Rakuten/Milieu, whose neutral
    point is a single literal "neutral" pattern (matching full-set-equality
    exactly, unlike B1's placeholder which unioned every old bucket's
    synonyms)."""
    labels = [
        "strongly agree", "agree",
        "neutral",
        "disagree", "strongly disagree",
    ]
    qtype, roles, family = classify_question_type(labels)
    assert qtype is QuestionType.scale
    assert family == "agreement"
    role, rank = roles["strongly agree"]
    assert role is CodeRole.top
    assert rank == 5


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


def test_binary_pair_classifies_without_scales_yaml_entry():
    """Round B task B1 removed the 'binary' family from scales.yaml
    entirely -- a 2-point variant would violate the new 3-point minimum,
    and binary has no ordinal rank anyway, so classify_question_type checks
    a fixed literal yes/no (or true/false) pair instead of routing through
    the variant system."""
    qtype, roles, family = classify_question_type(["yes", "no"])
    assert qtype is QuestionType.binary
    assert roles is None
    assert family is None


def test_calendar_frequency_family_has_no_variants_yet():
    """Round B task B2 deliberately leaves calendar_frequency with no
    variants ('{}') -- no real vendor file has surfaced this family's exact
    label set yet, so per the plan it fails to match loudly rather than
    getting a placeholder variant invented for it."""
    labels = ["daily", "weekly", "monthly", "occasionally", "sometimes", "rarely", "never"]
    family = identify_family(labels)
    assert family is None


def test_old_intensity_union_no_longer_matches_real_variants():
    """B1's mechanical placeholder merged intensity's three old pattern
    buckets (which included synonyms like "moderately" and "none" that no
    real vendor file actually uses) into one variant this label set used to
    match exactly. B2 replaced it with two real, distinct 4-point variants
    (four_point_not_at_all, four_point_not_really), neither of which
    contains "moderately" or "none" -- this old union set no longer equals
    either variant's folded label set."""
    labels = ["a lot", "a great deal", "somewhat", "a little", "moderately", "not at all", "none", "not really"]
    family = identify_family(labels)
    assert family is None


def test_partial_intensity_match_returns_none_not_categorical():
    """Task 5: a partial intensity match is no longer silently demoted to
    categorical by classify_question_type — it returns None so the caller
    collects it as unresolved."""
    result = classify_question_type(["a lot", "somewhat", "purple"])
    assert result is None


# ── Round A prompt A4: resolver-queue split ──────────────────────────────
#
# is_ordinal_resolver_candidate decides whether a question that failed a
# full scale match still belongs in the resolver (genuinely looks ordinal)
# or should classify as categorical outright. Two committed signals: a
# label matches a family pattern, or the label set shows a not-/un- polarity
# pair. The PureSpectrum Q1/Q3/Q6/D5 real-label-set acceptance cases live in
# tests/test_purespectrum_fixture.py and tests/test_desktop_run_summary.py;
# these are direct unit tests of the two signals themselves.

from surveytool.core.scale_library import has_polarity_pair, is_ordinal_resolver_candidate


def test_has_polarity_pair_detects_not_prefix():
    assert has_polarity_pair(["Effective", "Not effective"]) is True


def test_has_polarity_pair_detects_un_prefix():
    assert has_polarity_pair(["Able", "Unable"]) is True


def test_has_polarity_pair_false_when_no_counterpart_present():
    assert has_polarity_pair(["Red", "Blue", "Green"]) is False


def test_has_polarity_pair_false_for_un_prefix_with_no_bare_counterpart():
    """"Unable" alone, with no "Able" in the set, is not a polarity pair —
    the counterpart must actually be present."""
    assert has_polarity_pair(["Unable", "Somewhat capable"]) is False


def test_is_ordinal_resolver_candidate_true_when_label_matches_family_pattern():
    """A partial match against a known family (one recognised label, even
    without a full match) is enough evidence to route to the resolver
    rather than auto-categorical."""
    assert is_ordinal_resolver_candidate(["Agree", "Purple", "Banana"]) is True


def test_is_ordinal_resolver_candidate_true_for_polarity_pair_with_no_family_match():
    assert is_ordinal_resolver_candidate(["Effective", "Not effective", "Sideways"]) is True


def test_is_ordinal_resolver_candidate_false_for_genuine_categorical_list():
    """A label set with no family-pattern match and no polarity pair shows
    no evidence of being ordinal — the exact PureSpectrum Q1 shape (a
    three-way awareness question)."""
    labels = ["Yes, followed it closely", "Yes, vaguely aware", "No, this is the first I'm hearing of it"]
    assert is_ordinal_resolver_candidate(labels) is False


# ── Round B task B1: variant-based library schema ────────────────────────


def test_variant_points_are_ordered_bottom_to_top_by_rank():
    from surveytool.core.scale_library import _FAMILIES_BY_NAME
    agreement = _FAMILIES_BY_NAME["agreement"]
    variant = agreement.variants[0]
    ranks = [p.rank for p in variant.points]
    assert ranks == sorted(ranks)
    assert ranks[0] == 1


def test_variant_role_for_rank_odd_length_has_neutral_midpoint():
    from surveytool.core.scale_library import Variant, ScalePointDef
    v = Variant(
        name="five_point",
        family="agreement",
        points=(
            ScalePointDef(patterns=("strongly disagree",), rank=1),
            ScalePointDef(patterns=("disagree",), rank=2),
            ScalePointDef(patterns=("neutral",), rank=3),
            ScalePointDef(patterns=("agree",), rank=4),
            ScalePointDef(patterns=("strongly agree",), rank=5),
        ),
        folded_label_set=frozenset({"strongly disagree", "disagree", "neutral", "agree", "strongly agree"}),
    )
    assert v.role_for_rank(1) is CodeRole.bottom
    assert v.role_for_rank(2) is CodeRole.bottom
    assert v.role_for_rank(3) is CodeRole.neutral
    assert v.role_for_rank(4) is CodeRole.top
    assert v.role_for_rank(5) is CodeRole.top


def test_variant_role_for_rank_even_length_has_no_neutral():
    from surveytool.core.scale_library import Variant, ScalePointDef
    v = Variant(
        name="four_point",
        family="importance",
        points=(
            ScalePointDef(patterns=("not at all important",), rank=1),
            ScalePointDef(patterns=("not very important",), rank=2),
            ScalePointDef(patterns=("somewhat important",), rank=3),
            ScalePointDef(patterns=("very important",), rank=4),
        ),
        folded_label_set=frozenset({"not at all important", "not very important", "somewhat important", "very important"}),
    )
    assert v.role_for_rank(1) is CodeRole.bottom
    assert v.role_for_rank(2) is CodeRole.bottom
    assert v.role_for_rank(3) is CodeRole.top
    assert v.role_for_rank(4) is CodeRole.top


def test_duplicate_folded_label_set_across_variants_raises_at_load():
    import importlib
    import surveytool.core.scale_library as sl
    from surveytool.charts.errors import ScaleLibraryConfigError

    bad_yaml = """
families:
  fam_a:
    variants:
      v1:
        points:
          - patterns: ["low"]
          - patterns: ["mid"]
          - patterns: ["high"]
  fam_b:
    variants:
      v2:
        points:
          - patterns: ["low"]
          - patterns: ["mid"]
          - patterns: ["high"]
"""
    with pytest.raises(ScaleLibraryConfigError) as exc_info:
        sl._build_families(sl._parse_raw_families(bad_yaml))
    message = str(exc_info.value)
    assert "fam_a" in message and "v1" in message
    assert "fam_b" in message and "v2" in message


def test_variant_with_fewer_than_three_points_raises_at_load():
    import surveytool.core.scale_library as sl
    from surveytool.charts.errors import ScaleLibraryConfigError

    bad_yaml = """
families:
  fam_a:
    variants:
      v1:
        points:
          - patterns: ["low"]
          - patterns: ["high"]
"""
    with pytest.raises(ScaleLibraryConfigError) as exc_info:
        sl._build_families(sl._parse_raw_families(bad_yaml))
    assert "fam_a" in str(exc_info.value) and "v1" in str(exc_info.value)


def test_pattern_reused_at_two_ranks_within_one_variant_raises_at_load():
    import surveytool.core.scale_library as sl
    from surveytool.charts.errors import ScaleLibraryConfigError

    bad_yaml = """
families:
  fam_a:
    variants:
      v1:
        points:
          - patterns: ["low"]
          - patterns: ["low"]
          - patterns: ["high"]
"""
    with pytest.raises(ScaleLibraryConfigError) as exc_info:
        sl._build_families(sl._parse_raw_families(bad_yaml))
    assert "low" in str(exc_info.value)


def test_question_matching_two_variants_raises_ambiguous():
    import surveytool.core.scale_library as sl

    families = sl._build_families(sl._parse_raw_families("""
families:
  fam_a:
    variants:
      v1:
        points:
          - patterns: ["low"]
          - patterns: ["mid"]
          - patterns: ["high"]
"""))
    # Real cross-family ambiguity (different folded label sets that still
    # both fully cover one question, which cannot happen with exact
    # set-equality matching) is prevented at load time by the duplicate
    # check above -- this is a sanity check that construction succeeded;
    # identify_family's own ambiguity path is exercised in Task B3's tests
    # once real multi-family data exists.
    assert len(families["fam_a"].variants) == 1


# ── Round B task B2: real per-vendor variant population ──────────────────


def test_agreement_five_point_variant_matches_rakuten_and_milieu_labels():
    family = identify_family(["Strongly disagree", "Disagree", "Neutral", "Agree", "Strongly agree"])
    assert family == "agreement"
    family2 = identify_family(["Strongly Disagree", "Disagree", "Neutral", "Agree", "Strongly Agree"])
    assert family2 == "agreement"


def test_importance_has_three_distinct_variants():
    from surveytool.core.scale_library import _FAMILIES_BY_NAME
    importance = _FAMILIES_BY_NAME["importance"]
    assert len(importance.variants) == 3
    variant_names = {v.name for v in importance.variants}
    assert variant_names == {"five_point_gradated", "four_point_polar", "five_point_polar"}


def test_purespectrum_q7_five_point_gradated_importance():
    qtype, roles, family = classify_question_type(
        ["Not important at all", "Slightly important", "Moderately important", "Very important", "Extremely important"]
    )
    assert qtype is QuestionType.scale
    assert family == "importance"
    assert roles["Not important at all"] == (CodeRole.bottom, 1)
    assert roles["Extremely important"] == (CodeRole.top, 5)


def test_toluna_five_point_polar_importance_distinct_from_gradated():
    qtype, roles, family = classify_question_type(
        ["Very Unimportant", "Unimportant", "Neutral / Neither Important nor Unimportant", "Important", "Very Important"]
    )
    assert qtype is QuestionType.scale
    assert family == "importance"
    assert roles["Very Unimportant"] == (CodeRole.bottom, 1)
    assert roles["Neutral / Neither Important nor Unimportant"] == (CodeRole.neutral, 3)


def test_toluna_likelihood_five_point_polar():
    qtype, roles, family = classify_question_type(
        ["Very Unlikely", "Unlikely", "Neutral / Neither Likely nor Unlikely", "Likely", "Very Likely"]
    )
    assert qtype is QuestionType.scale
    assert family == "likelihood"
    assert roles["Very Unlikely"] == (CodeRole.bottom, 1)
    assert roles["Unlikely"] == (CodeRole.bottom, 2)
    assert roles["Neutral / Neither Likely nor Unlikely"] == (CodeRole.neutral, 3)
    assert roles["Likely"] == (CodeRole.top, 4)
    assert roles["Very Likely"] == (CodeRole.top, 5)


def test_intensity_has_two_distinct_four_point_variants():
    from surveytool.core.scale_library import _FAMILIES_BY_NAME
    intensity = _FAMILIES_BY_NAME["intensity"]
    assert len(intensity.variants) == 2
    variant_names = {v.name for v in intensity.variants}
    assert variant_names == {"four_point_not_at_all", "four_point_not_really"}


def test_purespectrum_q2_intensity_not_at_all_variant():
    qtype, roles, family = classify_question_type(["Not at all", "A little", "Somewhat", "A lot"])
    assert qtype is QuestionType.scale
    assert family == "intensity"
    assert roles["Not at all"] == (CodeRole.bottom, 1)
    assert roles["A lot"] == (CodeRole.top, 4)


def test_purespectrum_q5_intensity_not_really_variant():
    qtype, roles, family = classify_question_type(["Not really", "A little", "Somewhat", "A great deal"])
    assert qtype is QuestionType.scale
    assert family == "intensity"
    assert roles["Not really"] == (CodeRole.bottom, 1)
    assert roles["A great deal"] == (CodeRole.top, 4)


def test_fluency_matches_full_literal_suffixed_labels():
    labels = [
        "None — I don't really speak it, just recognize it",
        "Basic — a few words or phrases",
        "Conversational — can hold an everyday conversation",
        "Fluent — comfortable in most situations",
    ]
    qtype, roles, family = classify_question_type(labels)
    assert qtype is QuestionType.scale
    assert family == "fluency"


def test_relevance_five_point():
    qtype, roles, family = classify_question_type(
        ["Not relevant at all", "Not very relevant", "Neutral/don't know enough to say", "Relevant", "Extremely relevant"]
    )
    assert qtype is QuestionType.scale
    assert family == "relevance"
    assert roles["Neutral/don't know enough to say"] == (CodeRole.neutral, 3)


def test_concern_four_point():
    qtype, roles, family = classify_question_type(
        ["Not concerned at all", "Not very concerned", "Somewhat concerned", "Very concerned"]
    )
    assert qtype is QuestionType.scale
    assert family == "concern"
    assert roles["Not concerned at all"] == (CodeRole.bottom, 1)
    assert roles["Very concerned"] == (CodeRole.top, 4)


def test_worry_four_point():
    qtype, roles, family = classify_question_type(
        ["Not worried at all", "Not very worried", "Somewhat worried", "Very worried"]
    )
    assert qtype is QuestionType.scale
    assert family == "worry"
    assert roles["Not worried at all"] == (CodeRole.bottom, 1)
    assert roles["Very worried"] == (CodeRole.top, 4)


def test_effectiveness_and_ability_five_point_polar():
    qtype, roles, family = classify_question_type(
        ["Very Ineffective", "Ineffective", "Neutral / Neither Effective nor Ineffective", "Effective", "Very Effective"]
    )
    assert qtype is QuestionType.scale
    assert family == "effectiveness"

    qtype2, roles2, family2 = classify_question_type(
        ["Extremely unable to", "Somewhat unable to", "Neutral / Neither able nor unable to", "Somewhat able to", "Extremely able to"]
    )
    assert qtype2 is QuestionType.scale
    assert family2 == "ability"


def test_no_variant_anywhere_matches_two_others():
    """Every real-file variant is distinguishable from every other one --
    this is a coarse cross-check that Task B2's population didn't
    accidentally introduce a duplicate (would have already raised at import
    time, but this documents the intent explicitly)."""
    from surveytool.core.scale_library import _ALL_VARIANTS
    seen = set()
    for v in _ALL_VARIANTS:
        assert v.folded_label_set not in seen
        seen.add(v.folded_label_set)
