# Chart Style Selector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an analyst pick one of a small set of preset visual chart styles (palette + background + font colour) per question, in the breaks-view chart panel, persisted per survey per question, reaching both the on-screen Plotly chart and its branded PNG export.

**Architecture:** A new `surveytool/charts/styles.py` defines a frozen `ChartStyle` dataclass and a `STYLE_REGISTRY` of four presets (`brand`, `high_contrast`, `cool`, `warm`). `surveytool/charts/palette.py`'s `assign_series_colours` gains an explicit `palette` parameter (defaulting to the existing `CATEGORICAL_PALETTE`) so a style's own palette can flow through the same hash-based assignment logic. A new `surveytool/ingest/chart_style.py`, structurally identical to `surveytool/ingest/display_order.py`, stores one YAML file per survey mapping qid → chosen style name, validated against `STYLE_REGISTRY` at write time. Three new desktop endpoints in `surveytool/desktop/app.py` (`GET`/`PUT`/`DELETE /api/projects/{survey_id}/chart-style/{qid}`) mirror the existing display-order endpoints exactly. `compute_breaks_crosstab` gains a `chart_styles` parameter threaded into a new `QuestionResult.chart_style` field. `plotly_renderer.py`'s `build_figure` resolves the style once via `get_style` and threads it into `_apply_header` (background/font) and every bar-builder's `assign_series_colours` call (palette). The on-screen figure and the exported PNG are the same `Figure` object rasterized via kaleido, so wiring style into `plotly_renderer.py` alone makes both consistent by construction — `surveytool/charts/renderer.py` (the separate matplotlib pipeline for the legacy `dist`/`xbreak`/`means` chart system) is untouched, the same scope boundary Task C3's manual display order already drew. A new `buildChartStyleRow` in `surveytool/desktop/static/breaks.js`, modeled on the existing `buildChartTypeRow`, adds a style button row that optimistically re-renders client-side and persists via a background `PUT`.

**Tech Stack:** Python, Plotly, Pydantic, PyYAML, pytest, FastAPI (desktop/app.py). No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-31-chart-style-selector-design.md` — this plan implements that design in full. Read both together; this plan does not repeat the spec's rationale, only its concrete tasks.

## Global Constraints

- Full test suite must be green before moving to the next task and before this plan is considered done. Confirm the exact baseline count immediately before Task 1 Step 1 by running `python -m pytest -q` and record it.
- `brand` is the default style; every existing caller of `build_figure`/`assign_series_colours`/`compute_breaks_crosstab` that doesn't know about style gets byte-for-byte identical output to today (`chart_style=None` → `get_style(None)` → `DEFAULT_STYLE` = `brand`, which reuses `CATEGORICAL_PALETTE` and the current hardcoded `#F4F1EA`/`#222222` colours verbatim). This is the same "additive, nothing changes unless opted in" guarantee Round C1/C3 both maintained — no existing test's exact-colour or exact-figure assertion may change as a result of this feature.
- Style is per-question only, for this iteration — no global or resolver-level default style setting (explicitly out of scope per spec).
- No individual colour customization (picking an exact hex per response option) — explicitly out of scope per spec.
- The legacy `dist`/`xbreak`/`means` chart system (`surveytool/charts/renderer.py`, `surveytool/charts/chart_data.py`) is out of scope, same boundary `display_order.py`'s module docstring already documents for manual display order — this plan's new `chart_style.py` module docstring must state the same boundary for style.
- Every new dataclass/model follows the codebase's existing pattern: frozen dataclasses (`@dataclass(frozen=True)`) for pure value objects (`ChartStyle`), Pydantic `BaseModel` for anything crossing an API/serialization boundary (`ChartStyleChoice`, `ProjectChartStyles`, the endpoint payload models).
- New errors subclass `SurveyToolError` with a new `ErrorCode` member, a plain-English message, a `detail`, and a `next_action` — matching every existing error class in `surveytool/charts/errors.py`.
- Per persistent project memory: end users of this tool are non-technical — any new user-facing error message (e.g. an unknown style name rejected at write time, a corrupted chart-style file) must be plain English with a concrete remediation step, not a technical/internal-sounding message.
- The three non-brand presets' exact palette hex values are genuine implementation-time design work (Task 2 below) — they must be picked and validated for colourblind-safety and greyscale-distinguishability the same way Task C1's original `CATEGORICAL_PALETTE` was validated, never invented as arbitrary placeholder values.

---

### Task 1: `assign_series_colours` accepts an explicit palette parameter

**Files:**
- Modify: `surveytool/charts/palette.py`
- Test: `tests/test_palette.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `surveytool.charts.palette.assign_series_colours(series_identities: list[str], palette: tuple[str, ...] = CATEGORICAL_PALETTE) -> dict[str, str]` — same hash-based, identity-stable assignment logic as today, but resolved against whichever `palette` tuple is passed, defaulting to `CATEGORICAL_PALETTE` so every existing call site (none of which pass `palette` yet) is unaffected.

- [ ] **Step 1: Confirm the current test baseline**

Run: `python -m pytest -q`
Expected: whatever the current green baseline is. Record it — this plan's every later "run full suite" step compares against this number.

- [ ] **Step 2: Write the failing test for the new parameter**

Add to `tests/test_palette.py`:

```python
def test_assign_series_colours_accepts_explicit_palette():
    custom_palette = ("#111111", "#222222", "#333333")
    assignment = assign_series_colours(["A", "B"], palette=custom_palette)
    assert set(assignment.values()) <= set(custom_palette)


def test_assign_series_colours_default_palette_unchanged():
    """Confirms the default-parameter form is byte-identical to calling
    with no palette argument at all -- the existing call-site contract
    (plotly_renderer.py's three bar builders, none of which pass palette)
    must not change behaviour."""
    identities = ["Option A", "Option B", "Option C"]
    assert assign_series_colours(identities) == assign_series_colours(identities, palette=CATEGORICAL_PALETTE)


def test_assign_series_colours_raises_when_exceeding_explicit_palette_size():
    with pytest.raises(PaletteExhaustedError):
        assign_series_colours(["A", "B", "C", "D"], palette=("#111111", "#222222", "#333333"))
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_palette.py -k "explicit_palette or default_palette_unchanged or exceeding_explicit" -v`
Expected: `FAIL` — `assign_series_colours()` doesn't accept a `palette` keyword yet (`TypeError`).

- [ ] **Step 4: Add the `palette` parameter**

In `surveytool/charts/palette.py`, change the signature and every reference to `CATEGORICAL_PALETTE` inside the function body to use the parameter instead:

```python
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
```

- [ ] **Step 5: Run the palette tests**

Run: `python -m pytest tests/test_palette.py -v`
Expected: `PASS`, including every pre-existing test in the file (the default-parameter form must still satisfy all of Round C1's original assertions unchanged).

- [ ] **Step 6: Run the full suite**

Run: `python -m pytest -q`
Expected: all green, count higher than Step 1's baseline by 3 (the new tests). No existing test's expected colour values change, since every existing call site calls `assign_series_colours(identities)` with no `palette` argument and gets the identical default.

- [ ] **Step 7: Commit**

```bash
git add surveytool/charts/palette.py tests/test_palette.py
git commit -m "feat: assign_series_colours accepts an explicit palette parameter"
```

---

### Task 2: Pick and validate the three non-brand palettes, and build `styles.py`

**Files:**
- Create: `surveytool/charts/styles.py`
- Test: `tests/test_styles.py` (new)

**Interfaces:**
- Consumes: `surveytool.charts.palette.CATEGORICAL_PALETTE` (Task C1, unchanged).
- Produces:
  - `surveytool.charts.styles.ChartStyle` — frozen dataclass: `name: str`, `palette: tuple[str, ...]`, `background: str`, `font_color: str`.
  - `surveytool.charts.styles.STYLE_REGISTRY: dict[str, ChartStyle]` — keyed by `name`, four entries: `brand`, `high_contrast`, `cool`, `warm`.
  - `surveytool.charts.styles.DEFAULT_STYLE: ChartStyle` — the `brand` entry.
  - `surveytool.charts.styles.get_style(name: str | None) -> ChartStyle` — `None` or an unknown name both fall back to `DEFAULT_STYLE` silently.

- [ ] **Step 1: Confirm baseline**

Run: `python -m pytest -q`
Record the current passed count (after Task 1).

- [ ] **Step 2: Pick and validate three new 12-entry palettes**

This is real design work, not a value to guess at. Each of `high_contrast`, `cool`, and `warm` needs its own distinct 12-entry hex palette (not a recolouring of `CATEGORICAL_PALETTE`), validated the same way Task C1's original palette was validated (per its module docstring: "chosen for pairwise distinguishability under protanopia/deuteranopia/tritanopia simulation and in greyscale").

Write a throwaway validation script at `scratch_validate_palettes.py` (delete it in Step 5 once the palettes are finalized in `styles.py` — it is not part of the shipped codebase) that, for each candidate palette:

1. Converts every hex colour to greyscale luminance (`L = 0.299*R + 0.587*G + 0.114*B`) and confirms every pairwise luminance difference is at least 25 (on a 0-255 scale) — the same kind of numeric floor that makes two entries distinguishable when a chart is printed or viewed in greyscale. Report any pair below the floor.
2. Simulates protanopia, deuteranopia, and tritanopia for each colour using a standard simplified simulation matrix (e.g. the Brettel/Viénot-derived matrices commonly used for this purpose — implement directly in the script, no new dependency) and confirms every pairwise Euclidean RGB distance under each simulation is at least 30 (on a 0-255 per-channel scale). Report any pair below the floor.
3. Confirms all 12 entries are syntactically valid 7-character `#RRGGBB` hex strings and pairwise-distinct.

```python
# scratch_validate_palettes.py -- delete after Step 5; not part of the
# shipped codebase, used only to numerically justify the three new
# palettes hard-coded into styles.py.
from itertools import combinations


def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _luminance(rgb: tuple[int, int, int]) -> float:
    r, g, b = rgb
    return 0.299 * r + 0.587 * g + 0.114 * b


# Simplified protanopia/deuteranopia/tritanopia simulation matrices
# (Machado, Oliveira, Fluck 2009 -- commonly used approximations).
_SIM_MATRICES = {
    "protanopia": ((0.152, 1.053, -0.205), (0.115, 0.786, 0.099), (-0.004, -0.048, 1.052)),
    "deuteranopia": ((0.367, 0.861, -0.228), (0.280, 0.673, 0.047), (-0.012, 0.043, 0.969)),
    "tritanopia": ((1.256, -0.077, -0.179), (-0.078, 0.931, 0.148), (0.005, 0.691, 0.304)),
}


def _simulate(rgb: tuple[int, int, int], kind: str) -> tuple[float, float, float]:
    m = _SIM_MATRICES[kind]
    r, g, b = rgb
    return (
        m[0][0] * r + m[0][1] * g + m[0][2] * b,
        m[1][0] * r + m[1][1] * g + m[1][2] * b,
        m[2][0] * r + m[2][1] * g + m[2][2] * b,
    )


def _distance(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


def validate(name: str, palette: tuple[str, ...]) -> None:
    print(f"--- {name} ({len(palette)} entries) ---")
    assert len(palette) == 12, f"{name} must have exactly 12 entries, has {len(palette)}"
    assert len(set(palette)) == 12, f"{name} has duplicate hex values"
    for h in palette:
        assert h.startswith("#") and len(h) == 7, f"{name}: {h!r} is not a valid #RRGGBB hex string"

    rgbs = [_hex_to_rgb(h) for h in palette]
    failures = []

    for (i, a), (j, b) in combinations(enumerate(rgbs), 2):
        lum_diff = abs(_luminance(a) - _luminance(b))
        if lum_diff < 25:
            failures.append(f"  greyscale: {palette[i]} vs {palette[j]} luminance diff {lum_diff:.1f} < 25")
        for kind in _SIM_MATRICES:
            sim_a, sim_b = _simulate(a, kind), _simulate(b, kind)
            dist = _distance(sim_a, sim_b)
            if dist < 30:
                failures.append(f"  {kind}: {palette[i]} vs {palette[j]} distance {dist:.1f} < 30")

    if failures:
        print(f"FAILED ({len(failures)} violations):")
        for f in failures:
            print(f)
    else:
        print("PASSED: all pairs distinguishable in greyscale and under all three colourblindness simulations.")


if __name__ == "__main__":
    # Candidate palettes to validate -- iterate on these hex values until
    # every one prints PASSED, then copy the final values into styles.py.
    CANDIDATES = {
        "high_contrast": (
            "#000000", "#FFFFFF", "#E69F00", "#56B4E9",
            "#009E73", "#F0E442", "#0072B2", "#D55E00",
            "#CC79A7", "#999999", "#663300", "#004D40",
        ),
        "cool": (
            "#0D3B66", "#1B998B", "#3A506B", "#5C80BC",
            "#6A4C93", "#457B9D", "#264653", "#2A9D8F",
            "#8AB6D6", "#3D5A80", "#98C1D9", "#293241",
        ),
        "warm": (
            "#7A2E1B", "#C9483C", "#E07A5F", "#F4A259",
            "#8C3B3B", "#B5651D", "#D8973C", "#6B3E26",
            "#A44A3F", "#E8C170", "#9C5A3C", "#5C3A21",
        ),
    }
    for name, palette in CANDIDATES.items():
        validate(name, palette)
```

Run: `python scratch_validate_palettes.py`

If any palette reports failures, adjust the specific colliding hex values (nudge hue/lightness of one of the two colliding entries) and re-run until all three candidates print `PASSED`. Record the final validated hex tuples — these are what Step 3 hard-codes into `styles.py`. Do not proceed to Step 3 with a palette that failed validation.

- [ ] **Step 3: Write the failing tests**

Create `tests/test_styles.py`:

```python
from surveytool.charts.styles import ChartStyle, DEFAULT_STYLE, STYLE_REGISTRY, get_style
from surveytool.charts.palette import CATEGORICAL_PALETTE


def test_registry_has_exactly_four_presets():
    assert set(STYLE_REGISTRY) == {"brand", "high_contrast", "cool", "warm"}


def test_brand_is_the_default_style():
    assert DEFAULT_STYLE.name == "brand"
    assert DEFAULT_STYLE is STYLE_REGISTRY["brand"]


def test_brand_reuses_categorical_palette_verbatim():
    assert STYLE_REGISTRY["brand"].palette == CATEGORICAL_PALETTE


def test_brand_matches_current_hardcoded_colours():
    """Byte-for-byte match to the values plotly_renderer._apply_header
    hardcodes today (#F4F1EA / #222222) -- the additive guarantee that
    choosing no style is identical to today's behaviour."""
    assert STYLE_REGISTRY["brand"].background == "#F4F1EA"
    assert STYLE_REGISTRY["brand"].font_color == "#222222"


def test_every_preset_has_twelve_distinct_palette_entries():
    for style in STYLE_REGISTRY.values():
        assert len(style.palette) == 12, style.name
        assert len(set(style.palette)) == 12, style.name


def test_non_brand_presets_have_their_own_distinct_palette():
    """Each non-brand preset's palette must be its own set, not a
    recolouring/reuse of CATEGORICAL_PALETTE or of each other."""
    palettes = [STYLE_REGISTRY[name].palette for name in ("high_contrast", "cool", "warm")]
    all_palettes = [CATEGORICAL_PALETTE, *palettes]
    for i in range(len(all_palettes)):
        for j in range(i + 1, len(all_palettes)):
            assert all_palettes[i] != all_palettes[j]


def test_get_style_returns_named_style():
    assert get_style("cool") is STYLE_REGISTRY["cool"]


def test_get_style_none_falls_back_to_brand():
    assert get_style(None) is DEFAULT_STYLE


def test_get_style_unknown_name_falls_back_to_brand_silently():
    assert get_style("nonexistent_style_name") is DEFAULT_STYLE


def test_chart_style_is_frozen():
    style = STYLE_REGISTRY["brand"]
    try:
        style.name = "changed"
        assert False, "ChartStyle must be frozen"
    except AttributeError:
        pass
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `python -m pytest tests/test_styles.py -v`
Expected: `FAIL` — `surveytool.charts.styles` does not exist.

- [ ] **Step 5: Write `styles.py` with the validated palettes, then delete the scratch script**

Create `surveytool/charts/styles.py`, substituting Step 2's final validated hex tuples for `high_contrast`/`cool`/`warm` (do not use the illustrative candidate values verbatim without having actually run the validator on them — Step 2 is where the real numbers get fixed):

```python
"""Chart style presets (chart style selector feature).

A ChartStyle varies exactly three things about a rendered chart: its
categorical palette, its background colour, and its font colour. Nothing
else -- chart type, layout, spacing, and typography (font family/weight)
are unaffected by style, per the feature's design spec.

`brand` is the default: it reuses palette.py's CATEGORICAL_PALETTE
verbatim and the background/font-colour values plotly_renderer.py has
always hardcoded, so choosing no style is byte-for-byte identical to
pre-this-feature behaviour (the same "additive, nothing changes unless
opted in" guarantee Round C1/C3 both maintained).

Each non-brand preset has its own independently validated 12-entry
palette (not a recolouring of CATEGORICAL_PALETTE) -- checked for pairwise
distinguishability in greyscale and under protanopia/deuteranopia/
tritanopia simulation the same way CATEGORICAL_PALETTE itself was
validated (see palette.py's module docstring, and the validation script
used when this file's palettes were picked).
"""
from __future__ import annotations

from dataclasses import dataclass

from surveytool.charts.palette import CATEGORICAL_PALETTE


@dataclass(frozen=True)
class ChartStyle:
    name: str
    palette: tuple[str, ...]
    background: str
    font_color: str


_BRAND = ChartStyle(
    name="brand",
    palette=CATEGORICAL_PALETTE,
    background="#F4F1EA",
    font_color="#222222",
)

_HIGH_CONTRAST = ChartStyle(
    name="high_contrast",
    palette=(
        # <-- Step 2's validated high_contrast hex tuple goes here -->
    ),
    background="#FFFFFF",
    font_color="#000000",
)

_COOL = ChartStyle(
    name="cool",
    palette=(
        # <-- Step 2's validated cool hex tuple goes here -->
    ),
    background="#F0F4F7",
    font_color="#1A2733",
)

_WARM = ChartStyle(
    name="warm",
    palette=(
        # <-- Step 2's validated warm hex tuple goes here -->
    ),
    background="#FBF3EC",
    font_color="#332118",
)

STYLE_REGISTRY: dict[str, ChartStyle] = {s.name: s for s in (_BRAND, _HIGH_CONTRAST, _COOL, _WARM)}
DEFAULT_STYLE: ChartStyle = _BRAND


def get_style(name: str | None) -> ChartStyle:
    """Resolve a style name to its ChartStyle. None (no style chosen) and
    an unknown name (a style deleted from the registry after being saved,
    or corrupted input) both fall back to DEFAULT_STYLE silently -- a
    chart must never fail to render because of an unrecognised style
    name."""
    if name is None:
        return DEFAULT_STYLE
    return STYLE_REGISTRY.get(name, DEFAULT_STYLE)
```

Delete `scratch_validate_palettes.py` — it was a one-time design tool, not shipped code.

- [ ] **Step 6: Run the styles tests**

Run: `python -m pytest tests/test_styles.py -v`
Expected: `PASS`.

- [ ] **Step 7: Run the full suite**

Run: `python -m pytest -q`
Expected: all green.

- [ ] **Step 8: Commit**

```bash
git add surveytool/charts/styles.py tests/test_styles.py
git rm --cached scratch_validate_palettes.py 2>/dev/null || true
git commit -m "feat: chart style presets with validated colourblind-safe palettes"
```

---

### Task 3: `surveytool/ingest/chart_style.py` — per-survey style storage

**Files:**
- Create: `surveytool/ingest/chart_style.py`
- Modify: `surveytool/charts/errors.py`
- Test: `tests/test_chart_style.py` (new)

**Interfaces:**
- Consumes: `surveytool.charts.styles.STYLE_REGISTRY` (Task 2).
- Produces:
  - `surveytool.ingest.chart_style.ChartStyleChoice` — Pydantic `BaseModel`: `variable: str`, `style_name: str`, `saved_at: datetime`.
  - `surveytool.ingest.chart_style.ProjectChartStyles` — Pydantic `BaseModel`: `styles: dict[str, ChartStyleChoice]`, keyed by qid.
  - `surveytool.ingest.chart_style.load_chart_styles(path: Path) -> ProjectChartStyles`.
  - `surveytool.ingest.chart_style.write_chart_style(path: Path, choice: ChartStyleChoice) -> None` — raises `UnknownChartStyleError` if `choice.style_name` is not a key in `STYLE_REGISTRY`.
  - `surveytool.ingest.chart_style.delete_chart_style(path: Path, variable: str) -> None`.
  - `surveytool.ingest.chart_style.CorruptedChartStyleFileError(SurveyToolError)`.
  - `surveytool.charts.errors.UnknownChartStyleError(SurveyToolError)` — new. New `ErrorCode.UNKNOWN_CHART_STYLE`.

- [ ] **Step 1: Confirm baseline**

Run: `python -m pytest -q`

- [ ] **Step 2: Add `UnknownChartStyleError`**

In `surveytool/charts/errors.py`, add to `ErrorCode` (after `RENAME_FAILED`):

```python
    UNKNOWN_CHART_STYLE = "UNKNOWN_CHART_STYLE"
```

Add to `_STATUS_BY_CODE`:

```python
    ErrorCode.UNKNOWN_CHART_STYLE: 400,
```

Add the error class after `RenameFailedError` (check `grep -n "^class" surveytool/charts/errors.py` first to confirm it is still the last class):

```python
class UnknownChartStyleError(SurveyToolError):
    """Raised when a chart-style choice is written with a style_name that
    isn't in surveytool.charts.styles.STYLE_REGISTRY. A chart style choice
    is never persisted unvalidated -- an unrecognised name at save time is
    almost always a stale client (an old page that still offers a style
    that was since removed), not something to silently coerce to brand and
    save anyway."""

    def __init__(self, style_name: str, known_names: list[str]) -> None:
        self.style_name = style_name
        self.known_names = known_names
        detail = f"Requested style_name={style_name!r}; known styles: {', '.join(known_names)}."
        super().__init__(
            ErrorCode.UNKNOWN_CHART_STYLE,
            f"'{style_name}' isn't a chart style this tool recognises.",
            detail=detail,
            next_action=f"Choose one of: {', '.join(known_names)}. Reloading the page may also help if this style was recently removed.",
        )
```

- [ ] **Step 3: Write the failing tests**

Create `tests/test_chart_style.py` (mirrors `tests/test_display_order.py` exactly):

```python
from datetime import datetime, timezone
from pathlib import Path

import pytest

from surveytool.ingest.chart_style import (
    ChartStyleChoice,
    ProjectChartStyles,
    load_chart_styles,
    write_chart_style,
    delete_chart_style,
    CorruptedChartStyleFileError,
)
from surveytool.charts.errors import UnknownChartStyleError


def test_load_chart_styles_returns_empty_for_missing_file(tmp_path):
    result = load_chart_styles(tmp_path / "does_not_exist.yaml")
    assert result.styles == {}


def test_write_then_load_round_trips(tmp_path):
    path = tmp_path / "styles.yaml"
    choice = ChartStyleChoice(variable="Q7", style_name="cool", saved_at=datetime.now(timezone.utc))
    write_chart_style(path, choice)
    loaded = load_chart_styles(path)
    assert loaded.styles["Q7"].style_name == "cool"


def test_write_overwrites_existing_entry_for_same_variable(tmp_path):
    path = tmp_path / "styles.yaml"
    first = ChartStyleChoice(variable="Q7", style_name="cool", saved_at=datetime.now(timezone.utc))
    second = ChartStyleChoice(variable="Q7", style_name="warm", saved_at=datetime.now(timezone.utc))
    write_chart_style(path, first)
    write_chart_style(path, second)
    loaded = load_chart_styles(path)
    assert loaded.styles["Q7"].style_name == "warm"


def test_write_rejects_unknown_style_name(tmp_path):
    path = tmp_path / "styles.yaml"
    choice = ChartStyleChoice(variable="Q7", style_name="not_a_real_style", saved_at=datetime.now(timezone.utc))
    with pytest.raises(UnknownChartStyleError):
        write_chart_style(path, choice)
    # Nothing was written.
    assert load_chart_styles(path).styles == {}


def test_delete_chart_style_is_a_noop_when_nothing_saved(tmp_path):
    path = tmp_path / "styles.yaml"
    delete_chart_style(path, "Q7")  # must not raise
    assert load_chart_styles(path).styles == {}


def test_delete_chart_style_removes_entry(tmp_path):
    path = tmp_path / "styles.yaml"
    write_chart_style(path, ChartStyleChoice(variable="Q7", style_name="cool", saved_at=datetime.now(timezone.utc)))
    delete_chart_style(path, "Q7")
    assert load_chart_styles(path).styles == {}


def test_corrupted_file_raises_rather_than_silently_resetting(tmp_path):
    path = tmp_path / "styles.yaml"
    path.write_text("not: [valid, yaml: structure for this model", encoding="utf-8")
    with pytest.raises(CorruptedChartStyleFileError):
        load_chart_styles(path)
```

- [ ] **Step 4: Run to verify they fail**

Run: `python -m pytest tests/test_chart_style.py -v`
Expected: `FAIL` — module doesn't exist.

- [ ] **Step 5: Write `chart_style.py`**

Create `surveytool/ingest/chart_style.py`:

```python
"""Manual per-question chart style choice (chart style selector feature).

Structurally identical to display_order.py: one YAML file per survey_id,
keyed by qid, following the same load/write/round-trip and corrupted-file
handling pattern. A ChartStyleChoice is orthogonal to both classification
(overrides.py) and manual display order (display_order.py) -- it never
changes which points exist, their role/rank, or their display order, only
which ChartStyle (surveytool.charts.styles) a chart is rendered with.

style_name is validated against surveytool.charts.styles.STYLE_REGISTRY at
write time and rejected with a plain-English UnknownChartStyleError if
unrecognised -- never persisted unvalidated, since a bad style_name
written today would need get_style's silent fallback to mask it forever
after (get_style itself falls back for defense in depth on read, but this
module refuses to ever write a name get_style would have to fall back
from).

Scope note, mirroring display_order.py: chart style is currently consumed
only by the newer breaks/crosstab pipeline (the ``post_crosstab``/
``post_breaks_export`` endpoints and ``plotly_renderer.py``). It is not
read by the legacy ``dist``/``xbreak``/``means`` chart system
(``surveytool/charts/renderer.py`` and ``surveytool/charts/chart_data.py``)
-- a deliberate scope boundary, not an oversight.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, ValidationError

from surveytool.charts.errors import ErrorCode, SurveyToolError, UnknownChartStyleError
from surveytool.charts.styles import STYLE_REGISTRY


class ChartStyleChoice(BaseModel):
    variable: str
    style_name: str
    saved_at: datetime


class ProjectChartStyles(BaseModel):
    styles: dict[str, ChartStyleChoice] = Field(default_factory=dict)


class CorruptedChartStyleFileError(SurveyToolError):
    """Mirrors CorruptedDisplayOrderFileError -- a corrupted chart-style
    file must never be silently treated as 'no style chosen', since that
    would silently revert an analyst's saved style with no explanation."""

    def __init__(self, path: Path, reason: str) -> None:
        self.path = path
        detail = f"The chart style file at {path} could not be read: {reason}"
        super().__init__(
            ErrorCode.CONFIG_INVALID,
            "This project's saved chart style choices could not be read.",
            detail=detail,
            next_action=(
                "The chart style file may be corrupted. Check it at the path above, "
                "restore it from a backup, or delete it to reset every question to the default (brand) style."
            ),
        )


def load_chart_styles(path: Path) -> ProjectChartStyles:
    if not path.exists():
        return ProjectChartStyles()
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise CorruptedChartStyleFileError(path, str(exc)) from exc
    try:
        return ProjectChartStyles.model_validate(raw)
    except ValidationError as exc:
        raise CorruptedChartStyleFileError(path, str(exc)) from exc


def write_chart_style(path: Path, choice: ChartStyleChoice) -> None:
    if choice.style_name not in STYLE_REGISTRY:
        raise UnknownChartStyleError(choice.style_name, sorted(STYLE_REGISTRY))
    existing = load_chart_styles(path) if path.exists() else ProjectChartStyles()
    existing.styles[choice.variable] = choice
    path.write_text(yaml.dump(existing.model_dump(mode="json")), encoding="utf-8")


def delete_chart_style(path: Path, variable: str) -> None:
    """Remove a variable's saved style entirely (reset to brand). A no-op
    if no style was saved for this variable."""
    if not path.exists():
        return
    existing = load_chart_styles(path)
    existing.styles.pop(variable, None)
    path.write_text(yaml.dump(existing.model_dump(mode="json")), encoding="utf-8")
```

- [ ] **Step 6: Run the storage tests**

Run: `python -m pytest tests/test_chart_style.py -v`
Expected: `PASS`.

- [ ] **Step 7: Run the full suite**

Run: `python -m pytest -q`
Expected: all green.

- [ ] **Step 8: Commit**

```bash
git add surveytool/ingest/chart_style.py surveytool/charts/errors.py tests/test_chart_style.py
git commit -m "feat: per-survey chart style storage with validated style names"
```

---

### Task 4: Desktop endpoints — `GET`/`PUT`/`DELETE /api/projects/{survey_id}/chart-style/{qid}`

**Files:**
- Modify: `surveytool/desktop/app.py`
- Test: `tests/test_desktop_chart_style.py` (new)

**Interfaces:**
- Consumes: `ChartStyleChoice`, `ProjectChartStyles`, `load_chart_styles`, `write_chart_style`, `delete_chart_style` (Task 3); `_validate_survey_id`, `_resolve_under`, `_APP_DATA_DIR` (existing, `surveytool/desktop/app.py`).
- Produces:
  - `surveytool.desktop.app._project_chart_style_path(survey_id: str) -> Path` and a module-level `_CHART_STYLE_DIR = _APP_DATA_DIR / "chart_style"`.
  - `surveytool.desktop.app._load_chart_styles_for_survey(survey_id: str) -> dict[str, str]` (qid → style_name), for Task 5 to consume.
  - `GET /api/projects/{survey_id}/chart-style/{qid}` → `ChartStylePayload | None`.
  - `PUT /api/projects/{survey_id}/chart-style/{qid}` (body `{"style_name": "..."}`) → `ChartStylePayload`. Returns 400 (via `UnknownChartStyleError`) for an unrecognised `style_name`.
  - `DELETE /api/projects/{survey_id}/chart-style/{qid}` → `{"reset": True}`.

- [ ] **Step 1: Confirm baseline**

Run: `python -m pytest -q`

- [ ] **Step 2: Add the storage path helper and per-survey directory**

In `surveytool/desktop/app.py`, alongside the existing `_DISPLAY_ORDER_DIR`/`_project_display_order_path` (near line 88 for the directory constant, near line 304 for the path function):

```python
_CHART_STYLE_DIR = _APP_DATA_DIR / "chart_style"


def _project_chart_style_path(survey_id: str) -> Path:
    """Per-survey_id chart-style store. Mirrors _project_display_order_path's
    validation/layout exactly -- one YAML file per survey_id, in its own
    directory. No legacy-migration concern, same as display_order.py: this
    is a brand-new file kind with no prior tempdir location."""
    _validate_survey_id(survey_id)
    new_path = _resolve_under(_CHART_STYLE_DIR, survey_id)
    return new_path


def _load_chart_styles_for_survey(survey_id: str) -> dict[str, str]:
    path = _project_chart_style_path(survey_id)
    styles = load_chart_styles(path)
    return {qid: entry.style_name for qid, entry in styles.styles.items()}
```

Add the needed imports near the existing `display_order` imports:

```python
from surveytool.ingest.chart_style import (
    ChartStyleChoice,
    delete_chart_style,
    load_chart_styles,
    write_chart_style,
)
```

- [ ] **Step 3: Write the failing endpoint tests**

Create `tests/test_desktop_chart_style.py` (mirrors `tests/test_desktop_display_order.py` exactly):

```python
"""GUI chart-style endpoint integration tests (chart style selector).

Drops the real Toluna misinformation fixture through the desktop app's
upload endpoint, then exercises the new GET/PUT/DELETE
/api/projects/{survey_id}/chart-style/{qid} endpoints and confirms the
choice is picked up by the next /crosstab call.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).parent.parent
TOLUNA_PATH = ROOT / "toluna_survey_misinformation_data.xlsx"

_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

_QID = "7_local_mainstream_media"


@pytest.fixture
def client():
    from surveytool.desktop.app import app
    return TestClient(app)


def _upload_toluna(client, survey_id: str) -> str:
    with open(TOLUNA_PATH, "rb") as f:
        response = client.post(
            "/api/upload",
            data={"vendor": "toluna", "survey_id": survey_id},
            files={"file": (TOLUNA_PATH.name, f, _XLSX_MIME)},
        )
    assert response.status_code == 200, response.text
    return response.json()["session_id"]


def test_get_chart_style_is_none_when_nothing_saved(client):
    if not TOLUNA_PATH.exists():
        pytest.skip(f"{TOLUNA_PATH.name} not found in project root")
    survey_id = "style-default"
    _upload_toluna(client, survey_id)
    response = client.get(f"/api/projects/{survey_id}/chart-style/{_QID}")
    assert response.status_code == 200, response.text
    assert response.json() is None


def test_put_then_get_chart_style_round_trips(client):
    if not TOLUNA_PATH.exists():
        pytest.skip(f"{TOLUNA_PATH.name} not found in project root")
    survey_id = "style-roundtrip"
    _upload_toluna(client, survey_id)
    put_response = client.put(
        f"/api/projects/{survey_id}/chart-style/{_QID}",
        json={"style_name": "cool"},
    )
    assert put_response.status_code == 200, put_response.text
    assert put_response.json()["style_name"] == "cool"

    get_response = client.get(f"/api/projects/{survey_id}/chart-style/{_QID}")
    assert get_response.status_code == 200, get_response.text
    assert get_response.json()["style_name"] == "cool"


def test_put_unknown_style_name_is_refused(client):
    if not TOLUNA_PATH.exists():
        pytest.skip(f"{TOLUNA_PATH.name} not found in project root")
    survey_id = "style-unknown"
    _upload_toluna(client, survey_id)
    response = client.put(
        f"/api/projects/{survey_id}/chart-style/{_QID}",
        json={"style_name": "not_a_real_style"},
    )
    assert response.status_code == 400, response.text
    body = response.json()
    assert "chart style" in body["error"]["message"].lower() or "recognise" in body["error"]["message"].lower()

    get_response = client.get(f"/api/projects/{survey_id}/chart-style/{_QID}")
    assert get_response.json() is None


def test_delete_chart_style_resets_and_is_a_noop_when_nothing_saved(client):
    if not TOLUNA_PATH.exists():
        pytest.skip(f"{TOLUNA_PATH.name} not found in project root")
    survey_id = "style-delete"
    _upload_toluna(client, survey_id)

    response = client.delete(f"/api/projects/{survey_id}/chart-style/{_QID}")
    assert response.status_code == 200, response.text
    assert response.json() == {"reset": True}

    client.put(f"/api/projects/{survey_id}/chart-style/{_QID}", json={"style_name": "warm"})
    delete_response = client.delete(f"/api/projects/{survey_id}/chart-style/{_QID}")
    assert delete_response.status_code == 200, delete_response.text

    get_response = client.get(f"/api/projects/{survey_id}/chart-style/{_QID}")
    assert get_response.json() is None


def test_crosstab_picks_up_saved_chart_style(client):
    if not TOLUNA_PATH.exists():
        pytest.skip(f"{TOLUNA_PATH.name} not found in project root")
    survey_id = "style-crosstab"
    session_id = _upload_toluna(client, survey_id)

    client.put(f"/api/projects/{survey_id}/chart-style/{_QID}", json={"style_name": "high_contrast"})

    crosstab_response = client.post(
        f"/api/session/{session_id}/crosstab",
        json={"break_spec": {"dimensions": []}, "filter_spec": {"selections": {}}, "question_ids": [_QID]},
    )
    assert crosstab_response.status_code == 200, crosstab_response.text
    result = crosstab_response.json()[0]
    assert result["chart_style"] == "high_contrast"


def test_crosstab_chart_style_is_none_when_nothing_saved(client):
    if not TOLUNA_PATH.exists():
        pytest.skip(f"{TOLUNA_PATH.name} not found in project root")
    survey_id = "style-crosstab-default"
    session_id = _upload_toluna(client, survey_id)

    crosstab_response = client.post(
        f"/api/session/{session_id}/crosstab",
        json={"break_spec": {"dimensions": []}, "filter_spec": {"selections": {}}, "question_ids": [_QID]},
    )
    assert crosstab_response.status_code == 200, crosstab_response.text
    result = crosstab_response.json()[0]
    assert result["chart_style"] is None
```

- [ ] **Step 4: Run to verify they fail**

Run: `python -m pytest tests/test_desktop_chart_style.py -v`
Expected: `FAIL` — endpoints and `QuestionResult.chart_style` don't exist yet (this task adds the endpoints; Task 5 adds `chart_style` to `QuestionResult` and threads it through `compute_breaks_crosstab` — the crosstab-related tests in this file will only pass once Task 5 is also done; that is expected and acceptable since both tasks land before this plan's final full-suite run).

- [ ] **Step 5: Add the payload model and three endpoints**

In `surveytool/desktop/app.py`, alongside the existing `DisplayOrderPayload`/`get_display_order`/`put_display_order`/`reset_display_order` block:

```python
class ChartStylePayload(BaseModel):
    style_name: str


@app.get("/api/projects/{survey_id}/chart-style/{qid}")
async def get_chart_style(survey_id: str, qid: str) -> ChartStylePayload | None:
    """The analyst's saved chart style for one question, if any. Keyed by
    survey_id directly (not session_id), same as display order -- editable
    independent of any active upload session. Returns None when no style
    has been saved, so the UI can distinguish 'default (brand) style' from
    'a saved style'."""
    path = _project_chart_style_path(survey_id)
    styles = load_chart_styles(path)
    entry = styles.styles.get(qid)
    if entry is None:
        return None
    return ChartStylePayload(style_name=entry.style_name)


@app.put("/api/projects/{survey_id}/chart-style/{qid}")
async def put_chart_style(survey_id: str, qid: str, payload: ChartStylePayload) -> ChartStylePayload:
    """Save a chart style choice for one question. Does not itself
    recompute anything -- the next crosstab call for this survey_id picks
    it up via _load_chart_styles_for_survey (post_crosstab/
    post_breaks_export), exactly as a manual display order is picked up on
    the next run. write_chart_style raises UnknownChartStyleError (mapped
    to 400 by the app-level SurveyToolError handler) for a style_name not
    in STYLE_REGISTRY."""
    path = _project_chart_style_path(survey_id)
    choice = ChartStyleChoice(
        variable=qid,
        style_name=payload.style_name,
        saved_at=datetime.now(timezone.utc),
    )
    write_chart_style(path, choice)
    return payload


@app.delete("/api/projects/{survey_id}/chart-style/{qid}")
async def reset_chart_style(survey_id: str, qid: str) -> dict:
    """Reset one question back to the default (brand) style by deleting
    its saved choice entirely. A no-op if no style was saved."""
    path = _project_chart_style_path(survey_id)
    delete_chart_style(path, qid)
    return {"reset": True}
```

- [ ] **Step 6: Run the non-crosstab endpoint tests**

Run: `python -m pytest tests/test_desktop_chart_style.py -k "not crosstab" -v`
Expected: `PASS` (the two crosstab-dependent tests still fail until Task 5).

- [ ] **Step 7: Run the full suite**

Run: `python -m pytest -q`
Expected: all green except the two new crosstab-dependent tests in `tests/test_desktop_chart_style.py`, which are expected to fail until Task 5. Confirm no other test regresses.

- [ ] **Step 8: Commit**

```bash
git add surveytool/desktop/app.py tests/test_desktop_chart_style.py
git commit -m "feat: chart-style GET/PUT/DELETE endpoints"
```

---

### Task 5: Thread `chart_style` through `compute_breaks_crosstab` and `QuestionResult`

**Files:**
- Modify: `surveytool/compute/breaks_compute.py`
- Modify: `surveytool/desktop/app.py`
- Test: `tests/test_desktop_chart_style.py` (existing crosstab tests from Task 4 now pass)
- Test: `tests/test_breaks_compute.py` (or wherever `compute_breaks_crosstab` unit tests live — check with `grep -rn "def test.*compute_breaks_crosstab\|from surveytool.compute.breaks_compute import compute_breaks_crosstab" tests/` first)

**Interfaces:**
- Consumes: `_load_chart_styles_for_survey` (Task 4).
- Produces: `compute_breaks_crosstab(..., chart_styles: dict[str, str] | None = None)`; `QuestionResult.chart_style: str | None = None`.

- [ ] **Step 1: Confirm baseline**

Run: `python -m pytest -q`

- [ ] **Step 2: Locate the existing unit-test module for `compute_breaks_crosstab`**

Run: `grep -rln "compute_breaks_crosstab" tests/`
Open whichever file contains direct (non-desktop) unit tests of `compute_breaks_crosstab` (as opposed to the desktop integration tests) — this is where Step 4's new unit test for `chart_styles` belongs, following that file's existing fixture/setup pattern for building a `Survey`/`ResolvedRegistry`/`respondent_frame`.

- [ ] **Step 3: Add the `chart_style` field to `QuestionResult`**

In `surveytool/compute/breaks_compute.py`, add alongside `display_order_is_manual` (after line 159):

```python
    chart_style: str | None = None
    """Chart style selector feature: the analyst's saved chart-style name
    for this question (e.g. "cool"), or None if no style was saved (the
    renderer's get_style(None) then resolves to the brand default). Purely
    a rendering hint -- never affects any computed figure, nets, or mean."""
```

- [ ] **Step 4: Write the failing unit test for `chart_styles` threading**

In the file located in Step 2, add a test following its existing setup pattern (substitute the actual fixture/helper names used there — e.g. if the file builds a `Survey` via a helper called `_build_survey` or loads a real vendor fixture via a `respondent_frame` fixture, reuse that exact pattern rather than reinventing one):

```python
def test_compute_breaks_crosstab_threads_chart_style_into_question_result(
    # substitute this file's actual fixture parameters, e.g.:
    # toluna_survey, toluna_registry, toluna_respondent_frame, default_config
):
    """chart_styles is a qid -> style_name map; the resolved value lands on
    QuestionResult.chart_style unchanged, and a qid with no entry gets
    None."""
    qid = "7_local_mainstream_media"  # substitute the real qid this test file already uses elsewhere
    results = compute_breaks_crosstab(
        # substitute this file's actual positional argument pattern
        chart_styles={qid: "warm"},
    )
    result = next(r for r in results if r.question_id == qid)
    assert result.chart_style == "warm"


def test_compute_breaks_crosstab_chart_style_defaults_to_none(
    # substitute this file's actual fixture parameters
):
    results = compute_breaks_crosstab(
        # substitute this file's actual positional argument pattern, chart_styles omitted entirely
    )
    result = results[0]
    assert result.chart_style is None
```

- [ ] **Step 5: Run to verify the new tests fail**

Run: `python -m pytest tests/<the file from Step 2> -k "chart_style" -v`
Expected: `FAIL` — `compute_breaks_crosstab()` doesn't accept `chart_styles` yet.

- [ ] **Step 6: Thread `chart_styles` through `compute_breaks_crosstab`**

In `surveytool/compute/breaks_compute.py`'s `compute_breaks_crosstab` signature, add the parameter alongside the existing `display_orders` parameter (per the earlier `grep`, at line 355):

```python
    chart_styles: dict[str, str] | None = None,
```

Extend the function's docstring (per the existing `display_orders` doc block, around line 368) with a parallel note:

```python
    ``chart_styles`` (chart style selector feature): an optional qid ->
    style_name map. Threaded onto ``QuestionResult.chart_style`` for the
    matching question, None for any qid with no entry. Purely a rendering
    hint consumed by plotly_renderer.build_figure -- never affects any
    computed figure in this function.
```

At the `QuestionResult(...)` construction site (alongside the existing `display_order_is_manual=...` line, per the earlier `grep` at line 424), add:

```python
            chart_style=(chart_styles or {}).get(question.qid),
```

- [ ] **Step 7: Run the new unit tests**

Run: `python -m pytest tests/<the file from Step 2> -k "chart_style" -v`
Expected: `PASS`.

- [ ] **Step 8: Wire `_load_chart_styles_for_survey` into `post_crosstab` and `post_breaks_export`**

In `surveytool/desktop/app.py`, at the two `compute_breaks_crosstab(...)` call sites (Step numbers from the earlier `grep`: line ~1203 in `post_crosstab`, line ~1252 in `post_breaks_export`), add the new argument alongside the existing `display_orders=_load_display_orders_for_survey(session.survey_id)`:

```python
        display_orders=_load_display_orders_for_survey(session.survey_id),
        chart_styles=_load_chart_styles_for_survey(session.survey_id),
```

- [ ] **Step 9: Run the Task 4 crosstab-dependent tests**

Run: `python -m pytest tests/test_desktop_chart_style.py -v`
Expected: `PASS` — both `test_crosstab_picks_up_saved_chart_style` and `test_crosstab_chart_style_is_none_when_nothing_saved` (which failed at the end of Task 4) now pass.

- [ ] **Step 10: Run the full suite**

Run: `python -m pytest -q`
Expected: all green.

- [ ] **Step 11: Commit**

```bash
git add surveytool/compute/breaks_compute.py surveytool/desktop/app.py tests/
git commit -m "feat: thread chart_style through compute_breaks_crosstab and desktop endpoints"
```

---

### Task 6: Wire style into `plotly_renderer.py` — palette, background, font

**Files:**
- Modify: `surveytool/charts/plotly_renderer.py`
- Test: `tests/test_conformance.py` (or a new `tests/test_chart_style_rendering.py` — check whether `test_conformance.py` already has a plotly-renderer-focused section to extend, per Round C1's Task C1 Step 11 convention of adding directly to `test_conformance.py`)

**Interfaces:**
- Consumes: `surveytool.charts.styles.get_style` (Task 2), `QuestionResult.chart_style` (Task 5), `assign_series_colours(..., palette=...)` (Task 1).
- Produces: `build_figure(question_result, chart_type, *, break_spec=None, filter_spec=None)` unchanged in signature (style is read from `question_result.chart_style`, not a new parameter — the spec's data flow has style travel with the computed result, not as a separate call argument) but internally resolves and applies the style to every bar-figure builder and the header.

- [ ] **Step 1: Confirm baseline**

Run: `python -m pytest -q`

- [ ] **Step 2: Write the failing "nothing changes unless opted in" regression test**

This is the critical guard from the spec's testing approach. Add to `tests/test_conformance.py`:

```python
def _minimal_question_result(**overrides):
    """Builds a minimal QuestionResult sufficient to exercise
    plotly_renderer.build_figure directly, without going through the full
    compute_breaks_crosstab pipeline. Check this file's existing imports
    and any existing minimal-QuestionResult test helper before writing a
    new one from scratch -- if test_conformance.py or a sibling test file
    already has one (e.g. for the C1/C4 acceptance tests), reuse it and
    only add the fields this test needs."""
    from surveytool.compute.breaks_compute import ColumnResult, QuestionResult, ScalePoint
    from surveytool.core.suppression import Band

    defaults = dict(
        question_id="q_test",
        question_text="Test question?",
        scale_id="test_scale",
        scale_variant=None,
        scale_points=[
            ScalePoint(code="1", label="Agree", order=0, polarity="positive", rank=1),
            ScalePoint(code="2", label="Disagree", order=1, polarity="negative", rank=0),
        ],
        nets=[],
        base_total=100,
        base_filtered=100,
        columns=[
            ColumnResult(
                key=[], label_path=[], base_cell=100, base_valid=100, n_invalid=0,
                base_provenance=None, band=Band.reportable,
                counts={"1": 60, "2": 40}, percentages={"1": 60.0, "2": 40.0}, nets=None,
            )
        ],
        permitted_charts=[],
        chart_style=None,
    )
    defaults.update(overrides)
    return QuestionResult(**defaults)


def test_build_figure_with_no_chart_style_matches_pre_feature_brand_colours():
    """The critical additive guarantee: chart_style=None must produce a
    figure whose colours/background/font are identical to hardcoded brand
    values plotly_renderer used before this feature existed."""
    from surveytool.charts.plotly_renderer import _stacked_bar_100_figure, _apply_header
    from surveytool.core.chart_validity import ChartType

    result = _minimal_question_result(chart_style=None)
    fig = _stacked_bar_100_figure(result)
    _apply_header(fig, result, break_spec=None, filter_spec=None, chart_type=ChartType.stacked_bar_100)

    assert fig.layout.paper_bgcolor == "#F4F1EA"
    assert fig.layout.plot_bgcolor == "#F4F1EA"
    assert fig.layout.font.color == "#222222"

    from surveytool.charts.palette import assign_series_colours
    expected_colours = assign_series_colours(["Agree", "Disagree"])
    trace_colours = {trace.name: trace.marker.color for trace in fig.data if trace.name in ("Agree", "Disagree")}
    assert trace_colours == expected_colours


def test_build_figure_with_non_brand_style_applies_its_palette_background_and_font():
    """A non-brand style's background/font/palette actually appear in the
    built figure's layout and trace marker_color."""
    from surveytool.charts.plotly_renderer import _stacked_bar_100_figure, _apply_header
    from surveytool.charts.styles import STYLE_REGISTRY
    from surveytool.charts.palette import assign_series_colours
    from surveytool.core.chart_validity import ChartType

    style = STYLE_REGISTRY["cool"]
    result = _minimal_question_result(chart_style="cool")
    fig = _stacked_bar_100_figure(result)
    _apply_header(fig, result, break_spec=None, filter_spec=None, chart_type=ChartType.stacked_bar_100)

    assert fig.layout.paper_bgcolor == style.background
    assert fig.layout.plot_bgcolor == style.background
    assert fig.layout.font.color == style.font_color

    expected_colours = assign_series_colours(["Agree", "Disagree"], palette=style.palette)
    trace_colours = {trace.name: trace.marker.color for trace in fig.data if trace.name in ("Agree", "Disagree")}
    assert trace_colours == expected_colours


def test_build_figure_unknown_chart_style_falls_back_to_brand():
    """A stale/corrupted chart_style value on QuestionResult (e.g. a style
    later removed from STYLE_REGISTRY) must never crash rendering --
    get_style's silent fallback applies here exactly as it does anywhere
    else get_style is called."""
    from surveytool.charts.plotly_renderer import _apply_header, _stacked_bar_100_figure
    from surveytool.core.chart_validity import ChartType

    result = _minimal_question_result(chart_style="a_style_that_was_removed")
    fig = _stacked_bar_100_figure(result)
    _apply_header(fig, result, break_spec=None, filter_spec=None, chart_type=ChartType.stacked_bar_100)
    assert fig.layout.paper_bgcolor == "#F4F1EA"
```

(Adjust `_minimal_question_result`'s exact `ColumnResult`/`ScalePoint` field set to match whatever `breaks_compute.py`'s actual current field requirements are — re-check by reading the model definitions directly if constructing this raises a Pydantic validation error; the load-bearing assertions are the colour/background/font comparisons, not the exact fixture-construction mechanics.)

- [ ] **Step 3: Run to verify they fail**

Run: `python -m pytest tests/test_conformance.py -k "chart_style or build_figure_with" -v`
Expected: `FAIL` — `_stacked_bar_100_figure` and `_apply_header` don't yet accept/apply style, and `QuestionResult` doesn't have `chart_style` as a settable field via the plain constructor without Task 5 already merged (it is, by this point in the plan).

- [ ] **Step 4: Resolve style once in `build_figure` and thread it to the header**

In `surveytool/charts/plotly_renderer.py`, import `get_style`:

```python
from surveytool.charts.styles import ChartStyle, get_style
```

Change `_apply_header`'s signature to accept the resolved `ChartStyle` and use its fields instead of the hardcoded hex values:

```python
def _apply_header(
    fig: go.Figure,
    question_result: QuestionResult,
    break_spec: list[str] | None,
    filter_spec: dict[str, list[str]] | None,
    chart_type: ChartType,
    style: ChartStyle,
) -> None:
    fig.update_layout(
        title={
            "text": _header_text(question_result, break_spec, filter_spec, chart_type),
            "x": 0.02,
            "xanchor": "left",
            "font": {"size": 13},
        },
        margin={"t": 140},
        paper_bgcolor=style.background,
        plot_bgcolor=style.background,
        font={"color": style.font_color},
    )
```

In `build_figure`, resolve the style once and pass it through:

```python
    builder = _BUILDERS[chart_type]
    style = get_style(question_result.chart_style)
    fig = builder(question_result, style)
    _apply_header(fig, question_result, break_spec, filter_spec, chart_type, style)
    return fig
```

- [ ] **Step 5: Thread `style` into every bar-figure builder's `assign_series_colours` call**

Each of `_stacked_bar_100_figure`, `_diverging_stacked_bar_figure`, `_grouped_bar_figure` currently has the signature `(question_result: QuestionResult) -> go.Figure` and calls `assign_series_colours([point.label for point in question_result.scale_points])` with no palette argument. Change each builder's signature to accept `style: ChartStyle` and pass `palette=style.palette`:

```python
def _stacked_bar_100_figure(question_result: QuestionResult, style: ChartStyle) -> go.Figure:
    ...
    colour_by_label = assign_series_colours(
        [point.label for point in question_result.scale_points],
        palette=style.palette,
    )
    ...
```

Apply the identical change to `_diverging_stacked_bar_figure` and `_grouped_bar_figure` (both also call `assign_series_colours([point.label for point in question_result.scale_points])` with no palette, per the earlier `grep`).

`_net_bar_figure` and `_table_figure` don't call `assign_series_colours` (confirmed by the earlier `grep` — only the three bar builders do) but are still called via `_BUILDERS[chart_type]` in `build_figure`, so their signatures must also accept `style` for `builder(question_result, style)` to work uniformly, even though they don't use `style.palette`:

```python
def _net_bar_figure(question_result: QuestionResult, style: ChartStyle) -> go.Figure:
    ...  # body unchanged; style currently only affects header background/font, applied by _apply_header, not by this function


def _table_figure(question_result: QuestionResult, style: ChartStyle) -> go.Figure:
    ...  # body unchanged
```

- [ ] **Step 6: Run the new rendering tests**

Run: `python -m pytest tests/test_conformance.py -k "chart_style or build_figure_with" -v`
Expected: `PASS`.

- [ ] **Step 7: Run the full suite**

Run: `python -m pytest -q`
Expected: all green — every existing test that calls `build_figure` (not the private `_*_figure` builders directly) is unaffected since `build_figure`'s own signature didn't change; any existing test that calls one of the private builders directly must now also pass a `style` argument (`get_style(None)` for brand-equivalent) — search for direct builder calls and update them:

Run: `grep -rn "_stacked_bar_100_figure(\|_diverging_stacked_bar_figure(\|_grouped_bar_figure(\|_net_bar_figure(\|_table_figure(" tests/`

For each existing test call site found, add `get_style(None)` (or `STYLE_REGISTRY["brand"]`) as the second argument, then re-run the full suite until green.

- [ ] **Step 8: Commit**

```bash
git add surveytool/charts/plotly_renderer.py tests/test_conformance.py
git commit -m "feat: apply chart style palette, background, and font to plotly_renderer"
```

---

### Task 7: Frontend — chart style button row in `breaks.js`

**Files:**
- Modify: `surveytool/desktop/static/breaks.js`
- Modify: `surveytool/desktop/static/breaks.css` (or wherever `.chart-type-row`/`.chart-type-btn` are styled — check `grep -rn "chart-type-row\|chart-type-btn" surveytool/desktop/static/` first)

**Interfaces:**
- Consumes: `qr.chart_style` (from a `QuestionResult` JSON payload, Task 5), the existing `PUT /api/projects/{survey_id}/chart-style/{qid}` endpoint (Task 4), the existing `renderChartArea(qr, chartArea, chartType)` function and `controlsRow` DOM structure (both pre-existing, confirmed at `surveytool/desktop/static/breaks.js:711-720`).
- Produces: `buildChartStyleRow(qr)` — a DOM-building function modeled on the existing `buildChartTypeRow(qr)` (same file, confirmed at line 765), appended into `controlsRow` alongside `chartTypeRow` and the axis-flip button.

- [ ] **Step 1: Confirm the survey_id available in this file's scope**

Run: `grep -n "survey_id\|surveyId" surveytool/desktop/static/breaks.js`
Confirm which existing variable in this file's module scope holds the current survey_id (needed to build the `PUT` URL) — reuse it rather than introducing a new one. If none exists yet at module scope (only `sessionId`/`breaksSessionId` are visible per the earlier read), check whether the page already exposes `survey_id` via a data attribute, a global set at page load, or an existing fetch response the session object carries; follow whatever pattern the existing `display-order` PUT call (if the frontend already has one from Round C3) uses for its own survey_id lookup — check `grep -n "display-order" surveytool/desktop/static/breaks.js` first, since Task C3's frontend wiring (if present) already solved exactly this problem and this task should reuse the identical approach rather than inventing a second one.

- [ ] **Step 2: Define the style catalogue and label function**

In `surveytool/desktop/static/breaks.js`, alongside the existing `chartTypeLabel` function (used by `buildChartTypeRow`, confirmed at line 773 via `chartTypeLabel(perm.chart_type)` — locate its definition with `grep -n "function chartTypeLabel"`), add a parallel style catalogue. This list of style names must match `surveytool.charts.styles.STYLE_REGISTRY`'s keys from Task 2 exactly (`brand`, `high_contrast`, `cool`, `warm`):

```javascript
const CHART_STYLES = ["brand", "high_contrast", "cool", "warm"];

function chartStyleLabel(styleName) {
  const labels = {
    brand: "Brand",
    high_contrast: "High Contrast",
    cool: "Cool",
    warm: "Warm",
  };
  return labels[styleName] || styleName;
}
```

- [ ] **Step 3: Write `buildChartStyleRow`, modeled on `buildChartTypeRow`**

Add directly after `buildChartTypeRow` (line 798 in the current file):

```javascript
function buildChartStyleRow(qr) {
  const row = document.createElement("div");
  row.className = "chart-type-row chart-style-row";

  const activeStyle = qr.chart_style || "brand";

  CHART_STYLES.forEach((styleName) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "chart-type-btn";
    btn.textContent = chartStyleLabel(styleName);
    if (activeStyle === styleName) {
      btn.classList.add("active");
    }
    btn.addEventListener("click", () => {
      // Optimistic local update: re-render immediately using data already
      // present (palette/background are static per style, no server
      // computation needed), then persist in the background. On the next
      // full crosstab fetch (e.g. changing break/filter), the persisted
      // choice is naturally picked up from the server via
      // QuestionResult.chart_style -- this local mutation just keeps the
      // in-memory qr consistent with what was just clicked in the
      // meantime.
      qr.chart_style = styleName;
      row.querySelectorAll(".chart-type-btn").forEach((b) => { b.classList.remove("active"); });
      btn.classList.add("active");

      const block = row.closest(".breaks-question");
      const chartArea = block.querySelector(".breaks-chart-area");
      const chartType = breaksActiveChartType[qr.question_id];
      renderChartArea(qr, chartArea, chartType);

      // Background persist; failure is logged, not surfaced as a blocking
      // error, since the on-screen chart already reflects the choice and
      // the next crosstab/export round trip is what actually needs the
      // saved value to be durable.
      fetch(`/api/projects/${currentSurveyId}/chart-style/${qr.question_id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ style_name: styleName }),
      }).catch((err) => {
        console.error("Failed to save chart style choice", err);
      });
    });
    row.appendChild(btn);
  });

  return row;
}
```

(Replace `currentSurveyId` with whichever exact variable name Step 1 identified as this file's existing survey_id reference — do not introduce a second, differently-named survey_id variable if one already exists in scope.)

- [ ] **Step 4: Append the style row into `controlsRow`**

Modify the block around line 711-720 (where `chartTypeRow` and the axis-flip button are appended):

```javascript
    const controlsRow = document.createElement("div");
    controlsRow.className = "chart-controls-row";

    const chartTypeRow = buildChartTypeRow(qr);
    controlsRow.appendChild(chartTypeRow);

    const chartStyleRow = buildChartStyleRow(qr);
    controlsRow.appendChild(chartStyleRow);

    const flipBtn = buildAxisFlipButton(qr);
    controlsRow.appendChild(flipBtn);

    block.appendChild(controlsRow);
```

- [ ] **Step 5: Confirm `renderChartArea` reads `qr.chart_style` when re-rendering**

`renderChartArea` presumably calls into whatever client-side chart-drawing path exists for the on-screen Plotly chart (check `grep -n "function renderChartArea" surveytool/desktop/static/breaks.js` and read it). If the on-screen chart is drawn by the browser directly from `qr` fields (a client-side Plotly.js call reading `qr.scale_points`/`qr.columns` etc.), it needs to also read `qr.chart_style` and apply the corresponding style's background/font/palette client-side for the optimistic re-render in Step 3 to actually change what's on screen — this requires either (a) porting a minimal client-side copy of `STYLE_REGISTRY`'s palette/background/font values into `breaks.js`, or (b) `renderChartArea` re-fetching a server-rendered spec. Inspect `renderChartArea`'s current implementation before proceeding: if it already fetches a figure spec from the server per render (rather than building traces from `qr` client-side), the "optimistic" step in Step 3 must instead trigger a lightweight refetch rather than a truly local re-render, and this step's job is to make that refetch pass the just-clicked `chart_style` so the round trip doesn't need Task 4's `PUT` to have completed first. Document whichever of these two shapes is actually true in this codebase as a one-line comment above `buildChartStyleRow`, and adjust Step 3's optimistic-update body accordingly to match reality rather than the spec's idealized description.

- [ ] **Step 6: Manually verify in the browser**

Run the desktop app (check for an existing `run` skill or `README`/`Makefile` target — do not guess a start command; look for one first via `grep -rn "uvicorn\|def main" surveytool/desktop/`), upload a real vendor fixture (e.g. `toluna_survey_misinformation_data.xlsx`), open the breaks view, and confirm:
1. A row of four style buttons appears next to the chart-type row for a question with a rendered chart.
2. Clicking a non-brand style visibly changes the chart's colours/background without a full page reload.
3. Reloading the breaks view (or re-fetching crosstab) preserves the chosen style (confirms the `PUT` persisted and `post_crosstab` picks it up).
4. Exporting the chart (breaks-export) produces a PNG using the chosen style, not brand — open the exported file and visually confirm.

This is the plan's one explicitly-manual verification step, matching the project convention ("For UI or frontend changes... test the feature") — do not claim this task complete without having actually done this in a browser.

- [ ] **Step 7: Run the full suite**

Run: `python -m pytest -q`
Expected: all green (this task's changes are pure frontend; no backend test should be affected, but this confirms no accidental backend edit was introduced).

- [ ] **Step 8: Commit**

```bash
git add surveytool/desktop/static/breaks.js surveytool/desktop/static/breaks.css
git commit -m "feat: chart style selector button row in breaks view"
```

---

### Task 8: End-to-end acceptance test — style choice survives export

**Files:**
- Test: `tests/test_desktop_chart_style.py`

**Interfaces:**
- Consumes: everything from Tasks 1-6.

- [ ] **Step 1: Confirm baseline**

Run: `python -m pytest -q`

- [ ] **Step 2: Write the failing export acceptance test**

Add to `tests/test_desktop_chart_style.py`:

```python
def test_breaks_export_uses_saved_chart_style():
    """End-to-end: PUT a style, then breaks-export must render the PNG
    using that style, not brand -- confirmed by inspecting the figure
    object build_figure produces before rasterization (per the spec's
    testing approach: 'inspect the figure object before rasterization,
    not the PNG bytes'), reached the same way post_breaks_export reaches
    it internally.
    """
    if not TOLUNA_PATH.exists():
        pytest.skip(f"{TOLUNA_PATH.name} not found in project root")

    from fastapi.testclient import TestClient
    from surveytool.desktop.app import app, get_session, _load_chart_styles_for_survey
    from surveytool.compute.breaks_compute import compute_breaks_crosstab
    from surveytool.core.chart_validity import attach_chart_permissions
    from surveytool.charts.plotly_renderer import build_figure
    from surveytool.charts.styles import STYLE_REGISTRY
    from surveytool.compute.request_validation import validate_request

    client = TestClient(app)
    survey_id = "style-export-e2e"
    session_id = _upload_toluna(client, survey_id)

    put_response = client.put(
        f"/api/projects/{survey_id}/chart-style/{_QID}",
        json={"style_name": "warm"},
    )
    assert put_response.status_code == 200, put_response.text

    session = get_session(session_id)
    from surveytool.core.config import ToolConfig
    config = ToolConfig()

    validate_request([], {}, session.registry, session.survey, session.vendor, session.respondent_frame)
    results = compute_breaks_crosstab(
        session.respondent_frame,
        session.survey,
        [],
        {},
        [_QID],
        session.registry,
        session.vendor,
        config,
        chart_styles=_load_chart_styles_for_survey(survey_id),
    )
    results = attach_chart_permissions(results, config)
    question_result = results[0]
    assert question_result.chart_style == "warm"

    fig = build_figure(question_result, question_result.permitted_charts[0].chart_type)
    style = STYLE_REGISTRY["warm"]
    assert fig.layout.paper_bgcolor == style.background
    assert fig.layout.font.color == style.font_color
```

(Substitute the real function signatures/imports for `validate_request`/`ToolConfig`/`attach_chart_permissions` from wherever `post_breaks_export`'s actual implementation imports them in `surveytool/desktop/app.py` — this test intentionally reaches the same pipeline `post_breaks_export` uses internally, so its exact call shape must match that endpoint's real code, not be guessed independently. First permitted chart type is used for simplicity; if it happens to be `"table"` (which never uses `assign_series_colours`), the background/font assertions still hold since `_apply_header` applies uniformly to every chart type regardless of builder.)

- [ ] **Step 3: Run to verify it fails**

Run: `python -m pytest tests/test_desktop_chart_style.py -k "export_uses_saved" -v`
Expected: `FAIL` initially only if any import/signature guessed above doesn't match reality — fix the test's imports/call shape against the actual `post_breaks_export` implementation until it fails only for the right reason (missing feature, not a wrong import), then confirm Tasks 1-6 already make it pass once fixed.

- [ ] **Step 4: Run and confirm it passes**

Run: `python -m pytest tests/test_desktop_chart_style.py -v`
Expected: `PASS` for every test in the file, including this new one.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest -q`
Expected: all green, count matches Step 1's plus the new tests across every task in this plan.

- [ ] **Step 6: Commit**

```bash
git add tests/test_desktop_chart_style.py
git commit -m "test: end-to-end chart style acceptance covering breaks-export"
```

---

## Self-Review

**1. Spec coverage:**
- 3-4 curated presets, varying only palette/background/font-colour, brand as default → Task 2.
- Selectable per question in the breaks-view chart panel via a new button row → Task 7.
- Persisted per survey per question, following `display_order.py`'s pattern exactly → Task 3, Task 4.
- Reaches both on-screen Plotly chart and branded PNG export via the shared `build_figure`/`rasterize` path → Task 6 (renderer wiring), Task 8 (end-to-end proof covering export specifically).
- `assign_series_colours` signature change, backward-compatible default → Task 1.
- `renderer.py` (legacy matplotlib) left untouched → explicitly stated in Global Constraints and `chart_style.py`'s module docstring (Task 3); no task modifies `surveytool/charts/renderer.py` or `chart_data.py`.
- `ChartStyleChoice`/`ProjectChartStyles`/load/write/delete, `CorruptedChartStyleFileError`, style-name validation at write time with plain-English error → Task 3.
- Desktop endpoints mirroring C3 exactly, including `_project_chart_style_path` → Task 4.
- `compute_breaks_crosstab`'s `chart_styles` param, `QuestionResult.chart_style` → Task 5.
- Frontend `buildChartStyleRow` modeled on `buildChartTypeRow`, optimistic local update + background persist → Task 7.
- Data flow (click → optimistic render → background PUT → next crosstab/export naturally reflects it) → Task 7 Steps 3-5, proven end-to-end by Task 8.
- Testing approach's five bullet points (styles.py unit tests, chart_style.py unit tests mirroring test_display_order.py, desktop endpoint tests mirroring test_desktop_display_order.py, plotly_renderer byte-identical-when-None + non-brand-applies tests, end-to-end PUT→crosstab→export) → Tasks 2, 3, 4, 6, 8 respectively.
- Self-review's explicit flag: the three non-brand palettes' hex values are real implementation-time work, not placeholders → Task 2 Step 2 (validation script with numeric floors), never hard-coded without running it.
- Self-review's ambiguity resolution: DELETE resets to brand, mirroring `delete_display_order` → Task 3's `delete_chart_style`, Task 4's `reset_chart_style` endpoint.

**2. Placeholder scan:** Task 2 Step 5's `styles.py` template contains three `# <-- ... goes here -->` comments for the non-brand palette tuples — this is not a plan placeholder in the "No Placeholders" sense (a plan must never tell an engineer to "add appropriate values" with no way to know what they are); it is the plan explicitly directing the engineer to substitute Step 2's own just-validated output, produced by a concrete, runnable script earlier in the same task. No other step contains TBD/TODO/"handle appropriately" language. Task 7 Step 1 and Step 5 ask the engineer to inspect existing code before finalizing an exact variable name / re-render mechanism (`currentSurveyId`, `renderChartArea`'s actual data source) rather than guessing — this reflects genuine unknowns about a live codebase's exact frontend variable naming that a plan author without live JS execution cannot resolve more precisely than "grep for it and use what's there," consistent with how the Round C reference plan handled equivalent frontend uncertainty.

**3. Type consistency:** `ChartStyle` (Task 2) → consumed by `styles.get_style` (Task 2), `plotly_renderer._apply_header`/`build_figure`/bar builders (Task 6) — same three fields (`palette`, `background`, `font_color`) throughout. `ChartStyleChoice.style_name` (Task 3) → `ChartStylePayload.style_name` (Task 4) → JS `style_name` PUT body (Task 7) — consistent field name end-to-end, matching `DisplayOrder`/`DisplayOrderPayload`'s `label_order` precedent. `compute_breaks_crosstab(..., chart_styles: dict[str, str] | None)` (Task 5) → `QuestionResult.chart_style: str | None` (Task 5) → `get_style(question_result.chart_style)` (Task 6) — consistent optional-str-or-None threading throughout, matching `display_orders`/`display_order_is_manual`'s established shape. `_load_chart_styles_for_survey(survey_id) -> dict[str, str]` (Task 4) → passed as `chart_styles=` at both `post_crosstab` and `post_breaks_export` call sites (Task 5 Step 8) — same function, same two call sites `_load_display_orders_for_survey` already uses.
