from __future__ import annotations

from surveytool.charts.errors import ErrorCode, SurveyToolError
from surveytool.core.model import Question, QuestionType


class NettingNotAllowedError(SurveyToolError):
    """Raised when top-box, top-two-box, or bottom-box is requested on a
    question that isn't an ordered scale. Netting requires role-ordered
    labels; binary and categorical questions have no such ordering."""

    def __init__(self, qid: str, net_kind: str) -> None:
        self.qid = qid
        self.net_kind = net_kind
        detail = f"Question {qid!r} is not a scale, so {net_kind} cannot be computed for it."
        super().__init__(
            ErrorCode.NETTING_NOT_ALLOWED,
            f"'{qid}' isn't an ordered scale, so netting isn't available for it.",
            detail=detail,
            next_action="Netting requires an ordered scale. Choose a scale question, or view this question's plain frequency instead.",
        )


def require_scale_for_netting(question: Question, net_kind: str) -> None:
    """Raise NettingNotAllowedError if question.qtype is not scale.

    Call before computing top-box, top-two-box, or bottom-box for any
    question. Never returns a silently unnetted or zero figure instead.
    """
    if question.qtype is not QuestionType.scale:
        raise NettingNotAllowedError(question.qid, net_kind)
