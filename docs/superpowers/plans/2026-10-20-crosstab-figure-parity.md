# Cross-tab Figure Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The Cross-tab tab draws the server-built Plotly figure, so its on-screen chart and PNG export are one object. This fixes swapped-axis colours, cut-off labels and the export button that saves nothing.

**Architecture:** `plotly_renderer.build_figure` gains `swap_axes` and low-base labelling. A new `/breaks-figure` route serves `build_figure(...).to_plotly_json()`, built by the same helper the export routes use. `breaks.js` stops building traces and draws whatever the route returns. Single export writes into `out_dir` like bulk.

**Tech Stack:** Python 3.11+, FastAPI, Plotly + kaleido, pydantic v2, pytest; plain JS (no build), Plotly.js.

**Spec:** `docs/superpowers/specs/2026-10-20-crosstab-figure-parity-design.md`

## Global Constraints

- No chart logic in `breaks.js`. It may only override `layout.showlegend` (false when the custom answer-colour legend stands in).
- Flippable chart types are exactly `stacked_bar_100`, `diverging_stacked_bar` and `grouped_bar`. `swap_axes` is ignored for `net_bar` and `table`.
- Swapped view: grouped bars, x = wrapped answer labels, one trace per column, colours from `assign_series_colours(column display labels, palette=style.palette)`.
- Low-base column label: `"<label> (low base, n=<base_cell>)"`, alongside the existing `"<label> (suppressed, n=<base_cell>)"`.
- Every user-facing failure is a `SurveyToolError` with plain English and a `next_action`. The frontend switches on `code` only.
- Computation, netting, suppression and chart-validity code are untouched. `tests/test_breaks_invariants.py` and the conformance tests must stay green with no edits.
- Table chart type keeps its HTML table on screen.
- `node --check surveytool/desktop/static/breaks.js` must pass after every JS edit.
- Commits use `feat:`/`fix:`/`test:`/`chore:` prefixes and end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- The working tree has uncommitted edits in `breaks.js` and `charts.js`. Keep the scroll-preservation lines in `runCrosstab` (breaks.js). The hand-written diverging block is deleted by Task 4. Leave `charts.js` uncommitted; it is not this plan's change.

## Review Focus

1. **Swapped chart with a suppressed column.** The column stays in the legend, greyed with the suppressed name, and never shows a value. *(Task 1 test)*
2. **Two columns whose display labels collide** (e.g. nested breaks producing the same `label_path` text). Colours are keyed by label, so they would share a colour. Accept it; it's documented in the builder's docstring, not tested.
3. **Rapid clicks** (chart type, then swap, then style) before the first figure arrives. The chart must end up showing the *last* request, not whichever response lands last. *(Task 4 token guard; manual QA)*
4. **Export folder unwritable or never chosen.** Plain-English error naming the folder; no "Exported" success message. *(Task 3 test)*
5. **A colour or order edit in the legend.** The figure is re-fetched after the edit has been saved, so the new colour shows on screen and in the next export. *(Task 4; manual QA)*

---

### Task 1: `build_figure` supports `swap_axes` and labels low-base columns

**Files:**
- Modify: `surveytool/charts/plotly_renderer.py` (`_column_display_label` ~178, `build_figure` ~583, new `_swapped_bar_figure`)
- Test: `tests/test_breaks_export.py`

**Interfaces:**
- Produces: `build_figure(question_result, chart_type, *, break_spec=None, filter_spec=None, swap_axes: bool = False) -> go.Figure`
- Produces: `SWAPPABLE_CHART_TYPES: frozenset[ChartType]` (module-level, the three flippable types)

- [ ] **Step 1: Write failing tests** in `tests/test_breaks_export.py`. Add a `_low_base_column(key, label, base=40)` helper (like `_ok_column`, `band=Band.low_base`).

```python
def test_swapped_figure_has_one_trace_per_column_with_distinct_colours(question_result):
    fig = build_figure(question_result, ChartType.stacked_bar_100, swap_axes=True)
    assert [t.name for t in fig.data] == ["Male", "Female"]
    assert len({t.marker.color for t in fig.data}) == 2
    assert fig.layout.barmode == "group"

def test_swapped_figure_x_axis_is_wrapped_answer_labels():
    qr = _question_result([_ok_column("male", "Male")])
    qr.scale_points[0].label = "I prefer other modes of transport (e.g. cycling, ride-hailing)"
    fig = build_figure(qr, ChartType.grouped_bar, swap_axes=True)
    assert "<br>" in fig.data[0].x[0]
    assert fig.layout.margin.b > 100

@pytest.mark.parametrize("chart_type", [ChartType.stacked_bar_100, ChartType.diverging_stacked_bar, ChartType.grouped_bar])
def test_every_flippable_type_swaps(question_result, chart_type):
    fig = build_figure(question_result, chart_type, swap_axes=True)
    assert [t.name for t in fig.data] == ["Male", "Female"]

@pytest.mark.parametrize("chart_type", [ChartType.net_bar, ChartType.table])
def test_swap_axes_ignored_for_non_flippable_types(question_result, chart_type):
    assert build_figure(question_result, chart_type, swap_axes=True) == build_figure(question_result, chart_type)

def test_swapped_suppressed_column_is_grey_named_and_valueless(question_result_with_suppressed_cell):
    fig = build_figure(question_result_with_suppressed_cell, ChartType.grouped_bar, swap_axes=True)
    suppressed = fig.data[1]
    assert suppressed.name == "Female (suppressed, n=5)"
    assert suppressed.marker.color == "#D0D0D0"
    assert all(v == 0 for v in suppressed.y)

def test_low_base_column_label_is_marked():
    qr = _question_result([_ok_column("male", "Male"), _low_base_column("female", "Female", base=40)])
    fig = build_figure(qr, ChartType.stacked_bar_100)
    assert "Female (low base, n=40)" in fig.data[0].x
```

(`fig == fig` on `go.Figure` compares by value. If it doesn't, compare `.to_plotly_json()`.)

- [ ] **Step 2: Run them and confirm they fail.** `pytest tests/test_breaks_export.py -q -k "swap or low_base"`. Expected: `TypeError: unexpected keyword 'swap_axes'` and an assertion failure on the low-base label.

- [ ] **Step 3: Implement.**
  - `_column_display_label`: add the `Band.low_base` branch with the exact format from Global Constraints.
  - New `_swapped_bar_figure(question_result, style) -> go.Figure`:
    - x = `wrap_axis_labels([p.label for p in scale_points])`;
    - one `go.Bar` per column, `name=_column_display_label(column)`;
    - y = column percentages per scale-point code (0.0 when `percentages is None`);
    - `marker_color` from `assign_series_colours` over the column display labels; suppressed columns use `_SUPPRESSED_GREY` with `marker_pattern_shape="x"`;
    - `hovertemplate=_HOVER_TEMPLATE`, `barmode="group"`, `yaxis_title="%"`;
    - the docstring notes that colliding display labels share a colour.
  - `build_figure`: after the permission check, use `_swapped_bar_figure` when `swap_axes and chart_type in SWAPPABLE_CHART_TYPES`. Pass `axis_labels` to `_apply_header` as scale-point labels when swapped, column display labels otherwise.

- [ ] **Step 4: Run the tests.** `pytest tests/test_breaks_export.py -q`. Expected: all pass. Then `pytest -q tests/test_breaks_invariants.py tests/test_breaks_conformance.py tests/test_desktop_breaks_api.py`. Expected: pass. If an existing test asserts a plain low-base column label, update its expectation to the new format.

- [ ] **Step 5: Commit.** `feat: build_figure swaps axes with per-column colours and marks low-base columns`

---

### Task 2: `/breaks-figure` route, built by one shared helper

**Files:**
- Modify: `surveytool/core/breaks_models.py` (new `BreaksFigureRequest`; `ExportRequest` and `BulkExportRequest` gain fields)
- Modify: `surveytool/desktop/app.py` (`post_crosstab` ~1292, `post_breaks_export` ~1339, `post_breaks_export_bulk` ~1409, new route)
- Test: `tests/test_desktop_breaks_api.py`

**Interfaces:**
- Consumes: `build_figure(..., swap_axes=)` from Task 1.
- Produces models:
  - `BreaksFigureRequest(break_spec, filter_spec=FilterSpec(), chart_type: ChartType, question_id: str, swap_axes: bool = False)`;
  - `ExportRequest(BreaksFigureRequest)` adds `out_dir: str`;
  - `BulkExportRequest` adds `swap_axes: bool = False`.
- Produces helper `_compute_breaks_results(session, break_spec, filter_spec, question_ids) -> list[QuestionResult]` (validate → compute with the three `_load_*_for_survey` overrides → `attach_chart_permissions`). It is used by crosstab, figure, export and bulk.
- Produces route `POST /api/session/{session_id}/breaks-figure` → `{"figure": <plotly json>}`.

- [ ] **Step 1: Write failing tests.** Use `_upload_milieu`; skip if `MILIEU_PATH` is missing.

```python
def test_breaks_figure_equals_build_figure_for_styled_swapped_question(client):
    # PUT chart-style for q8: {"style_name": "cool", "response_colours": {<first q8 answer label>: "#1B667D"}}
    # POST /breaks-figure with break_spec {"dimensions": ["car_ownership"]}, chart_type "grouped_bar",
    #   question_id "q8", swap_axes True
    # expected = build_figure(_compute_breaks_results(session, ...)[0], ChartType.grouped_bar,
    #   break_spec=[...], filter_spec={}, swap_axes=True).to_plotly_json()
    assert served["figure"] == json.loads(json.dumps(expected, default=str))

def test_breaks_figure_swapped_q8_has_distinct_colours_per_car_ownership_group(client):
    # Leonard's case: OK columns' trace colours are pairwise distinct; tick text contains "<br>"
    ...

def test_breaks_figure_rejects_unpermitted_chart_type(client):
    # same shape as test_breaks_export_endpoint_rejects_unpermitted_chart_type; asserts body["code"]
    ...
```

Read q8's first answer label and the actual q8 id from the `/crosstab` response rather than hardcoding them. If Milieu's question id isn't `q8`, pick the multi-select question whose text starts "What are your main reasons for not owning".

- [ ] **Step 2: Run them and confirm they fail.** `pytest tests/test_desktop_breaks_api.py -q -k breaks_figure`. Expected: 404/405 on the new route.

- [ ] **Step 3: Implement** the models, the helper and the route. Refactor `post_crosstab` and both export routes onto `_compute_breaks_results`, with no behaviour change. `/breaks-export-bulk` passes `swap_axes` to `build_figure`. (Task 3 changes `/breaks-export`'s response.) In `tests/conftest.py`, nothing changes; no new persistent store.

- [ ] **Step 4: Run the tests.** `pytest tests/test_desktop_breaks_api.py tests/test_breaks_export.py -q`. Expected: pass. (Existing `/breaks-export` tests are still on the old body until Task 3. If `ExportRequest` now requires `out_dir` and breaks them, do Task 3's test updates in this commit instead.)

- [ ] **Step 5: Commit.** `feat: add /breaks-figure, sharing one compute path with Cross-tab export`

---

### Task 3: Single Cross-tab export saves into the export folder, as displayed

**Files:**
- Modify: `surveytool/desktop/app.py` (`post_breaks_export`; extract `_ensure_out_dir(out_dir: str) -> Path` from the bulk route's mkdir/`SurveyToolError` block)
- Test: `tests/test_desktop_breaks_api.py`

**Interfaces:**
- Consumes: `ExportRequest.out_dir`, `swap_axes` (Task 2).
- Produces: `/breaks-export` returns JSON `{"filename": str, "out_dir": str}`.
  - Filename is `f"{question_id}-{chart_type.value}{'-swapped' if swapped else ''}.png"`, where `swapped = swap_axes and chart_type in SWAPPABLE_CHART_TYPES`.
  - The bulk route uses the same filename rule.

- [ ] **Step 1: Update and add tests.**
  - Rewrite `test_breaks_export_endpoint_renders_a_png` to post `out_dir=str(tmp_path)` and assert `(tmp_path / body["filename"])` exists with size > 0.
  - Delete `test_breaks_export_endpoint_deletes_temp_file_after_response`; the route no longer stages a temp file.
  - Add:

```python
def test_breaks_export_swapped_writes_swapped_filename(client, tmp_path):
    # chart_type "grouped_bar", swap_axes True -> body["filename"] == "<qid>-grouped_bar-swapped.png", file exists

def test_breaks_export_unwritable_folder_is_plain_error(client, tmp_path):
    blocker = tmp_path / "file"; blocker.write_text("x")
    # out_dir = str(blocker / "sub") -> status 500, body["code"] == "INTERNAL",
    # body["message"] == "The export could not be saved to the chosen location."
```

- [ ] **Step 2: Run them and confirm they fail.** `pytest tests/test_desktop_breaks_api.py -q -k breaks_export`. Expected: the new assertions fail.

- [ ] **Step 3: Implement.** Use `_ensure_out_dir` in both export routes, then `rasterize` directly to `out_dir / filename`. Drop the `FileResponse`/`BackgroundTask`/temp-file code, and any imports it leaves unused.

- [ ] **Step 4: Run the tests.** `pytest tests/test_desktop_breaks_api.py -q`. Expected: pass.

- [ ] **Step 5: Commit.** `fix: Cross-tab single export saves the PNG to the export folder, honouring Swap axes`

---

### Task 4: `breaks.js` draws the server figure; exports send swap state

**Files:**
- Modify: `surveytool/desktop/static/breaks.js` (`renderBreaksResults` ~690, `renderChartArea` ~865, `renderBreaksChart` ~965 to end of function, both export click handlers ~1150+)

**Interfaces:**
- Consumes: `POST /breaks-figure` body `{break_spec: currentBreakSpec(), filter_spec: currentFilterSpec(), chart_type, question_id, swap_axes}` → `{figure}`. Consumes `/breaks-export` and `/breaks-export-bulk` with `out_dir` and `swap_axes`. Consumes `/breaks-export` response `{filename, out_dir}`.
- Produces: `async function renderBreaksChart(qr, chartArea, chartType)`.

- [ ] **Step 1: Replace `renderBreaksChart`'s body.**
  - Compute `const swapped = AXIS_FLIPPABLE_CHART_TYPES.has(chartType) && breaksAxisFlipped`.
  - Bump a per-area token: `const token = String((Number(chartArea.dataset.renderToken) || 0) + 1); chartArea.dataset.renderToken = token;`.
  - Leave the current chart in place (don't clear `innerHTML`) and fetch `/breaks-figure`.
  - On failure, `if (chartArea.dataset.renderToken !== token) return;`, then show `errorFromBody(body).message` in a `status-body error` div (and "Could not reach the local server." on a network error).
  - On success, after the same token check, call `Plotly.react(chartArea, fig.data, { ...fig.layout, showlegend: (chartType === "net_bar" || swapped) ? fig.layout.showlegend : false }, { displaylogo: false, responsive: true })`.
  - `Plotly.react` replaces any existing chart or error content in place. If the area holds a non-Plotly node (e.g. the table), clear it first: check `chartArea.querySelector("table, .status-body")`.
  - Delete `bandColors`, `patterns`, all trace branches (including the uncommitted diverging block), the `withChartTemplate`/`applyChartStyleToLayout` calls and the `qr.chart_style` gate.

- [ ] **Step 2: Hide the duplicated heading for figures.** In `renderChartArea`, hide the question block's `h3` and `.breaks-question-base` when a figure is drawn (the figure header carries both). Show them for the table and table-fallback paths. Keep the column strip.

- [ ] **Step 3: Exports.**
  - Single export: send `out_dir: outDir` and `swap_axes: AXIS_FLIPPABLE_CHART_TYPES.has(chartType) && breaksAxisFlipped`, and use the question whose block is on screen (`breaksSelectedQuestionId`, falling back to `breaksLatestResults[0]`). On success read the JSON and set the status to `` `Saved ${body.filename} to ${body.out_dir}` ``.
  - Bulk export: also send `swap_axes`.

- [ ] **Step 4: Remove dead code.** Run `grep -n "withChartTemplate\|CHART_TEMPLATE_LAYOUT\|CHART_COLORS" surveytool/desktop/static/breaks.js` and delete definitions in `breaks.js` that no longer have callers. `applyChartStyleToLayout` lives in `chart_legend.js`; remove it only if `grep -rn applyChartStyleToLayout surveytool/desktop/static` shows no callers left.

- [ ] **Step 5: Lint.** Run `node --check surveytool/desktop/static/breaks.js`. Expected: no output, exit 0.

- [ ] **Step 6: Smoke-test in the app.** Run `python -m uvicorn surveytool.desktop.app:app --port 8731` and load `milieu_survey_coe_data.csv` as Milieu. On the Cross-tab tab, choose q8, Break by Car ownership, then Swap axes. Check:
  - distinct colours with a legend;
  - wrapped labels, nothing clipped;
  - a style click and a legend colour edit both restyle the chart;
  - Export current chart produces `q8-…-swapped.png` in the folder, and the file matches the screen.

- [ ] **Step 7: Commit.** `fix: Cross-tab renders the server's figure, so screen, colours and export match`. This includes the kept scroll-preservation lines.

---

### Task 5: Full verification

- [ ] **Step 1:** Run `pytest -q`. Expected: all pass (≈3 min). Report any failure with its output; don't paper over it.
- [ ] **Step 2:** Work through the spec's QA gate checklist on real Rakuten, Milieu, Toluna and PureSpectrum files in `python -m surveytool.desktop.main`. Record which boxes were checked and which weren't.
