# Chart Parity, Manual Response Styling & Cross-tab Export — Design

**Date:** 2026-09-16
**Status:** Draft — pending user review
**Prerequisite:** `2026-08-31-chart-style-selector-design.md` (Chart Style Selector) — this design builds directly on its `ChartStyle`/`STYLE_REGISTRY` (`surveytool/charts/styles.py`), its per-question persistence pattern (`surveytool/ingest/chart_style.py`, `display_order.py`), and its finding that the breaks/crosstab pipeline already renders on-screen and export from one shared `plotly_renderer.py` figure.

## Problem

Client feedback on the current build raised five points. Investigation found they resolve to four build items plus one QA gate, because two of the "five" items turn out to be the same underlying fix and one export request is already mostly implemented:

1. The on-screen Charts tab chart doesn't visually match its own exported PNG (different renderer, different palette, different orientation).
2. No way to manually reorder response options or assign a specific colour to each one — the request also asked for a colour-editable legend, which is the same feature.
3. Long axis labels get truncated/overlap on-screen instead of wrapping.
4. Cross-tab charts need a PNG export button.
5. Need more testing across vendor datasets before shipping any of the above.

### Root cause: two disconnected chart pipelines

The app has **two independent charting subsystems** that were never made consistent with each other:

| | On-screen | Export |
|---|---|---|
| **Legacy Charts tab** | `surveytool/desktop/static/charts.js` — Plotly.js, hardcoded `CHART_COLORS` (always blue), no style presets, no label wrapping | `surveytool/charts/renderer.py` — **matplotlib**, hardcoded "Beta Insight" branding, has its own wrap/truncate logic (`core/text_hygiene.py`) |
| **Cross-tab** | `surveytool/desktop/static/breaks.js` — Plotly.js, already supports the 4 style presets (`CLIENT_CHART_STYLES`) | `surveytool/charts/plotly_renderer.py` — Plotly + kaleido, renders the *same* figure object shown on-screen, already style-aware |

The Cross-tab column is already internally consistent (this is what the 2026-08-31 spec built). The Legacy Charts tab column is not: matplotlib and Plotly.js are different rendering engines with different default typography, margins, and layout math, so they can never be made to pixel-match by tweaking colours alone. This is why the two screenshots in the client's feedback look like different products.

Two more scope boundaries carry over from the prior spec: `display_order.py` (manual response order) and `chart_style.py` (style-preset choice) are explicitly documented as **cross-tab-only** today — the legacy Charts tab reads neither.

## Scope

**In scope:**

- **Item A — Render parity.** Retire `renderer.py` (matplotlib) as the Charts-tab export engine. Route legacy Charts-tab exports through `plotly_renderer.py` instead, so the on-screen chart and its PNG export are the same Plotly figure, rasterized via kaleido — exactly the "on-screen and export can't drift, they're one object" guarantee the Cross-tab pipeline already has. As part of this, the Charts tab gains the Brand/High Contrast/Cool/Warm style-preset picker it currently lacks entirely.
- **Item B — Manual response order + colour, persisted per question.** Extend the existing per-question persistence (`display_order.py` for order, `chart_style.py` for style-preset choice) with a new persisted colour-override map keyed by response label. Surface this as a single legend panel — replacing Plotly's default legend — where each row shows the response label, a drag handle to reorder, and a colour swatch that opens a picker on click. Wire `display_order.py`/`chart_style.py` (and the new colour map) into the legacy Charts tab as well, which Item A's consolidation makes possible. Overrides apply everywhere that question is charted: Charts tab, Cross-tab, and both PNG export paths.
- **Item C — Label wrapping on-screen.** Port the existing wrap logic (`core/text_hygiene.py`, today only wired into the matplotlib path) to the shared Plotly on-screen/export layer: wrap long axis category labels with `<br>` breaks and size margins dynamically so wrapped text isn't clipped. Applies to both charts.js and breaks.js, since both currently show the same truncation/overlap symptom in rotated long labels.
- **Item D — Cross-tab bulk PNG export.** Cross-tab already has single-chart export (`breaks-export-btn` → `/breaks-export`). Add an "Export all as PNGs" bulk action matching the Charts tab's existing bulk export, looping the current question/break-by combinations in view through the existing `plotly_renderer.py` figure-building logic.
- **Item F — QA gate.** Before release, verify Items A–D against real datasets from every currently-onboarded vendor (not synthetic/sample data): render parity, order/colour persistence, label wrapping, and both single and bulk export, on each vendor's data. Treated as an acceptance gate, not a build task.

**Out of scope (explicitly):**

- Any new chart types, layout options, or typography changes beyond what's needed for parity and wrapping.
- A global/default colour or order setting — colour and order overrides remain per-question, matching the existing style-preset persistence model.
- Undo/history for manual reorder or recolour — last-saved-wins, same as the existing style-preset and display-order persistence.
- Automated cross-vendor test fixtures as a permanent CI suite (Item F is a pre-release manual/scripted verification pass for this feature set, not a new ongoing test infrastructure commitment — that would be a separate decision).

## Architecture

### Item A — Consolidating export onto `plotly_renderer.py`

The legacy Charts tab's data flow today: `chart_data.py` builds a `ChartSpec` → `renderer.py` (matplotlib) draws it for export, while `charts.js` independently re-derives a Plotly trace from `/api/session/{id}/charts` JSON for on-screen display. These two representations are built from the same underlying data but by two different code paths with no shared layout/colour logic — the actual defect.

The fix: give the legacy Charts tab the same shape the Cross-tab pipeline already has — one Plotly figure, shown on-screen and rasterized for export.

- `chart_data.py`'s `ChartSpec` output feeds a new (or extended) figure-builder in `plotly_renderer.py`, alongside its existing breaks/crosstab figure builders, producing a Plotly `Figure` for `dist`/`xbreak`/`means` chart types.
- `charts.js` renders that figure client-side (already using Plotly.js — this is a data-source change, not a new library).
- The `/api/session/{id}/export` route (app.py:1057) is repointed from `renderer.py` to `plotly_renderer.py`'s rasterize path.
- `renderer.py` and its matplotlib dependency are removed once nothing references them — confirm via `tests/test_charts.py`/`test_chart_data.py` which tests are renderer-specific vs. data-shape tests that should migrate rather than delete.
- Style-preset selection (`ChartStyle`/`STYLE_REGISTRY`) is wired into this new figure builder the same way it already is for breaks charts, and the Charts tab UI gains the same preset button row breaks.js already has.

This is the largest item; it touches the full path from `chart_data.py` through both render targets and removes a whole rendering engine. It should land before Items B and C, since both of those are scoped against the *shared* Plotly layer this item creates — building B/C against `charts.js`'s current bespoke path first would mean redoing them.

### Item B — Manual order + colour

Builds directly on the 2026-08-31 spec's storage pattern.

- **Persistence:** extend `surveytool/ingest/chart_style.py`'s per-question record with a new field, e.g. `response_colours: dict[str, str]` (response label → hex), alongside the existing `style_name`. Reuses the same YAML-per-survey file, same `GET`/`PUT`/`DELETE` endpoint shape, same `SurveyToolError`-based validation (reject malformed hex, same convention as the existing `style_name` validation). A manual colour override for a response, where set, takes precedence over `assign_series_colours`' hash-derived colour for that label; unset labels keep falling back to the hash-derived assignment so partial overrides don't break the rest of the palette.
- **Order:** no schema change needed — `display_order.py` already stores manual per-question label order; it just needs to be read by the new Charts-tab figure builder from Item A, same as it's already read by `breaks_compute.py`.
- **UI:** one legend panel component, shared by charts.js and breaks.js (replacing Plotly's default built-in legend for questions that have manual overrides). Each row: response label, drag handle (reorder → writes to `display_order.py`), colour swatch (click → colour picker → writes to the new `response_colours` field). Changes save immediately per-row, consistent with the existing style-preset picker's immediate-save behaviour — no separate "save" step.
- Because Item A unifies the Charts tab onto the shared figure-building layer, this legend component and its persistence reads/writes are the same code for both tabs — no duplicate implementation.

### Item C — Label wrapping

`core/text_hygiene.py` already has `wrap_text`/`truncate_with_ellipsis`, used today only by `renderer.py`'s `_wrap_title`/`_compute_left_margin` (matplotlib). Port an equivalent to the Plotly layer:

- Apply `wrap_text` to axis category labels before they're set as Plotly tick text, inserting `<br>` at wrap points (Plotly's native line-break syntax in tick labels).
- Compute margin size dynamically from the wrapped label's line count/longest line, mirroring what `_compute_left_margin` already does for matplotlib, so wrapped multi-line labels aren't clipped by a fixed margin.
- Since Item A moves the Charts tab onto the same Plotly figure-building code Cross-tab already uses, this is one implementation in `plotly_renderer.py`, consumed by both `charts.js` and `breaks.js` — not two separate patches.

### Item D — Cross-tab bulk export

- New endpoint or extended `/breaks-export` (app.py:1289) accepting a batch of question/break-by combinations (or "export all currently computed combinations for this survey"), looping the existing `build_figure`/`rasterize` calls per combination — no new rendering logic, just a batch wrapper around what `/breaks-export` already does per-call.
- New "Export all as PNGs" button in breaks.js's UI, next to the existing single "Export current chart" button, following the same folder-picker pattern the Charts tab's bulk export already uses.

### Item F — QA gate

Not a code change. A checklist run after Items A–D are implemented and before release:

- [ ] For each onboarded vendor's sample dataset: Charts tab on-screen chart visually matches its exported PNG (same colours, same orientation, same labels).
- [ ] Manual response reorder persists and is reflected in Charts tab, Cross-tab, and both exports for the same question.
- [ ] Manual response colour override persists and is reflected in all four surfaces; unset responses still get a sensible hash-derived colour alongside manually-coloured ones.
- [ ] Long response labels wrap (not truncate/overlap) on-screen in both tabs, and in both export paths.
- [ ] Cross-tab single-chart export and new bulk export both produce correct, complete PNGs for a multi-question, multi-break-by survey.
- [ ] No regression in existing style-preset behaviour (2026-08-31 spec) or existing unstyled-question defaults, per the invariant tests already in `tests/test_breaks_conformance.py`/`test_breaks_invariants.py`.

## Sequencing

Item A must land first (it creates the shared rendering layer). Items B and C depend on A and can proceed in parallel with each other once A is merged. Item D is independent of A/B/C and can be built any time. Item F runs last, after A–D are all merged, as the release gate.

## Testing

Following existing repo convention (one test file per module):

- Item A: migrate/extend `tests/test_charts.py`, `tests/test_chart_data.py` for the new Plotly-based figure builder; remove matplotlib-specific assertions once `renderer.py` is retired.
- Item B: extend `tests/test_chart_style.py` (persistence), `tests/test_desktop_chart_style.py` (API) for the new colour field; extend `tests/test_desktop_charts.py` for legend/order/colour reaching the Charts tab.
- Item C: new or extended tests asserting wrapped tick text and computed margins in the Plotly figure builder, mirroring `test_charts.py`'s existing matplotlib wrap-margin assertions.
- Item D: extend `tests/test_breaks_export.py` for the new bulk-export endpoint/loop.
- Item F: manual/scripted verification, not a new automated suite (see Out of scope).
