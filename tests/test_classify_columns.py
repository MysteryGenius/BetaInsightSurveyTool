import re

import pytest

from surveytool.core.column_classification import ColumnClassification, UnclassifiedColumnError
from surveytool.core.demographics import text_matches_demographic
from surveytool.ingest.classify_columns import classify_columns
from surveytool.ingest.vendor_profile import MILIEU_PROFILE, RAKUTEN_PROFILE, TOLUNA_PROFILE

_OE_SUFFIX_RE = re.compile(r"oe$")


def _no_open_end(_header: str) -> bool:
    return False


def _rakuten_demographic(qid: str) -> bool:
    return qid.startswith("S")


def test_status_classifies_as_metadata_rakuten():
    profile_with_status = RAKUTEN_PROFILE
    header = ["record", "uuid", "status", "S1", "Q1", "uid"]
    result = classify_columns(
        header,
        reserved_metadata_columns=profile_with_status.reserved_metadata_columns | {"status"},
        quality_columns=profile_with_status.quality_columns,
        demographic_predicate=_rakuten_demographic,
        open_end_predicate=_no_open_end,
    )
    assert result["status"] == ColumnClassification.METADATA


def test_flag_classifies_as_quality_rakuten():
    header = ["record", "uuid", "FLAG", "S1", "Q1", "uid"]
    result = classify_columns(
        header,
        reserved_metadata_columns=RAKUTEN_PROFILE.reserved_metadata_columns,
        quality_columns=RAKUTEN_PROFILE.quality_columns,
        demographic_predicate=_rakuten_demographic,
        open_end_predicate=_no_open_end,
    )
    assert result["FLAG"] == ColumnClassification.QUALITY


def test_q8r8oe_classifies_as_open_end():
    header = ["record", "uuid", "Q8r8oe", "uid"]
    result = classify_columns(
        header,
        reserved_metadata_columns=RAKUTEN_PROFILE.reserved_metadata_columns,
        quality_columns=RAKUTEN_PROFILE.quality_columns,
        demographic_predicate=_rakuten_demographic,
        open_end_predicate=lambda h: bool(_OE_SUFFIX_RE.search(h)),
    )
    assert result["Q8r8oe"] == ColumnClassification.OPEN_END


def test_unknown_column_raises():
    """With an explicit question_predicate that only matches real
    question-shaped columns (Q<number>...), a column matching nothing —
    not reserved, not quality, not open-end, not demographic, not
    question-shaped — raises. (Tests that omit question_predicate rely on
    its "match everything not otherwise classified" default and so cannot
    exercise this path; this test supplies a real predicate specifically to
    exercise it.)"""
    header = ["record", "uuid", "TotallyUnknownColumn"]
    with pytest.raises(UnclassifiedColumnError) as exc_info:
        classify_columns(
            header,
            reserved_metadata_columns=RAKUTEN_PROFILE.reserved_metadata_columns,
            quality_columns=RAKUTEN_PROFILE.quality_columns,
            demographic_predicate=lambda h: False,
            open_end_predicate=_no_open_end,
            question_predicate=lambda h: h.startswith("Q"),
        )
    assert exc_info.value.column == "TotallyUnknownColumn"


def test_precedence_reserved_beats_quality():
    """A column present in both reserved_metadata_columns and quality_columns
    (pathological, but precedence must be deterministic) classifies as
    METADATA, since reserved metadata is checked first."""
    header = ["dual"]
    result = classify_columns(
        header,
        reserved_metadata_columns=frozenset({"dual"}),
        quality_columns=frozenset({"dual"}),
        demographic_predicate=lambda h: False,
        open_end_predicate=_no_open_end,
    )
    assert result["dual"] == ColumnClassification.METADATA


def test_question_is_fallback_before_unclassified():
    header = ["Q1"]
    result = classify_columns(
        header,
        reserved_metadata_columns=frozenset(),
        quality_columns=frozenset(),
        demographic_predicate=lambda h: False,
        open_end_predicate=_no_open_end,
        question_predicate=lambda h: h == "Q1",
    )
    assert result["Q1"] == ColumnClassification.QUESTION
