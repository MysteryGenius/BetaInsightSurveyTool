from __future__ import annotations

from typing import Callable

from surveytool.core.column_classification import ColumnClassification, UnclassifiedColumnError


def classify_columns(
    header: list[str],
    *,
    reserved_metadata_columns: frozenset[str],
    quality_columns: frozenset[str],
    demographic_predicate: Callable[[str], bool],
    open_end_predicate: Callable[[str], bool],
    question_predicate: Callable[[str], bool] | None = None,
) -> dict[str, ColumnClassification]:
    """Classify every column in precedence order: reserved metadata, quality,
    open-end, demographic, question, then unclassified as the fallback.

    ``question_predicate`` decides QUESTION membership. When omitted
    (``None``), every column that clears the earlier rules is classified
    QUESTION by default — this is the convenience default most callers
    want (see test_status_classifies_as_metadata_rakuten and
    test_flag_classifies_as_quality_rakuten, both of which have a "Q1"
    column in their header and omit question_predicate, relying on this
    default so "Q1" classifies QUESTION rather than raising). Pass an
    explicit predicate when the caller wants a real positive check for
    QUESTION membership, with anything failing that check raising
    UnclassifiedColumnError instead of silently falling through (see
    test_question_is_fallback_before_unclassified and
    test_unknown_column_raises, both of which pass a predicate — the
    former to prove a matching column still classifies QUESTION, the
    latter to prove a non-matching column raises).

    Raises UnclassifiedColumnError, naming the column, for anything matching
    none of the rules. Never silently skips.
    """
    result: dict[str, ColumnClassification] = {}
    for column in header:
        if column is None:
            continue
        if column in reserved_metadata_columns:
            result[column] = ColumnClassification.METADATA
        elif column in quality_columns:
            result[column] = ColumnClassification.QUALITY
        elif open_end_predicate(column):
            result[column] = ColumnClassification.OPEN_END
        elif demographic_predicate(column):
            result[column] = ColumnClassification.DEMOGRAPHIC
        elif question_predicate is None or question_predicate(column):
            result[column] = ColumnClassification.QUESTION
        else:
            raise UnclassifiedColumnError(column=column, header_text=column)
    return result
