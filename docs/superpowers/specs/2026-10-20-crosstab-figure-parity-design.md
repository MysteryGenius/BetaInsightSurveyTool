# Cross-tab Figure Parity: Colours, Label Wrapping and Export — Design

**Date:** 2026-10-20
**Status:** Draft, pending user review
**Prerequisite:** `2026-09-16-chart-parity-and-manual-styling-design.md`. That design moved the **Charts tab** onto one server-built figure (commit `3ea7ea8`). This design does the same for the **Cross-tab** tab, which still builds its figures in the browser.

## Why

Client feedback (Leonard, beta group, 15 Sep) on Cross-tab, using `milieu_survey_coe_data.csv`, q8 "main reasons for not owning or driving a car", broken by Car ownership with **Swap axes** on:

1. "The colour coding doesn't seem to be working." Every series is the same navy.
2. "The text displayed is cut off along the bottom edge of the chart. Maybe wrap text for long text?"
3. "Can we also incorporate an 'Export to PNG' button for the Cross-tab charts as displayed?"

All three come from one cause. Cross-tab's on-screen chart is built by hand in `static/breaks.js` (`renderBreaksChart`). Its PNG is built separately by `charts/plotly_renderer.build_figure`. The two builders have drifted apart:

| Symptom | On-screen (`breaks.js`) | Export (`plotly_renderer.py`) |
|---|---|---|
| 1. Colours | With axes swapped, each trace is a break column coloured by **band** (`ok`→navy, `low_base`→grey). Every OK column is navy, so the series can't be told apart. | Swap axes isn't supported at all. |
| 2. Labels | No wrapping, fixed `margin.b = 100`. | `wrap_axis_labels` + `compute_axis_margin`, but only for column labels (unswapped). |
| 3. Export | n/a | "Export current chart" (`/breaks-export`) returns the PNG as a response body. `breaks.js` reports "Exported N bytes" and **throws it away**, so nothing is saved. Neither export endpoint knows about Swap axes, so neither can match "as displayed". |

The uncommitted change in `breaks.js` (a hand-copied diverging-bar renderer) is another instance of the same duplication.

## Goal

Cross-tab gets the guarantee the Charts tab already has: **one figure-building path, on the server**. The screen draws the server's figure exactly as served, and the PNG is a raster of that same figure. Once there's one path, the screen and the PNG can't drift apart, so all three feedback points are fixed and can't recur.

Success, checked against Leonard's own case (q8 × Car ownership, swapped):
- each car-ownership group is a visibly different colour, and the legend says which is which;
- long answer labels wrap and nothing is clipped at the bottom edge;
- "Export current chart" writes a PNG into the chosen export folder that looks like what's on screen, with axes swapped if they're swapped on screen.

## Non-goals

- New chart types, or new styling options beyond what's needed for parity.
- Editing colours for break groups. The existing legend edits **answer** colours and stays as it is. *(My call: break groups get distinct automatic colours from the chart's style palette. Making them editable is a possible follow-up.)*
- Changes to the Charts tab, which already has parity.
- Changes to computation, netting, suppression or chart-validity rules (INV-1 and conformance tests must stay green unchanged).

## Anti-goals (would count as failure even if it "works")

- Any chart logic left in `breaks.js` that decides colours, wrapping, margins or bar layout. The browser must draw what the server sends, apart from the legend override noted below.
- An export that differs from the screen, including in swap state, style or colour overrides.
- An export button that reports success without writing a file.
- Pill/break changes getting noticeably slower because every chart type is computed up front.

## Design

### 1. Server: swap axes becomes a figure option

`plotly_renderer.build_figure` gains a keyword `swap_axes: bool = False`. It applies to the chart types that are flippable on screen today (`AXIS_FLIPPABLE_CHART_TYPES` in `breaks.js`; the builder confirms the exact set, which is stacked_bar_100, diverging_stacked_bar and grouped_bar). For any other type it is ignored.

When swapped:
- X axis = answer options (scale-point labels), wrapped with `wrap_axis_labels`. The bottom margin comes from `compute_axis_margin` over **those** labels, not the column labels. (Today `build_figure` always passes column labels to `_apply_header`; that has to follow the swap.)
- One trace per break column, grouped bars, coloured with `assign_series_colours([column display labels], palette=style.palette)`. These are distinct per column and stable for a given label.
- Suppressed columns keep the existing suppressed treatment: grey with the `x` pattern, and "(suppressed, n=…)" in the name. They never get a fabricated value.
- Plotly's own legend is on. This legend is what fixes feedback 1.

*(My call: the swapped view uses grouped bars for every flippable type, as `breaks.js` does today. Stacking answer options of a multi-select question across break groups doesn't make sense.)*

### 2. Server: low-base marking moves into the figure

Today the on-screen chart greys low-base columns by bar colour. The PNG doesn't mark them at all. In the single server figure, a low-base column's axis label (or series name, when swapped) gets "(low base, n=…)", in the same way suppressed columns already get "(suppressed, n=…)". *(My call. It keeps the warning in exported PNGs too, where clients see it.)*

### 3. Server: a figure endpoint for the screen

New `POST /api/session/{id}/breaks-figure`. Its body is the same as `ExportRequest` (break_spec, filter_spec, question_id, chart_type) plus `swap_axes`. It runs the same validate → compute → attach-permissions → `build_figure` path as `/breaks-export` and returns `figure.to_plotly_json()` (the same serialisation `/charts` uses). Refactor the shared steps of the export and figure routes into one helper, so they can't diverge.

The `/crosstab` response stays as it is: cards, counts, permitted charts and the HTML table. The browser fetches one figure when a question renders, and again when the chart type, swap state, style or a colour changes. Only the chart on screen is ever built, so the `projection.py` "cheap on every pill change" rule isn't affected.

*(My call, versus putting all five figures in `/crosstab`: that would build five figures per question on every run.)*

### 4. Browser: `breaks.js` draws the server figure

`renderBreaksChart` drops all trace and layout construction and calls `Plotly.newPlot(chartArea, fig.data, fig.layout, …)`, as `charts.js` already does. Remove whatever becomes dead: `withChartTemplate` and `applyChartStyleToLayout` use in this path, `bandColors`/`patterns`, and the uncommitted diverging block. The uncommitted scroll-position preservation in `runCrosstab` is unrelated and is kept.

The one allowed override follows the Charts tab's precedent. When the traces are answer options (not swapped, not net_bar), the shared colour/drag legend (`chart_legend.js`) stands in for Plotly's legend, so the browser sets `showlegend: false`. Otherwise Plotly's legend stays.

The **Table** chart type keeps its HTML table on screen (it's more usable than a Plotly table) and exports via the server's `_table_figure` as it does now. That's an accepted difference.

*(My call: the server figure includes its header block — question, break/filter, bases — on screen too, so the screen shows exactly what will be exported. The builder may hide the in-page question heading above the chart if it then duplicates, but must not alter the figure.)*

Style and visual defaults: as with the Charts tab in `3ea7ea8`, an unstyled Cross-tab chart will now look like its export (brand palette on `#F4F1EA`) instead of the old white on-screen default. This is deliberate. The PNG is what clients receive.

### 5. Export that saves, as displayed

- Both `/breaks-export` and `/breaks-export-bulk` accept `swap_axes` and pass it through.
- "Export current chart" writes the file into the chosen export folder, like the bulk export (`out_dir` in the request). It returns `{filename, out_dir}`, and the status line names the saved file and folder. *(My call: single export becomes "save to folder", matching bulk, rather than a browser download. In pywebview a download is unreliable, and analysts already choose an export folder.)*
- Export uses the chart type **and swap state currently on screen**. The button exports the question shown (fixes the `breaksLatestResults[0]` assumption if more than one result can be on screen).
- Errors follow the `SurveyToolError` convention: plain English with a next step. A save that fails because of the folder reuses the bulk route's existing "could not be saved to the chosen location" error.

## Testing

Following the existing per-module convention:

- `tests/test_plotly_renderer*` / `tests/test_breaks_export.py`:
  - swapped figure has one trace per column with **pairwise distinct** colours;
  - x tick text is wrapped answer labels;
  - bottom margin is computed from answer labels;
  - suppressed and low-base columns are marked;
  - `swap_axes` is ignored for non-flippable types.
- New tests for `/breaks-figure`: it returns exactly `build_figure(...).to_plotly_json()` for the same inputs, including a styled + colour-overridden question and a swapped one. This mirrors the Charts-tab equality test in `test_desktop_charts.py`.
- `/breaks-export`: the file is written into `out_dir`, and the swapped export equals the swapped figure.
- Regression with long labels: Leonard's q8 labels, or a synthetic equivalent, produce wrapped ticks and a margin larger than the old fixed 100.
- INV-1, conformance and `node --check surveytool/desktop/static/breaks.js` stay green.

## QA gate (manual, before release)

On real files from Rakuten, Milieu, Toluna and PureSpectrum, in the desktop app:
- [ ] Leonard's exact case (Milieu q8 × Car ownership, swapped): distinct colours, wrapped labels, PNG saved and matching the screen.
- [ ] For every chart type, swapped and unswapped: the screen matches the exported PNG.
- [ ] Answer colour edits and drag reorder still apply on screen and in export.
- [ ] Single and bulk export both land in the chosen folder.

## Left to the builder

- Exact request/response field names, and how the shared route helper is factored.
- Whether to debounce figure fetches on rapid clicks.
- Loading state while a figure is fetched (keep the previous chart up rather than blanking, matching the Charts tab's uncommitted change).
- Commit granularity.
