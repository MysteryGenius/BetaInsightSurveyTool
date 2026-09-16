# Chart Parity, Manual Response Styling & Cross-tab Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Retire the legacy Charts tab's matplotlib export path in favour of the same Plotly figure shown on screen (so on-screen and exported PNG can never drift), add a persisted per-question manual response order + colour legend that reaches both the Charts tab and Cross-tab, port label-wrapping to the shared Plotly layer, and add a Cross-tab "export all as PNGs" bulk action.

**Architecture:** A new `_dist_figure`/`_xbreak_figure`/`_means_figure` trio in `surveytool/charts/plotly_renderer.py` (mirroring the five existing `_*_figure` builders' `(data, style) -> go.Figure` shape) replaces `surveytool/charts/renderer.py`'s matplotlib drawing for the legacy chart types, consuming the same `ChartData.trace` dict `chart_data.py` already builds. `charts.js` is repointed to render these same figures Plotly-side (already using Plotly.js — a data-source change, not a new library), and `/api/session/{id}/export` is repointed from `render_charts`/`renderer.py` to a new `render_charts_plotly`/`rasterize` path so the on-screen chart and its PNG are the same `Figure` object, exactly like Cross-tab already guarantees. `chart_data.py`'s three trace builders gain a manual-order parameter (mirroring `_scale_points`' `manual_label_order` in `breaks_compute.py`) and every new figure builder resolves `ChartStyle`/colour overrides the same way `plotly_renderer.py`'s existing five builders do — through `assign_series_colours(labels, palette=style.palette)`, now able to take a per-label override map. `surveytool/ingest/chart_style.py`'s `ChartStyleChoice` gains a new `response_colours: dict[str, str]` field (default `{}`), validated at write time the same way `style_name` already is. A new shared legend component (`renderLegend` in a new `surveytool/desktop/static/chart_legend.js`, loaded by both `charts.js` and `breaks.js`) replaces Plotly's built-in legend wherever a question has a manual order or colour saved, each row offering drag-to-reorder (writes `display-order`) and a colour swatch (writes the new `response_colours` field via `chart-style`). Label wrapping is ported from `renderer.py`'s `_wrap_title`/`_compute_left_margin` into a new `wrap_axis_labels`/`compute_axis_margin` pair in `plotly_renderer.py`, applied to every figure builder's category axis and consumed identically by `charts.js` and `breaks.js`. Cross-tab bulk export adds a `POST /api/session/{id}/breaks-export-bulk` endpoint accepting a list of `question_id`s and looping `build_figure`/`rasterize` per id, with a new "Export all as PNGs" button in `breaks.js` beside the existing single-chart export button.

**Tech Stack:** Python, Plotly, kaleido, Pydantic, PyYAML, pytest, FastAPI (`surveytool/desktop/app.py`). No new dependencies. `surveytool/charts/renderer.py` and its matplotlib dependency are removed once nothing references them.

**Spec:** `docs/superpowers/specs/2026-09-16-chart-parity-and-manual-styling-design.md` — this plan implements that design in full; read both together.

## Global Constraints

- Full test suite baseline immediately before Task 1 Step 1: `python -m pytest -q` → **583 passed, 17 failed, 4 skipped** (confirmed 2026-09-16). The 17 failures are pre-existing PureSpectrum vendor-resolution failures (`test_purespectrum*.py`, `test_desktop_resolve.py`, `test_desktop_run_summary.py`, `test_desktop_settings.py`, `test_errors.py`, `test_nonsubstantive_labels.py`, `test_overrides.py`) — entirely unrelated to charts/rendering. Every later "run full suite" step in this plan compares against **583 passed + 4 skipped never decreasing**, not against the 17 pre-existing failures going away. Never attempt to fix those 17 as part of this plan.
- `brand` is the default style; every existing caller that doesn't opt into a style or manual override gets byte-for-byte identical output to today. No existing test's exact-colour, exact-figure, or exact-PNG-bytes assertion may change as a result of this work unless that test is explicitly listed in this plan's own task steps as being updated.
- Colour and order overrides are per-question only — no global/default setting (explicitly out of scope per spec).
- No undo/history for reorder or recolour — last-saved-wins, matching the existing style-preset and display-order persistence.
- A manual colour override for a response, where set, takes precedence over `assign_series_colours`' hash-derived colour for that label; unset labels keep falling back to the hash-derived assignment so a partial override never breaks the rest of the palette.
- Every new dataclass/model follows the codebase's existing pattern: frozen dataclasses for pure value objects, Pydantic `BaseModel` for anything crossing an API/serialization boundary.
- New errors subclass `SurveyToolError` with a new `ErrorCode` member, a plain-English message, a `detail`, and a `next_action` — matching every existing error class in `surveytool/charts/errors.py`.
- Per persistent project memory: end users of this tool are non-technical — any new user-facing error message must be plain English with a concrete remediation step, not a technical/internal-sounding message.
- Item A (render-engine consolidation) must land and pass its own full-suite check before any Item B/C task begins — both are scoped against the shared Plotly figure-builder layer Item A creates. Item D (bulk export) has no dependency on A/B/C and its tasks may be done in any order relative to them, but this plan sequences it last for clarity.

---

### Task 1: `chart_data.py` trace builders accept manual order and colour overrides

**Files:**
- Modify: `surveytool/charts/chart_data.py`
- Test: `tests/test_chart_data.py`

**Interfaces:**
- Consumes: nothing new (uses existing `ChartSpec`, `FindingsRow`).
- Produces: `build_chart_data(findings, survey_id, questions, display_orders: dict[str, list[str]] | None = None) -> list[ChartData]` — `display_orders` is an optional `qid -> label_order` map, same shape `_load_display_orders_for_survey` already returns in `app.py`. When a qid has an entry, `_dist_trace`'s and `_means_trace`'s `labels` (and every list keyed the same way, e.g. `values`/`n`/`role`) are reordered to match; entries not present in `label_order` are appended in their original order at the end so a manual order that's gone stale (a label removed from the data) never drops a label silently.

- [ ] **Step 1: Confirm the current test baseline**

Run: `python -m pytest -q`
Expected: `583 passed, 17 failed, 4 skipped` (matches Global Constraints baseline).

- [ ] **Step 2: Write the failing test for manual order in dist trace**

Add to `tests/test_chart_data.py`:

```python
def test_dist_trace_applies_manual_display_order():
    from surveytool.charts.chart_data import build_chart_data
    from surveytool.core.model import Question, QuestionType
    from surveytool.findings.sheet import FindingsRow

    rows = [
        FindingsRow(qid="Q1", question_text="Q1 text", breakdown_variable="total",
                    breakdown_level="Total", metric="pct_1", convention="pct",
                    value=10.0, cell_base=100, role=None),
        FindingsRow(qid="Q1", question_text="Q1 text", breakdown_variable="total",
                    breakdown_level="Total", metric="n_1", convention="n",
                    value=10, cell_base=100, role=None),
        FindingsRow(qid="Q1", question_text="Q1 text", breakdown_variable="total",
                    breakdown_level="Total", metric="pct_2", convention="pct",
                    value=20.0, cell_base=100, role=None),
        FindingsRow(qid="Q1", question_text="Q1 text", breakdown_variable="total",
                    breakdown_level="Total", metric="n_2", convention="n",
                    value=20, cell_base=100, role=None),
    ]
    question = Question(qid="Q1", text="Q1 text", qtype=QuestionType.single_choice,
                         codes={}, base_eligible=True)

    default_data = build_chart_data(rows, "t", [question])
    dist = next(c for c in default_data if c.chart_type == "dist")
    assert dist.trace["labels"] == ["1", "2"]

    reordered_data = build_chart_data(rows, "t", [question], display_orders={"Q1": ["2", "1"]})
    dist_reordered = next(c for c in reordered_data if c.chart_type == "dist")
    assert dist_reordered.trace["labels"] == ["2", "1"]
    assert dist_reordered.trace["values"] == [20.0, 10.0]
    assert dist_reordered.trace["n"] == [20, 10]
```

Adjust the `FindingsRow`/`Question` constructor kwargs to match their actual field names if they differ (check `surveytool/findings/sheet.py` and `surveytool/core/model.py` for the exact signatures before running).

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/test_chart_data.py -k manual_display_order -v`
Expected: FAIL — `build_chart_data()` doesn't accept `display_orders` yet (`TypeError`), or the reordered case doesn't reorder.

- [ ] **Step 4: Implement the reorder in `_dist_trace` and `_means_trace`, and thread the parameter**

In `surveytool/charts/chart_data.py`, add a helper and thread it through:

```python
def _apply_manual_order(labels: list[str], *parallel: list, manual_order: list[str] | None) -> tuple:
    """Reorder `labels` (and every list in `parallel`, index-for-index) to
    match `manual_order`. Labels not present in `manual_order` are appended
    in their original relative order, so a stale manual order (referring to
    a label no longer present) never drops a label silently."""
    if not manual_order:
        return (labels, *parallel)
    order_index = {label: i for i, label in enumerate(manual_order)}
    n = len(labels)
    indices = sorted(range(n), key=lambda i: (order_index.get(labels[i], n), i))
    reordered_labels = [labels[i] for i in indices]
    reordered_parallel = tuple([lst[i] for i in indices] for lst in parallel)
    return (reordered_labels, *reordered_parallel)
```

Update `_dist_trace(spec, manual_order: list[str] | None = None)`: after building `labels`, `values`, `n`, `roles`, apply:

```python
labels, values, n, roles = _apply_manual_order(labels, values, n, roles, manual_order=manual_order)
```
right before the `return` statement, and change the `return` dict to use these reordered names.

Update `_means_trace(spec, manual_order: list[str] | None = None)` the same way for its `labels`/`values` pair (its `cell_base` is scalar, not parallel, so it's untouched).

`_xbreak_trace` is not in scope — `breakdown_variable != "total"` rows are breakdown levels, not response labels, and manual response order does not apply to them (matches the spec's scope: order/colour override response options, not breakdown levels).

Update `build_chart_data`:

```python
def build_chart_data(
    findings: list[FindingsRow],
    survey_id: str,
    questions: list[Question],
    display_orders: dict[str, list[str]] | None = None,
) -> list[ChartData]:
    entries: list[ChartData] = []
    for spec in iter_chart_specs(findings, survey_id, questions):
        if spec.chart_type == "dist":
            trace = _dist_trace(spec, manual_order=(display_orders or {}).get(spec.qid))
        elif spec.chart_type == "xbreak":
            trace = _xbreak_trace(spec)
        else:
            trace = _means_trace(spec, manual_order=(display_orders or {}).get(spec.qid))
        entries.append(ChartData(
            chart_type=spec.chart_type, filename=spec.filename, qid=spec.qid,
            question_text=spec.question_text, breakdown_variable=spec.breakdown_variable,
            metric=spec.metric, trace=trace,
        ))
    return entries
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_chart_data.py -v`
Expected: PASS, including the new test and every pre-existing test in the file (they all call `build_chart_data` with no `display_orders`, which defaults to `None` → unchanged behaviour).

- [ ] **Step 6: Run full suite**

Run: `python -m pytest -q`
Expected: `583 passed` → now `584 passed` (one new test), same `17 failed, 4 skipped`.

- [ ] **Step 7: Commit**

```bash
git add surveytool/charts/chart_data.py tests/test_chart_data.py
git commit -m "feat: chart_data trace builders accept manual display order"
```

---

### Task 2: `assign_series_colours` accepts per-label colour overrides

**Files:**
- Modify: `surveytool/charts/palette.py`
- Test: `tests/test_palette.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `assign_series_colours(series_identities: list[str], palette: tuple[str, ...] = CATEGORICAL_PALETTE, overrides: dict[str, str] | None = None) -> dict[str, str]` — for any identity present as a key in `overrides`, its assigned colour is that override value verbatim (no hash lookup, no collision slot consumed); every other identity is assigned exactly as today, from the remaining palette after removing colours already claimed by an override (so an override-locked colour cannot also be silently reused as a hash-derived colour for an unset label in the same chart).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_palette.py`:

```python
def test_assign_series_colours_overrides_take_precedence():
    identities = ["A", "B", "C"]
    result = assign_series_colours(identities, overrides={"B": "#FF00FF"})
    assert result["B"] == "#FF00FF"


def test_assign_series_colours_unset_labels_still_get_hash_derived_colour():
    identities = ["A", "B", "C"]
    with_override = assign_series_colours(identities, overrides={"B": "#FF00FF"})
    without_override = assign_series_colours(identities)
    assert with_override["A"] == without_override["A"]
    assert with_override["C"] == without_override["C"]


def test_assign_series_colours_override_colour_not_reused_for_other_identity():
    custom_palette = ("#111111", "#222222")
    result = assign_series_colours(["A", "B"], palette=custom_palette, overrides={"A": "#111111"})
    assert result["A"] == "#111111"
    assert result["B"] != "#111111"


def test_assign_series_colours_no_overrides_is_unchanged():
    identities = ["Option A", "Option B", "Option C"]
    assert assign_series_colours(identities) == assign_series_colours(identities, overrides=None)
    assert assign_series_colours(identities) == assign_series_colours(identities, overrides={})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_palette.py -k override -v`
Expected: FAIL — `assign_series_colours()` doesn't accept `overrides` yet (`TypeError`).

- [ ] **Step 3: Implement `overrides`**

In `surveytool/charts/palette.py`, change the signature and body:

```python
def assign_series_colours(
    series_identities: list[str],
    palette: tuple[str, ...] = CATEGORICAL_PALETTE,
    overrides: dict[str, str] | None = None,
) -> dict[str, str]:
    """... (existing docstring, plus:)

    `overrides` (manual response colour feature): an optional identity ->
    hex-colour map. Any identity present here is assigned that colour
    verbatim, bypassing the hash-based assignment entirely and never
    consuming a palette slot. Every other identity is still assigned from
    `palette` exactly as before, except palette entries that exactly match
    an override colour are excluded from the pool available to hash-derived
    identities in this same call, so an overridden colour is never also
    handed to an unrelated identity in the same chart.
    """
    overrides = overrides or {}
    remaining_identities = [i for i in series_identities if i not in overrides]
    override_colours = set(overrides.values())
    remaining_palette = tuple(c for c in palette if c not in override_colours) or palette

    if len(remaining_identities) > len(remaining_palette):
        raise PaletteExhaustedError(len(remaining_identities), len(remaining_palette))

    def _base_slot(identity: str) -> int:
        digest = hashlib.sha256(identity.encode("utf-8")).digest()
        return int.from_bytes(digest[:4], "big") % len(remaining_palette)

    assignment: dict[str, str] = {}
    used_slots: set[int] = set()
    for identity in sorted(set(remaining_identities)):
        slot = _base_slot(identity)
        while slot in used_slots:
            slot = (slot + 1) % len(remaining_palette)
        used_slots.add(slot)
        assignment[identity] = remaining_palette[slot]

    for identity, colour in overrides.items():
        if identity in series_identities:
            assignment[identity] = colour

    return assignment
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_palette.py -v`
Expected: PASS, including every pre-existing test (none pass `overrides`, so they hit the `overrides = overrides or {}` → `{}` path, which reduces to identical behaviour to before this change).

- [ ] **Step 5: Run full suite**

Run: `python -m pytest -q`
Expected: `584 passed` → now `588 passed` (4 new tests), same `17 failed, 4 skipped`.

- [ ] **Step 6: Commit**

```bash
git add surveytool/charts/palette.py tests/test_palette.py
git commit -m "feat: assign_series_colours accepts per-identity colour overrides"
```

---

### Task 3: `ChartStyleChoice` gains `response_colours`, validated at write time

**Files:**
- Modify: `surveytool/ingest/chart_style.py`
- Modify: `surveytool/charts/errors.py`
- Test: `tests/test_chart_style.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `ChartStyleChoice(variable: str, style_name: str, saved_at: datetime, response_colours: dict[str, str] = {})`; `write_chart_style(path, choice)` now also validates every value in `choice.response_colours` is a well-formed 6-digit hex colour (`#RRGGBB`, case-insensitive), raising a new `InvalidResponseColourError` (not `UnknownChartStyleError`) if any value fails — a different error so a caller/UI can distinguish "bad style name" from "bad hex value" without string-matching a message.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_chart_style.py`:

```python
def test_write_then_load_round_trips_response_colours(tmp_path):
    path = tmp_path / "styles.yaml"
    choice = ChartStyleChoice(
        variable="Q1", style_name="brand", saved_at=datetime.now(timezone.utc),
        response_colours={"Strongly agree": "#1B667D", "Disagree": "#C4856A"},
    )
    write_chart_style(path, choice)
    loaded = load_chart_styles(path)
    assert loaded.styles["Q1"].response_colours == {"Strongly agree": "#1B667D", "Disagree": "#C4856A"}


def test_write_defaults_response_colours_to_empty_dict(tmp_path):
    path = tmp_path / "styles.yaml"
    choice = ChartStyleChoice(variable="Q1", style_name="brand", saved_at=datetime.now(timezone.utc))
    write_chart_style(path, choice)
    loaded = load_chart_styles(path)
    assert loaded.styles["Q1"].response_colours == {}


def test_write_rejects_malformed_hex_colour(tmp_path):
    path = tmp_path / "styles.yaml"
    choice = ChartStyleChoice(
        variable="Q1", style_name="brand", saved_at=datetime.now(timezone.utc),
        response_colours={"Strongly agree": "not-a-colour"},
    )
    with pytest.raises(InvalidResponseColourError):
        write_chart_style(path, choice)
    assert not path.exists()
```

Add the needed imports at the top of the test file (`ChartStyleChoice`, `write_chart_style`, `load_chart_styles`, `InvalidResponseColourError`, `datetime`/`timezone`, `pytest`) matching whatever's already imported there — check the file's current import block first and extend it rather than duplicating.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_chart_style.py -k response_colours -v`
Expected: FAIL — `ChartStyleChoice` has no `response_colours` field yet, and `InvalidResponseColourError` doesn't exist.

- [ ] **Step 3: Add `InvalidResponseColourError`**

In `surveytool/charts/errors.py`, add a new `ErrorCode` member `INVALID_RESPONSE_COLOUR = "INVALID_RESPONSE_COLOUR"` to the enum, add it to `_STATUS_BY_CODE` mapped to `400`, and add the error class (place it near `UnknownChartStyleError`):

```python
class InvalidResponseColourError(SurveyToolError):
    """Raised when a manual response-colour override is written with a
    value that isn't a well-formed 6-digit hex colour. Never persisted
    unvalidated -- a malformed value would either fail confusingly deep in
    a later Plotly render, or (worse) get silently accepted by some
    renderers and not others."""

    def __init__(self, label: str, value: str) -> None:
        self.label = label
        self.value = value
        detail = f"Response colour for {label!r} is {value!r}, not a valid 6-digit hex colour (e.g. #1B667D)."
        super().__init__(
            ErrorCode.INVALID_RESPONSE_COLOUR,
            f"'{value}' isn't a valid colour for '{label}'.",
            detail=detail,
            next_action="Pick a colour from the colour picker rather than typing a value directly.",
        )
```

- [ ] **Step 4: Add `response_colours` field and validation**

In `surveytool/ingest/chart_style.py`:

```python
import re

_HEX_COLOUR = re.compile(r"^#[0-9a-fA-F]{6}$")


class ChartStyleChoice(BaseModel):
    variable: str
    style_name: str
    saved_at: datetime
    response_colours: dict[str, str] = Field(default_factory=dict)
```

And in `write_chart_style`, before the existing `style_name` check (or after — order doesn't matter since both must pass):

```python
def write_chart_style(path: Path, choice: ChartStyleChoice) -> None:
    if choice.style_name not in STYLE_REGISTRY:
        raise UnknownChartStyleError(choice.style_name, sorted(STYLE_REGISTRY))
    for label, value in choice.response_colours.items():
        if not _HEX_COLOUR.match(value):
            raise InvalidResponseColourError(label, value)
    existing = load_chart_styles(path) if path.exists() else ProjectChartStyles()
    existing.styles[choice.variable] = choice
    path.write_text(yaml.dump(existing.model_dump(mode="json")), encoding="utf-8")
```

Add `InvalidResponseColourError` to the module's import from `surveytool.charts.errors`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_chart_style.py -v`
Expected: PASS, all tests including pre-existing ones (`response_colours` defaults to `{}`, so every existing `ChartStyleChoice(...)` call without it is unaffected).

- [ ] **Step 6: Run full suite**

Run: `python -m pytest -q`
Expected: `588 passed` → now `591 passed`, same `17 failed, 4 skipped`.

- [ ] **Step 7: Commit**

```bash
git add surveytool/ingest/chart_style.py surveytool/charts/errors.py tests/test_chart_style.py
git commit -m "feat: chart style choice persists per-response colour overrides"
```

---

### Task 4: `/api/projects/{survey_id}/chart-style/{qid}` PUT/GET carry `response_colours`

**Files:**
- Modify: `surveytool/desktop/app.py`
- Test: `tests/test_desktop_chart_style.py`

**Interfaces:**
- Consumes: `ChartStyleChoice.response_colours` (Task 3), `InvalidResponseColourError` (Task 3, already mapped to a 400 by the app-level `SurveyToolError` handler — confirm this handler exists generically and needs no per-error-code change).
- Produces: `ChartStylePayload(style_name: str, response_colours: dict[str, str] = {})`; `GET`/`PUT`/`DELETE` behave exactly as before, now round-tripping `response_colours` too. `_load_chart_styles_for_survey(survey_id) -> dict[str, str]` is unchanged (style name only) — a new `_load_response_colours_for_survey(survey_id) -> dict[str, dict[str, str]]` (qid -> label -> hex) is added alongside it for the figure-builder tasks (Task 6/7) to consume.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_desktop_chart_style.py` (check the file's existing `client` fixture and survey_id conventions first, and match them):

```python
def test_put_then_get_chart_style_round_trips_response_colours(client):
    survey_id = "t-response-colours"
    response = client.put(
        f"/api/projects/{survey_id}/chart-style/Q1",
        json={"style_name": "brand", "response_colours": {"Agree": "#1B667D"}},
    )
    assert response.status_code == 200, response.text
    assert response.json()["response_colours"] == {"Agree": "#1B667D"}

    response = client.get(f"/api/projects/{survey_id}/chart-style/Q1")
    assert response.status_code == 200
    assert response.json()["response_colours"] == {"Agree": "#1B667D"}


def test_put_malformed_response_colour_is_refused(client):
    survey_id = "t-response-colours-bad"
    response = client.put(
        f"/api/projects/{survey_id}/chart-style/Q1",
        json={"style_name": "brand", "response_colours": {"Agree": "not-a-colour"}},
    )
    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "INVALID_RESPONSE_COLOUR"


def test_get_chart_style_response_colours_defaults_to_empty_dict(client):
    survey_id = "t-response-colours-default"
    client.put(f"/api/projects/{survey_id}/chart-style/Q1", json={"style_name": "brand"})
    response = client.get(f"/api/projects/{survey_id}/chart-style/Q1")
    assert response.json()["response_colours"] == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_desktop_chart_style.py -k response_colours -v`
Expected: FAIL — `ChartStylePayload` doesn't accept/return `response_colours` yet.

- [ ] **Step 3: Update `ChartStylePayload` and the three routes, add the loader helper**

In `surveytool/desktop/app.py`:

```python
class ChartStylePayload(BaseModel):
    style_name: str
    response_colours: dict[str, str] = Field(default_factory=dict)
```

(Confirm `Field` is already imported from `pydantic` in this file — it is, used elsewhere for `ProjectSettingsPayload` etc.)

```python
@app.get("/api/projects/{survey_id}/chart-style/{qid}")
async def get_chart_style(survey_id: str, qid: str) -> ChartStylePayload | None:
    path = _project_chart_style_path(survey_id)
    styles = load_chart_styles(path)
    entry = styles.styles.get(qid)
    if entry is None:
        return None
    return ChartStylePayload(style_name=entry.style_name, response_colours=entry.response_colours)


@app.put("/api/projects/{survey_id}/chart-style/{qid}")
async def put_chart_style(survey_id: str, qid: str, payload: ChartStylePayload) -> ChartStylePayload:
    path = _project_chart_style_path(survey_id)
    choice = ChartStyleChoice(
        variable=qid,
        style_name=payload.style_name,
        response_colours=payload.response_colours,
        saved_at=datetime.now(timezone.utc),
    )
    write_chart_style(path, choice)
    return payload
```

(`reset_chart_style`/`DELETE` is unchanged — it deletes the whole entry regardless of shape.)

Add the new loader helper next to `_load_chart_styles_for_survey`:

```python
def _load_response_colours_for_survey(survey_id: str) -> dict[str, dict[str, str]]:
    path = _project_chart_style_path(survey_id)
    styles = load_chart_styles(path)
    return {
        qid: entry.response_colours
        for qid, entry in styles.styles.items()
        if entry.response_colours
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_desktop_chart_style.py -v`
Expected: PASS, all tests including pre-existing ones (`response_colours` defaults to `{}` on `ChartStylePayload`, so every existing PUT call without it round-trips unchanged).

- [ ] **Step 5: Run full suite**

Run: `python -m pytest -q`
Expected: `591 passed` → now `594 passed`, same `17 failed, 4 skipped`.

- [ ] **Step 6: Commit**

```bash
git add surveytool/desktop/app.py tests/test_desktop_chart_style.py
git commit -m "feat: chart-style endpoint round-trips per-response colour overrides"
```

---

### Task 5: Label wrapping ported to the shared Plotly layer

**Files:**
- Modify: `surveytool/charts/plotly_renderer.py`
- Test: `tests/test_breaks_export.py`

**Interfaces:**
- Consumes: `wrap_text` (`surveytool/core/text_hygiene.py`, unchanged).
- Produces: `wrap_axis_labels(labels: list[str], max_chars_per_line: int = 24) -> list[str]` — wraps each label independently via `wrap_text`, joining wrapped lines with `<br>` (Plotly's native tick-label line break), so a caller can pass the result straight into `x`/`tickvals`+`ticktext`. `compute_axis_margin(labels: list[str], base_margin: int = 60, px_per_char: int = 7, px_per_line: int = 14) -> int` — a pure function (no rendering measurement, unlike matplotlib's `_compute_left_margin`, since Plotly's margin is set before any client-side render pass exists) returning a bottom-margin pixel value sized to the tallest wrapped label's line count and longest line's character count, floored at `base_margin`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_breaks_export.py` (near the existing figure-builder tests, matching that file's fixture style):

```python
def test_wrap_axis_labels_short_label_unchanged():
    from surveytool.charts.plotly_renderer import wrap_axis_labels
    assert wrap_axis_labels(["Agree"]) == ["Agree"]


def test_wrap_axis_labels_long_label_gets_br_break():
    from surveytool.charts.plotly_renderer import wrap_axis_labels
    long_label = "This is a very long response option label that should wrap onto multiple lines"
    wrapped = wrap_axis_labels([long_label], max_chars_per_line=24)[0]
    assert "<br>" in wrapped
    for line in wrapped.split("<br>"):
        assert len(line) <= 24


def test_compute_axis_margin_grows_with_wrapped_line_count():
    from surveytool.charts.plotly_renderer import compute_axis_margin
    short_margin = compute_axis_margin(["Agree", "Disagree"])
    long_margin = compute_axis_margin([
        "This is a very long response option label that needs several wrapped lines to fit"
    ])
    assert long_margin > short_margin


def test_compute_axis_margin_never_below_base():
    from surveytool.charts.plotly_renderer import compute_axis_margin
    assert compute_axis_margin(["A"], base_margin=60) >= 60
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_breaks_export.py -k "wrap_axis_labels or compute_axis_margin" -v`
Expected: FAIL — neither function exists yet (`ImportError`).

- [ ] **Step 3: Implement both functions**

In `surveytool/charts/plotly_renderer.py`, add near the top (after the existing imports, alongside `_header_text`):

```python
def wrap_axis_labels(labels: list[str], max_chars_per_line: int = 24) -> list[str]:
    """Wrap each category-axis label independently onto multiple lines via
    Plotly's native <br> tick-label break syntax, mirroring what
    renderer.py's _wrap_title/_compute_left_margin already do for the
    matplotlib path -- ported here so the shared on-screen/export Plotly
    layer gets the same treatment, rather than truncating or letting long
    labels overlap."""
    return ["<br>".join(wrap_text(label, max_chars_per_line=max_chars_per_line)) for label in labels]


def compute_axis_margin(
    labels: list[str],
    base_margin: int = 60,
    px_per_char: int = 7,
    px_per_line: int = 14,
) -> int:
    """Compute a margin (in pixels) sized to accommodate the widest/tallest
    wrapped label, so wrap_axis_labels' output is never clipped by a fixed
    margin. Unlike renderer.py's _compute_left_margin (which measures an
    actual rendered matplotlib text extent), this is a pure character-count
    estimate: Plotly's figure is serialized before any client render pass
    exists for this module to measure against, so an estimate errs generous
    rather than exact -- consistent with this module's existing "figure
    building has no file I/O, no rendering side effects" contract."""
    wrapped = wrap_axis_labels(labels)
    max_lines = max((w.count("<br>") + 1 for w in wrapped), default=1)
    max_line_chars = max((len(line) for w in wrapped for line in w.split("<br>")), default=0)
    estimated = int(max_line_chars * px_per_char * 0.3 + max_lines * px_per_line) + base_margin // 2
    return max(base_margin, estimated)
```

- [ ] **Step 4: Wire wrapping into the five existing figure builders' category axis**

In each of `_stacked_bar_100_figure`, `_diverging_stacked_bar_figure`, `_grouped_bar_figure`, `_net_bar_figure` (not `_table_figure` — a table has no axis to wrap), change the line building `x_labels` from:

```python
x_labels = [_column_display_label(c) for c in question_result.columns]
```
to:
```python
x_labels = wrap_axis_labels([_column_display_label(c) for c in question_result.columns])
```

And in `_apply_header` (the shared layout-application function), add a bottom margin sized to the same labels — accept the raw (unwrapped) labels as a new parameter:

```python
def _apply_header(
    fig: go.Figure,
    question_result: QuestionResult,
    break_spec: list[str] | None,
    filter_spec: dict[str, list[str]] | None,
    chart_type: ChartType,
    style: ChartStyle,
    axis_labels: list[str] | None = None,
) -> None:
    fig.update_layout(
        title={...},  # unchanged
        margin={"t": 140, "b": compute_axis_margin(axis_labels or [])},
        paper_bgcolor=style.background,
        plot_bgcolor=style.background,
        font={"color": style.font_color},
    )
```

Update `build_figure` to pass the raw column labels through:

```python
builder = _BUILDERS[chart_type]
style = get_style(question_result.chart_style)
fig = builder(question_result, style)
axis_labels = [_column_display_label(c) for c in question_result.columns]
_apply_header(fig, question_result, break_spec, filter_spec, chart_type, style, axis_labels=axis_labels)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_breaks_export.py -v`
Expected: PASS, including every pre-existing figure-builder test (they assert trace *values*/structure, not exact label strings, so wrapping a short label — which `wrap_axis_labels` leaves unchanged per Step 1's first test — does not break them; if any pre-existing test does assert an exact label string against a long label, update that assertion to expect the now-wrapped `<br>`-joined form, and note the change here).

- [ ] **Step 6: Run full suite**

Run: `python -m pytest -q`
Expected: `594 passed` → now `598 passed`, same `17 failed, 4 skipped`.

- [ ] **Step 7: Commit**

```bash
git add surveytool/charts/plotly_renderer.py tests/test_breaks_export.py
git commit -m "feat: wrap long axis labels in the shared Plotly figure layer"
```

---

### Task 6: New `_dist_figure`/`_xbreak_figure`/`_means_figure` builders in `plotly_renderer.py`

**Files:**
- Modify: `surveytool/charts/plotly_renderer.py`
- Test: `tests/test_charts.py` (new Plotly-specific tests added alongside, not replacing, the matplotlib tests yet — Task 8 removes those)

**Interfaces:**
- Consumes: `ChartData` (`surveytool/charts/chart_data.py`, unchanged shape — `chart_type`, `filename`, `qid`, `question_text`, `breakdown_variable`, `metric`, `trace: dict`), `ChartStyle`/`get_style` (unchanged), `assign_series_colours` with `overrides` (Task 2), `wrap_axis_labels`/`compute_axis_margin` (Task 5).
- Produces: `build_legacy_figure(chart: ChartData, style: ChartStyle, response_colours: dict[str, str] | None = None) -> go.Figure` — one function handling all three legacy chart types by dispatching on `chart.chart_type`, returning a figure whose data/layout is equivalent to what `charts.js`'s current `chartTraceAndLayout` produces client-side (horizontal bar for `dist`/`means`, vertical bar for `xbreak`), but styled via `style`/`response_colours` instead of the hardcoded `CHART_COLORS.accent`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_charts.py` (new section, keep pre-existing matplotlib tests untouched for now):

```python
# ── New Plotly-based legacy figure builder (Item A) ─────────────────────────

def _dist_chart_data():
    from surveytool.charts.chart_data import ChartData
    return ChartData(
        chart_type="dist", filename="t__Q1__dist__total.png", qid="Q1",
        question_text="How satisfied are you?", breakdown_variable="total", metric="pct",
        trace={
            "labels": ["Dissatisfied", "Neutral", "Satisfied"],
            "values": [10.0, 20.0, 70.0],
            "n": [10, 20, 70],
            "role": ["bottom", "neutral", "top"],
            "cell_base": 100, "mean": 4.1, "t2b": 70.0,
        },
    )


def _xbreak_chart_data():
    from surveytool.charts.chart_data import ChartData
    return ChartData(
        chart_type="xbreak", filename="t__Q1__xbreak__region.png", qid="Q1",
        question_text="How satisfied are you?", breakdown_variable="region", metric="t2b",
        trace={"levels": ["North", "South"], "values": [65.0, 75.0], "n": [50, 50],
               "metric": "t2b", "is_pct": True},
    )


def _means_chart_data():
    from surveytool.charts.chart_data import ChartData
    return ChartData(
        chart_type="means", filename="t__all__means__total.png", qid="Q1",
        question_text="Q1", breakdown_variable="total", metric="mean",
        trace={"labels": ["Q1", "Q2"], "values": [4.1, 3.8], "cell_base": 100},
    )


def test_build_legacy_figure_dist_has_one_bar_trace_with_all_labels():
    from surveytool.charts.plotly_renderer import build_legacy_figure
    from surveytool.charts.styles import DEFAULT_STYLE

    fig = build_legacy_figure(_dist_chart_data(), DEFAULT_STYLE)
    assert len(fig.data) == 1
    assert list(fig.data[0].x) == [10.0, 20.0, 70.0]


def test_build_legacy_figure_xbreak_bars_by_level():
    from surveytool.charts.plotly_renderer import build_legacy_figure
    from surveytool.charts.styles import DEFAULT_STYLE

    fig = build_legacy_figure(_xbreak_chart_data(), DEFAULT_STYLE)
    assert list(fig.data[0].x) == ["North", "South"]
    assert list(fig.data[0].y) == [65.0, 75.0]


def test_build_legacy_figure_means_horizontal_bar():
    from surveytool.charts.plotly_renderer import build_legacy_figure
    from surveytool.charts.styles import DEFAULT_STYLE

    fig = build_legacy_figure(_means_chart_data(), DEFAULT_STYLE)
    assert list(fig.data[0].y) == ["Q1", "Q2"]
    assert list(fig.data[0].x) == [4.1, 3.8]


def test_build_legacy_figure_applies_response_colour_override():
    from surveytool.charts.plotly_renderer import build_legacy_figure
    from surveytool.charts.styles import DEFAULT_STYLE

    fig = build_legacy_figure(
        _dist_chart_data(), DEFAULT_STYLE, response_colours={"Satisfied": "#FF00FF"}
    )
    colours = fig.data[0].marker.color
    labels = _dist_chart_data().trace["labels"]
    assert colours[labels.index("Satisfied")] == "#FF00FF"


def test_build_legacy_figure_applies_non_brand_style_background():
    from surveytool.charts.plotly_renderer import build_legacy_figure
    from surveytool.charts.styles import STYLE_REGISTRY

    fig = build_legacy_figure(_dist_chart_data(), STYLE_REGISTRY["cool"])
    assert fig.layout.paper_bgcolor == STYLE_REGISTRY["cool"].background
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_charts.py -k build_legacy_figure -v`
Expected: FAIL — `build_legacy_figure` doesn't exist yet (`ImportError`).

- [ ] **Step 3: Implement `build_legacy_figure`**

In `surveytool/charts/plotly_renderer.py`, add near the bottom (before `_BUILDERS`/`build_figure`, since those are for the *other* chart-type family and must stay untouched):

```python
def _dist_figure(chart: "ChartData", style: ChartStyle, response_colours: dict[str, str] | None) -> go.Figure:
    t = chart.trace
    colour_by_label = assign_series_colours(t["labels"], palette=style.palette, overrides=response_colours)
    wrapped_labels = wrap_axis_labels(t["labels"])
    fig = go.Figure(
        data=[go.Bar(
            orientation="h",
            x=t["values"],
            y=wrapped_labels,
            marker_color=[colour_by_label[label] for label in t["labels"]],
            customdata=t["n"],
            hovertemplate="%{y}: %{x:.1f}%<br>n=%{customdata}<extra></extra>",
        )],
    )
    fig.update_layout(
        title={"text": chart.question_text, "x": 0.02, "xanchor": "left"},
        xaxis_title="%",
        margin={"l": compute_axis_margin(t["labels"], base_margin=160), "r": 20, "t": 60, "b": 40},
    )
    return fig


def _xbreak_figure(chart: "ChartData", style: ChartStyle) -> go.Figure:
    t = chart.trace
    wrapped_levels = wrap_axis_labels(t["levels"])
    fig = go.Figure(
        data=[go.Bar(
            x=wrapped_levels,
            y=t["values"],
            marker_color=style.palette[0],
            customdata=t["n"],
            hovertemplate="%{x}: %{y:.1f}" + ("%" if t["is_pct"] else "") + "<br>n=%{customdata}<extra></extra>",
        )],
    )
    fig.update_layout(
        title={"text": f"{chart.question_text} by {chart.breakdown_variable}", "x": 0.02, "xanchor": "left"},
        margin={"l": 60, "r": 20, "t": 60, "b": compute_axis_margin(t["levels"])},
    )
    return fig


def _means_figure(chart: "ChartData", style: ChartStyle, response_colours: dict[str, str] | None) -> go.Figure:
    t = chart.trace
    colour_by_label = assign_series_colours(t["labels"], palette=style.palette, overrides=response_colours)
    wrapped_labels = wrap_axis_labels(t["labels"])
    fig = go.Figure(
        data=[go.Bar(
            orientation="h",
            x=t["values"],
            y=wrapped_labels,
            marker_color=[colour_by_label[label] for label in t["labels"]],
            hovertemplate="%{y}: %{x:.2f}<extra></extra>",
        )],
    )
    fig.update_layout(
        title={"text": "Mean score comparison", "x": 0.02, "xanchor": "left"},
        margin={"l": compute_axis_margin(t["labels"], base_margin=200), "r": 20, "t": 60, "b": 40},
    )
    return fig


def build_legacy_figure(
    chart: "ChartData",
    style: ChartStyle,
    response_colours: dict[str, str] | None = None,
) -> go.Figure:
    """Build the on-screen/export figure for a legacy dist/xbreak/means chart
    (chart_data.py's ChartData), the same shape build_figure already
    provides for the newer breaks/crosstab chart types -- one Plotly figure,
    shown on screen and rasterized for export via the same rasterize()
    function, so this chart family gets the identical "on-screen and export
    can't drift, they're one object" guarantee.

    xbreak charts show breakdown levels (North/South), not response
    options, so response_colours (a response-label -> hex map) does not
    apply there -- only dist/means, whose bars are response options/questions
    respectively, take a colour override.
    """
    fig = go.Figure()
    if chart.chart_type == "dist":
        fig = _dist_figure(chart, style, response_colours)
    elif chart.chart_type == "xbreak":
        fig = _xbreak_figure(chart, style)
    else:
        fig = _means_figure(chart, style, response_colours)

    fig.update_layout(
        paper_bgcolor=style.background,
        plot_bgcolor=style.background,
        font={"color": style.font_color},
    )
    return fig
```

Add a `TYPE_CHECKING`-guarded import at the top of the file: `from surveytool.charts.chart_data import ChartData` under `if TYPE_CHECKING:` (matching the module's existing style of quoting forward-referenced types), or a plain top-level import if that introduces no circular-import problem — check by running the test suite in Step 4 either way.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_charts.py -k build_legacy_figure -v`
Expected: PASS.

- [ ] **Step 5: Run full suite**

Run: `python -m pytest -q`
Expected: `598 passed` → now `604 passed` (6 new tests), same `17 failed, 4 skipped`.

- [ ] **Step 6: Commit**

```bash
git add surveytool/charts/plotly_renderer.py tests/test_charts.py
git commit -m "feat: add Plotly figure builder for legacy dist/xbreak/means charts"
```

---

### Task 7: `/api/session/{id}/export` repointed to the Plotly figure/rasterize path

**Files:**
- Modify: `surveytool/charts/chart_data.py` (add a rendering entry point alongside `build_chart_data`)
- Modify: `surveytool/desktop/app.py`
- Test: `tests/test_desktop_charts.py`

**Interfaces:**
- Consumes: `build_legacy_figure`, `rasterize` (Task 6, `surveytool/charts/plotly_renderer.py`, `rasterize` unchanged from its existing form), `_load_display_orders_for_survey`, `_load_chart_styles_for_survey`, `_load_response_colours_for_survey` (Task 4).
- Produces: `render_charts_plotly(findings, out_dir: Path, survey_id: str, questions: list[Question], display_orders=None, chart_styles=None, response_colours=None, chart_filter=None) -> list[ManifestEntry]` in `surveytool/charts/chart_data.py` — same manifest-entry return shape `render_charts` (the matplotlib version) already produces, so `app.py`'s response body (`{"exported": [...], "out_dir": ...}`) needs no shape change.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_desktop_charts.py`:

```python
def test_export_endpoint_produces_same_charts_as_charts_endpoint(client):
    """The exported PNG set must be exactly the charts /charts (JSON, now
    Plotly-backed same as export) reports -- the core parity guarantee of
    Item A: on-screen and export are the same figure-building code."""
    if not RAKUTEN_PATH.exists():
        pytest.skip(f"{RAKUTEN_PATH.name} not found in project root")

    session_id = _upload(client)
    charts_response = client.get(f"/api/session/{session_id}/charts")
    expected_filenames = {c["filename"] for c in charts_response.json()["charts"]}

    import tempfile
    with tempfile.TemporaryDirectory() as out_dir:
        response = client.post(f"/api/session/{session_id}/export", data={"out_dir": out_dir})
        assert response.status_code == 200, response.text
        assert set(response.json()["exported"]) == expected_filenames

        from pathlib import Path
        for filename in expected_filenames:
            png_path = Path(out_dir) / filename
            assert png_path.exists()
            assert png_path.stat().st_size > 0
```

- [ ] **Step 2: Run test to verify it fails or already passes vacuously**

Run: `python -m pytest tests/test_desktop_charts.py -k produces_same_charts -v`
Expected: Likely PASSES already against the current matplotlib `render_charts` (filenames match by construction, both drawing from `iter_chart_specs`) — this test's real job is to survive Step 4's swap unchanged, proving the swap didn't change which charts get exported. Confirm it passes now before continuing, so a later failure is attributable to the swap, not a pre-existing gap.

- [ ] **Step 3: Add `render_charts_plotly` to `chart_data.py`**

```python
def render_charts_plotly(
    findings: list[FindingsRow],
    out_dir: Path,
    survey_id: str,
    questions: list[Question],
    display_orders: dict[str, list[str]] | None = None,
    chart_styles: dict[str, str] | None = None,
    response_colours: dict[str, dict[str, str]] | None = None,
    chart_filter=None,
) -> list["ManifestEntry"]:
    """Plotly/kaleido equivalent of render_charts() (renderer.py's
    matplotlib path). Builds the same set of charts (from the same
    iter_chart_specs single source of truth) but through build_chart_data +
    build_legacy_figure + rasterize -- the identical figure-building code
    charts.js uses to draw the on-screen chart -- so the exported PNG can
    never visually drift from what's shown on screen, closing the gap
    render_charts()/charts.js's independent code paths left open.
    """
    from pathlib import Path as _Path
    from surveytool.charts.manifest import ManifestEntry, write_manifest
    from surveytool.charts.plotly_renderer import build_legacy_figure, rasterize
    from surveytool.charts.styles import get_style

    out_dir = _Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    chart_data_entries = build_chart_data(findings, survey_id, questions, display_orders=display_orders)
    entries: list[ManifestEntry] = []
    for chart in chart_data_entries:
        if chart_filter is not None:
            # chart_filter is written against ChartSpec (qid/chart_type/breakdown_variable);
            # ChartData carries the same three fields, so the same predicate applies unchanged.
            if not chart_filter(chart):
                continue
        style = get_style((chart_styles or {}).get(chart.qid))
        colours = (response_colours or {}).get(chart.qid)
        fig = build_legacy_figure(chart, style, response_colours=colours)
        out_path = out_dir / chart.filename
        rasterize(fig, out_path)
        entries.append(ManifestEntry(
            filename=chart.filename, qid=chart.qid, question_text=chart.question_text,
            breakdown_variable=chart.breakdown_variable, metric=chart.metric,
            findings_row_keys=[],  # Plotly path renders from ChartData, not FindingsRow directly; row provenance is not tracked per-entry here, matching build_chart_data's own contract of not re-deriving row keys.
        ))

    write_manifest(entries, out_dir / "manifest.json")
    return entries
```

Note: `chart_filter` callers in `app.py` build predicates like `lambda spec: spec.qid == qid and spec.chart_type == chart_type and spec.breakdown_variable == breakdown_variable` — `ChartData` has all three attributes with the same names as `ChartSpec`, so these predicates work unchanged against either.

- [ ] **Step 4: Repoint `export_charts` in `app.py`**

Replace the `export_charts` route body's import and call:

```python
@app.post("/api/session/{session_id}/export")
async def export_charts(
    session_id: str,
    out_dir: str = Form(...),
    qid: str | None = Form(None),
    chart_type: str | None = Form(None),
    breakdown_variable: str | None = Form(None),
):
    session = _require_session(session_id)

    chart_filter = None
    if qid is not None or chart_type is not None or breakdown_variable is not None:
        chart_filter = (
            lambda spec: spec.qid == qid
            and spec.chart_type == chart_type
            and spec.breakdown_variable == breakdown_variable
        )

    try:
        entries = render_charts_plotly(
            session.findings,
            Path(out_dir),
            session.survey.id,
            session.survey.questions,
            display_orders=_load_display_orders_for_survey(session.survey_id),
            chart_styles=_load_chart_styles_for_survey(session.survey_id),
            response_colours=_load_response_colours_for_survey(session.survey_id),
            chart_filter=chart_filter,
        )
    except OSError as exc:
        raise SurveyToolError(
            ErrorCode.INTERNAL,
            "The export could not be saved to the chosen location.",
            detail=str(exc),
            next_action="Choose a different export location and try again.",
        ) from exc

    if chart_filter is not None and not entries:
        raise SurveyToolError(
            ErrorCode.INTERNAL,
            "This chart could not be found in the current session.",
            next_action="Reload the page and try exporting again.",
        )

    return {"exported": [e.filename for e in entries], "out_dir": out_dir}
```

Update the import at the top of `app.py`: replace `from surveytool.charts import render_charts` (or wherever `render_charts` is imported for this route) with `from surveytool.charts.chart_data import render_charts_plotly` — check whether `render_charts` is used anywhere else in `app.py` before removing its import entirely (it is not expected to be, since Cross-tab uses `build_figure`/`rasterize` directly, but confirm with `grep -n "render_charts\b" surveytool/desktop/app.py`).

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_desktop_charts.py -v`
Expected: Some pre-existing tests in this file WILL fail here — specifically `test_export_endpoint_matches_direct_render_charts_output` and `test_export_endpoint_single_chart_matches_direct_render`, both of which call the matplotlib `render_charts` directly and assert byte-for-byte equality with the endpoint's output. Since the endpoint now produces Plotly PNGs and `render_charts` still produces matplotlib PNGs, these two tests' *comparison target* is now wrong, not the endpoint. Fix them in this step: replace their `from surveytool.charts import render_charts` call with `from surveytool.charts.chart_data import render_charts_plotly`, and pass the same `display_orders`/`chart_styles`/`response_colours` the endpoint now loads (empty dicts, since these tests don't set up any saved style/order — `_load_display_orders_for_survey(session.survey_id)` etc. still work against a session with nothing saved, returning `{}`). Re-run until green.

- [ ] **Step 6: Run full suite**

Run: `python -m pytest -q`
Expected: `604 passed` → now `605 passed` (1 new test; the 2 fixed tests are still counted as passing, just against a different comparison target), same `17 failed, 4 skipped`.

- [ ] **Step 7: Commit**

```bash
git add surveytool/charts/chart_data.py surveytool/desktop/app.py tests/test_desktop_charts.py
git commit -m "feat: repoint legacy chart export onto the Plotly/kaleido renderer"
```

---

### Task 8: `charts.js` renders the same Plotly figure server-side data, gains the style-preset row

**Files:**
- Modify: `surveytool/desktop/app.py` (extend `get_charts`'s response with style/order/colour context)
- Modify: `surveytool/desktop/static/charts.js`
- Test: `tests/test_desktop_charts.py`

**Interfaces:**
- Consumes: `_load_chart_styles_for_survey`, `_load_response_colours_for_survey`, `_load_display_orders_for_survey` (existing/Task 4), `build_chart_data`'s `display_orders` param (Task 1).
- Produces: `GET /api/session/{id}/charts` response gains two top-level fields alongside the existing `charts` list: `chart_styles: dict[str, str]` (qid -> style_name) and `response_colours: dict[str, dict[str, str]]` (qid -> label -> hex), so `charts.js` can apply the same style/colour a saved-style question would show without a second round trip per chart. `charts.js`'s `chartTraceAndLayout` is replaced by a style-aware version consuming these two new fields plus `CLIENT_CHART_STYLES` (already defined in `breaks.js` — moved to the new shared file in Task 9, referenced here).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_desktop_charts.py`:

```python
def test_charts_endpoint_returns_saved_chart_style_and_response_colours(client):
    if not RAKUTEN_PATH.exists():
        pytest.skip(f"{RAKUTEN_PATH.name} not found in project root")

    session_id = _upload(client)
    from surveytool.desktop.app import get_session
    session = get_session(session_id)
    survey_id = session.survey.id

    client.put(
        f"/api/projects/{survey_id}/chart-style/Q1",
        json={"style_name": "cool", "response_colours": {"Strongly agree": "#1B667D"}},
    )

    response = client.get(f"/api/session/{session_id}/charts")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["chart_styles"]["Q1"] == "cool"
    assert body["response_colours"]["Q1"] == {"Strongly agree": "#1B667D"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_desktop_charts.py -k saved_chart_style_and_response_colours -v`
Expected: FAIL — `body["chart_styles"]` raises `KeyError`.

- [ ] **Step 3: Extend `get_charts`**

```python
@app.get("/api/session/{session_id}/charts")
async def get_charts(session_id: str):
    session = _require_session(session_id)
    display_orders = _load_display_orders_for_survey(session.survey_id)
    chart_data = build_chart_data(
        session.findings, session.survey.id, session.survey.questions,
        display_orders=display_orders,
    )
    return {
        "charts": [asdict(c) for c in chart_data],
        "chart_styles": _load_chart_styles_for_survey(session.survey_id),
        "response_colours": _load_response_colours_for_survey(session.survey_id),
        "display_orders": display_orders,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_desktop_charts.py -k saved_chart_style_and_response_colours -v`
Expected: PASS.

- [ ] **Step 5: Run the full pre-existing `test_desktop_charts.py` suite to confirm no regression**

Run: `python -m pytest tests/test_desktop_charts.py -v`
Expected: PASS — the existing tests destructure `response.json()["charts"]` directly and never assert the response has *only* that key, so adding sibling keys is additive.

- [ ] **Step 6: Update `charts.js`'s trace/layout builder and add the style row**

In `surveytool/desktop/static/charts.js`, replace `chartTraceAndLayout` (and the hardcoded single-colour `marker`) with a style-aware version. First, add near the top of the file (after `CHART_TEMPLATE_LAYOUT`):

```javascript
// Populated once per loadCharts() call from the /charts response's sibling
// fields, keyed by qid — chartTraceAndLayout reads these instead of always
// using CHART_COLORS.accent, so a saved style/colour reaches the legacy
// Charts tab exactly like breaks.js's applyChartStyleToLayout already does
// for Cross-tab.
let chartsStyleByQid = {};
let chartsResponseColoursByQid = {};
```

Replace `chartTraceAndLayout(chart)`'s body to resolve per-chart style/colours:

```javascript
function chartTraceAndLayout(chart) {
  const t = chart.trace;
  const styleName = chartsStyleByQid[chart.qid] || "brand";
  const style = CLIENT_CHART_STYLES[styleName] || CLIENT_CHART_STYLES.brand;
  const overrides = chartsResponseColoursByQid[chart.qid] || {};

  function colourFor(label, fallbackIndex) {
    if (overrides[label]) return overrides[label];
    return style.palette[fallbackIndex % style.palette.length];
  }

  if (chart.chart_type === "dist") {
    return {
      data: [{
        type: "bar",
        orientation: "h",
        x: t.values,
        y: t.labels,
        marker: { color: t.labels.map((label, i) => colourFor(label, i)) },
        customdata: t.n,
        hovertemplate: "%{y}: %{x:.1f}%<br>n=%{customdata}<extra></extra>",
      }],
      layout: withChartTemplate({
        title: chart.question_text,
        margin: { l: 160, r: 20, t: 40, b: 40 },
        xaxis: { title: "%" },
        paper_bgcolor: style.background,
        plot_bgcolor: style.background,
        font: { color: style.fontColor },
      }),
    };
  }

  if (chart.chart_type === "xbreak") {
    return {
      data: [{
        type: "bar",
        x: t.levels,
        y: t.values,
        marker: { color: style.palette[0] },
        customdata: t.n,
        hovertemplate: "%{x}: %{y:.1f}" + (t.is_pct ? "%" : "") + "<br>n=%{customdata}<extra></extra>",
      }],
      layout: withChartTemplate({
        title: `${chart.question_text} by ${chart.breakdown_variable}`,
        margin: { l: 60, r: 20, t: 40, b: 60 },
        paper_bgcolor: style.background,
        plot_bgcolor: style.background,
        font: { color: style.fontColor },
      }),
    };
  }

  // means
  const n = t.labels.map(() => t.cell_base);
  return {
    data: [{
      type: "bar",
      orientation: "h",
      x: t.values,
      y: t.labels,
      marker: { color: t.labels.map((label, i) => colourFor(label, i)) },
      customdata: n,
      hovertemplate: "%{y}: %{x:.2f}<br>n=%{customdata}<extra></extra>",
    }],
    layout: withChartTemplate({
      title: "Mean score comparison",
      margin: { l: 200, r: 20, t: 40, b: 40 },
      paper_bgcolor: style.background,
      plot_bgcolor: style.background,
      font: { color: style.fontColor },
    }),
  };
}
```

Note: this references `CLIENT_CHART_STYLES`, which today lives only in `breaks.js` — Task 9 moves it to a new shared file both scripts load, so land Task 9 before testing this in a browser (or temporarily duplicate the constant here if manually smoke-testing between tasks; the final committed state has it shared, not duplicated).

Update `loadCharts` to populate the two new module-level maps from the response, and add a style-preset button row per chart (mirroring `breaks.js`'s `buildChartStyleRow`, adapted for `charts.js`'s per-chart wrapper structure):

```javascript
async function loadCharts(sessionId, container) {
  container.innerHTML = "Loading charts…";
  let response;
  try {
    response = await fetch(`/api/session/${sessionId}/charts`);
  } catch {
    renderInlineError(container, {
      code: "INTERNAL",
      message: "Could not reach the local server.",
      next_action: "Try again. If it keeps happening, restart the app.",
    });
    return;
  }

  const body = await parseJsonResponse(response);
  if (!response.ok) {
    renderInlineError(container, errorFromBody(body));
    return;
  }

  chartsStyleByQid = body.chart_styles || {};
  chartsResponseColoursByQid = body.response_colours || {};
  renderCharts(body.charts, container, sessionId);
}
```

In `renderCharts`, add a style row per chart above the export row, persisting via the existing `/api/projects/{survey_id}/chart-style/{qid}` PUT (needs the survey_id, which `charts.js` doesn't currently track — add a `currentSurveyId` module-level var set alongside `sessionId` wherever `loadCharts` is invoked from `index.html`'s view-switch logic; check that call site and thread survey_id through the same way `breaksSurveyId` is threaded in `breaks.js`):

```javascript
    const styleRow = buildChartStyleRow(chart.qid, chartsStyleByQid[chart.qid], sessionSurveyId, () => {
      renderCharts(charts, container, sessionId); // re-render all charts so the change is visible immediately
    });
    wrapper.appendChild(styleRow);
```

Add `buildChartStyleRow(qid, currentStyleName, surveyId, onChange)` to the new shared `chart_legend.js` file created in Task 9 (not duplicated here) — a generalization of `breaks.js`'s existing `buildChartStyleRow(qr)` that takes a bare `qid`/style name instead of a full `QuestionResult`, since `charts.js`'s `ChartData` has no such object.

- [ ] **Step 7: Manual smoke test**

Run: `python -m surveytool.desktop.app` (or however the desktop app is normally launched — check `README.md`/`pyproject.toml` `[project.scripts]` for the actual entry point first) and open the Charts tab in a browser. Confirm charts still render, and after Task 9 lands, confirm the style row appears and changing style recolours the chart immediately.

- [ ] **Step 8: Run full suite**

Run: `python -m pytest -q`
Expected: `605 passed` → now `606 passed`, same `17 failed, 4 skipped`. (JS has no pytest coverage; this task's Python-side test is Step 1-4's addition only.)

- [ ] **Step 9: Commit**

```bash
git add surveytool/desktop/app.py surveytool/desktop/static/charts.js tests/test_desktop_charts.py
git commit -m "feat: legacy Charts tab reads and applies saved chart style/colours"
```

---

### Task 9: Shared legend component (`chart_legend.js`) — reorder + colour picker, wired into both tabs

**Files:**
- Create: `surveytool/desktop/static/chart_legend.js`
- Modify: `surveytool/desktop/static/breaks.js` (move `CHART_STYLES`, `chartStyleLabel`, `CLIENT_CHART_STYLES`, `applyChartStyleToLayout`, `buildChartStyleRow` out to the new file; call the new legend renderer)
- Modify: `surveytool/desktop/static/charts.js` (call the same legend renderer)
- Modify: `surveytool/desktop/static/index.html` (add `<script src="chart_legend.js">` before both `charts.js` and `breaks.js`)
- No Python changes — this task is JS-only, backed entirely by the endpoints Tasks 3/4/8 already built.

**Interfaces:**
- Consumes: `PUT /api/projects/{survey_id}/display-order/{qid}` (existing, unchanged), `PUT /api/projects/{survey_id}/chart-style/{qid}` with `response_colours` (Task 4).
- Produces: `renderLegend(container, {qid, surveyId, labels, order, colours, styleName, onChange})` — draws one row per label in `order` (or `labels` if `order` is empty), each with a drag handle and a colour swatch; dragging a row calls `PUT display-order` with the new label order and calls `onChange()`; clicking a swatch opens the browser's native `<input type="color">` picker and on change calls `PUT chart-style` with `response_colours` merged (existing colours plus this one changed) and calls `onChange()`. `buildChartStyleRow(qid, currentStyleName, surveyId, onChange)` (generalized from `breaks.js`'s existing question-result-shaped version) is also exported from this file.

- [ ] **Step 1: Create `chart_legend.js` with the moved style-preset code**

Move `CHART_STYLES`, `chartStyleLabel`, `CLIENT_CHART_STYLES`, `applyChartStyleToLayout` verbatim from `breaks.js` into the new file (cut from `breaks.js`, paste here unchanged — these are pure data/functions with no dependency on `breaks.js`-only globals).

Generalize `buildChartStyleRow` to not require a full `QuestionResult`:

```javascript
// Shared between charts.js and breaks.js — style presets, and the manual
// order + colour legend (response order/colour overrides, per question).

function buildChartStyleRow(qid, currentStyleName, surveyId, onChange) {
  const row = document.createElement("div");
  row.className = "chart-type-row chart-style-row";
  const activeStyle = currentStyleName || "brand";

  CHART_STYLES.forEach((styleName) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "chart-type-btn";
    btn.textContent = chartStyleLabel(styleName);
    if (activeStyle === styleName) btn.classList.add("active");
    btn.addEventListener("click", () => {
      row.querySelectorAll(".chart-type-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      fetch(`/api/projects/${surveyId}/chart-style/${qid}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ style_name: styleName }),
      })
        .then(() => onChange(styleName))
        .catch((err) => console.error("Failed to save chart style choice", err));
    });
    row.appendChild(btn);
  });

  return row;
}

// Renders one legend row per label (drag handle + colour swatch). `order`
// is the currently-effective label order (server-saved manual order, or
// natural order if none saved); `colours` is the qid's saved
// response_colours map (label -> hex), empty for any label with no
// override. Persists immediately per interaction (drag-drop reorder, or
// colour picker change) — no separate save step, matching the existing
// style-preset picker's immediate-save behaviour.
function renderLegend(container, { qid, surveyId, labels, order, colours, onChange }) {
  container.innerHTML = "";
  const effectiveOrder = order && order.length ? order : labels;
  let currentOrder = [...effectiveOrder];
  const currentColours = { ...(colours || {}) };

  let dragFromIndex = null;

  currentOrder.forEach((label, index) => {
    const row = document.createElement("div");
    row.className = "legend-row";
    row.draggable = true;
    row.dataset.index = String(index);

    const handle = document.createElement("span");
    handle.className = "legend-drag-handle";
    handle.textContent = "⠿";
    row.appendChild(handle);

    const swatch = document.createElement("input");
    swatch.type = "color";
    swatch.className = "legend-colour-swatch";
    swatch.value = currentColours[label] || "#cccccc";
    swatch.addEventListener("input", () => {
      currentColours[label] = swatch.value;
      fetch(`/api/projects/${surveyId}/chart-style/${qid}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          style_name: container.dataset.currentStyle || "brand",
          response_colours: currentColours,
        }),
      })
        .then(() => onChange())
        .catch((err) => console.error("Failed to save response colour", err));
    });
    row.appendChild(swatch);

    const labelSpan = document.createElement("span");
    labelSpan.className = "legend-label";
    labelSpan.textContent = label;
    row.appendChild(labelSpan);

    row.addEventListener("dragstart", () => { dragFromIndex = index; });
    row.addEventListener("dragover", (e) => e.preventDefault());
    row.addEventListener("drop", (e) => {
      e.preventDefault();
      if (dragFromIndex === null || dragFromIndex === index) return;
      const moved = currentOrder.splice(dragFromIndex, 1)[0];
      currentOrder.splice(index, 0, moved);
      dragFromIndex = null;
      fetch(`/api/projects/${surveyId}/display-order/${qid}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ label_order: currentOrder }),
      })
        .then(() => onChange())
        .catch((err) => console.error("Failed to save display order", err));
      renderLegend(container, { qid, surveyId, labels, order: currentOrder, colours: currentColours, onChange });
    });

    container.appendChild(row);
  });
}
```

- [ ] **Step 2: Wire `<script>` load order in `index.html`**

Add `<script src="chart_legend.js"></script>` immediately before the existing `<script src="charts.js"></script>` and `<script src="breaks.js"></script>` tags (both scripts now reference its globals, so it must load first).

- [ ] **Step 3: Remove the moved code from `breaks.js`, call the shared functions**

Delete `breaks.js`'s own `CHART_STYLES`, `chartStyleLabel`, `CLIENT_CHART_STYLES`, `applyChartStyleToLayout` definitions (now living in `chart_legend.js`). Update the existing call site that builds the per-question style row (the one currently calling the old `buildChartStyleRow(qr)`) to call the new signature:

```javascript
const styleRow = buildChartStyleRow(qr.question_id, qr.chart_style, breaksSurveyId, (newStyleName) => {
  qr.chart_style = newStyleName;
  const chartType = breaksActiveChartType[qr.question_id];
  renderChartArea(qr, block.querySelector(".breaks-chart-area"), chartType);
});
```

Add a legend container beneath the chart area in the same per-question block builder (find where `chartArea`/style row are appended, add alongside):

```javascript
const legendContainer = document.createElement("div");
legendContainer.className = "chart-legend";
legendContainer.dataset.currentStyle = qr.chart_style || "brand";
block.appendChild(legendContainer);
renderLegend(legendContainer, {
  qid: qr.question_id,
  surveyId: breaksSurveyId,
  labels: qr.scale_points.map((sp) => sp.label),
  order: qr.scale_points.map((sp) => sp.label), // qr.scale_points is already server-ordered per display_order_is_manual
  colours: {}, // breaks.js does not yet fetch saved response_colours per question_id; see Task 10 for wiring QuestionResult.response_colours through
  onChange: () => { /* re-fetch or re-render on next crosstab call */ },
});
```

Leave a `# TODO`-free note in a code comment (not a TODO marker per repo convention) that the `colours: {}` placeholder is completed once `QuestionResult` carries `response_colours` — this is exactly what Task 10 below does; this step only wires the legend's *reorder* half completely, since order already flows through `QuestionResult.scale_points`, while colour needs the backend threading Task 10 adds first.

- [ ] **Step 4: Wire `charts.js`'s style row through the shared function**

In `charts.js`, replace the earlier `buildChartStyleRow` reference from Task 8 Step 6 (which was written against a to-be-shared function) to call `chart_legend.js`'s version directly:

```javascript
const styleRow = buildChartStyleRow(chart.qid, chartsStyleByQid[chart.qid], sessionSurveyId, (newStyleName) => {
  chartsStyleByQid[chart.qid] = newStyleName;
  renderCharts(charts, container, sessionId);
});
wrapper.appendChild(styleRow);

const legendContainer = document.createElement("div");
legendContainer.className = "chart-legend";
wrapper.appendChild(legendContainer);
if (chart.chart_type !== "xbreak") {  // xbreak bars are breakdown levels, not response options -- no colour override applies
  renderLegend(legendContainer, {
    qid: chart.qid,
    surveyId: sessionSurveyId,
    labels: chart.trace.labels,
    order: chart.trace.labels,
    colours: chartsResponseColoursByQid[chart.qid] || {},
    onChange: () => loadCharts(sessionId, container),
  });
}
```

- [ ] **Step 5: Manual smoke test**

Launch the desktop app, open the Charts tab: confirm each dist/means chart shows a legend panel below it with a colour swatch per response option, dragging a row reorders the chart on next reload, and clicking a swatch recolours that bar immediately. Repeat in Cross-tab.

- [ ] **Step 6: Run full suite (no Python changes, confirm nothing else broke)**

Run: `python -m pytest -q`
Expected: `606 passed`, unchanged, same `17 failed, 4 skipped` — this task touches no Python.

- [ ] **Step 7: Commit**

```bash
git add surveytool/desktop/static/chart_legend.js surveytool/desktop/static/breaks.js surveytool/desktop/static/charts.js surveytool/desktop/static/index.html
git commit -m "feat: shared drag-reorder + colour-picker legend for Charts tab and Cross-tab"
```

---

### Task 10: `QuestionResult` carries `response_colours`, threaded into Cross-tab's figures and legend

**Files:**
- Modify: `surveytool/compute/breaks_compute.py`
- Modify: `surveytool/charts/plotly_renderer.py` (thread `response_colours` into the five existing bar builders)
- Modify: `surveytool/desktop/app.py` (`post_crosstab`, `post_breaks_export` pass the new loader through)
- Modify: `surveytool/desktop/static/breaks.js` (complete Task 9 Step 3's placeholder)
- Test: `tests/test_breaks_export.py`, `tests/test_desktop_chart_style.py`

**Interfaces:**
- Consumes: `_load_response_colours_for_survey` (Task 4).
- Produces: `QuestionResult.response_colours: dict[str, str] = {}` (new field, label -> hex); `compute_breaks_crosstab(..., response_colours: dict[str, dict[str, str]] | None = None)` threads `(response_colours or {}).get(question.qid, {})` onto the matching result, mirroring how `chart_styles` is already threaded; `build_figure` resolves `question_result.response_colours` and passes it as `overrides=` to every `assign_series_colours` call the four bar builders already make (not `_table_figure`, which has no per-series colour).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_breaks_export.py`:

```python
def test_stacked_bar_100_figure_applies_response_colour_override():
    from surveytool.charts.plotly_renderer import build_figure
    from surveytool.core.chart_validity import ChartType

    qr = _question_result_with_permitted_charts()  # use whatever existing helper this file already has for a permitted QuestionResult fixture
    qr.response_colours = {"Strongly agree": "#FF00FF"}
    fig = build_figure(qr, ChartType.stacked_bar_100)
    agree_trace = next(t for t in fig.data if t.name == "Strongly agree")
    assert agree_trace.marker.color == "#FF00FF"
```

Adjust the fixture-construction call to whatever helper `test_breaks_export.py` already uses to build a permitted `QuestionResult` (check the file's Section A helpers from the earlier exploration — likely composes `_scale_points()`, `_ok_column(...)`, and a permission-attachment call; match that exactly rather than guessing a new helper name).

Add to `tests/test_desktop_chart_style.py`:

```python
def test_crosstab_picks_up_saved_response_colours(client):
    # Mirrors the existing test_crosstab_picks_up_saved_chart_style in this
    # file -- same upload/crosstab-request shape, checking response_colours
    # instead of chart_style.
    ...
```

Write this second test by copying the exact structure of the existing `test_crosstab_picks_up_saved_chart_style` test in the file (upload a real vendor fixture, `PUT` a chart-style with `response_colours` set, call `POST /api/session/{id}/crosstab`, assert the returned `QuestionResult.response_colours` matches) — do not invent a different upload/request shape.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_breaks_export.py -k response_colour_override tests/test_desktop_chart_style.py -k saved_response_colours -v`
Expected: FAIL — `QuestionResult` has no `response_colours` field yet.

- [ ] **Step 3: Add the field to `QuestionResult` and thread it through `compute_breaks_crosstab`**

In `surveytool/compute/breaks_compute.py`, add to `QuestionResult`:

```python
    response_colours: dict[str, str] = {}
    """Manual response colour override feature: the analyst's saved
    label -> hex map for this question, or {} if none saved. Purely a
    rendering hint threaded into plotly_renderer.build_figure's colour
    assignment -- never affects any computed figure, nets, or mean."""
```

Update `compute_breaks_crosstab`'s signature and body:

```python
def compute_breaks_crosstab(
    respondent_frame: pd.DataFrame,
    survey: Survey,
    break_spec: list[str],
    filter_spec: dict[str, list[str]],
    question_ids: list[str],
    registry: ResolvedRegistry,
    vendor: str,
    config: ToolConfig,
    display_orders: dict[str, list[str]] | None = None,
    chart_styles: dict[str, str] | None = None,
    response_colours: dict[str, dict[str, str]] | None = None,
) -> list[QuestionResult]:
```

Find the existing line building each `QuestionResult(...)` (near where `chart_style=(chart_styles or {}).get(question.qid)` is set, per the earlier exploration at line ~437) and add the sibling line:

```python
        chart_style=(chart_styles or {}).get(question.qid),
        response_colours=(response_colours or {}).get(question.qid, {}),
```

- [ ] **Step 4: Thread `response_colours` into `build_figure`'s bar builders**

In `surveytool/charts/plotly_renderer.py`, change every `assign_series_colours([...], palette=style.palette)` call inside `_stacked_bar_100_figure`, `_diverging_stacked_bar_figure`, `_grouped_bar_figure`, `_net_bar_figure` to:

```python
    colour_by_label = assign_series_colours(
        [point.label for point in question_result.scale_points],
        palette=style.palette,
        overrides=question_result.response_colours,
    )
```

(and the equivalent `[net_def.label for net_def in question_result.nets]` line in `_net_bar_figure`). `_table_figure` needs no change (uses `style.palette[0]` for the header only, no per-series colour).

- [ ] **Step 5: Thread the loader through `app.py`'s two call sites**

In `post_crosstab` and `post_breaks_export`, add `response_colours=_load_response_colours_for_survey(session.survey_id).get(...)` — actually, since `_load_response_colours_for_survey` already returns the full `qid -> {label: hex}` map (Task 4's shape), pass the whole map straight through, matching how `chart_styles=_load_chart_styles_for_survey(...)` is passed as a whole map already:

```python
    results = compute_breaks_crosstab(
        session.respondent_frame, session.survey, request.break_spec.dimensions,
        request.filter_spec.selections, question_ids, session.registry, session.vendor, config,
        display_orders=_load_display_orders_for_survey(session.survey_id),
        chart_styles=_load_chart_styles_for_survey(session.survey_id),
        response_colours=_load_response_colours_for_survey(session.survey_id),
    )
```

Apply this to both `post_crosstab` (question_ids variant) and `post_breaks_export` (`[request.question_id]` variant).

- [ ] **Step 6: Complete Task 9 Step 3's placeholder in `breaks.js`**

Replace the `colours: {}` placeholder from Task 9 Step 3 with the real field, now that `QuestionResult` carries it:

```javascript
renderLegend(legendContainer, {
  qid: qr.question_id,
  surveyId: breaksSurveyId,
  labels: qr.scale_points.map((sp) => sp.label),
  order: qr.scale_points.map((sp) => sp.label),
  colours: qr.response_colours || {},
  onChange: () => {
    const chartType = breaksActiveChartType[qr.question_id];
    renderChartArea(qr, block.querySelector(".breaks-chart-area"), chartType);
  },
});
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `python -m pytest tests/test_breaks_export.py tests/test_desktop_chart_style.py -v`
Expected: PASS, all tests including pre-existing ones (`response_colours` defaults to `{}` everywhere it's threaded, so every call site that doesn't pass it is unaffected).

- [ ] **Step 8: Run full suite**

Run: `python -m pytest -q`
Expected: `606 passed` → now `608 passed`, same `17 failed, 4 skipped`.

- [ ] **Step 9: Commit**

```bash
git add surveytool/compute/breaks_compute.py surveytool/charts/plotly_renderer.py surveytool/desktop/app.py surveytool/desktop/static/breaks.js tests/test_breaks_export.py tests/test_desktop_chart_style.py
git commit -m "feat: thread manual response colour overrides through Cross-tab's figures and legend"
```

---

### Task 11: Retire `renderer.py` and its matplotlib dependency

**Files:**
- Delete: `surveytool/charts/renderer.py`
- Modify: `surveytool/charts/__init__.py` (remove `render_charts`, which only `renderer.py`'s callers used, now that `export_charts` uses `render_charts_plotly`)
- Modify: `surveytool/charts/chart_data.py` (remove the `from surveytool.charts.renderer import _index_rows, _require_row` dependency — inline or relocate these two helpers)
- Modify: `tests/test_charts.py` (remove matplotlib-only assertions; keep/migrate data-shape assertions)
- Modify: `pyproject.toml`/`requirements*.txt` (remove `matplotlib` if nothing else in the codebase imports it — verify first)

**Interfaces:**
- Consumes: nothing new.
- Produces: `_index_rows`/`_require_row` relocated to `surveytool/charts/chart_data.py` itself (the only remaining caller) as module-private functions, same signatures as before.

- [ ] **Step 1: Confirm nothing else imports from `renderer.py` or matplotlib**

Run: `grep -rn "from surveytool.charts.renderer\|from surveytool.charts import.*render_charts\b\|import matplotlib" surveytool/ tests/`
Expected output: only `surveytool/charts/chart_data.py`'s `_index_rows`/`_require_row` import, `surveytool/charts/__init__.py`'s `render_charts` definition/re-export, and `tests/test_charts.py`'s test-only imports. If `app.py` or anything else still imports `render_charts`, stop and re-check Task 7 landed correctly before continuing — this task assumes it did.

- [ ] **Step 2: Move `_index_rows`/`_require_row` into `chart_data.py`**

Copy the two functions' bodies (from the earlier exploration: `_index_rows(rows) -> dict[tuple[str,str,str], FindingsRow]` and `_require_row(idx, breakdown_level, breakdown_variable, metric, qid) -> FindingsRow`) verbatim from `renderer.py` into `chart_data.py`, above `_dist_trace` (their sole caller). Remove the `from surveytool.charts.renderer import _index_rows, _require_row` import line and any now-unused imports it leaves behind in `chart_data.py`.

- [ ] **Step 3: Run `chart_data.py`'s tests to confirm the move didn't break anything**

Run: `python -m pytest tests/test_chart_data.py -v`
Expected: PASS, unchanged.

- [ ] **Step 4: Remove `render_charts` from `surveytool/charts/__init__.py`**

Delete the `render_charts` function definition and its `from surveytool.charts.manifest import write_manifest` / `from surveytool.charts.renderer import render_dist, render_means, render_xbreak` local imports inside it. Remove `"render_charts"` from `__all__`, leaving `__all__ = ["iter_chart_specs"]`. Keep `iter_chart_specs` and `_MeansSpec` — both are still the shared chart-selection source of truth `build_chart_data`/`render_charts_plotly` consume.

- [ ] **Step 5: Delete `renderer.py`**

```bash
git rm surveytool/charts/renderer.py
```

- [ ] **Step 6: Update `tests/test_charts.py`**

Remove every test that exercises matplotlib-specific behaviour no longer reachable (anything asserting on `.savefig`, `facecolor=_CREAM`, `_wrap_title`, `_compute_left_margin`, or calling `render_dist`/`render_xbreak`/`render_means`/`render_charts` directly) — per the earlier exploration, this includes tests like `test_dist_chart_real_labels_nonempty_png`, `test_xbreak_title_matches_breakdown_variable`, `test_render_charts_manifest_complete`, `test_nonsubstantive_codes_in_manifest_and_chart_renders`, `test_render_dist_scale_question_colours_unchanged_by_palette`, `test_render_dist_plain_categorical_gets_distinct_palette_colours`. Keep `test_missing_findings_row_raises` if it exercises `_dist_trace`/`_require_row` (now relocated into `chart_data.py`, not renderer-specific) — check each test's actual call target before deleting, since some of these names test `chart_data.py`'s data-shape logic (which survives) rather than `renderer.py`'s drawing (which doesn't). Any deleted matplotlib-specific coverage of "does the chart still contain the right data" is superseded by Task 6's new `build_legacy_figure` tests already added to this same file.

- [ ] **Step 7: Remove the `matplotlib` dependency if nothing else needs it**

Run: `grep -rn "^import matplotlib\|^from matplotlib" surveytool/ tests/`
Expected: no results (confirms nothing outside the now-deleted `renderer.py` used it). Then remove `matplotlib` from `pyproject.toml`'s dependency list (check the exact file — `pyproject.toml` or `requirements.txt`/`requirements-dev.txt`, whichever this repo uses) and run the environment's install command to confirm the app still starts without it (e.g. `pip install -e .` then launch the app per Task 8 Step 7's entry point).

- [ ] **Step 8: Run full suite**

Run: `python -m pytest -q`
Expected: `608 passed` minus however many matplotlib-only tests were deleted in Step 6, same `17 failed, 4 skipped` — record the new exact passed count here once run, since this is the last task to change that number before Item D.

- [ ] **Step 9: Commit**

```bash
git add -A surveytool/charts tests/test_charts.py pyproject.toml
git commit -m "chore: retire the matplotlib chart renderer, now fully superseded by the Plotly path"
```

---

### Task 12: Cross-tab bulk PNG export — endpoint

**Files:**
- Modify: `surveytool/core/breaks_models.py` (new request model)
- Modify: `surveytool/desktop/app.py` (new endpoint)
- Test: `tests/test_breaks_export.py`

**Interfaces:**
- Consumes: `build_figure`, `rasterize` (unchanged), `compute_breaks_crosstab`, `attach_chart_permissions` (unchanged), `_load_display_orders_for_survey`, `_load_chart_styles_for_survey`, `_load_response_colours_for_survey`.
- Produces: `BulkExportRequest(break_spec: BreakSpec, filter_spec: FilterSpec = FilterSpec(), chart_type: ChartType, question_ids: list[str])` in `surveytool/core/breaks_models.py`; `POST /api/session/{session_id}/breaks-export-bulk` returning `{"exported": [{"question_id": str, "filename": str}], "out_dir": str}` — unlike single-chart `/breaks-export` (which streams one `FileResponse`), the bulk route writes files to a server-chosen-or-caller-given directory and returns a manifest, matching the legacy Charts tab's existing `/export` bulk-response shape (`{"exported": [...], "out_dir": ...}`) for UI consistency.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_breaks_export.py` (a new endpoint-level test; check whether this file or `tests/test_desktop_breaks_api.py` is where endpoint tests for `/breaks-export` actually live per the file's own docstring at the top — the earlier exploration noted Section C endpoint tests live in `test_desktop_breaks_api.py`, not this file, so add it there instead if that file exists):

```python
def test_breaks_export_bulk_writes_one_png_per_question_id(client, tmp_path):
    if not RAKUTEN_PATH.exists():
        pytest.skip(f"{RAKUTEN_PATH.name} not found in project root")

    session_id = _upload(client)  # match this file's existing upload helper
    out_dir = tmp_path / "bulk"

    response = client.post(
        f"/api/session/{session_id}/breaks-export-bulk",
        json={
            "break_spec": {"dimensions": []},
            "filter_spec": {"selections": {}},
            "chart_type": "table",
            "question_ids": ["Q1", "Q2"],
            "out_dir": str(out_dir),
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert {e["question_id"] for e in body["exported"]} == {"Q1", "Q2"}
    for entry in body["exported"]:
        assert (out_dir / entry["filename"]).exists()
        assert (out_dir / entry["filename"]).stat().st_size > 0
```

Adjust `break_spec`/`filter_spec` request-body shapes and the `_upload` helper call to match whatever `BreakSpec`/`FilterSpec` and upload fixture this test file (or `test_desktop_breaks_api.py`, whichever is correct) already establishes elsewhere — copy an existing `/breaks-export` or `/crosstab` test's exact request body shape rather than guessing field names.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_breaks_export.py -k breaks_export_bulk -v` (or the correct file from Step 1)
Expected: FAIL — `404 Not Found`, route doesn't exist yet.

- [ ] **Step 3: Add `BulkExportRequest` to `breaks_models.py`**

```python
class BulkExportRequest(BaseModel):
    """POST .../breaks-export-bulk body. Unlike ExportRequest (single
    question_id, streamed FileResponse), this accepts a list and writes to
    out_dir, returning a manifest -- matching the legacy Charts tab's
    existing bulk /export response shape for UI consistency (Item D)."""

    break_spec: BreakSpec
    filter_spec: FilterSpec = Field(default_factory=FilterSpec)
    chart_type: ChartType
    question_ids: list[str]
    out_dir: str
```

- [ ] **Step 4: Add the endpoint to `app.py`**

Place it directly after `post_breaks_export`:

```python
@app.post("/api/session/{session_id}/breaks-export-bulk")
async def post_breaks_export_bulk(session_id: str, request: BulkExportRequest):
    """Export every question_id in `request.question_ids` as a PNG, for the
    same break/filter/chart_type combination, into `request.out_dir` --
    the Cross-tab equivalent of the legacy Charts tab's existing bulk
    /export (Item D). No new rendering logic: loops build_figure/rasterize
    per question_id, exactly what /breaks-export already does per-call.
    """
    session = _require_session(session_id)
    config = _default_config()

    validate_request(
        request.break_spec, request.filter_spec, session.registry,
        session.survey, session.vendor, session.respondent_frame,
    )

    results = compute_breaks_crosstab(
        session.respondent_frame, session.survey, request.break_spec.dimensions,
        request.filter_spec.selections, request.question_ids, session.registry,
        session.vendor, config,
        display_orders=_load_display_orders_for_survey(session.survey_id),
        chart_styles=_load_chart_styles_for_survey(session.survey_id),
        response_colours=_load_response_colours_for_survey(session.survey_id),
    )
    results = attach_chart_permissions(results, config)

    out_dir = Path(request.out_dir)
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise SurveyToolError(
            ErrorCode.INTERNAL,
            "The export could not be saved to the chosen location.",
            detail=str(exc),
            next_action="Choose a different export location and try again.",
        ) from exc

    exported = []
    for question_result in results:
        fig = build_figure(
            question_result, request.chart_type,
            break_spec=request.break_spec.dimensions,
            filter_spec=request.filter_spec.selections,
        )
        filename = f"{question_result.question_id}-{request.chart_type.value}.png"
        rasterize(fig, out_dir / filename)
        exported.append({"question_id": question_result.question_id, "filename": filename})

    return {"exported": exported, "out_dir": request.out_dir}
```

Add `BulkExportRequest` to the existing `from surveytool.core.breaks_models import (...)` import block at the top of `app.py`.

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_breaks_export.py -k breaks_export_bulk -v` (or wherever Step 1 actually placed it)
Expected: PASS.

- [ ] **Step 6: Run full suite**

Run: `python -m pytest -q`
Expected: previous count → +1, same `17 failed, 4 skipped`.

- [ ] **Step 7: Commit**

```bash
git add surveytool/core/breaks_models.py surveytool/desktop/app.py tests/test_breaks_export.py
git commit -m "feat: add Cross-tab bulk PNG export endpoint"
```

---

### Task 13: Cross-tab bulk PNG export — UI button

**Files:**
- Modify: `surveytool/desktop/static/index.html` (add the button markup)
- Modify: `surveytool/desktop/static/breaks.js` (wire the click handler)
- No new automated test — this is a thin UI wrapper around Task 12's already-tested endpoint; verified via manual smoke test, consistent with how the existing single-chart export button has no JS-level test either.

**Interfaces:**
- Consumes: `POST /api/session/{id}/breaks-export-bulk` (Task 12), `ensureExportDir()` (existing, `index.html`), `breaksLatestResults`, `breaksActiveChartType`, `breaksSessionId`, `currentBreakSpec()`, `currentFilterSpec()` (all existing `breaks.js` globals/functions), `GET /api/session/{id}/demographics` (existing — used to enumerate every base-eligible, non-demographic question for the "export all" set, since `breaksLatestResults` holds only the currently-selected question).

- [ ] **Step 1: Add the button markup**

In `surveytool/desktop/static/index.html`, in the `#breaks-export-row` div (currently containing only `#breaks-export-btn` and `#breaks-export-status`), add a sibling button:

```html
      <div id="breaks-export-row" style="display:none;">
        <button type="button" class="btn btn-secondary btn-small" id="breaks-export-btn">Export current chart</button>
        <button type="button" class="btn btn-secondary btn-small" id="breaks-export-bulk-btn">Export all as PNGs</button>
        <span class="status-body" id="breaks-export-status"></span>
      </div>
```

- [ ] **Step 2: Wire the click handler in `breaks.js`**

Add directly after the existing `breaks-export-btn` click handler (near line 1120+ per the earlier exploration). "Export all" means every base-eligible, non-demographic question in the survey (the same set `/demographics` already reports, and the same set the legacy Charts tab's bulk export covers) — not just the single question `breaksLatestResults` currently holds, since the button's purpose is exporting everything, not re-exporting the one chart already covered by "Export current chart":

```javascript
document.getElementById("breaks-export-bulk-btn").addEventListener("click", async () => {
  if (!breaksLatestResults || breaksLatestResults.length === 0) return;
  const statusEl = document.getElementById("breaks-export-status");
  const outDir = await ensureExportDir();
  if (!outDir) {
    statusEl.className = "status-body error";
    statusEl.textContent = "Choose an export folder first.";
    return;
  }

  const chartType = breaksActiveChartType[breaksLatestResults[0].question_id];

  statusEl.className = "status-body";
  statusEl.textContent = "Exporting…";

  // "Export all" = every base-eligible, non-demographic question in the
  // survey (matching the legacy Charts tab's bulk export, which exports
  // every chart currently computed for the session, not just the one
  // question on screen) -- not breaksLatestResults, which today holds only
  // the single currently-selected question. All are exported at the
  // currently-selected chart type and break/filter combination.
  let response;
  try {
    response = await fetch(`/api/session/${breaksSessionId}/demographics`);
  } catch {
    statusEl.className = "status-body error";
    statusEl.textContent = "Could not reach the local server.";
    return;
  }
  const demographicsBody = await parseJsonResponse(response);
  if (!response.ok) {
    statusEl.className = "status-body error";
    statusEl.textContent = errorFromBody(demographicsBody).message;
    return;
  }
  const questionIds = demographicsBody.questions.map((q) => q.qid);

  try {
    response = await fetch(`/api/session/${breaksSessionId}/breaks-export-bulk`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        break_spec: currentBreakSpec(),
        filter_spec: currentFilterSpec(),
        chart_type: chartType,
        question_ids: questionIds,
        out_dir: outDir,
      }),
    });
  } catch {
    statusEl.className = "status-body error";
    statusEl.textContent = "Could not reach the local server.";
    return;
  }

  const body = await parseJsonResponse(response);
  if (!response.ok) {
    statusEl.className = "status-body error";
    statusEl.textContent = errorFromBody(body).message;
    return;
  }

  statusEl.className = "status-body success";
  statusEl.textContent = `Exported ${body.exported.length} PNG(s) to ${body.out_dir}`;
});
```

- [ ] **Step 3: Manual smoke test**

Launch the desktop app, open Cross-tab, select a question and break/filter, click "Export all as PNGs", confirm a folder-picker prompt (if no folder chosen yet) then a success status line, and confirm the PNG(s) land in the chosen folder — one per base-eligible question in the survey, not just the currently-selected one.

- [ ] **Step 4: Run full suite (no Python changes)**

Run: `python -m pytest -q`
Expected: unchanged from Task 12's final count.

- [ ] **Step 5: Commit**

```bash
git add surveytool/desktop/static/index.html surveytool/desktop/static/breaks.js
git commit -m "feat: add Export all as PNGs button to Cross-tab"
```

---

### Task 14: Item F — QA gate (manual verification, not a code task)

Not a build task — run this checklist after Tasks 1–13 are all merged, before release. Record results (pass/fail per vendor per line) in the PR description or a release note, not as a new permanent test file (per the spec's explicit "not a new ongoing test infrastructure commitment").

- [ ] For each onboarded vendor's real sample dataset (Rakuten, Milieu, Toluna, PureSpectrum — whichever have real fixture files checked into the repo root per the existing `tests/test_desktop_charts.py` conventions), upload it and open the Charts tab: confirm the on-screen chart visually matches its exported PNG (same colours, same orientation, same labels, same wrapping).
- [ ] Manually reorder one question's response options via the new legend panel; confirm the new order shows in Charts tab, Cross-tab, and both PNG exports for that question.
- [ ] Manually recolour one response option via the legend's colour swatch; confirm the colour shows in all four surfaces, and that every other (unset) response option still gets a sensible hash-derived colour alongside it.
- [ ] Find or construct a question with a long response label; confirm it wraps (not truncates/overlaps) on-screen in both tabs and in both export paths.
- [ ] Run Cross-tab's single-chart export and new bulk export for a multi-question, multi-break-by survey; confirm both produce correct, complete PNGs.
- [ ] Run the full suite once more (`python -m pytest -q`) and confirm the passed count has only grown relative to this plan's baseline, the 17 pre-existing PureSpectrum-related failures are unchanged in identity (same test names), and nothing in `tests/test_breaks_conformance.py`/`tests/test_breaks_invariants.py` regressed.

If any line fails, file it as a follow-up bug rather than blocking this plan's already-merged tasks — Item F is a release gate on the feature as a whole, not a blocker on any individual task's own commit.
