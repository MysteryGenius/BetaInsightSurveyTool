from __future__ import annotations

import re

from surveytool.core.model import CodeRole
from surveytool.core.text_hygiene import normalise_whitespace

_DASH_FOLD = str.maketrans({
    "–": "-",  # en dash
    "—": "-",  # em dash
    "‑": "-",  # non-breaking hyphen
})
_QUOTE_FOLD = str.maketrans({
    "‘": "'",  # left single quote
    "’": "'",  # right single quote / apostrophe
    "“": '"',  # left double quote
    "”": '"',  # right double quote
})
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_label(label: str) -> str:
    """Normalise a label or question text: collapse any internal
    whitespace run (space, tab, newline, non-breaking space) to a single
    space, and strip leading/trailing whitespace. Delegates to
    surveytool.core.text_hygiene.normalise_whitespace, the single shared
    policy both chart renderers and the findings sheet rely on having
    already been applied to any text they receive (Round C2)."""
    return normalise_whitespace(label)


def fold_label(label: str) -> str:
    """Normalise a label for scale-library comparison.

    Folds en-dash, em-dash, and non-breaking hyphen to ASCII hyphen; folds
    non-breaking space to space; folds curly quotes/apostrophes to straight;
    case folds; collapses whitespace runs; strips leading/trailing
    whitespace. Nothing else — no stemming, no fuzzy distance, no substring
    guessing, so a wrong net is never silently produced from an approximate
    match.
    """
    folded = label.translate(_DASH_FOLD).translate(_QUOTE_FOLD)
    folded = folded.replace("\xa0", " ")
    folded = folded.casefold()
    folded = _WHITESPACE_RE.sub(" ", folded)
    return folded.strip()


def report_unresolved(
    labels: list[str],
    resolved: dict[str, CodeRole],
) -> list[str]:
    """Return labels that did not appear in the resolved mapping."""
    return [lb for lb in labels if lb not in resolved]
