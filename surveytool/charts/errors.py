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
    DIMENSION_NOT_IN_CANONICAL = "DIMENSION_NOT_IN_CANONICAL"
    CANONICAL_CATEGORY_UNREACHABLE = "CANONICAL_CATEGORY_UNREACHABLE"
    UNMAPPED_SOURCE_VALUE = "UNMAPPED_SOURCE_VALUE"
    DEMOGRAPHIC_NOT_IN_REGISTRY = "DEMOGRAPHIC_NOT_IN_REGISTRY"
    DUPLICATE_BREAK_DIMENSION = "DUPLICATE_BREAK_DIMENSION"
    DIMENSION_IN_BREAK_AND_FILTER = "DIMENSION_IN_BREAK_AND_FILTER"
    MULTISELECT_BREAK_REJECTED = "MULTISELECT_BREAK_REJECTED"
    FILTER_ZERO_MATCH = "FILTER_ZERO_MATCH"


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
    ErrorCode.DIMENSION_NOT_IN_CANONICAL: 400,
    ErrorCode.CANONICAL_CATEGORY_UNREACHABLE: 400,
    ErrorCode.UNMAPPED_SOURCE_VALUE: 400,
    ErrorCode.DEMOGRAPHIC_NOT_IN_REGISTRY: 400,
    ErrorCode.DUPLICATE_BREAK_DIMENSION: 400,
    ErrorCode.DIMENSION_IN_BREAK_AND_FILTER: 400,
    ErrorCode.MULTISELECT_BREAK_REJECTED: 400,
    ErrorCode.FILTER_ZERO_MATCH: 400,
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


class DimensionNotInCanonicalError(SurveyToolError):
    """Raised when a vendor mapping declares a dimension not present in the canonical registry.

    A registry-loading failure (YAML authoring bug), distinct from and prior
    to the request-time DEMOGRAPHIC_NOT_IN_REGISTRY check on a break/filter
    spec. Fails loudly rather than silently ignoring the extra dimension.
    """

    def __init__(self, vendor: str, dimension: str) -> None:
        self.vendor = vendor
        self.dimension = dimension
        detail = (
            f"Vendor mapping {vendor!r} declares dimension {dimension!r}, "
            f"which is not present in the canonical demographic registry."
        )
        super().__init__(
            ErrorCode.DIMENSION_NOT_IN_CANONICAL,
            "A vendor demographic mapping refers to a dimension this tool doesn't recognise.",
            detail=detail,
            next_action="Add the dimension to canonical.yaml, or remove it from the vendor mapping.",
        )


class CanonicalCategoryUnreachableError(SurveyToolError):
    """Raised when a canonical category has no source value mapping to it in a
    vendor mapping that declares the dimension.

    Cheap, YAML-only check (build plan section 3, rule 1) — runs before the
    unmapped-source-value check, which needs loaded response data.
    """

    def __init__(self, vendor: str, dimension: str, category: str) -> None:
        self.vendor = vendor
        self.dimension = dimension
        self.category = category
        detail = (
            f"Vendor {vendor!r} mapping for dimension {dimension!r} has no source value "
            f"mapping to canonical category {category!r}. Every canonical category must "
            f"be reachable from every vendor mapping that declares the dimension."
        )
        super().__init__(
            ErrorCode.CANONICAL_CATEGORY_UNREACHABLE,
            "A vendor demographic mapping is missing a category this tool expects.",
            detail=detail,
            next_action="Add a value_map entry in the vendor YAML that reaches this category, or remove the dimension from that vendor's mapping.",
        )


class UnmappedSourceValueError(SurveyToolError):
    """Raised when a source value present in the actual loaded response data
    for a dimension's source column has no entry in that vendor's value_map.

    Hard failure — never bucketed into "other" and never silently dropped
    (build plan section 3, rule 2).
    """

    def __init__(self, vendor: str, dimension: str, raw_value: object) -> None:
        self.vendor = vendor
        self.dimension = dimension
        self.raw_value = raw_value
        detail = (
            f"Vendor {vendor!r}, dimension {dimension!r}: source value {raw_value!r} "
            f"was found in the loaded data but has no entry in this vendor's value_map."
        )
        super().__init__(
            ErrorCode.UNMAPPED_SOURCE_VALUE,
            "This file has a demographic response value this tool doesn't recognise.",
            detail=detail,
            next_action="Add a value_map entry for this value in the vendor YAML.",
        )


class DemographicNotInRegistryError(SurveyToolError):
    """Raised when a break or filter spec names a dimension absent from the
    canonical demographic registry.

    First check in the request-validation order (build plan section 4) —
    every other check assumes the named dimensions are real.
    """

    def __init__(self, dimension: str) -> None:
        self.dimension = dimension
        detail = f"Dimension {dimension!r} is not present in the canonical demographic registry."
        super().__init__(
            ErrorCode.DEMOGRAPHIC_NOT_IN_REGISTRY,
            f"'{dimension}' isn't a demographic this tool recognises.",
            detail=detail,
            next_action="Choose a demographic from the list this tool supports.",
        )


class DuplicateBreakDimensionError(SurveyToolError):
    """Raised when the same dimension appears more than once in a break spec."""

    def __init__(self, dimension: str) -> None:
        self.dimension = dimension
        detail = f"Dimension {dimension!r} appears more than once in the break spec."
        super().__init__(
            ErrorCode.DUPLICATE_BREAK_DIMENSION,
            f"'{dimension}' is selected more than once for Break by.",
            detail=detail,
            next_action="Remove the duplicate so each demographic appears only once in Break by.",
        )


class DimensionInBreakAndFilterError(SurveyToolError):
    """Raised when a dimension appears in both the break spec and the filter spec.

    Nesting a dimension while also filtering on it is contradictory —
    filtering it fixes its value while breaking by it asks to see every value.
    """

    def __init__(self, dimension: str) -> None:
        self.dimension = dimension
        detail = f"Dimension {dimension!r} appears in both the break spec and the filter spec."
        super().__init__(
            ErrorCode.DIMENSION_IN_BREAK_AND_FILTER,
            f"'{dimension}' is used in both Break by and Filter by.",
            detail=detail,
            next_action="Use each demographic in only one of Break by or Filter by, not both.",
        )


class MultiselectBreakRejectedError(SurveyToolError):
    """Raised when a break spec includes a multi_select dimension.

    A respondent may hold more than one value for a multi-select dimension,
    so columns built from it would not sum to the sample. Message is shown
    verbatim to non-technical analysts.
    """

    def __init__(self, dimension: str, label: str) -> None:
        self.dimension = dimension
        self.label = label
        detail = (
            f"Dimension {dimension!r} ({label}) allows a respondent to hold more than one "
            f"value, so it cannot be used to build columns."
        )
        super().__init__(
            ErrorCode.MULTISELECT_BREAK_REJECTED,
            f"'{label}' can't be used to Break by, because a respondent can hold more than "
            f"one value here — the columns wouldn't add up to the total sample.",
            detail=detail,
            next_action="Use a different demographic for Break by, or move this one to Filter by instead.",
        )


class FilterZeroMatchError(SurveyToolError):
    """Raised when a filter spec, once applied, matches zero respondents."""

    def __init__(self, filter_spec: dict[str, list[str]]) -> None:
        self.filter_spec = filter_spec
        clauses = "; ".join(f"{dim}={values}" for dim, values in filter_spec.items())
        detail = f"No respondents matched this filter: {clauses}."
        super().__init__(
            ErrorCode.FILTER_ZERO_MATCH,
            "No respondents match this filter combination.",
            detail=detail,
            next_action="Remove or loosen one of the filter selections and try again.",
        )
