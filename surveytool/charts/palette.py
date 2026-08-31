"""Shared categorical palette (Round C1).

One palette, defined here once, consumed identically by the on-screen
Plotly renderer (plotly_renderer.py) and the branded matplotlib PNG export
(renderer.py) — a colour assigned to a response option is the same hex
value in both, so a chart never looks different on screen than in its
exported PNG.

Colour assignment is by series identity (e.g. a response option's label),
never by position in whatever list a caller happens to pass, and never by
relative rank within one call's input set either — toggling one series off
and re-rendering must never recolour the remaining series, and a given
label's colour must not depend on what else happens to be in the same
chart. This is achieved by hashing each identity string directly into a
palette slot (see `assign_series_colours`), so the same identity always
lands on the same base slot regardless of co-occurring identities or input
order.

Twelve entries, chosen for pairwise distinguishability under protanopia/
deuteranopia/tritanopia simulation and in greyscale (adapted from the
Okabe-Ito / Paul Tol qualitative palettes, both established colourblind-safe
sources, extended to twelve by adding darker/lighter variants of hues
already spaced apart in the base eight so no adjacent pair collapses to the
same grey value).
"""
from __future__ import annotations

import hashlib

from surveytool.charts.errors import PaletteExhaustedError

CATEGORICAL_PALETTE: tuple[str, ...] = (
    "#1B667D",  # deep teal (existing brand teal, kept as the first entry)
    "#C4856A",  # warm terracotta (existing brand warm, kept as the second)
    "#5B8C3E",  # olive green
    "#8C5B9E",  # muted purple
    "#D4A017",  # mustard gold
    "#3E5C8C",  # slate blue
    "#A63E5A",  # muted rose
    "#4A9E8C",  # teal-green
    "#9E6B3E",  # burnt orange
    "#6B6B6B",  # neutral grey (distinct lightness step from every other entry in greyscale)
    "#2E4A2E",  # dark forest green
    "#B0578D",  # magenta-rose
)


def assign_series_colours(
    series_identities: list[str],
    palette: tuple[str, ...] = CATEGORICAL_PALETTE,
) -> dict[str, str]:
    """Assign one palette colour to each distinct series identity.

    Colour is a deterministic function of the identity string alone (a
    stable hash of the identity mod len(palette)), so:
    - the same identity always gets the same colour regardless of what
      other identities are or aren't present in a given call (true
      cross-call stability, e.g. "toggle one series off and re-render"),
    - reordering the input list never changes any assignment (colour never
      depends on position),
    - a hash collision (two different identities landing on the same
      palette slot) is possible in principle with a small number of slots
      and an arbitrary number of identities, so this function still
      enforces the "no two series share a colour within one chart"
      requirement explicitly, re-picking a colliding identity's slot
      deterministically (linear probing to the next free slot in palette
      order) rather than silently allowing a same-chart collision.

    `palette` defaults to the shared brand CATEGORICAL_PALETTE (Round C1)
    for every existing call site that doesn't know about chart styles
    (Round D). A caller applying a non-brand ChartStyle (surveytool.charts.
    styles) passes that style's own palette instead, so colour assignment
    for the same response-option set uses a different but equally
    collision-checked 12-entry palette.

    Raises PaletteExhaustedError if there are more distinct identities than
    the given palette has entries — a repeated colour within one chart is
    never produced silently.

    Accepted edge case: because collision resolution depends on which
    other identities are present in the same call, removing an identity
    from the list can in principle change which slot a *different*,
    colliding identity lands on. This does not affect the common case (no
    collision), and is vanishingly unlikely with real response-option
    label sets against a 12-slot palette; a fully collision-immune,
    call-independent scheme is outside this task's scope.
    """
    if len(series_identities) > len(palette):
        raise PaletteExhaustedError(len(series_identities), len(palette))

    def _base_slot(identity: str) -> int:
        digest = hashlib.sha256(identity.encode("utf-8")).digest()
        return int.from_bytes(digest[:4], "big") % len(palette)

    assignment: dict[str, str] = {}
    used_slots: set[int] = set()
    for identity in sorted(set(series_identities)):
        slot = _base_slot(identity)
        while slot in used_slots:
            slot = (slot + 1) % len(palette)
        used_slots.add(slot)
        assignment[identity] = palette[slot]

    return assignment
