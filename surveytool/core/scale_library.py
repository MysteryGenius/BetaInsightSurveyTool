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


def _match_role(norm: str) -> CodeRole | None:
    if _NEITHER_NOR.search(norm):
        return CodeRole.neutral
    for family in _FAMILIES.values():
        if norm in family["top_patterns"]:
            return CodeRole.top
        if norm in family["neutral_patterns"]:
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


def identify_family(labels: list[str]) -> str | None:
    """Return the scale family name if the full label set matches exactly one family."""
    normed = [_normalise(lb) for lb in labels]
    matches: list[str] = []
    for name, family in _FAMILIES.items():
        all_patterns = (
            family["top_patterns"]
            + family["neutral_patterns"]
            + family["bottom_patterns"]
        )
        if all(n in all_patterns for n in normed):
            matches.append(name)
    return matches[0] if len(matches) == 1 else None
