from __future__ import annotations

import re
import warnings

from surveytool.core.model import CodeRole, Question, QuestionType, ResponseState

_LABEL_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"prefer not", re.IGNORECASE),
    re.compile(r"don.?t know", re.IGNORECASE),
    re.compile(r"not applicable", re.IGNORECASE),
    re.compile(r"\bn/a\b", re.IGNORECASE),
    re.compile(r"\brefused\b", re.IGNORECASE),
    re.compile(r"no opinion", re.IGNORECASE),
]

NUMERIC_SENTINELS: frozenset[int] = frozenset({98, 99, 999})


def is_nonsubstantive_label(label: str) -> bool:
    return any(p.search(label) for p in _LABEL_PATTERNS)


def is_nonsubstantive(
    value: str | int | None,
    question: Question,
    extra_sentinels: frozenset[int] = frozenset(),
) -> bool:
    """
    Return True if value is a non-substantive response for this question.

    Checks (in order):
    1. None → not nonsubstantive (caller should distinguish not_asked/item_missing)
    2. Label patterns (text values or mapped labels)
    3. Numeric sentinel values
    4. Out-of-range codes for scale questions
    """
    if value is None:
        return False

    sentinels = NUMERIC_SENTINELS | extra_sentinels

    # Check via label map on the question
    label_map = {sc.code: sc for sc in question.labels}
    if value in label_map:
        sc = label_map[value]
        if sc.role is CodeRole.nonsubstantive:
            return True
        if is_nonsubstantive_label(sc.label):
            return True

    # Text value directly matches a label pattern
    if isinstance(value, str) and is_nonsubstantive_label(value):
        return True

    # Numeric sentinel
    if isinstance(value, int) and value in sentinels:
        return True

    return False


def classify_response(
    raw: str | int | None,
    question: Question,
    extra_sentinels: frozenset[int] = frozenset(),
) -> ResponseState:
    """
    Classify a raw response value into a ResponseState.

    Callers set raw=None + state=not_asked for routing; this function handles
    the remaining cases.
    """
    if raw is None:
        return ResponseState.item_missing

    if is_nonsubstantive(raw, question, extra_sentinels):
        return ResponseState.nonsubstantive

    # For scale/single_choice/demographic check the code is known
    if question.qtype in (
        QuestionType.scale,
        QuestionType.single_choice,
        QuestionType.demographic,
    ):
        known_codes = {sc.code for sc in question.labels}
        if known_codes and raw not in known_codes:
            # Check numeric sentinels first (already done above); this is truly unknown
            warnings.warn(
                f"Unresolved code {raw!r} for question {question.qid!r}. "
                "Treating as item_missing.",
                stacklevel=2,
            )
            return ResponseState.item_missing

    return ResponseState.answered
