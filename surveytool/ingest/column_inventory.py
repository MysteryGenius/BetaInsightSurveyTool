from __future__ import annotations

from surveytool.core.column_classification import ColumnClassification
from surveytool.core.model import QuestionType, Survey
from surveytool.ingest.vendor_profile import VendorProfile

_OPEN_END_QTYPES = {QuestionType.numeric_open, QuestionType.text_open}


def build_column_classifications(
    header: list[str],
    qid_by_column: dict[str, str],
    survey: Survey,
    profile: VendorProfile,
) -> dict[str, ColumnClassification]:
    """Classify every raw column in `header` for the run summary's column
    inventory table.

    Reuses each adapter's own classification decisions (Survey.questions'
    qtype/is_demographic) rather than re-deriving demographic/open-end rules
    from column names — the adapters already parsed this correctly during
    load(), so this only maps their output onto the ColumnClassification
    taxonomy for display. `qid_by_column` bridges the raw column name to the
    qid the adapter assigned it, since a grid question's qid (e.g. Toluna's
    "7_local_mainstream_media") is a synthesized slug, not the literal
    column text. Reserved metadata and quality columns come straight from
    the vendor profile, matching classify_columns's own precedence
    (metadata and quality checked first). Any header column with no
    matching Question and no metadata/quality membership is UNCLASSIFIED
    rather than silently dropped — the run summary must account for every
    column exactly once.
    """
    questions_by_qid = {q.qid: q for q in survey.questions}
    result: dict[str, ColumnClassification] = {}

    for column in header:
        if column is None:
            continue
        if column in profile.reserved_metadata_columns:
            result[column] = ColumnClassification.METADATA
        elif column in profile.quality_columns:
            result[column] = ColumnClassification.QUALITY
        else:
            qid = qid_by_column.get(column)
            question = questions_by_qid.get(qid) if qid is not None else None
            if question is None:
                result[column] = ColumnClassification.UNCLASSIFIED
            elif question.qtype in _OPEN_END_QTYPES:
                result[column] = ColumnClassification.OPEN_END
            elif question.qtype is QuestionType.demographic or question.is_demographic:
                result[column] = ColumnClassification.DEMOGRAPHIC
            else:
                result[column] = ColumnClassification.QUESTION

    return result
