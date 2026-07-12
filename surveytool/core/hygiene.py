from __future__ import annotations

from surveytool.core.model import CodeRole


def normalize_label(label: str) -> str:
    """Strip whitespace and replace non-breaking spaces with regular spaces."""
    return label.replace("\xa0", " ").strip()


def report_unresolved(
    labels: list[str],
    resolved: dict[str, CodeRole],
) -> list[str]:
    """Return labels that did not appear in the resolved mapping."""
    return [lb for lb in labels if lb not in resolved]
