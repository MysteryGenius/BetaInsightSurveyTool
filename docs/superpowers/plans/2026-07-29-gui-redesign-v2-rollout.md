# GUI Redesign v2 Rollout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply the approved "redesign v2" visual system (`surveytool-redesign-v2.html`) to the real desktop app (`surveytool/desktop/static/index.html` and `charts.js`), and add the two structural pieces the mockup showed that don't exist yet: staged pipeline progress during upload, and an enriched provenance strip with a "Load a different file" reset.

**Architecture:** Two static files, no build step. `index.html` carries all CSS tokens/components and the upload/tab/reset JS inline (matches the file's existing all-in-one pattern — do not split it into separate CSS/JS files, that's an unrelated restructuring this task doesn't need). `charts.js` owns anything Plotly renders, because Plotly draws to canvas/SVG and cannot read CSS custom properties — its `CHART_COLORS` object is the single source of truth for chart colors and must be manually kept in sync with `index.html`'s `:root` tokens (this constraint already exists in the codebase, see the comment at `charts.js:66-68`).

**Tech Stack:** Plain HTML/CSS/vanilla JS, FastAPI backend (untouched), Plotly.js (vendored locally, untouched).

## Global Constraints

- No changes to `app.py`, error taxonomy, or any Python code in this plan — GUI files only.
- No changes to API contracts, request/response shapes, or endpoint behavior.
- Significance stays inert and renders as plain static text — never a disabled/hidden control (build plan section 5/F). The current markup already does this correctly (`index.html:533-536`) and must not regress.
- Copy rules from `gui-fix-pass-build-plan.md` section 5 apply to any new/changed user-facing text: past tense, name the cause, one next action, no apologies, sentence case, no exclamation marks. Banned words: exception, traceback, stack, parser, adapter, schema, null, NaN, index, module, code paths.
- Staged pipeline progress is **client-side simulated** (confirmed with user) — it must never contradict the real result. If the real fetch resolves before the simulated steps finish, jump immediately to the final state. If the real fetch is still pending after the simulated sequence completes, hold at the last active step (spinner still animating) rather than looping or fabricating a 5th step.
- "Load a different file" is a pure client-side reset — there is no session-teardown endpoint (confirmed: `app.py` only ever adds to `_SESSIONS`, never removes). Do not attempt to call a delete/teardown API that does not exist.
- Existing per-chart export (`exportSingleChart` in `charts.js:255-283`) and bulk export already work correctly — this plan only re-themes their visual output, it does not touch their request logic.
- Cross-tab status vocabulary from the real API is exactly `"ok"`, `"grey"`, `"suppressed"` (`charts.js:216-224`, matching `compute/cross_tab.py`'s `CellStatus`) — not "warn". Any new copy/markup must use this vocabulary, correcting the mockup's incorrect use of "warn".

---

## File Map

| File | Responsibility |
|---|---|
| `surveytool/desktop/static/index.html` | `:root` design tokens, all component CSS, static markup for provenance strip + staged-progress steps, inline JS for upload flow / stage simulation / reset action |
| `surveytool/desktop/static/charts.js` | `CHART_COLORS` constant (re-themed only — no logic changes) |

---

## Task 1: Replace design tokens and component CSS with the v2 system

**Files:**
- Modify: `surveytool/desktop/static/index.html:7-429` (the entire `<style>` block)

**Interfaces:**
- Produces: CSS custom properties `--ink`, `--ink-soft`, `--ink-faint`, `--paper` (replaces `--surface-sunken` as the page background), `--panel` (replaces `--surface`), `--line` (replaces `--border`), `--line-strong` (replaces `--border-strong`), `--accent` (`#3d5a85`, replaces `#2f5fb3`), `--accent-hover`, `--accent-soft`, `--accent-soft-line`, `--good`, `--good-bg`, `--warn`, `--warn-bg`, `--muted`, `--muted-bg`, `--danger` (replaces `--error`), `--danger-bg` (replaces `--error-bg`), `--danger-line`. Existing component class names (`.btn`, `.card`, `.field`, `#dropzone`, `.status-box`, `.chip`, etc.) are preserved so Task 4/5's JS (which toggles these classes) does not need to change.
- Consumes: nothing (first task).

- [ ] **Step 1: Replace the `:root` token block**

Replace `index.html:7-43` with the v2 token set (values taken directly from the approved, contrast-corrected `surveytool-redesign-v2.html`):

```css
  :root {
    /* ---- design tokens (v2) ---- */
    --ink: #14181f;
    --ink-soft: #5b6270;
    --ink-faint: #656c79;
    --paper: #f6f6f4;
    --panel: #ffffff;
    --line: #e2e3e0;
    --line-strong: #c7c9c5;

    /* brand: swap this one value when brand assets exist. logo slot is in the top bar. */
    --accent: #3d5a85;
    --accent-hover: #324a6d;
    --accent-soft: #eef1f4;
    --accent-soft-line: #cdd7e1;

    --good: #177349;
    --good-bg: #eaf6f0;
    --warn: #9a6b00;
    --warn-bg: #fbf3e0;
    --muted: #6f6f66;
    --muted-bg: #eeeeec;

    --danger: #b3402f;
    --danger-bg: #fbeeec;
    --danger-line: #e3b3a9;

    --font-ui: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
    --font-num: "Inter", ui-monospace, "SF Mono", "Cascadia Mono", monospace;

    --space-1: 4px;
    --space-2: 8px;
    --space-3: 12px;
    --space-4: 16px;
    --space-5: 24px;
    --space-6: 32px;

    --radius-sm: 4px;
    --radius-md: 6px;

    --text-xs: 11.5px;
    --text-sm: 13px;
    --text-base: 14.5px;
    --text-lg: 18px;
    --text-xl: 24px;
  }
```

- [ ] **Step 2: Update every selector that referenced a renamed token**

Search-and-replace across the whole `<style>` block (`index.html:45-429`):

| Old token | New token |
|---|---|
| `var(--surface)` | `var(--panel)` |
| `var(--surface-sunken)` | `var(--paper)` |
| `var(--surface-shell)` | `var(--paper)` |
| `var(--border)` | `var(--line)` |
| `var(--border-strong)` | `var(--line-strong)` |
| `var(--error)` | `var(--danger)` |
| `var(--error-bg)` | `var(--danger-bg)` |
| `var(--ok)` | `var(--accent)` |
| `var(--grey-cell)` | `var(--muted)` |
| `var(--suppressed-cell)` | `var(--muted-bg)` |

Note: `--success` / `--success-bg` (used only by `.status-box.success`) map to the new `--good` / `--good-bg` — replace those two references too.

- [ ] **Step 3: Restyle `.card`, `.btn`, `.field`, `#dropzone`, `.status-box`, `.chip`, `.legend-tick` for the v2 look**

These class names stay identical (so the JS in Task 4 doesn't need changes) but their declarations change to match the mockup's calmer, less boxy system: `border-radius: var(--radius-md)` on cards (was a flatter 6px already — keep numeric value the same, just confirm it now reads from `--radius-md`), buttons get the softer hover/active states from the mockup (`background: var(--accent-hover)` on hover, no `filter: brightness()` trick — replace the existing `.btn:hover { filter: brightness(1.08); }` / `.btn:active { filter: brightness(0.95); }` rules with explicit color swaps):

```css
  .btn {
    appearance: none;
    border: 1px solid var(--accent);
    background: var(--accent);
    color: var(--panel);
    font-family: var(--font-ui);
    font-size: var(--text-base);
    padding: var(--space-2) var(--space-4);
    border-radius: var(--radius-sm);
    cursor: pointer;
    transition: background 100ms ease, border-color 100ms ease;
  }
  .btn:hover { background: var(--accent-hover); border-color: var(--accent-hover); }
  .btn:active { background: #16309e; } /* placeholder replaced below */
```

Replace the placeholder active color with a darker step of `--accent-hover` consistent with the mockup: use `#28374d` (a further-darkened `#324a6d`) for `.btn:active`.

- [ ] **Step 4: Manually verify no `--surface`/`--border`/`--error`/`--ok`/`--grey-cell`/`--suppressed-cell`/`--success` references remain**

Run: `grep -n "var(--surface\b\|var(--border\b\|var(--error\|var(--ok)\|var(--grey-cell)\|var(--suppressed-cell)\|var(--success" surveytool/desktop/static/index.html`
Expected: no output (all references migrated in Step 2).

- [ ] **Step 5: Open the app in a browser and visually confirm the upload card, buttons, and status boxes render with the new palette**

Run: `cd surveytool/desktop && python -m http.server 8010 --directory static` (or run the app's normal launch command if one exists), open `http://localhost:8010/`, confirm the page loads with the warm-neutral background and slate-blue accent button, no console errors.

- [ ] **Step 6: Commit**

```bash
git add surveytool/desktop/static/index.html
git commit -m "style: replace GUI design tokens with the approved redesign v2 palette"
```

---

## Task 2: Re-theme Plotly chart colors in charts.js

**Files:**
- Modify: `surveytool/desktop/static/charts.js:69-77` (the `CHART_COLORS` constant)

**Interfaces:**
- Consumes: nothing new — `CHART_COLORS` is read by `chartTraceAndLayout()` (line 98) and `crossTabTraceAndLayout()` (line 213), both unchanged in this task.
- Produces: `CHART_COLORS.ink`, `.inkSoft`, `.border`, `.accent`, `.ok`, `.grey`, `.suppressed` — same property names, new values, so no call site changes.

- [ ] **Step 1: Replace the `CHART_COLORS` values**

```javascript
const CHART_COLORS = {
  ink: "#14181f",
  inkSoft: "#5b6270",
  border: "#e2e3e0",
  accent: "#3d5a85",
  ok: "#3d5a85",
  grey: "#8a8a83",
  suppressed: "#e2e3e0",
};
```

Note: `grey` (used for the cross-tab "below threshold" bars) is kept slightly lighter than the CSS `--muted` token (`#6f6f66`) because Plotly bar fills read darker as large flat shapes than the same hex does as small text — this mirrors the reasoning already applied when tuning `--accent` for chart bars in the approved mockup. If this reads too light once rendered against a real cross-tab, darken to `#78786f` (still ≥4.1:1 against white, matching the mockup's contrast-corrected `--muted` intermediate value) rather than reusing `--accent`.

- [ ] **Step 2: Update the code comment above `CHART_TEMPLATE_LAYOUT` referencing the font family**

`charts.js:80` currently hardcodes `font: { family: '"Segoe UI", system-ui, sans-serif', ... }`. Change to match the new `--font-ui` stack:

```javascript
const CHART_TEMPLATE_LAYOUT = {
  font: { family: '"Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif', color: CHART_COLORS.ink, size: 13 },
  paper_bgcolor: "#ffffff",
  plot_bgcolor: "#ffffff",
  xaxis: { gridcolor: CHART_COLORS.border, zerolinecolor: CHART_COLORS.border },
  yaxis: { gridcolor: CHART_COLORS.border, zerolinecolor: CHART_COLORS.border },
  colorway: [CHART_COLORS.accent, CHART_COLORS.inkSoft],
};
```

- [ ] **Step 3: Load a real session and visually confirm chart colors**

Using a real vendor file (per the build plan's "no synthetic fixtures" rule — reuse one of the repo's real sample files, e.g. `milieu_survey_coe_data.csv` at the project root), run the full app, upload the file, and confirm the distribution/xbreak/means charts render in the new slate-blue, and the cross-tab chart shows `ok` bars in slate-blue, `grey` (below-threshold) bars visibly muted, and `suppressed` bars with the diagonal pattern fill in the new muted-line color.

- [ ] **Step 4: Commit**

```bash
git add surveytool/desktop/static/charts.js
git commit -m "style: re-theme Plotly chart colors to match redesign v2"
```

---

## Task 3: Enrich the provenance strip (source filename, load time, reset action)

**Files:**
- Modify: `surveytool/desktop/static/index.html:87-113` (CSS for `#session-summary`)
- Modify: `surveytool/desktop/static/index.html:438-455` (markup for `#session-summary`)
- Modify: `surveytool/desktop/static/index.html:567, 754-833` (JS: element refs and the `uploadFile` success branch)

**Interfaces:**
- Consumes: `body.session_id`, `vendor`, `surveyId`, `body.n_raw`, `body.n_analysis`, `body.question_count` — all already available in the existing `uploadFile()` success branch (`index.html:797-822`), no API changes.
- Produces: a new `resetToUpload()` function callable by the "Load a different file" button; new DOM ids `summary-source` and a `<button id="summary-reset-btn">` element.

- [ ] **Step 1: Add `prov-source` styling and the two new stat cells + reset button to the CSS**

Add after the existing `#session-summary .stat-value` rule (`index.html:109-112`):

```css
  #session-summary .stat-source {
    flex: 1 1 auto;
    min-width: 200px;
  }
  #session-summary .stat-source .stat-value { color: var(--ink-soft); }
```

- [ ] **Step 2: Add the source/load-time stat and reset button to the markup**

Replace `index.html:438-455` with:

```html
<div id="session-summary">
  <div class="stat">
    <span class="stat-label">Vendor</span>
    <span class="stat-value" id="summary-vendor"></span>
  </div>
  <div class="stat">
    <span class="stat-label">Survey ID</span>
    <span class="stat-value" id="summary-survey-id"></span>
  </div>
  <div class="stat">
    <span class="stat-label">Respondents</span>
    <span class="stat-value num" id="summary-respondents"></span>
  </div>
  <div class="stat">
    <span class="stat-label">Questions</span>
    <span class="stat-value num" id="summary-questions"></span>
  </div>
  <div class="stat stat-source">
    <span class="stat-label">Source</span>
    <span class="stat-value" id="summary-source"></span>
  </div>
  <button type="button" class="btn btn-secondary btn-small" id="summary-reset-btn">Load a different file</button>
</div>
```

- [ ] **Step 3: Add a relative-time helper and wire the new fields in the upload success branch**

Add this helper function near the top of the `<script>` block, after the existing `const` declarations (after `index.html:571`, before `let currentSessionId = null;`):

```javascript
// Formats a load timestamp as a short relative string ("loaded just now",
// "loaded 3 min ago"). Re-evaluated fresh each time it's read, not live —
// the strip doesn't need a ticking clock, just an accurate value at a
// glance.
function formatLoadedAgo(loadedAtMs) {
  const deltaMin = Math.round((Date.now() - loadedAtMs) / 60000);
  if (deltaMin < 1) return "loaded just now";
  if (deltaMin === 1) return "loaded 1 min ago";
  return `loaded ${deltaMin} min ago`;
}

let currentFileName = null;
let currentLoadedAtMs = null;
```

- [ ] **Step 4: Capture the filename and load time, and render the source stat, in the upload success branch**

In `uploadFile(file)` (`index.html:754`), immediately after `showUploadWorking();` add:

```javascript
  currentFileName = file.name;
```

Then in the success branch, after the existing line `document.getElementById("summary-questions").textContent = body.question_count;` (`index.html:821`), add:

```javascript
  currentLoadedAtMs = Date.now();
  document.getElementById("summary-source").textContent =
    `${currentFileName} · ${formatLoadedAgo(currentLoadedAtMs)}`;
```

- [ ] **Step 5: Write the reset function and wire the button**

Add this function after `activateTab()` (after `index.html:699`, the closing brace of `activateTab`):

```javascript
// Client-side-only reset: there is no session-teardown endpoint (the
// backend just accumulates sessions in memory), so "loading a different
// file" means returning the UI to the empty upload state and discarding
// our reference to the old session — the old session object is simply
// never read again.
function resetToUpload() {
  currentSessionId = null;
  currentFileName = null;
  currentLoadedAtMs = null;

  sessionSummary.style.display = "none";
  tabNav.style.display = "none";
  exportRow.style.display = "none";
  chartsContainer.innerHTML = "";
  crosstabResult.innerHTML = "";
  ctQuestionSelect.innerHTML = "";
  ctDemographicSelect.innerHTML = "";

  resultBox.className = "status-box";
  resultTitle.textContent = "";
  resultBody.textContent = "";
  warningsNotice.className = "";
  warningsNotice.innerHTML = "";

  document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
  document.getElementById("upload-view").classList.add("active");
}

document.getElementById("summary-reset-btn").addEventListener("click", resetToUpload);
```

Note: `ctQuestionSelect`, `ctDemographicSelect`, and `crosstabResult` are already declared as consts later in the file (`index.html:835-837`, after `const chartsContainer = ...` at line 559) — since this plan adds `resetToUpload()` textually before those declarations but function bodies aren't executed until called (well after full-script parse), this is safe. If Task 3 Step 5's function is placed before those `const` lines are read at runtime it would throw a temporal-dead-zone error; confirm by re-reading the final file that `resetToUpload()`'s body is not invoked until after line 846 (`ctQuestionSelect.addEventListener(...)`) has executed, which it is since it only runs on a click.

- [ ] **Step 6: Manually verify the reset flow**

Run the app, upload a real file, confirm the provenance strip shows `filename · loaded just now`, click "Load a different file", confirm the app returns to the empty upload card with vendor/survey-id fields intact and no leftover charts/cross-tab content, then upload again to confirm a second session loads cleanly.

- [ ] **Step 7: Commit**

```bash
git add surveytool/desktop/static/index.html
git commit -m "feat: add source/load-time provenance and a load-a-different-file reset action"
```

---

## Task 4: Staged pipeline progress during upload

**Files:**
- Modify: `surveytool/desktop/static/index.html:230-270` (CSS: replace/extend the `.status-box` "Working" state with a stage-list component)
- Modify: `surveytool/desktop/static/index.html:488-494` (markup: add a stage-list container inside `#result`)
- Modify: `surveytool/desktop/static/index.html:716-756` (JS: `showUploadWorking()` and the surrounding upload flow)

**Interfaces:**
- Consumes: nothing new from the API — this is purely a client-side perceived-progress UI layered over the existing single `/api/upload` request.
- Produces: `startStageSimulation()` / `stopStageSimulation(finalState)` functions; a `#stage-list` DOM element with 4 `.stage` children.

- [ ] **Step 1: Add stage-list CSS**

Add after the existing `.status-box .status-dismiss` rule (`index.html:258-269`):

```css
  /* ---- staged pipeline progress (client-side simulated) ---- */
  #stage-list { display: none; flex-direction: column; margin-top: var(--space-2); }
  #stage-list.visible { display: flex; }
  .stage {
    display: flex;
    align-items: flex-start;
    gap: var(--space-3);
    padding: var(--space-2) 0;
  }
  .stage-marker {
    flex: none;
    width: 20px;
    height: 20px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    margin-top: 1px;
    font-size: 11px;
  }
  .stage.done .stage-marker { background: var(--good); color: var(--panel); }
  .stage.active .stage-marker {
    border: 2px solid var(--accent);
    background: var(--accent-soft);
    animation: stage-pulse 1.5s ease-in-out infinite;
  }
  .stage.pending .stage-marker { border: 2px solid var(--line-strong); }
  @keyframes stage-pulse {
    0%, 100% { box-shadow: 0 0 0 0 var(--accent-soft-line); }
    50% { box-shadow: 0 0 0 4px transparent; }
  }
  .stage-label { font-size: var(--text-sm); padding-top: 1px; }
  .stage.pending .stage-label { color: var(--ink-faint); }
  @media (prefers-reduced-motion: reduce) {
    .stage.active .stage-marker { animation: none; }
  }
```

- [ ] **Step 2: Add the stage-list markup**

Inside `#result` (`index.html:488-494`), after the existing `<div id="result-box" ...>` block's closing `</div>` and before the outer `</div>` that closes `#result`, add:

```html
      <div id="stage-list">
        <div class="stage" data-stage="0"><div class="stage-marker"></div><div class="stage-label">Reading file</div></div>
        <div class="stage" data-stage="1"><div class="stage-marker"></div><div class="stage-label">Detecting scale labels</div></div>
        <div class="stage" data-stage="2"><div class="stage-marker"></div><div class="stage-label">Excluding low-quality respondents</div></div>
        <div class="stage" data-stage="3"><div class="stage-marker"></div><div class="stage-label">Building findings sheet</div></div>
      </div>
```

- [ ] **Step 3: Write the stage simulation functions**

Add near the top of the `<script>` block, after the `formatLoadedAgo` helper added in Task 3 Step 3:

```javascript
const stageListEl = document.getElementById("stage-list");
const STAGE_ADVANCE_MS = 650;
let stageTimerId = null;
let stageIndex = -1;

function setStageClasses() {
  stageListEl.querySelectorAll(".stage").forEach((el) => {
    const i = Number(el.dataset.stage);
    el.classList.remove("done", "active", "pending");
    if (i < stageIndex) el.classList.add("done");
    else if (i === stageIndex) el.classList.add("active");
    else el.classList.add("pending");
  });
}

// Advances a client-side-only progress illusion while the single real
// /api/upload request is in flight. Never claims a step is done unless the
// simulation reached it — if the real response returns first,
// stopStageSimulation jumps straight to the true outcome instead of letting
// a stale "in progress" step linger.
function startStageSimulation() {
  stageIndex = 0;
  stageListEl.classList.add("visible");
  setStageClasses();
  stageTimerId = setInterval(() => {
    if (stageIndex < 3) {
      stageIndex += 1;
      setStageClasses();
    } else {
      clearInterval(stageTimerId);
      stageTimerId = null;
    }
  }, STAGE_ADVANCE_MS);
}

function stopStageSimulation() {
  if (stageTimerId !== null) {
    clearInterval(stageTimerId);
    stageTimerId = null;
  }
  stageListEl.classList.remove("visible");
  stageIndex = -1;
}
```

- [ ] **Step 4: Call the simulation from the upload flow**

In `showUploadWorking()` (`index.html:718-725`), add a call to `startStageSimulation()` at the end of the function body.

In `uploadFile(file)`, call `stopStageSimulation()` at the start of every exit path that currently exists: immediately before each `showUploadError(...)` call in the abort/network-failure catch block (`index.html:775-793`), immediately before `showUploadError(errorFromBody(body))` on a non-ok response (`index.html:798-801`), and immediately before the success branch's `setStatusBox(...)` call (`index.html:803`). Concretely, each of those three call sites gets one new line, `stopStageSimulation();`, directly above it.

- [ ] **Step 5: Manually verify the staged sequence**

Run the app, upload a real file, and confirm the 4 named steps light up in sequence (done → active → pending) while the request is in flight, then confirm the stage list disappears once the result renders (success case) — repeat with a deliberately mismatched vendor (e.g. a real Milieu file with Rakuten selected) to confirm the stage list also disappears cleanly on the error path and the error message renders normally underneath.

- [ ] **Step 6: Commit**

```bash
git add surveytool/desktop/static/index.html
git commit -m "feat: add client-side staged pipeline progress during upload"
```

---

## Task 5: Full walkthrough against the build plan's real-file verification cases

**Files:** none (verification only)

**Interfaces:** none

- [ ] **Step 1: Re-run the build plan's verification table (section 9) end to end against the redesigned GUI**

Using real files already in the repo root (`milieu_survey_coe_data.csv`, `rakuten_survey_chn_clans_data.xlsx`, `rakuten_survey_support_measures_data.xlsx`, `toluna_survey_misinformation_data.xlsx`):
- Vendor mismatch: pick Rakuten with a real Milieu file selected → confirm the stage list clears, a plain-English `VENDOR_MISMATCH` message renders in the new danger-colored status box, "Try again"/dismiss both work.
- Happy path per vendor: confirm charts render in the new palette with no extra clicks, provenance strip shows filename + "loaded just now", cross-tab pickers populate.
- Per-chart export: export one chart, confirm the file opens and the success message renders in the new status-box styling.
- Load a different file: from a loaded session, click the reset button, confirm a clean return to the empty state, then load a second real file successfully.

- [ ] **Step 2: Confirm no regressions in copy or accessibility**

Run: `grep -niE "exception|traceback|\bstack\b|\bparser\b|\badapter\b|\bschema\b|\bnull\b|\bnan\b|\bmodule\b" surveytool/desktop/static/index.html surveytool/desktop/static/charts.js`
Expected: no matches in user-facing string literals (matches inside code/comments referring to internals are fine — only strings rendered to the user matter; inspect any hits by hand).

Confirm no hidden/disabled interactive controls exist: `grep -n "disabled\|display:\s*none\|hidden" surveytool/desktop/static/index.html` and manually confirm every match is either (a) a state class intentionally toggled by JS (e.g. `.view` panels, `#session-summary` before load) or (b) the significance note, which must remain plain static text with no `disabled`/`hidden` attribute on any control.

- [ ] **Step 3: Commit the verification note**

If all checks pass with no further code changes needed, no commit is required for this task — it is verification-only. If any check surfaces a defect, fix it as a new small commit referencing which verification step caught it, then re-run Step 1 for the affected flow.

---

## Self-Review Notes

- Spec coverage: visual token replacement (Task 1), Plotly re-theme (Task 2), provenance strip enrichment (Task 3), staged pipeline progress (Task 4), and full real-file verification (Task 5) — all five pieces from the approved design are covered.
- Per-chart export was confirmed already correct in the real app and is explicitly out of scope (no task touches `exportSingleChart` logic, only the colors it inherits from Task 1/2's tokens).
- Cross-tab status vocabulary corrected to the real `ok`/`grey`/`suppressed` values throughout (Task 2 comment, Task 5 verification) rather than the mockup's "warn".
- No placeholders: every step has literal code to write, not a description of intent.
