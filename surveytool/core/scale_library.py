from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import yaml

from surveytool.charts.errors import UnresolvedScaleLabelsError
from surveytool.core.hygiene import fold_label
from surveytool.core.model import CodeRole, QuestionType

_NEITHER_NOR = re.compile(r"neither.+nor", re.IGNORECASE)

_SCALES_PATH = Path(__file__).parent / "scales.yaml"


def _load_families() -> dict[str, dict[str, list[str]]]:
    raw = yaml.safe_load(_SCALES_PATH.read_text(encoding="utf-8"))
    return raw["families"]


_FAMILIES: dict[str, dict[str, list[str]]] = _load_families()


def _normalise(label: str) -> str:
    return fold_label(label)


def _is_neutral_label(norm: str, family: dict[str, list[str]]) -> bool:
    """A label counts as neutral for a family if it matches the neither…nor
    regex, or is a literal member of that family's neutral_patterns."""
    return bool(_NEITHER_NOR.search(norm)) or norm in family["neutral_patterns"]


def _match_role(norm: str) -> CodeRole | None:
    for family in _FAMILIES.values():
        if norm in family["top_patterns"]:
            return CodeRole.top
        if _is_neutral_label(norm, family):
            return CodeRole.neutral
        if norm in family["bottom_patterns"]:
            return CodeRole.bottom
    return None


def resolve_roles(
    labels: list[str],
    override: dict[str, CodeRole] | None = None,
) -> dict[str, CodeRole]:
    """
    Map each label to a CodeRole.

    Resolution order:
    1. Explicit per-label override
    2. neither…nor regex → neutral
    3. Scale library pattern match
    4. Raise ValueError naming every unresolved label
    """
    result: dict[str, CodeRole] = {}
    unresolved: list[str] = []

    for label in labels:
        if override and label in override:
            result[label] = override[label]
            continue
        role = _match_role(_normalise(label))
        if role is None:
            unresolved.append(label)
        else:
            result[label] = role

    if unresolved:
        raise UnresolvedScaleLabelsError(unresolved)
    return result


def _label_in_family(norm: str, family: dict[str, list[str]]) -> bool:
    if norm in family["top_patterns"] or norm in family["bottom_patterns"]:
        return True
    return _is_neutral_label(norm, family)


def _role_in_family(norm: str, family: dict[str, list[str]]) -> CodeRole | None:
    """Like `_match_role`, but resolved against one specific family's
    patterns rather than searching every family in library order — needed
    wherever the caller has already chosen which family a label belongs to
    (e.g. the best-matching family in an ambiguous match), since a label
    can appear in more than one family's patterns and `_match_role` would
    silently return the role from whichever family it hits first."""
    if norm in family["top_patterns"]:
        return CodeRole.top
    if _is_neutral_label(norm, family):
        return CodeRole.neutral
    if norm in family["bottom_patterns"]:
        return CodeRole.bottom
    return None


def identify_family(labels: list[str]) -> str | None:
    """Return the scale family name if the full label set matches exactly one family."""
    normed = [_normalise(lb) for lb in labels]
    matches: list[str] = []
    for name, family in _FAMILIES.items():
        if all(_label_in_family(n, family) for n in normed):
            matches.append(name)
    return matches[0] if len(matches) == 1 else None


class MatchOutcome(str, Enum):
    """Result of matching a question's label set against the scale library."""

    full = "full"
    """Every label maps to a role in a single family."""
    partial = "partial"
    """At least one label maps to a family and at least one does not."""
    none = "none"
    """No label maps to any family."""


@dataclass(frozen=True)
class FamilyMatch:
    """Richer, non-raising result of matching a question's labels against
    the scale library — unlike `identify_family`, this distinguishes a
    partial match (some labels resolve, some don't) from a genuine
    non-match (nothing resolves), and records which specific labels fell on
    each side plus the role each matched label would take.

    outcome: MatchOutcome.full / .partial / .none.
    family: the family name for a full or partial match; None for no match.
        When candidate families tie or multiple families each match at
        least one label, this is the family with the highest count of
        matched labels (ties broken by _FAMILIES iteration order).
    matched_labels: original (unnormalised) label text -> CodeRole, for
        every label that matched `family`'s patterns. Empty for no match.
    unmatched_labels: original (unnormalised) label text for every label
        that did not match `family`'s patterns, in input order. Empty for
        a full match.
    ambiguous: True if labels matched (at least partially) across more
        than one family — `family` is then the family with the highest
        match count, chosen deterministically, but callers should treat
        the result as uncertain.
    """

    outcome: MatchOutcome
    family: str | None
    matched_labels: dict[str, CodeRole]
    unmatched_labels: list[str]
    ambiguous: bool


def match_family(labels: list[str]) -> FamilyMatch:
    """Match a question's full label set against every scale family and
    report how well it fits the best-matching family, without raising.

    Unlike `identify_family` (which only succeeds when every label matches
    exactly one family), this reports partial matches — useful for telling
    "one label short of a known scale" apart from "not a scale at all".

    Where labels match across more than one family, the family with the
    highest count of matched labels is reported and `ambiguous` is set.
    """
    normed = [_normalise(lb) for lb in labels]

    counts: dict[str, int] = {}
    for name, family in _FAMILIES.items():
        count = sum(1 for n in normed if _label_in_family(n, family))
        if count > 0:
            counts[name] = count

    if not counts:
        return FamilyMatch(
            outcome=MatchOutcome.none,
            family=None,
            matched_labels={},
            unmatched_labels=list(labels),
            ambiguous=False,
        )

    best_family = max(counts, key=lambda name: counts[name])
    ambiguous = len(counts) > 1

    family_def = _FAMILIES[best_family]
    matched_labels: dict[str, CodeRole] = {}
    unmatched_labels: list[str] = []
    for label, norm in zip(labels, normed):
        if _label_in_family(norm, family_def):
            role = _role_in_family(norm, family_def)
            assert role is not None
            matched_labels[label] = role
        else:
            unmatched_labels.append(label)

    outcome = MatchOutcome.partial if unmatched_labels else MatchOutcome.full

    return FamilyMatch(
        outcome=outcome,
        family=best_family,
        matched_labels=matched_labels,
        unmatched_labels=unmatched_labels,
        ambiguous=ambiguous,
    )


def classify_question_type(
    labels: list[str],
) -> tuple[QuestionType, dict[str, CodeRole] | None, str | None] | None:
    """Classify a question's substantive labels as SCALE or BINARY.

    SCALE: every label matches a single family (identify_family succeeds).
    Netting applies; returns the resolved roles and family name.

    BINARY: exactly two labels, and they match the 'binary' family.
    No netting; roles/family are None since a binary question has no
    top/neutral/bottom ordering to net over.

    Neither: returns None. CATEGORICAL is no longer inferred here — a
    label set that doesn't achieve a full scale or binary match (including
    a genuine partial match, where some labels match a family and others
    don't) is not this function's business to demote silently. Callers
    (the vendor adapters, via the load-path collector in
    surveytool.ingest.validate_questions) collect a None result as an
    unresolved question for the analyst to confirm via the resolver.
    CATEGORICAL remains a valid Question.qtype, but only ever as the
    outcome of a stored project override, never as an inference from a
    failed match — see Task 5's brief.
    """
    normed = [_normalise(lb) for lb in labels]

    if len(labels) == 2:
        binary_family = _FAMILIES.get("binary")
        if binary_family is not None and all(_label_in_family(n, binary_family) for n in normed):
            return QuestionType.binary, None, None

    family = identify_family(labels)
    if family is not None:
        roles = {lb: role for lb, role in zip(labels, (_match_role(n) for n in normed))}
        return QuestionType.scale, roles, family

    return None
