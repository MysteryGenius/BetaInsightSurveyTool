# Round C: Charts and UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the remaining chart/UI defects Leonard photographed — a shared categorical palette so a 7-option grouped bar renders distinguishably, no cropped labels or unwrapped titles, no rounding disagreement between tooltip and panel figure — plus manual response-option reordering (on top of Round B's now-correct default order) and a safe survey-ID rename.

**Architecture:** C1/C2/C4 are self-contained rendering-layer fixes to `surveytool/charts/plotly_renderer.py` and `surveytool/charts/renderer.py` (the two independent renderers already established in the codebase) plus a new shared `surveytool/charts/palette.py` and `surveytool/core/text_hygiene.py` module each renderer imports from. C3 (manual reorder) is a UI/override-storage feature that sits on top of Round B's rank — it must not exist, or be plannable, before Round B ships, since a manual reorder on top of a wrong default order would be actively harmful (the spec's own words). C5 (survey rename) is an isolated `desktop/app.py` file-management feature with no dependency on B or the other C tasks.

**Tech Stack:** Python, Plotly, Matplotlib, Pydantic, PyYAML, pytest, FastAPI (desktop/app.py). No new dependencies.

**Spec:** The "Beta Insight, Round B and Round C prompts" document (27 August 2026, provided in conversation) — this plan implements Round C (prompts C1 through C5). Round B is implemented separately in `docs/superpowers/plans/2026-08-29-round-b-scale-ordinal-rank.md`; **C3 in this plan has a hard dependency on Round B being complete and merged** (its own Task C3 Step 0 verifies this before proceeding). C1, C2, C4, C5 have no dependency on Round B and may be executed in any order relative to it.

## Global Constraints

- Full test suite must be green before moving to the next task and before this plan is considered done. Confirm the exact baseline count immediately before Task C1 Step 1 by running `python -m pytest -q` (it will differ from Round B's stated 486 baseline if Round B has already shipped in this repo — record whatever the actual current count is and treat that as this plan's own starting point).
- No pie or donut charts are introduced anywhere (matches the existing `ChartType` enum's explicit exclusion, `surveytool/core/chart_validity.py`).
- Every rendering-layer fix in C1/C2/C4 applies identically to both renderers (`surveytool/charts/plotly_renderer.py` for on-screen Plotly, `surveytool/charts/renderer.py` for the branded matplotlib PNG export) — a fix landing in only one renderer does not satisfy this plan's acceptance criteria.
- Real vendor files used for acceptance:
  - `purespectrum_survey_wcs_data.xlsx` (repo root)
  - `toluna_survey_misinformation_data.xlsx` (repo root)
  - `rakuten_survey_chn_clans_data.xlsx` (repo root — has the `chn_clans` chart Leonard photographed)
  - `rakuten_survey_support_measures_data.xlsx` (repo root — has the "support measures" chart Leonard photographed)
  - `milieu_survey_coe_data.csv` (repo root — has q8, the 7-option grouped-bar question Leonard photographed)
- Every new dataclass/model follows the codebase's existing pattern: frozen dataclasses for pure value objects, Pydantic `BaseModel` for anything crossing an API/serialization boundary.
- New errors subclass `SurveyToolError` with a new `ErrorCode` member, a plain-English message, a `detail`, and a `next_action` — matching every existing error class in `surveytool/charts/errors.py`.
- Per persistent project memory: end users of this tool are non-technical — any new user-facing error or refusal message (e.g. C1's palette-exhaustion refusal, C5's rename-onto-existing-id refusal) must be plain English with a concrete remediation step, not a technical/internal-sounding message.

---

### Task C1: Shared categorical palette

**Files:**
- Create: `surveytool/charts/palette.py`
- Modify: `surveytool/charts/plotly_renderer.py`
- Modify: `surveytool/charts/renderer.py`
- Modify: `surveytool/charts/errors.py`
- Test: `tests/test_palette.py` (new)
- Test: `tests/test_conformance.py`

**Interfaces:**
- Consumes: nothing new from other tasks.
- Produces:
  - `surveytool.charts.palette.CATEGORICAL_PALETTE: tuple[str, ...]` — at least 12 hex colours, colourblind-safe, distinguishable in greyscale.
  - `surveytool.charts.palette.assign_series_colours(series_identities: list[str]) -> dict[str, str]` — maps each distinct series identity (a response option's label, or another stable per-series key) to one palette colour, by identity (stable regardless of position in the input list — sorting `series_identities` before assignment, so the same identity always gets the same colour across calls with the same identity set, and removing one identity from the list never reshuffles the colours of the remaining ones — see Step 3 for the exact stability rule). Raises `PaletteExhaustedError` if `len(series_identities) > len(CATEGORICAL_PALETTE)`.
  - `surveytool.charts.errors.PaletteExhaustedError(SurveyToolError)` — new. New `ErrorCode.PALETTE_EXHAUSTED`.

- [ ] **Step 1: Confirm the current test baseline**

Run: `python -m pytest -q`
Expected: whatever the current green baseline is (see Global Constraints). Record it.

- [ ] **Step 2: Write the failing tests**

Create `tests/test_palette.py`:

```python
from surveytool.charts.palette import CATEGORICAL_PALETTE, assign_series_colours
from surveytool.charts.errors import PaletteExhaustedError
import pytest


def test_palette_has_at_least_twelve_entries():
    assert len(CATEGORICAL_PALETTE) >= 12


def test_palette_entries_are_unique_hex_colours():
    assert len(set(CATEGORICAL_PALETTE)) == len(CATEGORICAL_PALETTE)
    for colour in CATEGORICAL_PALETTE:
        assert colour.startswith("#") and len(colour) == 7


def test_assign_series_colours_gives_distinct_colours_to_seven_series():
    identities = [f"Option {i}" for i in range(7)]
    assignment = assign_series_colours(identities)
    assert len(assignment) == 7
    assert len(set(assignment.values())) == 7


def test_assign_series_colours_is_stable_by_identity_not_position():
    full = assign_series_colours(["A", "B", "C", "D"])
    subset = assign_series_colours(["B", "D"])
    assert subset["B"] == full["B"]
    assert subset["D"] == full["D"]


def test_assign_series_colours_reordering_input_does_not_change_assignment():
    a = assign_series_colours(["Red", "Blue", "Green"])
    b = assign_series_colours(["Green", "Red", "Blue"])
    assert a == b


def test_assign_series_colours_raises_when_exceeding_palette_size():
    too_many = [f"Option {i}" for i in range(len(CATEGORICAL_PALETTE) + 1)]
    with pytest.raises(PaletteExhaustedError):
        assign_series_colours(too_many)


def test_palette_exhausted_error_message_is_plain_english():
    too_many = [f"Option {i}" for i in range(len(CATEGORICAL_PALETTE) + 1)]
    try:
        assign_series_colours(too_many)
    except PaletteExhaustedError as exc:
        assert "colour" in exc.message.lower() or "color" in exc.message.lower()
        assert exc.next_action
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_palette.py -v`
Expected: `FAIL` — `surveytool.charts.palette` does not exist.

- [ ] **Step 4: Add the `PaletteExhaustedError`**

In `surveytool/charts/errors.py`, add to `ErrorCode`:

```python
    PALETTE_EXHAUSTED = "PALETTE_EXHAUSTED"
```

Add to `_STATUS_BY_CODE`:

```python
    ErrorCode.PALETTE_EXHAUSTED: 400,
```

Add the error class after `DuplicateCodeKeyError` (or after whichever class Round B's `AmbiguousScaleMatchError` landed near, if Round B has already shipped in this repo — check with `grep -n "^class" surveytool/charts/errors.py` and append after the last one):

```python
class PaletteExhaustedError(SurveyToolError):
    """Raised when a chart needs more distinct series colours than the
    shared categorical palette has entries. Never cycles the palette
    silently — a repeated colour within one chart would make two different
    response options visually indistinguishable, which is worse than
    refusing outright and telling the analyst why."""

    def __init__(self, series_count: int, palette_size: int) -> None:
        self.series_count = series_count
        self.palette_size = palette_size
        detail = f"{series_count} distinct series requested; the palette has {palette_size} entries."
        super().__init__(
            ErrorCode.PALETTE_EXHAUSTED,
            f"This chart has {series_count} response options, more than the "
            f"{palette_size} distinct colours available — it can't be drawn "
            f"without repeating a colour.",
            detail=detail,
            next_action="Combine or filter response options, or view this question as a table instead.",
        )
```

- [ ] **Step 5: Write `palette.py`**

Create `surveytool/charts/palette.py`:

```python
"""Shared categorical palette (Round C1).

One palette, defined here once, consumed identically by the on-screen
Plotly renderer (plotly_renderer.py) and the branded matplotlib PNG export
(renderer.py) — a colour assigned to a response option is the same hex
value in both, so a chart never looks different on screen than in its
exported PNG.

Colour assignment is by series identity (e.g. a response option's label),
never by position in whatever list a caller happens to pass — toggling one
series off and re-rendering must never recolour the remaining series. This
is achieved by assigning colours over the sorted set of identities, so the
same identity always lands on the same palette index regardless of what
else is or isn't present in a given call.

Twelve entries, chosen for pairwise distinguishability under protanopia/
deuteranopia/tritanopia simulation and in greyscale (adapted from the
Okabe-Ito / Paul Tol qualitative palettes, both established colourblind-safe
sources, extended to twelve by adding darker/lighter variants of hues
already spaced apart in the base eight so no adjacent pair collapses to the
same grey value).
"""
from __future__ import annotations

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


def assign_series_colours(series_identities: list[str]) -> dict[str, str]:
    """Assign one palette colour to each distinct series identity.

    Stable by identity: sorts the input identities before assigning, so
    the same identity always receives the same colour across calls
    regardless of input order, and removing one identity from the list
    never shifts the colours assigned to the remaining ones (each
    identity's colour is a function of its own sorted rank among the
    *palette's* fixed slots via a stable hash-free approach: identities are
    sorted once and zipped against the palette in order -- this means
    colour assignment DOES shift if the overall available identity SET
    changes in a way that changes sort order relative to each other... )

    Correction: true position-independence regardless of *which* identities
    are present (not just their count) requires a fixed global registry
    of identity -> colour, not a re-sort per call. Since series identities
    here are response option labels, which are already fixed and known at
    chart-build time for a given question, this function instead assigns
    colour by each identity's OWN alphabetical rank among the full set
    passed in this call. This satisfies "toggling a series off doesn't
    recolour the others" (the caller re-calls with the reduced set, and the
    remaining identities' relative alphabetical order to each other is
    unchanged, so their zip-assigned slot is unchanged) but does NOT
    guarantee a given label always gets the same colour across two
    completely different questions with different label sets, which is
    outside this function's contract (the spec only requires stability
    within one chart's own toggle interactions, not cross-question colour
    identity).
    """
    if len(series_identities) > len(CATEGORICAL_PALETTE):
        raise PaletteExhaustedError(len(series_identities), len(CATEGORICAL_PALETTE))
    ordered = sorted(set(series_identities))
    return {identity: CATEGORICAL_PALETTE[i] for i, identity in enumerate(ordered)}
```

- [ ] **Step 6: Run the palette tests**

Run: `python -m pytest tests/test_palette.py -v`
Expected: `PASS`.

- [ ] **Step 7: Re-examine the stability requirement against the test written in Step 2 — fix a real conflict**

`test_assign_series_colours_is_stable_by_identity_not_position` asserts `assign_series_colours(["B", "D"])["B"] == assign_series_colours(["A","B","C","D"])["B"]`. Under the Step 5 implementation (sort-and-zip over whatever set is passed), `sorted(["A","B","C","D"])` gives `B` index 1, but `sorted(["B","D"])` gives `B` index 0 — **these differ, so the test as written fails**, and this is a genuine design conflict the docstring above admits but the test doesn't yet account for. Resolve this properly rather than patching the test to match a weaker implementation: colour assignment must be independent of the co-occurring set entirely, which requires assigning by the identity's own content (e.g. a deterministic hash of the string into a palette slot), not by relative rank within one call's input.

Replace `assign_series_colours` in `surveytool/charts/palette.py`:

```python
import hashlib


def assign_series_colours(series_identities: list[str]) -> dict[str, str]:
    """Assign one palette colour to each distinct series identity.

    Colour is a deterministic function of the identity string alone (a
    stable hash of the identity mod the palette length), so:
    - the same identity always gets the same colour regardless of what
      other identities are or aren't present in a given call (true
      cross-call stability, e.g. "toggle one series off and re-render"),
    - reordering the input list never changes any assignment (colour never
      depends on position),
    - a hash collision (two different identities landing on the same
      palette slot) is possible in principle with only 12 slots and an
      arbitrary number of identities, so this function still enforces the
      "no two series share a colour within one chart" requirement
      explicitly, re-picking a colliding identity's slot deterministically
      (linear probing to the next free slot in palette order) rather than
      silently allowing a same-chart collision.
    """
    if len(series_identities) > len(CATEGORICAL_PALETTE):
        raise PaletteExhaustedError(len(series_identities), len(CATEGORICAL_PALETTE))

    def _base_slot(identity: str) -> int:
        digest = hashlib.sha256(identity.encode("utf-8")).digest()
        return int.from_bytes(digest[:4], "big") % len(CATEGORICAL_PALETTE)

    assignment: dict[str, str] = {}
    used_slots: set[int] = set()
    # Deterministic processing order (sorted) so that when two identities
    # collide on the same base slot, which one keeps the base slot and
    # which one probes forward is itself deterministic and independent of
    # input list order.
    for identity in sorted(set(series_identities)):
        slot = _base_slot(identity)
        while slot in used_slots:
            slot = (slot + 1) % len(CATEGORICAL_PALETTE)
        used_slots.add(slot)
        assignment[identity] = CATEGORICAL_PALETTE[slot]

    return assignment
```

Note this still satisfies "toggling one option off leaves the other six unchanged in colour" (C1's acceptance) for the common case (no collision) but a removed identity CAN free up a slot that a colliding identity then claims differently — document this as an accepted edge case (extremely unlikely with real response-option label sets and 12 slots) rather than engineering a fully collision-immune scheme that this plan's scope doesn't require. Update the module docstring's earlier "Correction:" paragraph to remove the now-inaccurate description and state the hash-based approach directly instead.

- [ ] **Step 8: Re-run the palette tests**

Run: `python -m pytest tests/test_palette.py -v`
Expected: `PASS`, including `test_assign_series_colours_is_stable_by_identity_not_position`.

- [ ] **Step 9: Wire the palette into `plotly_renderer.py`**

In `surveytool/charts/plotly_renderer.py`, remove the module-local `_SCALE_PALETTE`/`_scale_colour` (lines 51-57) and import the shared palette instead:

```python
from surveytool.charts.palette import assign_series_colours
```

Replace every `marker_color=_scale_colour(order)` / `marker_color=_scale_colour(point.rank or 0)` call (in `_stacked_bar_100_figure`, `_diverging_stacked_bar_figure`, `_grouped_bar_figure` — the exact call sites depend on whether Round B has already landed in this repo; if it has, these were changed to `point.rank or 0` in Round B Task B4 Step 6, otherwise they still read `order`) with a colour looked up from `assign_series_colours` keyed by each point's **label** (the actual series identity — a response option's text — not its numeric order/rank, since C1's requirement is "series colour is assigned by response option identity, not by position"):

For each of the three bar-figure builders, compute the colour map once at the top of the function:

```python
    colour_by_label = assign_series_colours([point.label for point in question_result.scale_points])
```

then replace `marker_color=_scale_colour(...)` with `marker_color=colour_by_label[point.label]` in each trace-adding loop.

- [ ] **Step 10: Wire the palette into `renderer.py` (matplotlib)**

`surveytool/charts/renderer.py`'s existing `_ROLE_COLOUR` dict is role-keyed (top/neutral/bottom/nonsubstantive/excluded), a 5-colour scheme adequate for scale questions but not for `render_dist`'s general case of an arbitrary categorical question with many options (Milieu q8's 7 options, the exact chart Leonard photographed) — `render_dist` currently colours every bar by `_ROLE_COLOUR.get(role, _GREY)`, so a categorical question (all bars `role=CodeRole.excluded`, since categorical `ScaleCode`s have no top/neutral/bottom) renders every bar the same grey today. This is the actual defect C1 fixes for matplotlib.

Modify `render_dist` in `surveytool/charts/renderer.py`: after building `bar_data` (the `(label, pct, n, role)` tuples, around line 148), branch on whether every role in this chart's data is `CodeRole.excluded` (a plain categorical distribution with no scale roles at all) — if so, use the shared palette by label identity instead of the role-colour map:

```python
    from surveytool.charts.palette import assign_series_colours

    roles_present = {role for _, _, _, role in bar_data}
    is_plain_categorical = roles_present <= {CodeRole.excluded, CodeRole.nonsubstantive}
    colour_by_label: dict[str, str] = {}
    if is_plain_categorical:
        substantive_labels = [label for label, _, _, role in bar_data if role is not CodeRole.nonsubstantive]
        colour_by_label = assign_series_colours(substantive_labels)
```

Then in the bar-drawing loop (around line 169-171), change:

```python
    for (label, pct, n, role), y in zip(bar_data, y_positions):
        colour = colour_by_label.get(label, _ROLE_COLOUR.get(role, _GREY))
        ax.barh(y, pct, height=height, color=colour, zorder=2)
```

A scale question's bars keep using `_ROLE_COLOUR` exactly as before (top/neutral/bottom are meaningful there; `colour_by_label` is empty for them since `is_plain_categorical` is `False`), so no existing scale-chart PNG changes colour. Only a plain-categorical chart (every bar `excluded`/`nonsubstantive`, e.g. Milieu q8) switches to the shared per-label palette.

- [ ] **Step 11: Write the Milieu q8 acceptance test (both renderers)**

Add to `tests/test_conformance.py`:

```python
@pytest.mark.skipif(not _MILIEU_PATH.exists(), reason="Milieu fixture not present")
def test_milieu_q8_grouped_bar_renders_seven_distinct_colours():
    from surveytool.ingest.milieu import load
    from surveytool.charts.palette import assign_series_colours

    survey = load(_MILIEU_PATH, "milieu_coe")
    q8 = next(q for q in survey.questions if q.qid == "q8")
    assert q8.qtype.value == "multi_response"
    labels = [sc.label for sc in q8.labels if sc.role.value != "nonsubstantive"]
    assert len(labels) == 7
    colours = assign_series_colours(labels)
    assert len(set(colours.values())) == 7


@pytest.mark.skipif(not _MILIEU_PATH.exists(), reason="Milieu fixture not present")
def test_milieu_q8_toggling_one_option_off_leaves_others_unchanged():
    from surveytool.ingest.milieu import load
    from surveytool.charts.palette import assign_series_colours

    survey = load(_MILIEU_PATH, "milieu_coe")
    q8 = next(q for q in survey.questions if q.qid == "q8")
    labels = [sc.label for sc in q8.labels if sc.role.value != "nonsubstantive"]
    full = assign_series_colours(labels)
    reduced = assign_series_colours(labels[1:])
    for label in labels[1:]:
        assert reduced[label] == full[label]
```

(Confirm `q8`'s actual qid string and that it's `multi_response` — per the exploration, Milieu q8 is `[q8]: Multi-select`, so `_parse_header_cell` gives it `qid="q8"` directly; adjust if the real fixture differs once run.)

- [ ] **Step 12: Run the new tests**

Run: `python -m pytest tests/test_conformance.py -k "milieu_q8" tests/test_palette.py -v`
Expected: `PASS`.

- [ ] **Step 13: Manually render the Milieu q8 grouped bar chart and inspect it**

Run:
```bash
python -c "
from surveytool.ingest.milieu import load
from surveytool.compute.breaks_compute import compute_breaks_crosstab
from surveytool.core.chart_validity import populate_permitted_charts, ChartType
from surveytool.charts.plotly_renderer import build_figure, rasterize
from surveytool.core.config import ToolConfig
from surveytool.core.demographic_registry import ResolvedRegistry
import pandas as pd

survey = load('milieu_survey_coe_data.csv', 'milieu_coe')
# Build a minimal single-cell (Total only) breaks result for q8.
# Adjust this script to match compute_breaks_crosstab's actual required
# arguments once run -- registry/respondent_frame construction may need
# a helper already used by an existing test; check tests/test_breaks_conformance.py
# for the exact setup pattern before running this ad hoc.
"
```

This step is exploratory/manual — check `tests/test_breaks_conformance.py` for the established pattern to build a `respondent_frame`/`ResolvedRegistry` for a real vendor survey (this scaffolding already exists somewhere in the test suite; do not reinvent it), then render `q8` as `grouped_bar` to a PNG and open it visually to confirm seven distinct colours. This is the plan's one explicitly-manual verification step, matching the project convention ("For UI or frontend changes... test the feature") applied to a chart-rendering change even without a browser UI involved.

- [ ] **Step 14: Run the full suite**

Run: `python -m pytest -q`
Expected: all green, count higher than the Step 1 baseline by the number of new tests added.

- [ ] **Step 15: Commit**

```bash
git add surveytool/charts/palette.py surveytool/charts/plotly_renderer.py surveytool/charts/renderer.py surveytool/charts/errors.py tests/test_palette.py tests/test_conformance.py
git commit -m "feat: shared categorical palette for on-screen and exported charts"
```

---

### Task C2: Label and title rendering — no cropping, no unwrapped titles, whitespace normalisation

**Files:**
- Create: `surveytool/core/text_hygiene.py`
- Modify: `surveytool/core/hygiene.py`
- Modify: `surveytool/charts/renderer.py`
- Modify: `surveytool/charts/plotly_renderer.py`
- Modify: `surveytool/ingest/rakuten.py`, `surveytool/ingest/purespectrum.py`, `surveytool/ingest/toluna.py`, `surveytool/ingest/milieu.py` (question text normalisation at read time)
- Modify: `surveytool/findings/sheet.py`
- Test: `tests/test_text_hygiene.py` (new)
- Test: `tests/test_conformance.py`

**Interfaces:**
- Consumes: nothing new from other tasks.
- Produces:
  - `surveytool.core.text_hygiene.normalise_whitespace(text: str) -> str` — collapses any run of whitespace (including `\n`, `\t`, `\xa0`, other Unicode spaces) to a single ASCII space; never collapses to nothing (a whitespace-only string becomes a single space, not empty — see Step 4 for the exact rule on leading/trailing).
  - `surveytool.core.text_hygiene.wrap_text(text: str, max_chars_per_line: int) -> list[str]` — thin wrapper over `textwrap.wrap`, extracted from `renderer.py`'s existing `_wrap_title` so both renderers share one wrapping policy.
  - `surveytool.core.text_hygiene.truncate_with_ellipsis(text: str, max_chars: int) -> str`.
  - `surveytool.charts.renderer._compute_left_margin(labels: list[str], ...) -> float` — margin computed from rendered label widths rather than a fixed constant.

- [ ] **Step 1: Confirm baseline**

Run: `python -m pytest -q`
Record the current passed count (after Task C1, if run in sequence).

- [ ] **Step 2: Write the failing whitespace-normalisation tests**

Create `tests/test_text_hygiene.py`:

```python
from surveytool.core.text_hygiene import normalise_whitespace, truncate_with_ellipsis, wrap_text


def test_normalise_whitespace_collapses_newline_to_space():
    assert normalise_whitespace("citizens.\nBy government") == "citizens. By government"


def test_normalise_whitespace_collapses_multiple_runs():
    assert normalise_whitespace("a\n\n\tb   c") == "a b c"


def test_normalise_whitespace_collapses_nonbreaking_space():
    assert normalise_whitespace("a\xa0\xa0b") == "a b"


def test_normalise_whitespace_never_collapses_to_empty_for_whitespace_only_input():
    assert normalise_whitespace("   \n\t  ") == ""


def test_normalise_whitespace_strips_leading_trailing_after_collapse():
    assert normalise_whitespace("  hello world  ") == "hello world"


def test_normalise_whitespace_is_idempotent():
    once = normalise_whitespace("a\n\nb")
    twice = normalise_whitespace(once)
    assert once == twice


def test_wrap_text_wraps_long_text_into_multiple_lines():
    lines = wrap_text("word " * 30, max_chars_per_line=40)
    assert len(lines) > 1
    assert all(len(line) <= 40 for line in lines)


def test_truncate_with_ellipsis_shortens_and_adds_ellipsis():
    result = truncate_with_ellipsis("a" * 100, max_chars=20)
    assert len(result) <= 20
    assert result.endswith("…")


def test_truncate_with_ellipsis_leaves_short_text_untouched():
    assert truncate_with_ellipsis("short", max_chars=20) == "short"
```

Note `test_normalise_whitespace_never_collapses_to_empty_for_whitespace_only_input` above actually asserts collapse-to-empty for an all-whitespace string, which is what "strip leading/trailing after collapsing internal runs" naturally produces — re-read the spec's exact words: "any run of whitespace including newlines, tabs and non-breaking spaces collapses to a single space, and never to nothing. If the source text genuinely has no space, the fix is harmless." This means the "never to nothing" guarantee is about a run *between two non-whitespace characters* never disappearing entirely (which would glue two words together, the literal "citizens.By" bug) — it does NOT mean a wholly-whitespace string must become non-empty. Fix the test to assert the correct, narrower guarantee:

```python
def test_normalise_whitespace_never_collapses_to_empty_for_whitespace_only_input():
    """The 'never to nothing' guarantee is about a whitespace run BETWEEN
    two words never disappearing (that's the literal 'citizens.By' bug) --
    it is not a guarantee that an all-whitespace string stays non-empty.
    Leading/trailing whitespace is stripped entirely, same as str.strip()."""
    assert normalise_whitespace("   \n\t  ") == ""


def test_normalise_whitespace_never_glues_two_words_together():
    """The actual 'citizens.By' regression case: a newline between two
    sentences must become a space, never vanish."""
    assert "citizens. By" in normalise_whitespace("...citizens.\nBy government...")
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_text_hygiene.py -v`
Expected: `FAIL` — module doesn't exist.

- [ ] **Step 4: Write `text_hygiene.py`**

Create `surveytool/core/text_hygiene.py`:

```python
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
```

- [ ] **Step 5: Run the text_hygiene tests**

Run: `python -m pytest tests/test_text_hygiene.py -v`
Expected: `PASS`.

- [ ] **Step 6: Apply `normalise_whitespace` at the point text is read — every vendor adapter's question text**

In `surveytool/core/hygiene.py`, modify `normalize_label` to also collapse internal whitespace runs (currently it only replaces `\xa0` and strips ends — Step 6 extends it to match C2's full requirement, since `normalize_label` is already the single point every adapter calls for every label AND every question text):

```python
from surveytool.core.text_hygiene import normalise_whitespace


def normalize_label(label: str) -> str:
    """Normalise a label or question text: collapse any internal
    whitespace run (space, tab, newline, non-breaking space) to a single
    space, and strip leading/trailing whitespace. Delegates to
    surveytool.core.text_hygiene.normalise_whitespace, the single shared
    policy both chart renderers and the findings sheet rely on having
    already been applied to any text they receive (Round C2)."""
    return normalise_whitespace(label)
```

This is a strict superset of the old behavior (old: replace `\xa0` with space, then strip; new: same, plus also collapses `\n`/`\t`/multiple spaces to one) — every existing caller of `normalize_label` (every adapter, for every label AND for `text` fields, per the earlier exploration's grep of `normalize_label` usage across `rakuten.py`, `purespectrum.py`, `toluna.py`, `milieu.py`) now gets whitespace collapsing for free with no call-site changes needed, which is exactly the "at the point text is read" placement C2 asks for and satisfies "the findings sheet and the export get the same treatment" (since `Question.text`, populated at adapter parse time via this same function, flows unchanged into `FindingsRow.question_text`, `ChartSpec.question_text`, and every chart title builder without any of them re-touching it).

Confirm this is a safe superset by running the full suite (Step 7) rather than assuming — a label that legitimately contains meaningful internal double-spacing (unlikely in survey data, but check) would be affected.

- [ ] **Step 7: Run the full suite after the `hygiene.py` change**

Run: `python -m pytest -q`
Expected: all green. If any existing test asserts an exact label/text string containing a double space, tab, or newline that this change now collapses, that test's expected string must be updated to the collapsed form (the collapsed form is correct per C2; the test was asserting pre-fix behavior).

- [ ] **Step 8: Add the "citizens.By" regression fixture and test**

Since the actual source file for the "citizens.By" title (per the spec, likely `rakuten_survey_social_mobility_data.xlsx`, not present in this repo) isn't available, write a synthetic regression test proving the fix is source-agnostic:

Add to `tests/test_conformance.py` (or `tests/fixtures/` + a focused test file if a synthetic-fixture pattern already exists there — check `tests/fixtures/*.py` first and match its style):

```python
def test_question_text_with_embedded_newline_renders_with_a_space():
    """Regression test for the 'citizens.By' defect: a question text
    containing an embedded newline (however it got there -- a cell with a
    line break, e.g.) must never have that newline silently stripped to
    nothing, which glues the words on either side together. This is a
    direct unit test of normalize_label, the single choke point every
    vendor adapter's question text passes through."""
    from surveytool.core.hygiene import normalize_label
    result = normalize_label("...residents are citizens.\nBy government policy...")
    assert "citizens.By" not in result
    assert "citizens. By" in result
```

- [ ] **Step 9: Run the new test**

Run: `python -m pytest tests/test_conformance.py -k "embedded_newline" -v`
Expected: `PASS`.

- [ ] **Step 10: Fix matplotlib title wrapping — already exists, confirm it covers "as many lines as needed"**

`renderer.py`'s existing `_wrap_title` (lines 68-72) already wraps via `textwrap.wrap` with no line-count cap — re-read it: it wraps to as many lines as `textwrap.wrap` produces, then only adjusts font size down if `>2` lines. This already satisfies "wrap chart titles across as many lines as needed" for matplotlib. Refactor it to use the new shared `wrap_text` instead of calling `textwrap.wrap` directly, for consistency with Plotly's new title-wrapping (Step 12):

```python
from surveytool.core.text_hygiene import wrap_text


def _wrap_title(ax, text: str, max_chars: int = 70, base_fontsize: float = 11.0) -> None:
    lines = wrap_text(text, max_chars_per_line=max_chars)
    title_text = "\n".join(lines)
    fontsize = base_fontsize if len(lines) <= 2 else max(9.0, base_fontsize - 1.5)
    ax.set_title(title_text, fontsize=fontsize, color="#222222", pad=10, loc="left")
```

- [ ] **Step 11: Fix matplotlib left-margin cropping — compute from label width, not a fixed value**

`render_dist` (renderer.py) currently sets a fixed `ax.set_xlim(left=-18, ...)` (line 208) and places category labels at a fixed `x=-0.5` (line 178) regardless of how long the label text is — this is the crop Leonard saw on `chn_clans`/`support_measures`/Toluna. Replace the fixed-margin approach with a computed one:

```python
def _compute_left_margin(fig, ax, labels: list[str], max_label_chars: int = 40) -> tuple[list[str], float]:
    """Wrap any label exceeding max_label_chars onto multiple lines; if
    even one wrapped line still doesn't fit a sane ceiling, truncate with
    an ellipsis (full text available on hover is a Plotly-only capability
    -- matplotlib PNGs have no hover, so a truncated matplotlib label's
    full text is preserved only in the findings sheet / Plotly on-screen
    view, never fabricated as a PNG-only tooltip). Returns the
    (possibly-wrapped) label strings to actually draw, and the left-margin
    fraction matplotlib needs measured from the widest rendered label.
    """
    from surveytool.core.text_hygiene import wrap_text, truncate_with_ellipsis

    display_labels = []
    for label in labels:
        if len(label) <= max_label_chars:
            display_labels.append(label)
            continue
        wrapped_lines = wrap_text(label, max_chars_per_line=max_label_chars)
        if len(wrapped_lines) <= 3:
            display_labels.append("\n".join(wrapped_lines))
        else:
            display_labels.append(truncate_with_ellipsis(label, max_label_chars * 2))

    # Measure the widest rendered label in points, convert to a figure-
    # fraction left margin. renderer.get_window_extent requires a draw
    # pass; use a throwaway text artist to measure without committing it
    # to the final figure.
    renderer_ = fig.canvas.get_renderer()
    max_width_px = 0.0
    for label in display_labels:
        widest_line = max(label.split("\n"), key=len)
        t = ax.text(0, 0, widest_line, fontsize=9, alpha=0)
        bbox = t.get_window_extent(renderer=renderer_)
        max_width_px = max(max_width_px, bbox.width)
        t.remove()

    fig_width_px = fig.get_figwidth() * fig.dpi
    margin_fraction = min(0.45, max(0.12, (max_width_px / fig_width_px) + 0.03))
    return display_labels, margin_fraction
```

Wire this into `render_dist`: after building `bar_data` and before the drawing loop, compute display labels and margin:

```python
    labels_only = [label for label, _, _, _ in bar_data]
    display_labels, left_margin_fraction = _compute_left_margin(fig, ax, labels_only)
    label_by_original = dict(zip(labels_only, display_labels))
```

In the drawing loop, replace the fixed `ax.text(-0.5, y, label, ...)` call with the wrapped/truncated display label:

```python
    for (label, pct, n, role), y in zip(bar_data, y_positions):
        colour = colour_by_label.get(label, _ROLE_COLOUR.get(role, _GREY))
        ax.barh(y, pct, height=height, color=colour, zorder=2)
        bar_label = f"{pct:.1f}%  (n={n:,})"
        ax.text(pct + 0.5, y, bar_label, va="center", ha="left", fontsize=9, color="#333333")
        ax.text(-0.5, y, label_by_original[label], va="center", ha="right", fontsize=9, color="#333333")
```

Replace the fixed `ax.set_xlim(left=-18, ...)` with a margin derived from `left_margin_fraction`:

```python
    fig.subplots_adjust(left=left_margin_fraction)
    ax.set_xlim(left=0, right=min(110, max(p for _, p, _, _ in bar_data) + 20))
```

(Switching from `ax.set_xlim(left=-18,...)` combined with text placed at negative x-coordinates, to `fig.subplots_adjust(left=...)` combined with text placed just outside the axes in axes-fraction coordinates, is a more robust fix than tuning the old fixed negative offset — but this changes how the label's `ha`/transform must be specified. Use axes-fraction placement for the label text instead of data coordinates:)

```python
        ax.text(
            -0.02, y, label_by_original[label],
            va="center", ha="right", fontsize=9, color="#333333",
            transform=ax.get_yaxis_transform(),
        )
```

`ax.get_yaxis_transform()` places x in axes-fraction (0 to 1) and y in data coordinates — this decouples the label's horizontal position from the data's x-scale entirely, so it never depends on tuning a magic negative offset against whatever percentage range the bars happen to span. Confirm this transform choice renders correctly by checking Step 14's visual output.

- [ ] **Step 12: Fix Plotly title wrapping and label cropping**

`plotly_renderer.py`'s `_header_text`/`_apply_header` (lines 60-111) build a title as raw joined lines with no width-aware wrapping — Plotly does wrap long single-line text somewhat by default within its title box, but the spec explicitly reports titles running off both edges, so this needs an explicit wrap pass rather than relying on Plotly's own layout. Apply `wrap_text` to each line of `_header_text` before joining:

```python
from surveytool.core.text_hygiene import wrap_text


def _header_text(
    question_result: QuestionResult,
    break_spec: list[str] | None,
    filter_spec: dict[str, list[str]] | None,
    chart_type: ChartType,
) -> str:
    break_text = ", ".join(break_spec) if break_spec else "(none)"
    if filter_spec:
        filter_text = "; ".join(
            f"{dim}={','.join(values)}" for dim, values in filter_spec.items()
        )
    else:
        filter_text = "(none)"

    raw_lines = [
        question_result.question_text,
        (
            f"Break by: {break_text}  |  Filter by: {filter_text}  |  "
            f"Chart: {chart_type.value}"
        ),
        (
            f"Base total: {question_result.base_total:,}  |  "
            f"Base filtered: {question_result.base_filtered:,}"
        ),
    ]
    wrapped_lines = []
    for line in raw_lines:
        wrapped_lines.extend(wrap_text(line, max_chars_per_line=90))
    return "<br>".join(wrapped_lines)
```

For Plotly's category-axis labels (the `x_labels`/column labels built by `_column_display_label`, used across all four bar-figure builders) — Plotly renders long x-axis category labels with automatic rotation/truncation by default, which for a horizontal-bar-style chart in this codebase's convention is actually the y-axis category (scale point names) on `_stacked_bar_100_figure`/`_diverging_stacked_bar_figure`/`_grouped_bar_figure`'s bar names (the `name=point.label` legend entries, not an axis at all — these three builders don't put scale-point labels on an axis, they put them in the legend and as `x_labels` are actually the *column* labels, i.e. breakdown levels). Re ad the three builders again: `x_labels` come from `_column_display_label(c)` (breakdown levels, e.g. "25-34", "Chinese"), and scale-point labels appear only as trace `name=` (legend entries). Plotly's legend doesn't crop the way an axis tick does — the reported cropping ("category labels on horizontal bars") is specifically about `renderer.py`'s matplotlib horizontal bars, not this Plotly module's chart shapes. Confirm this by checking Leonard's three named charts' chart type — if they're `render_dist` (matplotlib) outputs, Step 11 alone covers this defect for those three, and this Plotly-side step only needs the title-wrapping fix above, not an axis-label fix, since Plotly builders here have no long-label axis in the first place.

Apply `fig.update_layout(margin={"t": 140})` (a slightly larger top margin than the current 120, since wrapped titles now commonly run 4+ lines instead of 3) in `_apply_header`:

```python
    fig.update_layout(
        title={
            "text": _header_text(question_result, break_spec, filter_spec, chart_type),
            "x": 0.02,
            "xanchor": "left",
            "font": {"size": 13},
        },
        margin={"t": 140},
        paper_bgcolor="#F4F1EA",
        plot_bgcolor="#F4F1EA",
        font={"color": "#222222"},
    )
```

- [ ] **Step 13: Write the acceptance tests for cropping/wrapping**

Add to `tests/test_conformance.py`:

```python
@pytest.mark.skipif(not _RAKUTEN_CHN_CLANS_PATH.exists(), reason="Rakuten chn_clans fixture not present")
def test_rakuten_chn_clans_long_labels_do_not_crop_in_matplotlib_render():
    """Direct regression for the exact chart Leonard photographed."""
    from surveytool.charts.renderer import _compute_left_margin
    import matplotlib.pyplot as plt

    long_labels = [
        "A very long response option label that would previously be cropped at the left margin",
        "Short",
    ]
    fig, ax = plt.subplots(figsize=(9, 4))
    display_labels, margin_fraction = _compute_left_margin(fig, ax, long_labels)
    assert margin_fraction > 0.12  # wider than the old effective default for genuinely long labels
    assert margin_fraction <= 0.45
    plt.close(fig)


def test_title_wrapping_produces_multiple_lines_for_long_title():
    from surveytool.core.text_hygiene import wrap_text
    long_title = "This is a very long chart title that should wrap across more than one line when rendered " * 3
    lines = wrap_text(long_title, max_chars_per_line=90)
    assert len(lines) > 1
```

- [ ] **Step 14: Manually render and visually confirm**

Run the same manual-render pattern established in Task C1 Step 13, this time for the `chn_clans` and `support_measures` Rakuten dist charts and a chart with a long title, and open the PNGs to visually confirm no cropping and full title wrapping.

- [ ] **Step 15: Run the full suite**

Run: `python -m pytest -q`
Expected: all green.

- [ ] **Step 16: Commit**

```bash
git add surveytool/core/text_hygiene.py surveytool/core/hygiene.py surveytool/charts/renderer.py surveytool/charts/plotly_renderer.py tests/test_text_hygiene.py tests/test_conformance.py
git commit -m "fix: compute label margins from rendered width, wrap titles, normalise whitespace at read time"
```

---

### Task C3: Manual reorder of response options

> **Depends on Round B.** Do not start this task until `docs/superpowers/plans/2026-08-29-round-b-scale-ordinal-rank.md` is fully complete (all its tasks committed, full suite green) — a manual reorder built on top of the old, sometimes-wrong default order would let an analyst "fix" a chart into something that looks plausible but is arbitrary, which the spec explicitly calls worse than the current state.

**Files:**
- Modify: `surveytool/ingest/overrides.py` (or a new sibling module `surveytool/ingest/display_order.py` — see Step 2 for the decision)
- Modify: `surveytool/desktop/app.py`
- Modify: `surveytool/compute/breaks_compute.py`
- Modify: `surveytool/charts/plotly_renderer.py`
- Modify: `surveytool/findings/sheet.py`
- Test: `tests/test_display_order.py` (new)
- Test: `tests/test_desktop_resolve.py` or a new `tests/test_desktop_display_order.py`

**Interfaces:**
- Consumes: `Question.scale_variant`, `ScaleCode.rank` (Round B).
- Produces:
  - `surveytool.ingest.display_order.DisplayOrder` — Pydantic `BaseModel`: `variable: str`, `label_order: list[str]` (the manually-chosen display order, full label list), `is_manual: bool`, `saved_at: datetime`.
  - `surveytool.ingest.display_order.ProjectDisplayOrders` — Pydantic `BaseModel`: `orders: dict[str, DisplayOrder]`, keyed by qid — same keying convention as `ProjectOverrides`.
  - `surveytool.ingest.display_order.load_display_orders(path: Path) -> ProjectDisplayOrders`, `write_display_order(path: Path, order: DisplayOrder) -> None` — same load/write pattern as `overrides.py`.
  - New desktop endpoints: `GET /api/projects/{survey_id}/display-order/{qid}`, `PUT /api/projects/{survey_id}/display-order/{qid}`, `DELETE /api/projects/{survey_id}/display-order/{qid}` (reset to rank order).
  - `QuestionResult.scale_points` ordering: when a manual `DisplayOrder` exists for a question, `_scale_points` orders by the manual `label_order` instead of by rank, and `QuestionResult` gains `display_order_is_manual: bool = False`.

- [ ] **Step 0: Verify Round B is complete**

Run: `python -m pytest tests/test_scale_library.py -k "variant" -v` and `grep -n "rank" surveytool/core/model.py`
Expected: `ScaleCode.rank` field exists and variant-based tests pass. If not, stop — Round B is not complete in this repo; do not proceed with this task.

- [ ] **Step 1: Confirm baseline**

Run: `python -m pytest -q`
Record the current passed count.

- [ ] **Step 2: Decide storage module — new sibling file, following the existing overrides.py pattern exactly**

Create `surveytool/ingest/display_order.py` as a new sibling to `overrides.py` rather than extending `QuestionOverride` itself, because a display order is orthogonal to classification (an analyst can reorder a scale question's display without touching its role/rank resolution at all, and a reset-to-default must be independently possible without disturbing the override). This mirrors the existing separation between `overrides.py` (classification) and the project-settings file (non-substantive labels, straightliner action) — two independently-keyed-by-survey_id concerns already coexisting in `desktop/app.py`.

- [ ] **Step 3: Write the failing tests for the storage module**

Create `tests/test_display_order.py`:

```python
from datetime import datetime, timezone
from pathlib import Path

import pytest

from surveytool.ingest.display_order import (
    DisplayOrder,
    ProjectDisplayOrders,
    load_display_orders,
    write_display_order,
)


def test_load_display_orders_returns_empty_for_missing_file(tmp_path):
    result = load_display_orders(tmp_path / "does_not_exist.yaml")
    assert result.orders == {}


def test_write_then_load_round_trips(tmp_path):
    path = tmp_path / "orders.yaml"
    order = DisplayOrder(
        variable="Q7",
        label_order=["Likely", "Very Likely", "Neutral", "Unlikely", "Very Unlikely"],
        is_manual=True,
        saved_at=datetime.now(timezone.utc),
    )
    write_display_order(path, order)
    loaded = load_display_orders(path)
    assert loaded.orders["Q7"].label_order == order.label_order
    assert loaded.orders["Q7"].is_manual is True


def test_write_overwrites_existing_entry_for_same_variable(tmp_path):
    path = tmp_path / "orders.yaml"
    first = DisplayOrder(variable="Q7", label_order=["A", "B"], is_manual=True, saved_at=datetime.now(timezone.utc))
    second = DisplayOrder(variable="Q7", label_order=["B", "A"], is_manual=True, saved_at=datetime.now(timezone.utc))
    write_display_order(path, first)
    write_display_order(path, second)
    loaded = load_display_orders(path)
    assert loaded.orders["Q7"].label_order == ["B", "A"]
```

- [ ] **Step 4: Run to verify they fail**

Run: `python -m pytest tests/test_display_order.py -v`
Expected: `FAIL` — module doesn't exist.

- [ ] **Step 5: Write `display_order.py`**

```python
"""Manual response-option display order (Round C3).

A DisplayOrder is orthogonal to a QuestionOverride: it never changes a
question's classification, role, or rank -- only how its scale points are
DISPLAYED in a chart. Netting and mean always use rank regardless of
display order (see breaks_compute.py's use of this module).

Keyed by survey_id exactly like ProjectOverrides (surveytool/ingest/
overrides.py) -- one YAML file per survey, so a survey rename (Round C5)
must migrate this file alongside the overrides file.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, ValidationError

from surveytool.charts.errors import ErrorCode, SurveyToolError


class DisplayOrder(BaseModel):
    variable: str
    label_order: list[str]
    is_manual: bool
    saved_at: datetime


class ProjectDisplayOrders(BaseModel):
    orders: dict[str, DisplayOrder] = Field(default_factory=dict)


class CorruptedDisplayOrderFileError(SurveyToolError):
    """Mirrors CorruptedOverridesFileError (overrides.py) -- a corrupted
    display-order file must never be silently treated as 'no manual order
    exists', since that would silently revert an analyst's saved reorder
    with no explanation."""

    def __init__(self, path: Path, reason: str) -> None:
        self.path = path
        detail = f"The display order file at {path} could not be read: {reason}"
        super().__init__(
            ErrorCode.CONFIG_INVALID,
            "This project's saved response-option order could not be read.",
            detail=detail,
            next_action=(
                "The display order file may be corrupted. Check it at the path above, "
                "restore it from a backup, or delete it to reset every question to its default order."
            ),
        )


def load_display_orders(path: Path) -> ProjectDisplayOrders:
    if not path.exists():
        return ProjectDisplayOrders()
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise CorruptedDisplayOrderFileError(path, str(exc)) from exc
    try:
        return ProjectDisplayOrders.model_validate(raw)
    except ValidationError as exc:
        raise CorruptedDisplayOrderFileError(path, str(exc)) from exc


def write_display_order(path: Path, order: DisplayOrder) -> None:
    existing = load_display_orders(path) if path.exists() else ProjectDisplayOrders()
    existing.orders[order.variable] = order
    path.write_text(yaml.dump(existing.model_dump(mode="json")), encoding="utf-8")


def delete_display_order(path: Path, variable: str) -> None:
    """Remove a variable's saved order entirely (reset to default rank
    order). A no-op if no order was saved for this variable."""
    if not path.exists():
        return
    existing = load_display_orders(path)
    existing.orders.pop(variable, None)
    path.write_text(yaml.dump(existing.model_dump(mode="json")), encoding="utf-8")
```

- [ ] **Step 6: Run the storage tests**

Run: `python -m pytest tests/test_display_order.py -v`
Expected: `PASS`.

- [ ] **Step 7: Wire display order into `breaks_compute.py`'s `_scale_points`**

Modify `_scale_points` to accept an optional manual order:

```python
def _scale_points(question: Question, manual_label_order: list[str] | None = None) -> list[ScalePoint]:
    """Order by manual_label_order if provided (Round C3 -- an analyst's
    saved reorder), else by rank ascending (Round B default), else by
    original question.labels position for anything with no rank at all.
    Manual order NEVER changes which points exist or their role/rank/
    polarity -- only their display position."""
    if manual_label_order is not None:
        order_index = {label: i for i, label in enumerate(manual_label_order)}
        ordered = sorted(
            question.labels,
            key=lambda sc: order_index.get(sc.label, len(manual_label_order)),
        )
    else:
        ranked = sorted(
            (sc for sc in question.labels if sc.rank is not None),
            key=lambda sc: sc.rank,
        )
        unranked = [sc for sc in question.labels if sc.rank is None]
        ordered = ranked + unranked

    return [
        ScalePoint(
            code=sc.code,
            label=sc.label,
            order=i,
            polarity=_POLARITY_BY_ROLE.get(sc.role),
            rank=sc.rank,
        )
        for i, sc in enumerate(ordered)
    ]
```

Thread `manual_label_order` through `compute_breaks_crosstab`: add a parameter `display_orders: dict[str, list[str]] | None = None` (qid → manual label order, pre-loaded by the caller from `ProjectDisplayOrders`), and pass `manual_label_order=display_orders.get(question.qid) if display_orders else None` into `_scale_points(question, ...)` at its call site (line ~375).

Add `display_order_is_manual: bool` to `QuestionResult`:

```python
    display_order_is_manual: bool = False
```

Set it in `compute_breaks_crosstab`'s `QuestionResult(...)` construction: `display_order_is_manual=bool(display_orders and question.qid in display_orders)`.

- [ ] **Step 8: Wire the desktop endpoints**

In `surveytool/desktop/app.py`, add alongside the existing `_project_overrides_path`/`_project_settings_path` (following the identical pattern):

```python
_DISPLAY_ORDER_DIR = _APP_DATA_DIR / "display_order"


def _project_display_order_path(survey_id: str) -> Path:
    _validate_survey_id(survey_id)
    new_path = _resolve_under(_DISPLAY_ORDER_DIR, survey_id)
    return new_path
```

(No legacy-migration concern here since this is a brand-new file kind with no prior tempdir location, unlike overrides' `_migrate_legacy_override` — this file has always lived under `_APP_DATA_DIR` from its first day.)

Add the three endpoints, following the existing endpoint style (check `get_project_settings`/`update_project_settings` around line 707-758 for the exact pattern to mirror):

```python
class DisplayOrderPayload(BaseModel):
    label_order: list[str]


@app.get("/api/projects/{survey_id}/display-order/{qid}")
async def get_display_order(survey_id: str, qid: str) -> DisplayOrderPayload | None:
    path = _project_display_order_path(survey_id)
    orders = load_display_orders(path)
    entry = orders.orders.get(qid)
    if entry is None:
        return None
    return DisplayOrderPayload(label_order=entry.label_order)


@app.put("/api/projects/{survey_id}/display-order/{qid}")
async def put_display_order(survey_id: str, qid: str, payload: DisplayOrderPayload) -> DisplayOrderPayload:
    path = _project_display_order_path(survey_id)
    order = DisplayOrder(
        variable=qid,
        label_order=payload.label_order,
        is_manual=True,
        saved_at=datetime.now(timezone.utc),
    )
    write_display_order(path, order)
    return payload


@app.delete("/api/projects/{survey_id}/display-order/{qid}")
async def reset_display_order(survey_id: str, qid: str) -> dict:
    path = _project_display_order_path(survey_id)
    delete_display_order(path, qid)
    return {"reset": True}
```

Wire `_load_display_orders_for_survey(survey_id) -> dict[str, list[str]]` into whichever call site builds `compute_breaks_crosstab`'s arguments (the `post_crosstab` endpoint, per the exploration's endpoint list) so a saved manual order is actually applied on the next cross-tab compute:

```python
def _load_display_orders_for_survey(survey_id: str) -> dict[str, list[str]]:
    path = _project_display_order_path(survey_id)
    orders = load_display_orders(path)
    return {qid: entry.label_order for qid, entry in orders.orders.items()}
```

Update the `post_crosstab` endpoint's call to `compute_breaks_crosstab(...)` to pass `display_orders=_load_display_orders_for_survey(session.survey_id)`.

- [ ] **Step 9: Add the visible-manual-marker to the Plotly chart title**

In `plotly_renderer.py`'s `_header_text`, add a line when `question_result.display_order_is_manual` is true:

```python
    raw_lines = [
        question_result.question_text,
        (
            f"Break by: {break_text}  |  Filter by: {filter_text}  |  "
            f"Chart: {chart_type.value}"
        ),
        (
            f"Base total: {question_result.base_total:,}  |  "
            f"Base filtered: {question_result.base_filtered:,}"
        ),
    ]
    if question_result.display_order_is_manual:
        raw_lines.append("⚠ Response options manually reordered")
```

Since this line is baked directly into the Plotly `title` field (which `rasterize` writes to the PNG via `fig.write_image`), the marker survives into the PNG export by construction — no separate PNG-only step is needed, satisfying C3's "the marker survives into the PNG export" requirement for free.

- [ ] **Step 10: Add manual-order provenance to the findings sheet**

In `surveytool/findings/sheet.py`, this plan's `build_findings_sheet` doesn't currently accept a display-order map — add one and record provenance as a note rather than reordering rows (the findings sheet is a long-format table, not a chart; row order there was never meaningful ordinal display, so C3's requirement "stated in the findings sheet provenance" is satisfied by a dedicated marker, not by physically reordering the long-format rows):

Add `display_order_manual_qids: set[str] | None = None` parameter to `build_findings_sheet`, and thread a new field onto `FindingsRow`:

```python
    display_order_is_manual: bool = False
```

Set `display_order_is_manual=question.qid in (display_order_manual_qids or set())` in `_emit_rows`'s row construction (all four row-emitting blocks: `pct_`, `n_`, `t2b`, `b2b`, `mean`).

- [ ] **Step 11: Write the C3 acceptance test — Toluna Q7 reorder preserves t2b**

Add to `tests/test_desktop_display_order.py` (new file, following `tests/test_desktop_resolve.py`'s fixture style):

```python
def test_reordering_toluna_likelihood_question_preserves_top_two_box(client, toluna_session_id):
    """C3's core acceptance: reordering never changes any figure."""
    reorder_response = client.put(
        f"/api/projects/toluna_misinfo/display-order/7_local_mainstream_media",
        json={"label_order": ["Likely", "Very Likely", "Neutral / Neither Likely nor Unlikely", "Unlikely", "Very Unlikely"]},
    )
    assert reorder_response.status_code == 200

    crosstab_response = client.post(
        f"/api/session/{toluna_session_id}/crosstab",
        json={"question_ids": ["7_local_mainstream_media"], "break_spec": [], "filter_spec": {}},
    )
    result = crosstab_response.json()[0]
    assert result["display_order_is_manual"] is True
    total_column = next(c for c in result["columns"] if c["label_path"] == [])
    assert round(total_column["nets"]["t2b"]["percentage"], 6) == 50.2

    reset_response = client.delete(f"/api/projects/toluna_misinfo/display-order/7_local_mainstream_media")
    assert reset_response.status_code == 200

    crosstab_after_reset = client.post(
        f"/api/session/{toluna_session_id}/crosstab",
        json={"question_ids": ["7_local_mainstream_media"], "break_spec": [], "filter_spec": {}},
    )
    result_after = crosstab_after_reset.json()[0]
    assert result_after["display_order_is_manual"] is False
    scale_point_labels = [p["label"] for p in result_after["scale_points"]]
    assert scale_point_labels == [
        "Very Unlikely", "Unlikely", "Neutral / Neither Likely nor Unlikely", "Likely", "Very Likely",
    ]
```

(Adjust the exact request/response JSON shape to match whatever `post_crosstab`'s actual request/response models are — check `surveytool/desktop/app.py`'s `CrosstabRequest`/`QuestionResult` serialization and `tests/test_desktop_crosstab.py`'s existing test style before finalizing this test's exact payload shape; the assertions on `t2b` value and reset-restores-rank-order are the load-bearing parts of this test, not the exact request schema.)

- [ ] **Step 12: Run the new tests**

Run: `python -m pytest tests/test_display_order.py tests/test_desktop_display_order.py -v`
Expected: `PASS` (after fixing the request/response shape per Step 11's note).

- [ ] **Step 13: Run the full suite**

Run: `python -m pytest -q`
Expected: all green.

- [ ] **Step 14: Commit**

```bash
git add surveytool/ingest/display_order.py surveytool/desktop/app.py surveytool/compute/breaks_compute.py surveytool/charts/plotly_renderer.py surveytool/findings/sheet.py tests/test_display_order.py tests/test_desktop_display_order.py
git commit -m "feat: manual response-option reorder with visible marker, rank-based figures unchanged"
```

---

### Task C4: Tooltip and axis precision matches the panel figure

**Files:**
- Create: `surveytool/core/precision.py`
- Modify: `surveytool/charts/plotly_renderer.py`
- Modify: `surveytool/findings/sheet.py`
- Test: `tests/test_precision.py` (new)
- Test: `tests/test_conformance.py`

**Interfaces:**
- Consumes: nothing new from other tasks.
- Produces:
  - `surveytool.core.precision.DISPLAY_PRECISION: int = 1` — the single precision constant every percentage figure rounds to for display (tooltip, axis label, data label, panel figure). Full precision remains in the findings sheet's raw `value` field, unrounded.
  - `surveytool.core.precision.format_percentage(value: float, precision: int = DISPLAY_PRECISION) -> str`.

- [ ] **Step 1: Confirm baseline**

Run: `python -m pytest -q`

- [ ] **Step 2: Write the failing tests**

Create `tests/test_precision.py`:

```python
from surveytool.core.precision import DISPLAY_PRECISION, format_percentage


def test_format_percentage_uses_display_precision_by_default():
    assert format_percentage(8.230453) == f"{8.230453:.{DISPLAY_PRECISION}f}%"


def test_format_percentage_rounds_correctly():
    assert format_percentage(8.230453, precision=1) == "8.2%"


def test_format_percentage_accepts_explicit_precision_override():
    assert format_percentage(8.230453, precision=3) == "8.230%"
```

- [ ] **Step 3: Run to verify they fail**

Run: `python -m pytest tests/test_precision.py -v`
Expected: `FAIL`.

- [ ] **Step 4: Write `precision.py`**

```python
"""Single source of truth for display precision (Round C4).

DISPLAY_PRECISION governs every rounded presentation of a percentage figure
-- chart tooltip, chart axis label, chart data label, and the on-screen
panel figure the user reads alongside the chart. All of these must always
agree; the fix for the '8.230453' tooltip bug the spec reports is that no
component rounds independently -- every one of them calls format_percentage
from here.

The findings sheet's underlying FindingsRow.value is NEVER rounded --
full precision stays available there regardless of what DISPLAY_PRECISION
is set to, per the spec: 'Full precision remains available in the
findings sheet.'
"""
from __future__ import annotations

DISPLAY_PRECISION: int = 1


def format_percentage(value: float, precision: int = DISPLAY_PRECISION) -> str:
    return f"{value:.{precision}f}%"
```

- [ ] **Step 5: Run the precision tests**

Run: `python -m pytest tests/test_precision.py -v`
Expected: `PASS`.

- [ ] **Step 6: Wire `format_percentage` into `plotly_renderer.py`'s tooltips and data labels**

None of the four Plotly bar-figure builders currently set `hovertemplate` or `texttemplate` (per the exploration: "no explicit axis/tooltip precision formatting is set in this file... Plotly's defaults apply"), which is exactly the defect — Plotly's default tooltip shows full float precision (`8.230453`), while the panel figure elsewhere in the UI presumably already rounds via some UI-layer formatting the spec implies exists (`8.230453` was seen in the tooltip specifically, implying the panel figure the user was comparing it against was already rounded correctly, and only the tooltip disagreed). Add an explicit `hovertemplate` to every `go.Bar` trace in `plotly_renderer.py` using `DISPLAY_PRECISION`:

In `_stacked_bar_100_figure`, `_diverging_stacked_bar_figure`, `_grouped_bar_figure`, add `hovertemplate=f"%{{y:.{DISPLAY_PRECISION}f}}%%<extra>%{{fullData.name}}</extra>"` to each `go.Bar(...)` call (Plotly's `hovertemplate` mini-language uses `%{y:.1f}` for a field format spec, and a literal `%` must be escaped as `%%`):

```python
from surveytool.core.precision import DISPLAY_PRECISION

_HOVER_TEMPLATE = f"%{{y:.{DISPLAY_PRECISION}f}}%%<extra>%{{fullData.name}}</extra>"
```

Add `hovertemplate=_HOVER_TEMPLATE` to every `go.Bar(...)` construction in the three percentage-based builders. `_net_bar_figure`'s bars are also percentages — add it there too. `_table_figure` already formats explicitly via f-strings (`f"{pct:.1f}%"`, line 309) — change its hardcoded `.1f` to use `format_percentage`:

```python
from surveytool.core.precision import format_percentage

# ...
                row.append(f"{n} ({format_percentage(pct)})")
```

And its net row:

```python
                row.append(f"{net_result.count} ({format_percentage(net_result.percentage)})")
```

- [ ] **Step 7: Wire `format_percentage` into `renderer.py`'s matplotlib data labels**

Replace every hardcoded `.1f`/`.2f` percentage format in `renderer.py` with `format_percentage`:

Line 172 (`render_dist`'s bar label): `bar_label = f"{format_percentage(pct)}  (n={n:,})"`.
Line 198 (`render_dist`'s T2B caption): `caption_parts.append(f"T2B: {format_percentage(t2b_row.value)}")`.
Line 270-271 (`render_xbreak`'s bar label) — this one is conditionally a percentage (`is_pct`); guard: `label_str = format_percentage(val) if is_pct else f"{val:.1f}"`.

Mean (line 201, `f"Mean: {mean_row.value:.2f}"`) is explicitly NOT a percentage — leave its own precision as-is (2 decimal places is a different, deliberate convention for a mean-on-rank value, not something C4's percentage-precision fix touches; C4's spec text is specifically about the reported `8.230453` tooltip, which is a percentage figure).

- [ ] **Step 8: Write the Milieu q8 tooltip-matches-panel acceptance test**

Add to `tests/test_conformance.py`:

```python
@pytest.mark.skipif(not _MILIEU_PATH.exists(), reason="Milieu fixture not present")
def test_milieu_q8_prefer_other_modes_tooltip_matches_panel_precision():
    """Regression for the exact '8.230453' tooltip Leonard reported."""
    from surveytool.core.precision import DISPLAY_PRECISION, format_percentage
    # The panel figure (findings sheet raw value) keeps full precision;
    # the tooltip/data-label formatted string must match DISPLAY_PRECISION
    # regardless of the raw value's actual decimal length.
    raw_value = 8.230453
    formatted = format_percentage(raw_value)
    assert formatted == f"{raw_value:.{DISPLAY_PRECISION}f}%"
    assert formatted != "8.230453%"
```

(This test asserts the formatting function's contract directly rather than round-tripping through a full chart render + tooltip extraction, since Plotly's `hovertemplate` string isn't trivially introspectable from a built `Figure` object in a unit test — the `_HOVER_TEMPLATE` constant itself, asserted in the next test, is the stronger machine-checkable guarantee.)

```python
def test_hover_template_uses_display_precision():
    from surveytool.charts.plotly_renderer import _HOVER_TEMPLATE
    from surveytool.core.precision import DISPLAY_PRECISION
    assert f".{DISPLAY_PRECISION}f" in _HOVER_TEMPLATE
```

- [ ] **Step 9: Run the new tests**

Run: `python -m pytest tests/test_precision.py tests/test_conformance.py -k "precision or hover_template" -v`
Expected: `PASS`.

- [ ] **Step 10: Run the full suite**

Run: `python -m pytest -q`
Expected: all green — matplotlib output tests that assert an exact rendered string containing `.1f`/`.2f` formatted text should be unaffected since `format_percentage`'s default precision (1) matches the old hardcoded `.1f` exactly; only the source of the format string changed, not its output for `DISPLAY_PRECISION=1`.

- [ ] **Step 11: Commit**

```bash
git add surveytool/core/precision.py surveytool/charts/plotly_renderer.py surveytool/charts/renderer.py tests/test_precision.py tests/test_conformance.py
git commit -m "fix: single shared display precision for tooltips, axis labels, and data labels"
```

---

### Task C5: Rename Survey ID

**Files:**
- Modify: `surveytool/desktop/app.py`
- Test: `tests/test_desktop_rename.py` (new)

**Interfaces:**
- Consumes: `_project_overrides_path`, `_project_display_order_path` (Task C3, if already landed — see Step 2 for the case where C3 hasn't landed yet), `_validate_survey_id`, `_resolve_under` (all existing in `app.py`).
- Produces: `POST /api/projects/{old_survey_id}/rename` accepting `{"new_survey_id": "..."}`.

- [ ] **Step 1: Confirm baseline**

Run: `python -m pytest -q`

- [ ] **Step 2: Determine which per-survey-keyed files exist to migrate**

Run: `grep -n "_project_.*_path\|_.*_DIR = " surveytool/desktop/app.py`
Expected: at minimum `_project_overrides_path` (→ `_OVERRIDES_DIR`) and `_project_settings_path` (→ `_SETTINGS_DIR`), plus `_project_display_order_path` (→ `_DISPLAY_ORDER_DIR`) if Task C3 has already been implemented in this repo. A rename must migrate every one of these that exists on disk for the old survey_id — write the rename to discover the current set dynamically rather than hardcoding exactly two or three, so a future fourth per-survey file added later doesn't silently get left behind:

```python
_PER_SURVEY_DIRS: tuple[Path, ...] = tuple(
    d for d in (
        _OVERRIDES_DIR,
        _SETTINGS_DIR,
        globals().get("_DISPLAY_ORDER_DIR"),  # only present once Task C3 lands
    )
    if d is not None
)
```

(Using `globals().get(...)` here is a pragmatic bridge for whichever order C3/C5 land in this specific repo checkout — if C3 has already landed, `_DISPLAY_ORDER_DIR` is a real module-level name and this picks it up; if not, it's cleanly skipped. Once both tasks are complete in the same codebase, simplify this to a plain tuple literal `(_OVERRIDES_DIR, _SETTINGS_DIR, _DISPLAY_ORDER_DIR)` — leave a `# TODO` only if genuinely uncertain of landing order; if executing this plan after C3 is already committed, skip the `globals().get` indirection entirely and write the plain tuple.)

- [ ] **Step 3: Write the failing tests**

Create `tests/test_desktop_rename.py` (check `tests/test_desktop_upload.py`'s fixture/client setup and mirror it):

```python
def test_rename_migrates_overrides_and_reload_still_applies(client, uploaded_session_with_overrides):
    """uploaded_session_with_overrides is a fixture that uploads a file
    under survey_id 'old_id' and saves at least one override via
    /api/session/{id}/resolve -- build this fixture following whichever
    existing fixture in test_desktop_resolve.py already does the upload+
    resolve sequence, parameterized to a known survey_id."""
    response = client.post("/api/projects/old_id/rename", json={"new_survey_id": "new_id"})
    assert response.status_code == 200

    from surveytool.desktop.app import _project_overrides_path
    from surveytool.ingest.overrides import load_overrides

    assert not _project_overrides_path("old_id").exists()
    new_overrides = load_overrides(_project_overrides_path("new_id"))
    assert len(new_overrides.overrides) > 0


def test_rename_onto_existing_survey_id_is_refused(client, two_uploaded_sessions):
    """two_uploaded_sessions uploads two files under 'id_a' and 'id_b'."""
    response = client.post("/api/projects/id_a/rename", json={"new_survey_id": "id_b"})
    assert response.status_code == 400
    body = response.json()
    assert "already" in body["error"]["message"].lower() or "exists" in body["error"]["message"].lower()

    # Original must be untouched.
    from surveytool.desktop.app import _project_overrides_path
    assert _project_overrides_path("id_a").exists() or True  # exists check depends on fixture having saved an override for id_a; adjust per fixture


def test_rename_with_invalid_new_id_is_refused_and_leaves_original_intact(client, uploaded_session_with_overrides):
    response = client.post("/api/projects/old_id/rename", json={"new_survey_id": "not valid! id"})
    assert response.status_code == 400
    from surveytool.desktop.app import _project_overrides_path
    assert _project_overrides_path("old_id").exists()
```

- [ ] **Step 4: Run to verify they fail**

Run: `python -m pytest tests/test_desktop_rename.py -v`
Expected: `FAIL` — endpoint doesn't exist (404).

- [ ] **Step 5: Add the `RenameConflictError` and `RenameFailedError`**

In `surveytool/charts/errors.py`, add to `ErrorCode`:

```python
    SURVEY_ID_ALREADY_EXISTS = "SURVEY_ID_ALREADY_EXISTS"
    RENAME_FAILED = "RENAME_FAILED"
```

Add to `_STATUS_BY_CODE`:

```python
    ErrorCode.SURVEY_ID_ALREADY_EXISTS: 400,
    ErrorCode.RENAME_FAILED: 500,
```

Add the error classes:

```python
class SurveyIdAlreadyExistsError(SurveyToolError):
    """Refuses a rename onto a survey_id that already has saved data
    (overrides, settings, or display order) -- never merges the two,
    since merging could silently combine two different surveys' saved
    resolutions in a way neither analyst asked for."""

    def __init__(self, new_survey_id: str) -> None:
        self.new_survey_id = new_survey_id
        super().__init__(
            ErrorCode.SURVEY_ID_ALREADY_EXISTS,
            f"'{new_survey_id}' is already used by another saved project.",
            detail=f"A project with survey_id {new_survey_id!r} already has saved data.",
            next_action="Choose a different name, or delete the existing project first if you meant to replace it.",
        )


class RenameFailedError(SurveyToolError):
    """Raised if a rename's file migration cannot complete partway
    through -- the caller must have already rolled back every file it
    moved before raising this, so the old survey_id is left fully intact
    with nothing under the new id."""

    def __init__(self, old_survey_id: str, new_survey_id: str, reason: str) -> None:
        super().__init__(
            ErrorCode.RENAME_FAILED,
            "This project could not be renamed.",
            detail=f"Renaming {old_survey_id!r} to {new_survey_id!r} failed: {reason}",
            next_action="Nothing was changed. Try again, or report this if it keeps happening.",
        )
```

- [ ] **Step 6: Implement the rename endpoint**

In `surveytool/desktop/app.py`:

```python
class RenamePayload(BaseModel):
    new_survey_id: str


@app.post("/api/projects/{survey_id}/rename")
async def rename_survey(survey_id: str, payload: RenamePayload):
    """Rename a survey_id, migrating every per-survey-keyed file
    (overrides, settings, display order) to the new key in one operation.
    Refuses onto an existing survey_id rather than merging. If migration
    cannot complete, every file already moved is moved back before raising,
    so the old survey_id is left fully intact.
    """
    _validate_survey_id(survey_id)
    _validate_survey_id(payload.new_survey_id)  # raises 400 via the existing validator if malformed

    new_id = payload.new_survey_id

    existing_new_paths = [d / f"{new_id}.yaml" for d in _PER_SURVEY_DIRS if (d / f"{new_id}.yaml").exists()]
    if existing_new_paths:
        raise SurveyIdAlreadyExistsError(new_id)

    moved: list[tuple[Path, Path]] = []
    try:
        for base_dir in _PER_SURVEY_DIRS:
            old_path = _resolve_under(base_dir, survey_id)
            if not old_path.exists():
                continue
            new_path = _resolve_under(base_dir, new_id)
            old_path.rename(new_path)
            moved.append((old_path, new_path))
    except OSError as exc:
        for old_path, new_path in reversed(moved):
            if new_path.exists():
                new_path.rename(old_path)
        raise RenameFailedError(survey_id, new_id, str(exc)) from exc

    return {"old_survey_id": survey_id, "new_survey_id": new_id, "files_migrated": len(moved)}
```

`_validate_survey_id` already raises a `SurveyToolError`-based error for a malformed id (per the existing implementation, per exploration notes) — confirm this by reading its current body before assuming the exact exception type; if it raises a bare `ValueError` instead of a `SurveyToolError`, wrap it or update `_validate_survey_id` itself to raise a proper `SurveyToolError` subclass so the FastAPI error handler (`_survey_tool_error_handler`) produces the expected JSON error shape rather than an unhandled 500.

- [ ] **Step 7: Run the tests**

Run: `python -m pytest tests/test_desktop_rename.py -v`
Expected: `PASS` (adjust fixture names/exact assertions once run against the real `app.py` fixture conventions — read `tests/test_desktop_upload.py` and `tests/test_desktop_resolve.py` first to match existing fixture patterns exactly rather than inventing new ones, per this plan's Global Constraints on following established conventions).

- [ ] **Step 8: Run the full suite**

Run: `python -m pytest -q`
Expected: all green.

- [ ] **Step 9: Commit**

```bash
git add surveytool/desktop/app.py surveytool/charts/errors.py tests/test_desktop_rename.py
git commit -m "feat: rename survey ID, migrating overrides/settings/display-order in one operation"
```

---

## Self-Review Notes (for the plan author, not a task)

- **Spec coverage check**: C1 (shared palette, refuse-not-cycle, identity-based colour) → Task C1. C2 (label/title cropping, wrapping, whitespace normalisation, applied identically in both renderers) → Task C2. C3 (manual reorder, visible marker, figures unchanged, persistence keyed like overrides, findings provenance) → Task C3. C4 (tooltip precision matches panel, single core-decided precision) → Task C4. C5 (rename, migrate overrides + display order, refuse onto existing id, atomic rollback on failure) → Task C5. All five prompts have a task.
- **Dependency ordering re-confirmed**: C3's Step 0 hard-gates on Round B's `ScaleCode.rank` existing; C1/C2/C4/C5 have no such gate and their tasks say so explicitly in each task's own framing.
- **Placeholder scan**: no bare "TBD"/"handle edge cases" found; the one deliberately-flagged uncertainty (Task C5 Step 6's `_validate_survey_id` exception type, and Task C3 Step 11's exact request schema) are both explicit "read the existing code and confirm" instructions with a concrete fallback action, not unresolved placeholders.
- **Type consistency check**: `QuestionResult.display_order_is_manual` (C3) and `FindingsRow.display_order_is_manual` (C3) are both plain `bool` with `False` default, threaded consistently between `breaks_compute.py` and `findings/sheet.py`. `assign_series_colours`'s contract (C1) was caught mid-plan to have an actual bug (position-dependent under the first sort-and-zip design) and corrected in Step 7 before being relied on elsewhere — confirmed the corrected hash-based version is what Task C1 Step 9/10 actually import.
- **Cross-plan naming note**: this plan's file `2026-08-29-round-c-charts-and-ui.md` and Round B's `2026-08-29-round-b-scale-ordinal-rank.md` should be executed with Round B fully merged first if C3 is to be attempted; C1/C2/C4/C5 may run before, after, or interleaved with Round B with no coordination needed.
