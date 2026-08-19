from __future__ import annotations

from enum import Enum

from surveytool.charts.errors import ErrorCode, SurveyToolError


class ColumnClassification(str, Enum):
    QUESTION = "question"
    DEMOGRAPHIC = "demographic"
    METADATA = "metadata"
    QUALITY = "quality"
    OPEN_END = "open_end"
    UNCLASSIFIED = "unclassified"


class UnclassifiedColumnError(SurveyToolError):
    """Raised when a column matches none of the classification rules.

    Never silently skipped — an unclassified column halts the run with a
    plain-English explanation naming the column.
    """

    def __init__(self, column: str, header_text: str) -> None:
        self.column = column
        self.header_text = header_text
        detail = f"Column {column!r} (header: {header_text!r}) did not match any classification rule."
        super().__init__(
            ErrorCode.UNCLASSIFIED_COLUMN,
            f"This file has a column this tool doesn't know how to classify: {column!r}.",
            detail=detail,
            next_action="Check the vendor setting, or report this column so it can be added to the vendor profile.",
        )
