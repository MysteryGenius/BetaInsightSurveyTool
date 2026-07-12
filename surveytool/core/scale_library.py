from __future__ import annotations

import re
from pathlib import Path

import yaml

from surveytool.core.model import CodeRole

_NEITHER_NOR = re.compile(r"neither.+nor", re.IGNORECASE)

_SCALES_PATH = Path(__file__).parent / "scales.yaml"


def _load_families() -> dict[str, dict[str, list[str]]]:
    raw = yaml.safe_load(_SCALES_PATH.read_text(encoding="utf-8"))
    return raw["families"]


_FAMILIES: dict[str, dict[str, list[str]]] = _load_families()


def _normalise(label: str) -> str:
    return label.replace("\xa0", " ").strip().lower()


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
        raise ValueError(
            f"Scale library could not resolve label(s): {unresolved}. "
            "Add an override or extend scales.yaml."
        )
    return result


def any_label_matches_family(labels: list[str]) -> bool:
    """True if at least one label matches some scale family's role patterns.

    Used by ingest adapters to distinguish a genuine non-scale categorical
    column (no label matches anything) from a scale column that the library
    only partially resolves (some labels match, others don't) — the latter
    must fail loudly rather than silently demote to single_choice.
    """
    return any(_match_role(_normalise(label)) is not None for label in labels)


def _label_in_family(norm: str, family: dict[str, list[str]]) -> bool:
    if norm in family["top_patterns"] or norm in family["bottom_patterns"]:
        return True
    return _is_neutral_label(norm, family)


def identify_family(labels: list[str]) -> str | None:
    """Return the scale family name if the full label set matches exactly one family."""
    normed = [_normalise(lb) for lb in labels]
    matches: list[str] = []
    for name, family in _FAMILIES.items():
        if all(_label_in_family(n, family) for n in normed):
            matches.append(name)
    return matches[0] if len(matches) == 1 else None
