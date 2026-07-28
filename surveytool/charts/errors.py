from __future__ import annotations

from enum import Enum


class ErrorCode(str, Enum):
    """Stable, machine-readable error codes. The GUI switches on these, never on message text."""

    VENDOR_MISMATCH = "VENDOR_MISMATCH"
    FILE_UNREADABLE = "FILE_UNREADABLE"
    MISSING_SHEET = "MISSING_SHEET"
    MISSING_COLUMNS = "MISSING_COLUMNS"
    UNRESOLVED_SCALE_LABELS = "UNRESOLVED_SCALE_LABELS"
    NO_QUESTIONS_FOUND = "NO_QUESTIONS_FOUND"
    DEMOGRAPHIC_NOT_FOUND = "DEMOGRAPHIC_NOT_FOUND"
    CONFIG_INVALID = "CONFIG_INVALID"
    NO_SESSION = "NO_SESSION"
    INTERNAL = "INTERNAL"


# Codes that are the user's fault (bad input, missing selection) get a 400.
# NO_SESSION is a normal sequencing state (upload not done yet), not a data
# failure, so it gets its own status. INTERNAL is the only 500.
_STATUS_BY_CODE: dict[ErrorCode, int] = {
    ErrorCode.VENDOR_MISMATCH: 400,
    ErrorCode.FILE_UNREADABLE: 400,
    ErrorCode.MISSING_SHEET: 400,
    ErrorCode.MISSING_COLUMNS: 400,
    ErrorCode.UNRESOLVED_SCALE_LABELS: 400,
    ErrorCode.NO_QUESTIONS_FOUND: 400,
    ErrorCode.DEMOGRAPHIC_NOT_FOUND: 400,
    ErrorCode.CONFIG_INVALID: 400,
    ErrorCode.NO_SESSION: 404,
    ErrorCode.INTERNAL: 500,
}


class SurveyToolError(Exception):
    """Base error for every user-facing failure the core can produce.

    Carries a stable code, a plain-English message, an optional detail line,
    and an optional next action. The GUI renders these fields and must never
    inspect message text to decide what a failure means.
    """

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        detail: str | None = None,
        next_action: str | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.detail = detail
        self.next_action = next_action
        super().__init__(detail if detail is not None else message)

    @property
    def status_code(self) -> int:
        return _STATUS_BY_CODE[self.code]

    def to_response(self) -> dict:
        body: dict = {"code": self.code.value, "message": self.message}
        if self.detail is not None:
            body["detail"] = self.detail
        if self.next_action is not None:
            body["next_action"] = self.next_action
        return {"error": body}


class NoSessionError(SurveyToolError):
    """Raised when an endpoint is called before a file has been uploaded for this session.

    A normal sequencing state, not a data failure — the analyst just hasn't
    uploaded a file yet in this session.
    """

    def __init__(self) -> None:
        super().__init__(
            ErrorCode.NO_SESSION,
            "No file has been uploaded yet.",
            next_action="Upload a survey file to start a session.",
        )


class WarningCode(str, Enum):
    """Stable codes for non-fatal, informational conditions surfaced alongside a success response."""

    STRAIGHTLINERS_EXCLUDED = "STRAIGHTLINERS_EXCLUDED"


class MissingFindingsRow(SurveyToolError):
    """Raised when a required row is absent from the findings sheet.

    Never substitute a zero or default — the chart must fail loudly so the
    caller knows the findings sheet is incomplete for this question/breakdown.
    This is a data-integrity bug in the render path, not a user-triggerable
    condition, so it always maps to INTERNAL.
    """

    def __init__(self, qid: str, breakdown_variable: str, breakdown_level: str, metric: str) -> None:
        self.qid = qid
        self.breakdown_variable = breakdown_variable
        self.breakdown_level = breakdown_level
        self.metric = metric
        detail = (
            f"Missing findings row: qid={qid!r} breakdown_variable={breakdown_variable!r} "
            f"breakdown_level={breakdown_level!r} metric={metric!r}"
        )
        super().__init__(
            ErrorCode.INTERNAL,
            "Something failed while building charts for this file.",
            detail=detail,
        )


class UnresolvedScaleLabelsError(SurveyToolError, ValueError):
    """Raised when one or more response labels can't be matched to a known scale family.

    Subclasses ValueError so existing ``pytest.raises(ValueError)`` call sites
    against ``resolve_roles`` keep passing. Must fail loudly, never demote to
    a lower-fidelity question type.
    """

    def __init__(self, unresolved: list[str]) -> None:
        self.unresolved = unresolved
        detail = f"Scale library could not resolve label(s): {unresolved}. Add an override or extend scales.yaml."
        super().__init__(
            ErrorCode.UNRESOLVED_SCALE_LABELS,
            "This file has response labels this tool doesn't recognise.",
            detail=detail,
            next_action="Add the missing labels to the scale library, or check the vendor setting.",
        )
