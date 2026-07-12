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
class QuestionStats:
    qid: str
    base: int
    code_stats: tuple[CodeStat, ...]
    t2b: float | None  # None if question has no top codes
    b2b: float | None  # None if question has no bottom codes
    mean: float | None  # None if no code has numeric_value
