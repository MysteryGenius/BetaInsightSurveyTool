from __future__ import annotations

import functools
import re
import warnings
from collections.abc import Sequence

from surveytool.core.hygiene import fold_label
from surveytool.core.model import CodeRole, Question, QuestionType, ResponseState
from surveytool.core.scale_library import is_recognised_scale_point

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

# Folded form of the defaults, used to tell whether one entry in a caller's
# configured `labels` list is one of the built-in six (and therefore
# eligible for the scale-point exception below) versus a label the analyst
# added deliberately (which is never subject to that exception — see
# is_nonsubstantive_label).
_FOLDED_DEFAULTS: frozenset[str] = frozenset(fold_label(lb) for lb in DEFAULT_NONSUBSTANTIVE_LABELS)

# Compiled patterns for the built-in defaults, preserved verbatim from the
# original hardcoded implementation (word-boundary handling for "n/a" and
# "refused", "don.?t know" allowing an apostrophe or not) so that the
# default list produces the same matching behavior as before this list
# became configurable.
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
    since a project's list doesn't change mid-run) don't recompile.

    Each configured label is folded through `fold_label` (curly quotes/
    apostrophes to straight, dash variants to ASCII hyphen, casefolded,
    whitespace collapsed) before being escaped into a pattern, so it
    matches a candidate label regardless of which punctuation variant the
    source file used — see `is_nonsubstantive_label` for why this needs to
    line up with the default regex path's behavior.
    """
    return tuple(re.compile(re.escape(fold_label(label)), re.IGNORECASE) for label in labels)


def is_nonsubstantive_label(label: str, labels: Sequence[str] | None = None) -> bool:
    """Return True if `label` matches a non-substantive pattern.

    `labels` is the project's configured non-substantive label list. When
    None (the default), falls back to the built-in default patterns. When
    provided, `labels` is authoritative: it entirely replaces the default
    patterns rather than being unioned with them, so a project that has
    removed a default label from its configured list will no longer flag
    that label as non-substantive.

    Both paths match against `fold_label(label)` rather than the raw
    label, so a source file's curly apostrophe (e.g. PureSpectrum's
    "Neutral/don't know enough to say") folds to a straight one before
    either path compares it — the default path's regex ("don.?t know",
    already apostrophe-agnostic via its `.?`) and the configured-list
    path's literal substring match (which, pre-fold, only recognized a
    straight apostrophe) no longer disagree purely because of which
    apostrophe variant the source file happened to use.

    Folding alone is not sufficient, though: "Neutral/don't know enough
    to say" genuinely *contains* the substring "don't know" once folded,
    so a bare substring/regex search over either path would still flag it
    as non-substantive — directly contradicting scales.yaml's documented,
    deliberate decision that this exact label is the `relevance` family's
    `neutral` role, not a refusal. Whenever the matching pattern being
    tested is one of the built-in six defaults (reached either via the
    `labels is None` path, or via a configured list that still contains
    that exact default entry — e.g. the desktop app's unmodified
    ToolConfig() default), a label that also exactly matches a scale
    family's top/neutral/bottom pattern (after the same fold_label
    normalisation the scale library itself uses, via
    `is_recognised_scale_point`) is exempt from that one default pattern,
    since an exact, deliberate scale-library classification takes
    precedence over the generic six-pattern floor. This exception is
    scoped to the six built-in defaults only: a label the analyst
    deliberately ADDS to their configured list — e.g. "Neutral", which is
    also a bare scale-library neutral pattern in every family, but is not
    one of the six defaults — is never exempted, because adding it was a
    specific, deliberate decision for that project (see
    test_adding_custom_label_changes_base_size /
    test_removing_default_label_stops_excluding_it). Net effect: the
    default-pattern question ("is this flagged by the six-pattern floor,
    once apostrophes are folded, minus its scale-library exceptions?")
    gets the same answer regardless of whether it's reached via `None` or
    via an unmodified default configured list, while any genuinely custom
    entry in a configured list remains fully authoritative with no
    scale-library exception.
    """
    folded = fold_label(label)
    if labels is None:
        candidates = zip(DEFAULT_NONSUBSTANTIVE_LABELS, _DEFAULT_LABEL_PATTERNS)
    else:
        patterns = _compile_patterns(tuple(labels))
        candidates = zip(labels, patterns)

    for source_label, pattern in candidates:
        if not pattern.search(folded):
            continue
        if fold_label(source_label) in _FOLDED_DEFAULTS and is_recognised_scale_point(label):
            continue
        return True
    return False


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
