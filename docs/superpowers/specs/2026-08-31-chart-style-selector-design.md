# Chart Style Selector — Design

**Date:** 2026-08-31
**Status:** Approved for planning
**Prerequisite:** Round C (merged to `main`) — this design builds directly on Task C1 (shared palette, `assign_series_colours`) and Task C3 (manual display order, `display_order.py` storage pattern).

## Problem

Round C's shared categorical palette (C1) fixed under-differentiated colours but gave analysts no way to change the look of a chart. The request: let an analyst pick from a small set of preset visual styles, per question, with the choice reaching both the on-screen chart and its branded PNG export.

## Scope

**In scope:**
- 3–4 curated style presets. Each preset varies: the categorical palette, the chart background colour, and the font/text colour. Nothing else — chart type, layout, spacing, and typography (font family/weight) are unaffected by style.
- `brand` (the current cream/teal look) is the default preset; choosing no style is identical to today's behaviour.
- Selectable per question, in the breaks-view chart panel, via a new button row next to the existing chart-type row.
- Persisted per survey per question, following Task C3's `display_order.py` storage pattern exactly (same `_APP_DATA_DIR`-keyed YAML-per-survey convention, same `GET`/`PUT`/`DELETE` endpoint shape).
- Reaches both the on-screen Plotly chart and the branded PNG export.

**Out of scope (explicitly):**
- Individual colour customization (picking an exact hex per response option). A future request, not this one.
- Typography, borders, gridlines, or any other visual dimension beyond palette/background/font colour.
- A global or resolver-level default style setting. Per-question only, for this iteration.
- The legacy `dist`/`xbreak`/`means` chart system (`surveytool/charts/renderer.py`, `surveytool/charts/chart_data.py`). This is the same scope boundary Task C3 already drew for manual display order (documented in `display_order.py`'s module docstring) — this design extends that same note to also cover style, rather than opening a second parallel gap.

## Architecture

### Why `renderer.py` is untouched

Investigation during design found that the "branded PNG export" for the breaks/crosstab pipeline (the one this feature targets, and the same one C3's manual reorder already reaches) is `surveytool/charts/plotly_renderer.py`'s `build_figure` + `rasterize` — the on-screen figure and the exported PNG are the *same* Plotly `Figure` object, rasterized via kaleido. There is no separate matplotlib code path in this pipeline. `surveytool/charts/renderer.py` (matplotlib) serves a different, older chart system (`ChartSpec`/`chart_type: Literal["dist","xbreak","means"]`) that neither C3's display order nor `post_crosstab`/`post_breaks_export` ever touch.

This means style only needs to be wired into `plotly_renderer.py`. One renderer, one code path, on-screen and export automatically consistent by construction — no risk of the two drifting apart the way two independent renderers could.

### Components

**1. `surveytool/charts/styles.py` (new)**

```python
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class ChartStyle:
    name: str
    palette: tuple[str, ...]  # same shape as palette.CATEGORICAL_PALETTE
    background: str           # hex, used for both paper_bgcolor and plot_bgcolor
    font_color: str           # hex

_BRAND = ChartStyle(
    name="brand",
    palette=CATEGORICAL_PALETTE,  # re-export Task C1's existing 12-entry palette verbatim
    background="#F4F1EA",
    font_color="#222222",
)
_HIGH_CONTRAST = ChartStyle(
    name="high_contrast",
    palette=(...),  # a separate, distinct 12-entry colourblind-safe/greyscale-distinguishable set
    background="#FFFFFF",
    font_color="#000000",
)
_COOL = ChartStyle(name="cool", palette=(...), background="#F0F4F7", font_color="#1A2733")
_WARM = ChartStyle(name="warm", palette=(...), background="#FBF3EC", font_color="#332118")

STYLE_REGISTRY: dict[str, ChartStyle] = {s.name: s for s in (_BRAND, _HIGH_CONTRAST, _COOL, _WARM)}
DEFAULT_STYLE = _BRAND

def get_style(name: str | None) -> ChartStyle:
    if name is None:
        return DEFAULT_STYLE
    return STYLE_REGISTRY.get(name, DEFAULT_STYLE)  # unknown name falls back silently to brand
```

Every non-brand preset gets its own distinct 12-entry palette (not just a recolouring of the brand palette), independently checked for colourblind-safety and greyscale distinguishability the same way Task C1's original palette was validated — this is real design work at implementation time, not a placeholder.

`assign_series_colours` (Task C1, `surveytool/charts/palette.py`) already takes a palette as an implicit global; it needs a small signature change to accept an explicit palette parameter (defaulting to `CATEGORICAL_PALETTE` for backward compatibility with every existing call site), so a style's palette can flow through the same hash-based, identity-stable assignment logic C1 built — no new colour-assignment algorithm, just a parameterized palette source.

**2. `surveytool/ingest/chart_style.py` (new)**

Structurally identical to `display_order.py`: `ChartStyleChoice(variable, style_name, saved_at)`, `ProjectChartStyles(styles: dict[str, ChartStyleChoice])`, `load_chart_styles`/`write_chart_style`/`delete_chart_style`, `CorruptedChartStyleFileError` mirroring `CorruptedDisplayOrderFileError`. `style_name` is validated against `STYLE_REGISTRY` at write time (reject an unknown name with a plain-English error, same `SurveyToolError` convention as everywhere else) — never persisted unvalidated.

**3. Desktop endpoints** (`surveytool/desktop/app.py`)

`GET`/`PUT`/`DELETE /api/projects/{survey_id}/chart-style/{qid}`, following C3's `_project_display_order_path`/`get_display_order`/`put_display_order`/`reset_display_order` pattern exactly, including a new `_project_chart_style_path` helper reusing the existing `_validate_survey_id`/`_resolve_under`.

`compute_breaks_crosstab` (`surveytool/compute/breaks_compute.py`) gains a `chart_styles: dict[str, str] | None = None` parameter (qid → style name), threaded the same two call sites C3 already wired for `display_orders`: `post_crosstab` and `post_breaks_export`. `QuestionResult` gains a `chart_style: str | None` field so the resolved style name travels with the computed result into `plotly_renderer.py`.

**4. Renderer wiring** (`surveytool/charts/plotly_renderer.py`)

- `build_figure` resolves `get_style(question_result.chart_style)` once and threads the resulting `ChartStyle` into `_apply_header` (background/font) and into each bar-figure builder's `assign_series_colours(labels, palette=style.palette)` call.
- `_apply_header`: `paper_bgcolor`/`plot_bgcolor` become `style.background`, `font.color` becomes `style.font_color`, replacing the current hardcoded `"#F4F1EA"`/`"#222222"`.
- Every existing caller of `build_figure` that doesn't know about style (none currently pass one) gets `chart_style=None` → `get_style(None)` → `DEFAULT_STYLE` (brand) → byte-for-byte identical output to today. This is the same "additive, nothing changes unless opted in" guarantee C1/C3 both maintained.

**5. Frontend** (`surveytool/desktop/static/breaks.js`)

A new `buildChartStyleRow(qr)` function, modeled directly on the existing `buildChartTypeRow` (same button-row markup/CSS class conventions), placed in `controlsRow` alongside `chartTypeRow` and the axis-flip button. Unlike chart-type/axis-flip (pure client-side, no network call), clicking a style button:
1. Optimistically re-renders the chart area client-side using data already present (no wait for the round trip, since palette/background are static per style and don't need server computation).
2. Fires a `PUT` to `/api/projects/{survey_id}/chart-style/{qid}` in the background to persist the choice.
3. On the next full `post_crosstab` fetch (e.g. changing break/filter), the persisted choice is naturally picked up from the server via `QuestionResult.chart_style`.

This mirrors the "optimistic local update + background persist" pattern that's the natural extension of the existing button-row convention, while still guaranteeing the export endpoint (which does a fresh server round trip) always reflects the saved choice.

## Data flow summary

```
Analyst clicks a style button
  → breaks.js: re-render chart area locally (palette/background swapped)
  → PUT /api/projects/{survey_id}/chart-style/{qid}  (background, persisted)

Later: post_crosstab / post_breaks_export
  → compute_breaks_crosstab(..., chart_styles=_load_chart_styles_for_survey(survey_id))
  → QuestionResult.chart_style = "high_contrast" (or None → brand)
  → plotly_renderer.build_figure(question_result, ...) resolves style, applies palette+background+font
  → rasterize() writes the SAME figure to PNG — on-screen and export always match
```

## Testing approach

Following the established Round C pattern per component:
- `styles.py`: unit tests — every preset has ≥12 palette entries, all distinct, `get_style(None)`/`get_style("unknown")` both fall back to brand.
- `chart_style.py`: unit tests mirroring `test_display_order.py` exactly (load/write/round-trip, corrupted file, unknown style name rejected).
- Desktop endpoints: mirroring `test_desktop_display_order.py`.
- `plotly_renderer.py`: a test asserting `build_figure` with `chart_style=None` produces byte-identical output to the pre-this-feature baseline (the critical "nothing changes unless opted in" regression guard), plus a test asserting a non-brand style's background/font/palette actually appear in the built figure's `layout`/trace `marker_color`.
- End-to-end: PUT a style, re-fetch via `post_crosstab`, confirm `chart_style` round-trips; export via `post_breaks_export`, confirm the exported PNG's figure was built with the non-default style (inspect the figure object before rasterization, not the PNG bytes).

## Self-review

- **Placeholder scan:** the three non-brand palettes' exact hex values are left as "(...)" in this doc — this is a deliberate implementation-time task (validating colourblind-safety/greyscale-distinguishability per palette is real design work, not a value to guess at spec-writing time), not an unresolved requirement. The implementation plan must include picking and validating these three palettes as an explicit step, not silently invent them inline.
- **Internal consistency:** confirmed `renderer.py` is genuinely untouched by tracing the actual call graph (`app.py` never imports it; the new pipeline's export is `plotly_renderer.rasterize`) rather than assuming from the plan's naming.
- **Scope check:** single cohesive feature, fits one implementation plan.
- **Ambiguity check:** "reset" behavior (DELETE endpoint) returns a question to `DEFAULT_STYLE` (brand), mirroring `delete_display_order`'s "no saved order = default" convention exactly.
