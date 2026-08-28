from __future__ import annotations

from dataclasses import dataclass

from surveytool.core.model import CodeRole


@dataclass(frozen=True)
class CodeStat:
    code: str | int
    label: str
    role: CodeRole
    n: int
    pct: float  # n / base * 100, full precision — round only at presentation


@dataclass(frozen=True)
class BaseProvenance:
    """Round A prompt A5: why a question's/cell's answering base is smaller
    than the respondent cohort it was computed over. Every count here is
    part of ``cohort_size`` but excluded from ``base`` — ``base +
    routed + item_missing + nonsubstantive_excluded == cohort_size``
    always holds by construction (see build_base_provenance).

    Never collapses to a single label when more than one reason applies —
    each reason is its own field, all present at once when applicable.
    Suppression and straightliner exclusion are NOT reasons this dataclass
    itself carries: suppression is a presentation-layer decision made after
    the base is already known (see cross_tab.py's CellStatus /
    breaks_compute.py's Band), and straightliner exclusion currently removes
    a respondent from the cohort entirely before compute_question_stats
    ever sees them (see build_findings_sheet's exclude_respondent_ids) —
    neither is a per-response reason a single question's base sees.
    """

    cohort_size: int
    routed: int = 0
    """Responses with ResponseState.not_asked — the question did not apply
    to this respondent (routed by a prior answer)."""
    item_missing: int = 0
    """Responses with ResponseState.item_missing — the question applied but
    the respondent's answer wasn't a recognised code (raw_value is None or
    unresolved)."""
    nonsubstantive_excluded: int = 0
    """Responses with ResponseState.nonsubstantive, counted here only when
    the caller's exclude_nonsubstantive_from_base setting removed them from
    the base — nonsubstantive responses are IN the base by default (see
    frequency._BASE_STATES), so this is 0 unless that setting is active."""

    @property
    def reduced(self) -> bool:
        return self.routed > 0 or self.item_missing > 0 or self.nonsubstantive_excluded > 0


@dataclass(frozen=True)
class QuestionStats:
    qid: str
    base: int
    code_stats: tuple[CodeStat, ...]
    t2b: float | None  # None if question has no top codes
    b2b: float | None  # None if question has no bottom codes
    mean: float | None  # None if no code has numeric_value
    provenance: BaseProvenance | None = None
