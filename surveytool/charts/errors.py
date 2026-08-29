from __future__ import annotations

from dataclasses import dataclass
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
    UNCLASSIFIED_COLUMN = "UNCLASSIFIED_COLUMN"
    NETTING_NOT_ALLOWED = "NETTING_NOT_ALLOWED"
    DUPLICATE_CODE_KEY = "DUPLICATE_CODE_KEY"
    SCALE_LIBRARY_CONFIG_INVALID = "SCALE_LIBRARY_CONFIG_INVALID"
    AMBIGUOUS_SCALE_MATCH = "AMBIGUOUS_SCALE_MATCH"
    PALETTE_EXHAUSTED = "PALETTE_EXHAUSTED"


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
    ErrorCode.UNCLASSIFIED_COLUMN: 400,
    ErrorCode.NETTING_NOT_ALLOWED: 400,
    ErrorCode.DUPLICATE_CODE_KEY: 400,
    ErrorCode.SCALE_LIBRARY_CONFIG_INVALID: 500,
    ErrorCode.AMBIGUOUS_SCALE_MATCH: 400,
    ErrorCode.PALETTE_EXHAUSTED: 400,
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
    """Raised by resolve_roles() when one or more response labels can't be
    matched to a known scale family.

    Task 5 removed this error from every load path (Milieu/Toluna no
    longer call resolve_roles from parse_header; the collector in
    surveytool.ingest.validate_questions handles the unresolved case by
    collecting into UnresolvedQuestionsError instead) — resolve_roles
    itself, and this error, still exist and still raise, but are reachable
    only by a caller that calls resolve_roles directly (a synthetic
    conformance test, not any adapter's load()). No next_action naming
    scales.yaml is set, since this no longer reaches an analyst through
    any live path — that instruction is what audit finding #2 flagged for
    removal.

    Subclasses ValueError so existing ``pytest.raises(ValueError)`` call
    sites against ``resolve_roles`` keep passing.
    """

    def __init__(self, unresolved: list[str]) -> None:
        self.unresolved = unresolved
        detail = f"Scale library could not resolve label(s): {unresolved}."
        super().__init__(
            ErrorCode.UNRESOLVED_SCALE_LABELS,
            "This file has response labels this tool doesn't recognise.",
            detail=detail,
        )


@dataclass(frozen=True)
class UnresolvedQuestion:
    variable: str
    question_text: str
    codes: list[tuple[int, str]]
    reason: str
    close_family_hint: str | None = None


class UnresolvedQuestionsError(SurveyToolError):
    """Raised once per load, after a single validation pass over every
    question in the file, listing every question that failed to resolve.

    Replaces stop-at-first-failure: a file with several unresolved
    questions is reported completely in one error, not discovered one
    question per load attempt. The message and next_action are addressed to
    a non-technical analyst and never name scales.yaml, YAML, an overrides
    file, or any repository path — the remediation path is 'use the
    resolver', described in plain English.
    """

    def __init__(self, entries: list[UnresolvedQuestion]) -> None:
        self.detail_entries = entries
        count = len(entries)
        plural = "question" if count == 1 else "questions"
        variables = ", ".join(e.variable for e in entries)
        detail = f"Unresolved {plural}: {variables}."
        super().__init__(
            ErrorCode.UNRESOLVED_SCALE_LABELS,
            f"This file has {count} {plural} with response labels this tool doesn't recognise.",
            detail=detail,
            next_action="Open the resolver to assign each unrecognised response a role, or mark the question as not a scale.",
        )

    def to_response(self) -> dict:
        """Extends the base flat-string response with the per-question list
        the resolver UI needs. `detail`/`next_action` stay as the base class
        renders them, for any caller still treating this generically as a
        SurveyToolError; `detail_entries` carries the structured list a
        resolver-aware client reads instead."""
        body = super().to_response()
        entries = []
        for e in self.detail_entries:
            entry_dict = {
                "variable": e.variable,
                "question_text": e.question_text,
                "codes": [[code, label] for code, label in e.codes],
                "reason": e.reason,
            }
            if e.close_family_hint is not None:
                entry_dict["close_family_hint"] = e.close_family_hint
            entries.append(entry_dict)
        body["error"]["detail_entries"] = entries
        return body


class DuplicateCodeKeyError(SurveyToolError):
    """Raised when a question's code-to-label map has the same numeric code
    assigned to two different labels, or the same label assigned to two
    different codes — a silent-overwrite hazard (Round A prompt A2). Before
    prompt A1 fixed the Datamap block-header rule, this class of defect
    happened by accident (Q9 absorbing Q10's rows gave it two labels under
    code 1); this guard stops it recurring through any other route,
    including a project override that would collapse two codes onto one
    label.
    """

    def __init__(self, qid: str, code: object, label: str, other_code: object, other_label: str) -> None:
        self.qid = qid
        self.conflicting_code = code
        self.conflicting_label = label
        self.other_code = other_code
        self.other_label = other_label
        detail = (
            f"Question {qid!r} has conflicting entries: code {code!r} -> {label!r} "
            f"and code {other_code!r} -> {other_label!r}."
        )
        super().__init__(
            ErrorCode.DUPLICATE_CODE_KEY,
            f"This file's codebook has a conflicting entry for question '{qid}'.",
            detail=detail,
            next_action="Check the codebook sheet for this question, or pick a different file.",
        )


class ScaleLibraryConfigError(SurveyToolError):
    """Raised when scales.yaml itself is malformed: two variants (anywhere
    in the file, same or different families) share a folded label set, a
    variant declares fewer than three points, or one pattern appears at two
    different ranks within a single variant. This is always a defect in the
    shipped library file, never something a user's data can trigger."""

    def __init__(self, detail: str) -> None:
        super().__init__(
            ErrorCode.SCALE_LIBRARY_CONFIG_INVALID,
            "The scale library configuration is invalid.",
            detail=detail,
            next_action="This is a defect in the application's scale library file, not your data. Report it.",
        )


class AmbiguousScaleMatchError(SurveyToolError):
    """Raised when a question's full label set matches more than one
    variant in the scale library. Ambiguity is never resolved by picking
    one variant silently -- see the Round B spec's B1 task: 'Ambiguity in
    the library is a library defect and must surface as one.'"""

    def __init__(self, qid: str | None, labels: list[str], variant_names: list[str]) -> None:
        self.qid = qid
        self.labels = labels
        self.variant_names = variant_names
        where = f"Question {qid!r}" if qid else "This label set"
        detail = (
            f"{where} with labels {labels!r} matches more than one scale "
            f"variant: {variant_names!r}."
        )
        super().__init__(
            ErrorCode.AMBIGUOUS_SCALE_MATCH,
            "This question's response options match more than one known scale, and the tool won't guess which.",
            detail=detail,
            next_action="Resolve this question manually in the resolver, or add a distinguishing variant to the scale library.",
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


class NotCollectedReasonMissingError(SurveyToolError):
    """Raised when a vendor mapping's `not_collected` entry for a dimension
    has an empty or blank reason.

    A declared-not-collected category (Task 9) must carry a real, free-text
    reason an analyst can read in the run summary — never a placeholder.
    """

    def __init__(self, vendor: str, dimension: str, category: str) -> None:
        self.vendor = vendor
        self.dimension = dimension
        self.category = category
        detail = (
            f"Vendor {vendor!r} mapping for dimension {dimension!r} declares category "
            f"{category!r} as not_collected but supplies no reason text."
        )
        super().__init__(
            ErrorCode.CANONICAL_CATEGORY_UNREACHABLE,
            "A vendor demographic mapping declares a category as not collected without saying why.",
            detail=detail,
            next_action="Add a non-empty reason for this category in the vendor YAML's not_collected mapping.",
        )


class NotCollectedConflictsWithValueMapError(SurveyToolError):
    """Raised when a vendor mapping declares the same canonical category both
    reachable via value_map AND not_collected.

    A category cannot simultaneously be collected (has a source value mapped
    to it) and declared as a genuine content gap.
    """

    def __init__(self, vendor: str, dimension: str, category: str) -> None:
        self.vendor = vendor
        self.dimension = dimension
        self.category = category
        detail = (
            f"Vendor {vendor!r} mapping for dimension {dimension!r} lists category "
            f"{category!r} in both value_map and not_collected."
        )
        super().__init__(
            ErrorCode.CANONICAL_CATEGORY_UNREACHABLE,
            "A vendor demographic mapping declares a category as both collected and not collected.",
            detail=detail,
            next_action="Remove this category from either value_map or not_collected in the vendor YAML, not both.",
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


class PaletteExhaustedError(SurveyToolError):
    """Raised when a chart needs more distinct series colours than the
    shared categorical palette has entries. Never cycles the palette
    silently — a repeated colour within one chart would make two different
    response options visually indistinguishable, which is worse than
    refusing outright and telling the analyst why."""

    def __init__(self, series_count: int, palette_size: int) -> None:
        self.series_count = series_count
        self.palette_size = palette_size
        detail = f"{series_count} distinct series requested; the palette has {palette_size} entries."
        super().__init__(
            ErrorCode.PALETTE_EXHAUSTED,
            f"This chart has {series_count} response options, more than the "
            f"{palette_size} distinct colours available — it can't be drawn "
            f"without repeating a colour.",
            detail=detail,
            next_action="Combine or filter response options, or view this question as a table instead.",
        )
