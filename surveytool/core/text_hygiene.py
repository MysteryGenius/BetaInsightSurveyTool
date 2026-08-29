"""Whitespace, wrapping, and truncation policy shared by both chart
renderers and the findings sheet (Round C2).

normalise_whitespace is applied at the point text is READ (adapter parse
time, findings sheet build time) — not at render time — so the findings
sheet export and every chart derived from the same question text get
identical treatment; a renderer never re-normalises text that was already
normalised upstream, and never receives text that wasn't.
"""
from __future__ import annotations

import re
import textwrap

_WHITESPACE_RUN_RE = re.compile(r"\s+")


def normalise_whitespace(text: str) -> str:
    """Collapse any run of whitespace (space, tab, newline, non-breaking
    space, or any other Unicode whitespace \\s matches) to a single ASCII
    space, then strip leading/trailing whitespace.

    A run BETWEEN two non-whitespace characters always becomes exactly one
    space -- it never disappears, which is what prevents two sentences
    joined by a stripped newline from gluing into one word (the
    "citizens.By" defect). A wholly-whitespace input still collapses to an
    empty string after stripping, same as str.strip() -- there is no
    non-whitespace content on either side of that run to protect.
    """
    collapsed = _WHITESPACE_RUN_RE.sub(" ", text)
    return collapsed.strip()


def wrap_text(text: str, max_chars_per_line: int) -> list[str]:
    """Wrap text into lines of at most max_chars_per_line characters each,
    breaking on word boundaries. Thin wrapper over textwrap.wrap so both
    renderers call one shared policy rather than each hand-rolling their
    own wrap width/behaviour."""
    return textwrap.wrap(text, width=max_chars_per_line) or [text]


def truncate_with_ellipsis(text: str, max_chars: int) -> str:
    """Shorten text to at most max_chars characters, replacing truncated
    content with a trailing ellipsis. Text already within the limit is
    returned unchanged."""
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"
