# Beta Insight: UI Build Report

Build report for the nine-prompt resolver UI, executed against the core layer landed in [2026-08-20-beta-insight-core.md](2026-08-20-beta-insight-core.md).

**Result:** 9/9 prompts shipped. 396 tests passing, 5 skipped (unrelated, awaiting client fixtures — traffic-law and confirmation of a PureSpectrum multi-select shape). All four vendors verified live end to end.

## Summary

The prompt set assumed a finished core: a fingerprint pre-check, an override write path, a run summary object, a non-substantive-response setting. Each existed as tested code — and each turned out to be disconnected from the actual upload pipeline. Wiring the UI kept surfacing gaps in that wiring, and closing them became most of the work.

Every prompt was verified two ways: the Python test suite (pytest, real vendor fixtures, no mocks) and a live headless-Chrome pass driving the actual server — real file uploads through the real endpoints, not a scripted DOM.

## The nine prompts

### 1. Vendor dropdown and mismatch message

Added PureSpectrum to the dropdown, alphabetical, no beta label. Wired `check_fingerprint` into the upload path — it existed and passed its own tests, but nothing called it.

- **Core gap closed:** fingerprint check never wired into `/api/upload`.
- **Bug fixed:** a vendor with an empty signature (Milieu) could never pass its own vacuous-match guard, so every genuine Milieu upload was rejected.

### 2. Error card rewrite

Rewrote the card to render a list of unresolved questions with codes, labels, and reasons, one block per question. The structured error object it needed already existed in the core — but the response serializer dropped the structure on the way to JSON.

- **Core gap closed:** `UnresolvedQuestionsError.to_response()` never serialized `detail_entries`.

### 3. Resolver shell and navigation

One question per view, back/forward navigation, an exit confirmation that's honest about what's kept and what's discarded. Pure UI — no core gaps here.

### 4. Classification picker

Four options, exact wording, nothing pre-selected. The close-family hint renders when the core supplies one — which is never, today; no code path computes it. Built to support it rather than fabricate it.

### 5. Scale label assignment

Top / neutral / bottom per label, running count, a validation requiring at least one top and one bottom.

- **Bug fixed:** the completeness check and the validity check were conflated in the frontend, so forward navigation stayed enabled with zero labels assigned. Caught by a headless-browser test, fixed, reverified.

### 6. Save, write, and re-run

The largest gap in the set. The override write function existed and was tested — but no adapter's `load()` accepted an override, so a saved resolution had zero effect on any future load.

- **Core gap closed:** threaded overrides through all four vendor adapters (Rakuten, Milieu, Toluna, PureSpectrum), added `QuestionType.excluded` for the "leave this out of reporting" path, built the write → re-run → reject-and-retry loop end to end.
- **Security fix:** an automated review flagged a path-traversal vulnerability in `survey_id` handling (interpolated directly into a filesystem path with no validation). Fixed with an allowlist regex plus a containment check.

### 7. Run summary panel, column inventory

Verifying this against the real PureSpectrum file surfaced an adapter bug, not a UI one: two multi-select question groups (`Q10`, `D4`) were silently absent from every parsed survey — no error, just missing columns.

- **Bug fixed:** PureSpectrum's adapter now builds proper `multi_response` questions for these groups, accounting for all 42 columns instead of 27.
- **Bug fixed:** Milieu's vendor profile was missing 13 real metadata/tracking columns, which were being misclassified as questions.

### 8. Quality and verification statements

Both statements render unconditionally, in the panel's plain text treatment — confirmed in the browser that neither Rakuten's nor PureSpectrum's statement block ever resolves to the danger or warn color, including PureSpectrum's "nothing unusual" case.

- **Core gap closed:** override-resolution timestamps were computed by the core but the endpoint had been sending them as an empty list.

### 9. Non-substantive response settings

The exclude-from-base toggle existed as a `ToolConfig` field with nowhere to live — never threaded into the sheet that computes bases and percentages.

- **Core gap closed:** wired `exclude_nonsubstantive_from_base` through to `build_findings_sheet`, added settings persistence and re-run endpoints.
- **Bug fixed:** a browser test caught the toggle's own save handler reading stale state, so the setting silently failed to persist on the first save attempt.

## Final review pass

An eight-angle automated review ran against the full diff after prompt 9 — line-by-line, removed-behavior, cross-file, reuse, simplification, efficiency, altitude, and conventions. Two real bugs were found, independently confirmed across multiple angles, and fixed before this report was written.

| Status | What | Where |
|---|---|---|
| Fixed | Milieu grid question overridden to binary/categorical crashed with a false "incomplete override" error | Grid branch always built a scale question regardless of the override's actual type |
| Fixed | Binary and categorical overrides silently collapsed to a generic type | Milieu and Toluna hadn't adopted the shared override-resolution helper (`resolve_with_override`); Rakuten and PureSpectrum had |
| Fixed | Toluna's run-summary column mapping could disagree with the load it was describing | Re-parsed the file without the same overrides the real load used — latent, not reachable with current fixtures, closed anyway |
| Noted | Every upload, resolve, and re-run opens the source file 4–5 separate times | Header, status column, verification sheet, and the load itself each re-open independently instead of sharing one parse |
| Noted | Vendor dispatch repeated as three near-identical if/elif ladders in `app.py` | A fifth vendor means editing three places instead of one registry |

Both noted items are real but architectural rather than correctness bugs — nothing produces a wrong answer today. Fixing them well means a small refactor (a single vendor-capability registry; one parse per request, shared downstream) rather than a patch, so they're left for a deliberate follow-up.

Six regression tests were added for the two fixed bugs (`tests/test_override_qtype_preserved.py`).

## What's still outside this build

- The close-family hint (prompt 4) has UI support but no core computation feeding it.
- The editable non-substantive labels list is persisted but display-only — actual classification still runs on the fixed regex patterns in the core, by design, to avoid changing historical results for every vendor without a separate decision to do so.
- The "collect every unresolved question in one pass" error the whole resolver assumes still isn't wired into any real adapter load. Rakuten and PureSpectrum silently demote unmatched scales to categorical; Toluna and Milieu hard-fail on the first one. The error card and resolver are built and tested against the shape this would produce; nothing in the real pipeline produces it yet.

## New files

- `surveytool/ingest/column_inventory.py` — column classification for the run summary.
- `surveytool/core/demographics/vendor_purespectrum.yaml` — PureSpectrum demographic mapping (gender, ethnicity; age_band deliberately excluded, same reachability gap as Toluna).
- `tests/test_desktop_resolve.py`, `tests/test_desktop_run_summary.py`, `tests/test_desktop_settings.py`, `tests/test_findings_nonsubstantive_base.py`, `tests/test_override_qtype_preserved.py`.
