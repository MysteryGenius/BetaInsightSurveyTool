from __future__ import annotations

import functools
import re
import warnings
from collections.abc import Sequence

from surveytool.core.model import CodeRole, Question, QuestionType, ResponseState

# Default non-substantive label patterns. This is the DEFAULT list used when
# a project has no configured `nonsubstantive_labels` (or explicitly passes
# None) — it is NOT a floor. A project's configured label list, when
# provided, is authoritative and replaces this list entirely rather than
# being unioned with it: removing one of these patterns from a project's
# configured list means that pattern is no longer treated as
# non-substantive for that project.
DEFAULT_NONSUBSTANTIVE_LABELS: tuple[str, ...] = (
    "prefer not",
    "don't know",
    "not applicable",
    "n/a",
    "refused",
    "no opinion",
)

# Compiled patterns for the built-in defaults, preserved verbatim from the
# original hardcoded implementation (word-boundary handling for "n/a" and
# "refused", "don.?t know" allowing an apostrophe or not) so that the
# default list produces byte-identical matching behavior to before this
# list became configurable.
_DEFAULT_LABEL_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"prefer not", re.IGNORECASE),
    re.compile(r"don.?t know", re.IGNORECASE),
    re.compile(r"not applicable", re.IGNORECASE),
    re.compile(r"\bn/a\b", re.IGNORECASE),
    re.compile(r"\brefused\b", re.IGNORECASE),
    re.compile(r"no opinion", re.IGNORECASE),
]

NUMERIC_SENTINELS: frozenset[int] = frozenset({98, 99, 999})


@functools.lru_cache(maxsize=256)
def _compile_patterns(labels: tuple[str, ...]) -> tuple[re.Pattern[str], ...]:
    """Compile a project's configured label list into substring,
    case-insensitive regex patterns, cached by the exact tuple of labels
    so repeated calls with the same configured list (the common case,
    since a project's list doesn't change mid-run) don't recompile."""
    return tuple(re.compile(re.escape(label), re.IGNORECASE) for label in labels)


def is_nonsubstantive_label(label: str, labels: Sequence[str] | None = None) -> bool:
    """Return True if `label` matches a non-substantive pattern.

    `labels` is the project's configured non-substantive label list. When
    None (the default), falls back to the built-in default patterns —
    identical behavior to before this list was configurable. When
    provided, `labels` is authoritative: it entirely replaces the default
    patterns rather than being unioned with them, so a project that has
    removed a default label from its configured list will no longer flag
    that label as non-substantive.
    """
    if labels is None:
        return any(p.search(label) for p in _DEFAULT_LABEL_PATTERNS)
    patterns = _compile_patterns(tuple(labels))
    return any(p.search(label) for p in patterns)


def is_nonsubstantive(
    value: str | int | None,
    question: Question,
    extra_sentinels: frozenset[int] = frozenset(),
    nonsubstantive_labels: Sequence[str] | None = None,
) -> bool:
    """
    Return True if value is a non-substantive response for this question.

    Checks (in order):
    1. None → not nonsubstantive (caller should distinguish not_asked/item_missing)
    2. Label patterns (text values or mapped labels)
    3. Numeric sentinel values
    4. Out-of-range codes for scale questions

    `nonsubstantive_labels`, when provided, is the project's configured
    label list and is authoritative for label-pattern matching (see
    is_nonsubstantive_label). When None, the built-in defaults are used.
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
        if is_nonsubstantive_label(sc.label, nonsubstantive_labels):
            return True

    # Text value directly matches a label pattern
    if isinstance(value, str) and is_nonsubstantive_label(value, nonsubstantive_labels):
        return True

    # Numeric sentinel
    if isinstance(value, int) and value in sentinels:
        return True

    return False


def classify_response(
    raw: str | int | None,
    question: Question,
    extra_sentinels: frozenset[int] = frozenset(),
    nonsubstantive_labels: Sequence[str] | None = None,
) -> ResponseState:
    """
    Classify a raw response value into a ResponseState.

    Callers set raw=None + state=not_asked for routing; this function handles
    the remaining cases.

    `nonsubstantive_labels`, when provided, is the project's configured
    label list, threaded through to is_nonsubstantive (see there).
    """
    if raw is None:
        return ResponseState.item_missing

    if is_nonsubstantive(raw, question, extra_sentinels, nonsubstantive_labels):
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
