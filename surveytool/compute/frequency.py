from __future__ import annotations

import warnings

from surveytool.core.model import (
    CodeRole,
    Question,
    QuestionType,
    Response,
    ResponseState,
    ScaleCode,
    Survey,
)
from surveytool.compute.stats import BaseProvenance, CodeStat, QuestionStats
from surveytool.core.netting_gate import require_scale_for_netting

_BASE_STATES: frozenset[ResponseState] = frozenset(
    {ResponseState.answered, ResponseState.nonsubstantive}
)
_DEFAULT_MR_DELIMITER = "; "


def _build_label_map(question: Question) -> dict[str | int, ScaleCode]:
    return {sc.code: sc for sc in question.labels}


def _base_responses(
    responses: list[Response],
    *,
    exclude_nonsubstantive: bool = False,
) -> list[Response]:
    if exclude_nonsubstantive:
        return [r for r in responses if r.state is ResponseState.answered]
    return [r for r in responses if r.state in _BASE_STATES]


def _count_scale_codes(
    question: Question,
    base_responses: list[Response],
    base: int,
) -> tuple[CodeStat, ...]:
    counts: dict[str | int, int] = {sc.code: 0 for sc in question.labels}
    for r in base_responses:
        if r.raw_value in counts:
            counts[r.raw_value] += 1
    result = []
    for sc in question.labels:
        n = counts[sc.code]
        pct = n / base * 100 if base > 0 else 0.0
        result.append(CodeStat(code=sc.code, label=sc.label, role=sc.role, n=n, pct=pct))
    return tuple(result)


def _count_multi_response_codes(
    question: Question,
    base_responses: list[Response],
    base: int,
) -> tuple[CodeStat, ...]:
    delimiter = question.multi_response_delimiter
    if delimiter is None:
        warnings.warn(
            f"Question {question.qid!r} has no multi_response_delimiter; "
            f"falling back to {_DEFAULT_MR_DELIMITER!r}.",
            stacklevel=4,
        )
        delimiter = _DEFAULT_MR_DELIMITER

    counts: dict[str | int, int] = {sc.code: 0 for sc in question.labels}
    label_map = _build_label_map(question)

    for r in base_responses:
        if r.state is not ResponseState.answered or r.raw_value is None:
            continue
        raw = str(r.raw_value)
        for part in raw.split(delimiter):
            code: str | int = part.strip()
            if code not in counts:
                # Try int coercion for numeric-coded multi-response
                try:
                    code = int(code)  # type: ignore[assignment]
                except (ValueError, TypeError):
                    pass
            if code in counts:
                counts[code] += 1

    result = []
    for sc in question.labels:
        n = counts[sc.code]
        pct = n / base * 100 if base > 0 else 0.0
        result.append(CodeStat(code=sc.code, label=sc.label, role=sc.role, n=n, pct=pct))
    return tuple(result)


def build_base_provenance(
    responses: list[Response],
    *,
    exclude_nonsubstantive_from_base: bool = False,
) -> BaseProvenance:
    """Round A prompt A5: classify every response in this cohort by why it
    is or isn't part of the answering base, from ResponseState alone —
    deterministic, and never changes what compute_question_stats counts,
    only names it. `responses` is the same one-row-per-respondent list
    compute_question_stats receives (already filtered to one qid), so
    `cohort_size == len(responses)` accounts for every respondent exactly
    once, with no possibility of a respondent contributing zero or multiple
    rows silently going unaccounted for.
    """
    routed = sum(1 for r in responses if r.state is ResponseState.not_asked)
    item_missing = sum(1 for r in responses if r.state is ResponseState.item_missing)
    nonsubstantive_excluded = (
        sum(1 for r in responses if r.state is ResponseState.nonsubstantive)
        if exclude_nonsubstantive_from_base
        else 0
    )
    return BaseProvenance(
        cohort_size=len(responses),
        routed=routed,
        item_missing=item_missing,
        nonsubstantive_excluded=nonsubstantive_excluded,
    )


def compute_question_stats(
    question: Question,
    responses: list[Response],
    *,
    exclude_nonsubstantive_from_base: bool = False,
) -> QuestionStats:
    """Compute frequency statistics for a single question.

    ``responses`` must already be filtered to only this question's qid.
    ``exclude_nonsubstantive_from_base``, when True, removes nonsubstantive
    responses from the percentage base (default keeps them in the base,
    per project setting default). Demographic questions never call this
    with the flag set — banner variables are unaffected by construction,
    since callers only pass the flag through for question tables, not
    cross-tab banner computation (cross_tab.py is untouched by this task).
    The base is always present on the returned QuestionStats regardless of
    the setting.
    """
    base_resps = _base_responses(responses, exclude_nonsubstantive=exclude_nonsubstantive_from_base)
    base = len(base_resps)
    provenance = build_base_provenance(responses, exclude_nonsubstantive_from_base=exclude_nonsubstantive_from_base)

    if base == 0:
        code_stats = tuple(
            CodeStat(code=sc.code, label=sc.label, role=sc.role, n=0, pct=0.0)
            for sc in question.labels
        )
        return QuestionStats(qid=question.qid, base=0, code_stats=code_stats,
                             t2b=None, b2b=None, mean=None, provenance=provenance)

    if question.qtype is QuestionType.multi_response:
        code_stats = _count_multi_response_codes(question, base_resps, base)
        mean = None  # no canonical numeric ordering for multi-select
    else:
        code_stats = _count_scale_codes(question, base_resps, base)
        label_map = _build_label_map(question)
        ranks = [
            label_map[r.raw_value].rank
            for r in responses
            if r.state is ResponseState.answered
            and r.raw_value in label_map
            and label_map[r.raw_value].rank is not None
        ]
        mean = sum(ranks) / len(ranks) if ranks else None

    has_top = any(sc.role is CodeRole.top for sc in question.labels)
    has_bottom = any(sc.role is CodeRole.bottom for sc in question.labels)
    if (has_top or has_bottom) and question.qtype in (QuestionType.binary, QuestionType.categorical):
        # Binary/categorical questions (Task 9) never carry genuine netting
        # semantics even if a label happens to carry a top/bottom role —
        # gate explicitly rather than trusting adapters never assign those
        # roles to non-scale questions. Scale and multi_response questions
        # are unaffected: multi_response legitimately computes t2b/b2b today
        # (see tests/fixtures/multi_response.py) and must keep doing so.
        require_scale_for_netting(question, "top_two_box" if has_top else "bottom_two_box")
    t2b = sum(cs.pct for cs in code_stats if cs.role is CodeRole.top) if has_top else None
    b2b = sum(cs.pct for cs in code_stats if cs.role is CodeRole.bottom) if has_bottom else None

    return QuestionStats(
        qid=question.qid,
        base=base,
        code_stats=code_stats,
        t2b=t2b,
        b2b=b2b,
        mean=mean,
        provenance=provenance,
    )


def compute_survey_stats(
    survey: Survey,
    qids: list[str] | None = None,
) -> list[QuestionStats]:
    """Compute frequency statistics for all eligible questions in a survey.

    Skips questions where ``base_eligible=False`` (demographics, open-ended).
    If ``qids`` is provided, only those questions are computed.
    """
    response_index: dict[str, list[Response]] = {}
    for r in survey.responses:
        response_index.setdefault(r.qid, []).append(r)

    results = []
    for question in survey.questions:
        if not question.base_eligible:
            continue
        if qids is not None and question.qid not in qids:
            continue
        q_responses = response_index.get(question.qid, [])
        results.append(compute_question_stats(question, q_responses))
    return results
