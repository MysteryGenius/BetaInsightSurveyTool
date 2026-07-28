from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import pandas as pd

from surveytool.charts.errors import ErrorCode, SurveyToolError
from surveytool.compute.frequency import compute_question_stats
from surveytool.core.config import ToolConfig
from surveytool.core.demographics import (
    CONDITIONAL_DEMOGRAPHIC_ALIASES as _CONDITIONAL_DEMOGRAPHIC_ALIASES,
    STANDARD_DEMOGRAPHIC_ALIASES as _STANDARD_DEMOGRAPHIC_ALIASES,
)
from surveytool.core.model import CodeRole, Question, Response, Survey

_SIGNIFICANCE_NOT_IMPLEMENTED_MESSAGE = (
    "significance testing not yet implemented; "
    "use --significance once the two-proportion z-test is available"
)

# Demographic ScaleCodes use CodeRole.excluded (they are not scale items).
# Valid breakdown levels are codes with a substantive role — excludes nonsubstantive sentinels.
_BANNER_LEVEL_ROLES = frozenset({
    CodeRole.top, CodeRole.neutral, CodeRole.bottom, CodeRole.excluded
})


class DemographicNotFoundError(SurveyToolError):
    """Raised when a demographic name cannot be resolved against the survey's questions."""

    def __init__(self, message: str) -> None:
        super().__init__(
            ErrorCode.DEMOGRAPHIC_NOT_FOUND,
            "This demographic is not in the file.",
            detail=message,
            next_action="Choose a different demographic, or check the file's cross-tab variables.",
        )


class CellStatus(str, Enum):
    ok = "ok"
    grey = "grey"
    suppressed = "suppressed"


@dataclass(frozen=True)
class CrossTabCell:
    subgroup_code: str | int
    subgroup_label: str
    n: int
    status: CellStatus
    t2b: float | None
    b2b: float | None
    mean: float | None


@dataclass(frozen=True)
class CrossTabResult:
    qid: str
    question_text: str
    demographic: str
    cells: tuple[CrossTabCell, ...]


@dataclass(frozen=True)
class DemographicAvailability:
    standard: dict[str, Question]
    conditional: dict[str, Question]


def resolve_demographic_question(survey: Survey, name: str) -> Question:
    """Resolve a demographic name/qid to a Question.

    Raises DemographicNotFoundError, with the reason, if no is_demographic
    question matches by qid or text substring. Never returns None, never
    warns-and-skips — callers must handle the failure explicitly.
    """
    name_lower = name.lower()
    for q in survey.questions:
        if not q.is_demographic:
            continue
        if q.qid.lower() == name_lower or name_lower in q.text.lower():
            return q
    available = [q.qid for q in survey.questions if q.is_demographic]
    raise DemographicNotFoundError(
        f"Demographic {name!r} could not be resolved against survey {survey.id!r}: "
        f"no is_demographic question matched by qid or text substring. "
        f"Available demographic questions: {available}"
    )


def detect_available_demographics(survey: Survey) -> DemographicAvailability:
    """Data-driven demographic detection.

    Standard set (age/gender/region) is included when resolvable via aliases.
    Conditional set (income/race) is included only when present in the file.
    Never raises — absent fields are simply omitted from the result.
    """
    standard: dict[str, Question] = {}
    for canonical, aliases in _STANDARD_DEMOGRAPHIC_ALIASES.items():
        for alias in aliases:
            try:
                standard[canonical] = resolve_demographic_question(survey, alias)
                break
            except DemographicNotFoundError:
                continue

    conditional: dict[str, Question] = {}
    for canonical, aliases in _CONDITIONAL_DEMOGRAPHIC_ALIASES.items():
        for alias in aliases:
            try:
                conditional[canonical] = resolve_demographic_question(survey, alias)
                break
            except DemographicNotFoundError:
                continue

    return DemographicAvailability(standard=standard, conditional=conditional)


def _cell_status(n: int, config: ToolConfig) -> CellStatus:
    if n < config.cross_tab_suppress_threshold:
        return CellStatus.suppressed
    if n < config.cross_tab_grey_threshold:
        return CellStatus.grey
    return CellStatus.ok


def _build_cell(sc, qs_result, config: ToolConfig) -> CrossTabCell:
    status = _cell_status(qs_result.base, config)
    if status is CellStatus.suppressed:
        return CrossTabCell(
            subgroup_code=sc.code,
            subgroup_label=sc.label,
            n=qs_result.base,
            status=status,
            t2b=None,
            b2b=None,
            mean=None,
        )
    return CrossTabCell(
        subgroup_code=sc.code,
        subgroup_label=sc.label,
        n=qs_result.base,
        status=status,
        t2b=qs_result.t2b,
        b2b=qs_result.b2b,
        mean=qs_result.mean,
    )


def compute_cross_tab(
    respondent_frame: pd.DataFrame,
    survey: Survey,
    question: Question,
    demographic: str,
    *,
    config: ToolConfig | None = None,
    exclude_respondent_ids: set[str] | None = None,
    significance: bool = False,
) -> CrossTabResult:
    """Compute a demographic cross-tab for a single question.

    Slices ``respondent_frame`` by demographic subgroup and nets each subgroup's
    figure by passing the sliced responses through the existing netting function
    (``compute_question_stats``). No netting or statistics are reimplemented here.
    """
    if significance:
        raise NotImplementedError(_SIGNIFICANCE_NOT_IMPLEMENTED_MESSAGE)

    if config is None:
        config = ToolConfig()

    demo_question = resolve_demographic_question(survey, demographic)

    excluded = exclude_respondent_ids or set()
    frame = respondent_frame.drop(
        index=[rid for rid in excluded if rid in respondent_frame.index]
    )

    if demo_question.qid not in frame.columns:
        raise DemographicNotFoundError(
            f"Demographic question {demo_question.qid!r} (resolved from {demographic!r}) "
            f"has no column in the respondent frame; frame and survey are out of sync."
        )

    response_index: dict[str, list[Response]] = {}
    for r in survey.responses:
        if r.respondent_id in excluded:
            continue
        response_index.setdefault(r.qid, []).append(r)
    q_responses = response_index.get(question.qid, [])

    valid_scs = [sc for sc in demo_question.labels if sc.role in _BANNER_LEVEL_ROLES]

    cells: list[CrossTabCell] = []
    for sc in valid_scs:
        subgroup_rids = set(frame.index[frame[demo_question.qid] == sc.code])
        cell_responses = [r for r in q_responses if r.respondent_id in subgroup_rids]
        qs_result = compute_question_stats(question, cell_responses)
        cells.append(_build_cell(sc, qs_result, config))

    return CrossTabResult(
        qid=question.qid,
        question_text=question.text,
        demographic=demo_question.qid,
        cells=tuple(cells),
    )
