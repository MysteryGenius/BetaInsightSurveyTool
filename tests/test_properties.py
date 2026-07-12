"""
Phase 5 property tests.

Three invariants that must hold for any synthetic question/response distribution:

1. Percentages sum to 100 within rounding (±0.1).
2. Cell counts reconcile to the base: sum(cs.n) == qs.base.
3. Top + neutral + bottom == 100 for pure scale items (no nonsubstantive codes).

All tests use hypothesis to vary respondent counts and response distributions.
No file I/O.
"""
from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from surveytool.compute.frequency import compute_question_stats
from surveytool.core.model import (
    CodeRole,
    Question,
    QuestionType,
    Response,
    ResponseState,
    ScaleCode,
)


# ── Shared fixtures ──────────────────────────────────────────────────────────

def _pure_scale_question(qid: str = "Q1") -> Question:
    """5-point agreement scale, no nonsubstantive codes."""
    return Question(
        qid=qid,
        text="Test scale question",
        qtype=QuestionType.scale,
        scale_family="agreement",
        labels=[
            ScaleCode(code=1, label="Strongly Agree", role=CodeRole.top, numeric_value=5),
            ScaleCode(code=2, label="Agree", role=CodeRole.top, numeric_value=4),
            ScaleCode(code=3, label="Neither Agree Nor Disagree", role=CodeRole.neutral, numeric_value=3),
            ScaleCode(code=4, label="Disagree", role=CodeRole.bottom, numeric_value=2),
            ScaleCode(code=5, label="Strongly Disagree", role=CodeRole.bottom, numeric_value=1),
        ],
    )


def _scale_with_ns(qid: str = "Q1") -> Question:
    """5-point scale plus one nonsubstantive code."""
    return Question(
        qid=qid,
        text="Test scale with NS",
        qtype=QuestionType.scale,
        scale_family="agreement",
        labels=[
            ScaleCode(code=1, label="Strongly Agree", role=CodeRole.top, numeric_value=5),
            ScaleCode(code=2, label="Agree", role=CodeRole.top, numeric_value=4),
            ScaleCode(code=3, label="Neither Agree Nor Disagree", role=CodeRole.neutral, numeric_value=3),
            ScaleCode(code=4, label="Disagree", role=CodeRole.bottom, numeric_value=2),
            ScaleCode(code=5, label="Strongly Disagree", role=CodeRole.bottom, numeric_value=1),
            ScaleCode(code=99, label="Prefer not to answer", role=CodeRole.nonsubstantive),
        ],
    )


def _make_responses(question: Question, code_sequence: list[int]) -> list[Response]:
    """Build answered Response objects from a list of codes."""
    codes = {sc.code for sc in question.labels}
    ns_codes = {sc.code for sc in question.labels if sc.role is CodeRole.nonsubstantive}
    responses = []
    for i, code in enumerate(code_sequence):
        if code not in codes:
            continue
        state = ResponseState.nonsubstantive if code in ns_codes else ResponseState.answered
        responses.append(Response(
            respondent_id=f"R{i}",
            qid=question.qid,
            raw_value=code,
            state=state,
        ))
    return responses


# ── Property 1: percentages sum to 100 within rounding ───────────────────────

@given(
    n=st.integers(min_value=1, max_value=200),
    distribution=st.lists(
        st.integers(min_value=1, max_value=6),
        min_size=1,
        max_size=200,
    ),
)
@settings(max_examples=300)
def test_pct_sum_to_100(n: int, distribution: list[int]) -> None:
    """sum(code_stat.pct) == 100.0 ± 0.1 for any non-empty response set."""
    question = _scale_with_ns()
    valid_codes = [c for c in distribution if 1 <= c <= 6]
    # Remap code 6 → 99 (our nonsubstantive sentinel)
    remapped = [99 if c == 6 else c for c in valid_codes]
    if not remapped:
        return  # skip degenerate case
    responses = _make_responses(question, remapped)
    if not responses:
        return
    qs = compute_question_stats(question, responses)
    total_pct = sum(cs.pct for cs in qs.code_stats)
    assert abs(total_pct - 100.0) <= 0.1, (
        f"Percentages summed to {total_pct:.4f}, expected 100.0 ± 0.1"
    )


# ── Property 2: cell counts reconcile to the base ────────────────────────────

@given(
    distribution=st.lists(
        st.integers(min_value=1, max_value=6),
        min_size=1,
        max_size=300,
    ),
)
@settings(max_examples=300)
def test_cell_counts_reconcile_to_base(distribution: list[int]) -> None:
    """sum(cs.n for cs in qs.code_stats) == qs.base for all distributions."""
    question = _scale_with_ns()
    remapped = [99 if c == 6 else c for c in distribution]
    responses = _make_responses(question, remapped)
    if not responses:
        return
    qs = compute_question_stats(question, responses)
    assert sum(cs.n for cs in qs.code_stats) == qs.base, (
        f"sum(n) = {sum(cs.n for cs in qs.code_stats)} != base {qs.base}"
    )


# ── Property 3: top + neutral + bottom == 100 for pure scale items ───────────

@given(
    distribution=st.lists(
        st.integers(min_value=1, max_value=5),
        min_size=1,
        max_size=300,
    ),
)
@settings(max_examples=300)
def test_top_neutral_bottom_sum_to_100(distribution: list[int]) -> None:
    """For pure scale items (no NS codes), t2b + neutral_pct + b2b == 100 ± 0.1."""
    question = _pure_scale_question()
    responses = _make_responses(question, distribution)
    if not responses:
        return
    qs = compute_question_stats(question, responses)

    neutral_pct = sum(
        cs.pct for cs in qs.code_stats if cs.role is CodeRole.neutral
    )
    t2b = qs.t2b or 0.0
    b2b = qs.b2b or 0.0
    total = t2b + neutral_pct + b2b
    assert abs(total - 100.0) <= 0.1, (
        f"T2B({t2b:.4f}) + neutral({neutral_pct:.4f}) + B2B({b2b:.4f}) = {total:.4f}, "
        f"expected 100.0 ± 0.1"
    )
