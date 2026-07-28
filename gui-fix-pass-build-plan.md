# Beta Insight GUI: Fix Pass Build Plan

Revision 2. Revised against the Phase 0 verification report run at HEAD.
Status: ready for execution by Jian Zhen.
Scope: repair the GUI so it is shippable to Leonard's analysts. Not a redesign.

---

## 1. Why this pass exists

A driven walkthrough of the local build found five defects. Two of them make the app unusable for a non-technical operator: after a successful upload the user is stranded on the upload card, and a pipeline failure hangs the spinner forever with no message.

The second matters beyond the bug. The compute core is built on loud failure over silent degradation. The GUI currently does the opposite. For a tool whose premise is that the numbers can be trusted, a UI that hangs silently is worse than one that stops and says why.

This pass fixes that contradiction and the other defects. It does not restructure the app. The state model, staged progress, guardrail presentation and session-level export design are a separate deliverable sequenced after this lands.

---

## 2. What verification changed

Phase 0 was run and is complete. Results, and what they change:

| Item | Status at HEAD | Change to plan |
|---|---|---|
| A. Error taxonomy | Unresolved. Entirely new work. Two unrelated custom exceptions exist. `errors.py` exists as a module | Taxonomy lands in `errors.py`. Both existing exceptions fold into it. New code added. Ad hoc catches deleted, not layered over |
| B. Error surfacing | Unresolved. 12 producer sites, 4 unguarded parse sites, no timeout | Plus one new finding: a silent-failure path not in the original audit. Added to scope |
| C. View activation | Partially resolved. `activateTab` is already clean | Root cause is narrower than the audit stated. Phase shrinks |
| D. Chart sizing | Unresolved. All four sub-items outstanding | Confirmed. Ordering dependency on C is now explicit |
| E. Laptop layout | Unresolved. All six sub-items outstanding | No change |
| F. Significance chip | Unresolved. Only hidden/disabled control in the markup | Confirmed inert end to end. Removal is now clearly correct |
| G. Per-chart export | Partially built, and the hard part is done correctly | Rescoped substantially. See item G |

Three findings deserve calling out because they change decisions rather than just details.

**The export already does the right thing.** It POSTs to a session export endpoint that calls the core render path, so it serves the core-produced PNG rather than a client-side Plotly render, and file naming is already deterministic through `ChartSpec.filename`. The architectural risk I wrote a warning about does not exist. What is missing is a per-chart affordance, and the existing bulk export writes to a folder path the user types by hand.

**The warnings channel currently has no producer.** Significance graceful exit is resolved at the CLI layer, but at the API boundary the same condition is returned as a bare-string 400, and the frontend never sends a significance parameter at all, so the condition cannot fire in the GUI today. See the decision in section 5 item A.

**One silent failure was found that the audit missed.** The cross-tab picker loader returns quietly on a non-ok response. That is the same class of defect as the hanging spinner and belongs in this pass.

---

## 3. Sequencing

| Phase | Item | Layer |
|---|---|---|
| 0 | Verify findings against HEAD | complete |
| 1 | Error taxonomy | core |
| 2 | Error surfacing and timeout | API + GUI |
| 3 | View activation after upload | GUI |
| 4 | Chart sizing and resize safeguard | GUI |
| 5 | Laptop layout | GUI |
| 6 | Significance chip removal | GUI |
| 7 | Per-chart export affordance | API + GUI |

Phases 1 and 2 are one logical change split across layers. Do not ship 2 without 1. Phase 4 depends on Phase 3, because charts are currently drawn inside the upload success path before any tab activation happens.

---

## 4. Constraints carried forward

**No figure is recomputed in the UI layer.** This extends to exports. The existing export already honours it.

**The core owns the error taxonomy. The GUI renders it and never interprets it.** The GUI must not inspect message text, pattern match, or decide what a failure means. If the GUI needs to distinguish two failures, the core gives it two codes.

**Loud failure over silent degradation.** No path may quietly return nothing.

**Single session.** One survey at a time.

**No synthetic fixture data.** Failure cases come from real vendor files mishandled deliberately: wrong adapter, truncated file, renamed sheet.

**Nothing ships that does nothing.** This is why the significance chip is being removed, and it applies one layer down too. Do not build infrastructure with no producer and no consumer.

---

## 5. Audience and voice

Operators are Leonard's analysts. Not developers, not Rakuten end users.

**Safe:** top-two-box, net, base size, base, scale labels, weighting, significance, cross-tab, banner, suppression, threshold, respondent, wave, demographic.

**Banned in anything a user sees:** exception, traceback, stack, parser, adapter, schema, null, NaN, index, module, and any path inside the codebase. Vendor names are fine. The user's own file names are fine.

**Copy rules:**

- State what happened, past tense, concretely.
- Name the cause if the core knows it. Do not guess if it does not.
- Give one next action the user can take.
- No apologies. No "something went wrong". No exclamation marks. Sentence case.

Good: `This file does not look like a Rakuten export. It has no Datamap sheet. Check the vendor setting, or pick a different file.`

Bad: `Error: unexpected exception in ingest adapter. Please try again.`

---

## 6. Work items

### A. Error taxonomy (core)

**Confirmed at HEAD.** No typed error carrying code, message, detail and next action exists. Two custom exceptions exist and are unrelated to each other: a demographic lookup failure in the cross-tab module, and a findings-row lookup failure in `errors.py`. Config and the Milieu and Toluna ingest paths still raise bare `ValueError`. The API catches specific builtins per endpoint ad hoc across a dozen sites and has no blanket handler, so anything uncaught produces the framework's raw 500.

**Change.**

1. The taxonomy lands in the existing `errors.py`. It already exists and already holds one error type, so it is the natural home and avoids a second parallel error module.

2. Define one error type carrying a stable machine code, a user-facing message, an optional detail line, an optional next action.

3. Fold both existing exceptions into the taxonomy rather than leaving them alongside it. The demographic lookup failure is a genuine user-facing condition, an analyst picking a demographic the file does not contain, and gets its own code. The findings-row failure is internal and maps to the generic internal code unless the code shows otherwise.

4. **Delete the ad hoc per-endpoint catches.** Replace them with a single boundary handler. Do not layer a handler on top of twelve inconsistent catch blocks and leave both in place.

5. Response shape moves from the bare `{"error": "<string>"}` to:

```json
{
  "error": {
    "code": "VENDOR_MISMATCH",
    "message": "This file does not look like a Rakuten export.",
    "detail": "No Datamap sheet was found.",
    "next_action": "Check the vendor setting, or pick a different file."
  }
}
```

All twelve producers and all four consumers change together. Do not leave both shapes live.

**Minimum code set:**

| Code | Meaning |
|---|---|
| `VENDOR_MISMATCH` | File does not match the selected vendor adapter |
| `FILE_UNREADABLE` | Corrupt, empty, password protected, or wrong file type |
| `MISSING_SHEET` | Expected sheet absent from the workbook |
| `MISSING_COLUMNS` | Expected columns absent |
| `UNRESOLVED_SCALE_LABELS` | Labels could not be resolved. Must fail, never demote |
| `NO_QUESTIONS_FOUND` | File read but nothing computable in it |
| `DEMOGRAPHIC_NOT_FOUND` | Selected cross-tab demographic is not in this file |
| `CONFIG_INVALID` | Project config malformed or missing a required key |
| `INTERNAL` | Anything uncaught. Fixed generic message, detail to the log only |

Codes live in one registry. No scattered string literals.

**Warnings channel: conditional.** The plan originally required a `warnings` array on the success response. Verification shows it would have no producer today. Significance-unavailable is returned as a 400 at the API boundary, and the frontend never sends the parameter, so the condition cannot fire in the GUI at all.

**The call: identify a real producer first, or do not build it.** Suppression counts, excluded straightliners and skipped questions are all plausible non-fatal conditions an analyst should see. Jian Zhen names at least one that exists in the core today and routes it. If none exists, the channel is dropped from this pass and recorded for the restructure. Shipping an unused channel is the same error as shipping the disabled checkbox in item F, one layer down.

Significance itself does not get wired up here either way. It is inert end to end and stays that way until the restructure.

**Acceptance.** No endpoint can return a non-JSON body under any input. Verified with a real Milieu file fed to the Rakuten adapter, a truncated real file, and a real file with a required sheet renamed.

---

### B. Error surfacing and timeout (API + GUI)

**Confirmed at HEAD.** `response.json()` is unconditional and unguarded at all four fetch sites. No abort controller or timeout exists anywhere in the desktop package. Consumers read `body.error` as a flat string with a fallback.

**New finding, added to scope.** The cross-tab picker loader returns silently on a non-ok response. The user gets an empty picker with no explanation. Same defect class as the hanging spinner.

**Change.**

1. Guard every response parse. Check status and content type before parsing. On a non-JSON body, construct a synthetic internal error object locally rather than throwing. The catch path must be reachable from every failure mode.
2. Abort controller with a 180 second timeout on the upload request. On abort, a timeout error with a retry action.
3. One error surface. Inline panel, not a browser alert. Message as heading, detail beneath if present, next action as body text. Dismiss returns the user to the upload card with vendor and survey ID preserved.
4. The spinner has exactly three exits: success, structured error, timeout. No fourth.
5. The picker loader surfaces its failure through the same surface instead of returning quietly.
6. If the warnings channel survives the decision in item A, render it as a quiet persistent notice above the results. Not a modal, not a vanishing toast.

**Acceptance.** Real Milieu file with Rakuten selected: spinner stops, plain-English message. Backend killed mid-request: spinner stops, timeout message. Neither requires a reload.

---

### C. View activation after upload (GUI)

**Confirmed at HEAD, narrower than the audit stated.** `activateTab` is already a clean single-writer implementation. The static `.active` class is on the tab button only, not on the view panel, so clicking Charts manually does work. The audit's claim that the manual workaround was a no-op is wrong. The real and only defect is that the upload success branch never calls `activateTab`.

**Change.**

1. Call `activateTab("charts-view")` on upload success, before charts are drawn. The ordering matters for item D.
2. Remove the static `.active` class from the tab button so `activateTab` is the sole writer and the DOM cannot disagree with the visible panel.

This is the minimal fix. Do not build the two-state empty/loaded model or the load-different-file action. Both are deferred, see section 7.

**Acceptance.** Charts visible after upload with no further clicks. Tab button state matches the visible panel at every point.

---

### D. Chart sizing and resize safeguard (GUI)

**Confirmed at HEAD.** Both `newPlot` calls pass display options only. No `responsive`, no `Plotly.Plots.resize()`, no resize handler anywhere. Charts are drawn inside the upload success path before any tab activation, into a panel that is `display: none`, so they size to a zero-height container.

**Change.**

1. Draw charts only after the containing panel is visible. Phase 3 provides this.
2. `responsive: true` in the Plotly config for every chart.
3. `Plotly.Plots.resize()` on each chart in a panel when that panel becomes visible, retained as a safeguard.
4. Debounced window resize handler.

**Acceptance.** Re-verify the cross-tab chart against a real file after Phase 3 lands. If bars are still flat, that is a compute or data problem surfacing as a display problem. Report it. Do not adjust the rendering to make it look right.

---

### E. Laptop layout (GUI)

**Confirmed at HEAD.** No size arguments on the window creation call. Zero media queries, zero flex-wrap in the stylesheet. The picker row has no wrap fallback. The only max-width in the sheet belongs to the upload card.

**Target.** 1366x768, leaving roughly 650px of usable content height. On a laptop the vertical budget binds, not the horizontal.

**Change.**

1. Minimum window size 1024x700 on the pywebview window.
2. Layout wraps below 1024 anyway. A minimum does not cover display scaling.
3. Picker row wraps rather than truncating. No mid-word truncation at any width.
4. Chart containers get `max-width: 100%`. Long titles wrap.
5. Session summary strip stays on one line at 1366.
6. Chart area takes remaining height and scrolls internally. The window should not need a scrollbar to reach the tab nav.

Keyboard focus outlines currently work and must survive this change.

**Acceptance.** At 1366x768 the session strip, tab nav and one full chart are visible without scrolling. At 1024x700 nothing overflows and no label truncates.

---

### F. Significance chip removal (GUI)

**Confirmed at HEAD.** Still in the DOM, disabled, hidden, v1.1 copy intact. It is the only hidden or disabled interactive control in the markup, and verification confirms it is inert end to end: the frontend never sends a significance parameter at all.

**Change.** Remove the input. Keep the v1.1 note as plain static text.

**Acceptance.** No hidden or disabled interactive controls remain.

---

### G. Per-chart export (API + GUI)

**Rescoped. The hard part is already built and built correctly.** The existing export calls the core render path server-side, so it serves the core-produced PNG rather than a client render, and naming is already deterministic through `ChartSpec.filename`. The warning I wrote about client-side rendering does not apply. Delete it from your mental model of this phase.

Two things are actually wrong.

**Missing per-chart affordance.** Export is session-wide bulk only. There is no control next to an individual chart. Analysts pulling one chart into a client deck have to export everything and hunt for the file.

**The destination is a typed folder path.** Asking an analyst to type a filesystem path into a text field is the wrong affordance for this audience, and it is the kind of thing that generates support questions. This was not in the original five findings, so veto it if you want the phase kept tight.

**Change.**

1. Add a per-chart export control that requests the single core-produced PNG for that chart.
2. Reuse the existing endpoint and naming. Do not build a second export path.
3. Replace the typed folder field with the native save dialog. Default to a sensible location, remember it within the session.
4. Keep the existing bulk export. It works and analysts will want it. This reverses my earlier note that session-level export was deferred: it already exists, so deferring it would mean removing something functional.
5. Export failures use the error surface from Phase 2.

**Acceptance.** Export one chart, open the PNG, confirm base labels and suppression marks match the on-screen version. If they differ, report it with both screenshots. Do not adjust either to match. Fidelity between the two rendering paths is a restructure decision, not a patch.

---

## 7. Deferred to the restructure pass

- Two-state model: empty and loaded, upload card retiring into the session strip with an explicit load-different-file action.
- Staged progress during the pipeline run.
- Guardrail presentation: suppression readable from the cell without the legend, hover base size, summary line above the table.
- Provenance in the session strip.
- Findings sheet access in the GUI.
- Whether significance gets a real control, and whether it moves from a 400 to a warning.
- Fidelity between the Plotly on-screen chart and the core-produced PNG.
- The warnings channel, if item A finds no producer for it today.

---

## 8. Open decisions for Jodie

1. **Warnings channel.** Build only if Jian Zhen names a real producer. Recommendation stands.
2. **Native save dialog in Phase 7.** Beyond the original five findings. Cheap, and the typed path is a real support cost. Veto to keep the phase tight.
3. **Timeout value.** 180 seconds is a guess. Raise it before shipping if a real Toluna or Rakuten file runs longer.
4. **`MISSING_COLUMNS` detail depth.** Recommendation: name the missing columns. Leonard's analysts work with these exports directly and will recognise them.

---

## 9. Verification

No synthetic fixtures. Every failure case comes from a real vendor file.

| Case | How to produce it | Expected |
|---|---|---|
| Vendor mismatch | Real Milieu file, Rakuten selected | `VENDOR_MISMATCH`, spinner stops |
| Unreadable file | Truncate a real file | `FILE_UNREADABLE` |
| Missing sheet | Real Rakuten file, Datamap renamed | `MISSING_SHEET` |
| Unresolved labels | Real file with an unmappable label | `UNRESOLVED_SCALE_LABELS`, no demotion |
| Demographic not found | Request a demographic absent from a real file | `DEMOGRAPHIC_NOT_FOUND` |
| Picker load failure | Force a non-ok response on the picker endpoint | Visible error, not an empty picker |
| Backend death | Kill the server mid-request | Timeout message, app still usable |
| Happy path | Real file per vendor | Charts visible with no extra clicks |
| Narrow window | 1024x700 | No overflow, no truncation |
| Per-chart export | Any chart | PNG matches on-screen chart |

Report coverage honestly. If a case cannot be produced from real files, say so rather than fabricating one.
