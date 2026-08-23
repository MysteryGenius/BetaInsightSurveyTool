# State audit remediation — ten prompts

Spec: `docs/state-audit-2026-08-22.md`

Ten prompts, executed in order, addressing the findings in the audit above.

## Global Constraints

- Sequence matters more than usual here. Prompt 3 must land before prompt 5, or turning on loud failure will stop every PureSpectrum load on eight questions the library could have matched. Prompt 4 must land before prompts 5 and 6, which both consume its output.
- The Rakuten numerical fixtures asserted against the HC sheets are the regression guard for this entire round (`tests/test_compute.py`, `tests/test_cross_tab.py`, `tests/test_findings.py`, `tests/test_demographic_registry.py`, `tests/test_chart_data.py`, `tests/test_breaks_compute.py`, `tests/test_breaks_conformance.py`, `tests/test_projection.py` — all asserting against the `HC` sheet in the Rakuten `.xlsx` fixtures). If any of them change by any amount at any step, stop and report rather than updating the expected values.
- Read only where the audit says read only. This set fixes things, but nothing here authorises rewriting a test to make a change pass.
- No synthetic fixtures. Where a test needs data we do not have, the test is skipped with a named reason or not written.
- Run `python3 -m pytest tests/ -q` after every task. Baseline before this plan started: 396 passed, 5 skipped, 0 failed (401 collected), after the pre-audit snapshot commit.
- Prompt 9 (declared-not-collected demographics) requires Jodie's explicit confirmation before it runs — do not execute it as part of the automated sequence. Stop before Task 9 and ask.

## Task 1: Wire straightliner_action

Highest-severity finding in the audit, unrelated to the vendor work. Do it first and in isolation.

`ToolConfig.straightliner_action` (`surveytool/core/config.py:13`) declares a default of `"keep"`. It is never read. `surveytool/desktop/app.py:370-376` calls `detect_straightliners()` and passes the flagged respondents as `exclude_respondent_ids` unconditionally on every pipeline run, for every vendor. The tool has been excluding straightliners from every report while its own configuration says it keeps them.

Read the setting in `_run_pipeline` and honour it:
- `"keep"`: detection still runs and the count is still reported, but no respondent is excluded and the base is unchanged.
- `"exclude"`: current behaviour applies (exclude flagged respondents).

Add a statement to the run summary that is always present, in the same unconditional style as the existing quality and verification statements: how many respondents were flagged as straightliners, and whether they were excluded from the base or kept in it. Never report a count without saying what was done with it.

Do not change the default. `"keep"` stays the default — that is the documented behaviour, and the decision to exclude belongs to the analyst per project.

**Acceptance:** a run with the default setting produces a larger base than the same run today, and the Rakuten HC fixtures either still pass or fail in a way attributable precisely to this change. If they fail, stop and report the delta rather than adjusting anything — that result is itself the finding, because it would mean the golden figures were computed against silently excluded respondents.

## Task 2: Move override storage out of the temporary directory

`_project_overrides_path` (`surveytool/desktop/app.py:191-205`) writes project overrides under `tempfile.gettempdir()/surveytool-overrides`. On Windows that location is subject to cleanup. An analyst who resolves a file's questions and reboots loses the work, with no warning that it went.

Relocate override storage to a persistent per-project location alongside the project data, as the approved design specified. Keep one file per `survey_id`.

Preserve the existing path validation. The audit records an allowlist regex and containment check on `survey_id` added after a path-traversal finding. That protection must survive the move intact. If the new base directory changes what containment means, re-derive the check against the new base rather than dropping it.

Add a migration read: if an override file exists at the old temp path and not at the new one, read it, write it to the new location, and record a notice. Do not delete the old file.

**Acceptance:** an override written, followed by a simulated process restart with the temp directory cleared, still applies on the next load. Path traversal attempts on `survey_id` are still rejected, with the existing tests passing unmodified.

## Task 3: Extend the scale library

The audit's coverage run found eight ordered scales in the PureSpectrum fixture falling to categorical. Six of them are library gaps rather than architectural ones. Close those before Task 5 turns unmatched questions into hard stops.

Add to `scales.yaml`:
- `concern`: top patterns "very concerned", "extremely concerned". Neutral patterns "somewhat concerned", "moderately concerned". Bottom patterns "not very concerned", "not concerned at all", "not at all concerned".
- `worry`: top patterns "very worried", "extremely worried". Neutral patterns "somewhat worried". Bottom patterns "not very worried", "not worried at all", "not at all worried".
- `relevance`: top patterns "extremely relevant", "very relevant", "relevant". Neutral patterns "neutral", "moderately relevant". Bottom patterns "not very relevant", "not relevant at all", "not at all relevant", "irrelevant".
- `fluency`: top patterns "fluent", "conversational". Neutral patterns "basic". Bottom patterns "none", "not at all".

Add to the existing `importance` family: "somewhat important", "not very important".

Add to the existing `intensity` family: "not really".

Two cautions:
1. The `relevance` family's neutral must tolerate the PureSpectrum wording that combines a neutral point with a don't-know, since "Neutral/don't know enough to say" is a single label carrying both. Decide deliberately whether that label is neutral or non-substantive and record the reasoning in a comment. Default position: neutral, because it is a mid-point on an ordered scale the respondent selected, not a refusal to answer — but check the wording against the file before committing.
2. The `fluency` family's labels in the fixture carry a descriptive suffix after a dash, e.g. "Basic — a few words or phrases". Confirm whether the current normalisation reduces these to a matchable stem or whether they will still miss. If they still miss, do not add fuzzy prefix matching to make them fit. Report it and let those questions go to the resolver, which is what it is for.

**Acceptance:** re-run the audit's coverage script approach against all five fixtures. PureSpectrum's scale count rises from 1. Rakuten, Milieu and Toluna classifications are unchanged, and their numerical fixtures still pass. Any question that changes classification on a vendor other than PureSpectrum is a regression, not an improvement, and must be reported.

## Task 4: Structured match results

`identify_family` (`surveytool/core/scale_library.py:94-101`) currently returns a family or nothing. That all-or-nothing answer is why a question one label short of the `importance` family is treated identically to a question that is not a scale at all. Tasks 5 and 6 both need the difference.

Introduce a match result type carrying: the outcome (full match, partial match, no match), the family where a full or partial match occurred, the labels that matched with their roles, and the labels that did not match.

A partial match is when at least one label maps to a family and at least one does not. Where labels match across more than one family, report the family with the highest count of matched labels, and record that the result was ambiguous.

`identify_family` keeps its current signature and behaviour for existing callers. Add the richer result as a separate function so this task changes no behaviour anywhere.

**Acceptance:** PureSpectrum Q7 returns a partial match against `importance` naming the two unmatched labels, evaluated before Task 3's additions are considered. Q8 returns no match. Rakuten Q1 returns a full match against `agreement`. Full existing test suite passes unmodified.

## Task 5: Single-pass detection wired into all four load paths

The core of this round. The audit found that `validate_all_questions` is called from nowhere, that Rakuten and PureSpectrum demote unmatched questions to categorical silently, and that Milieu and Toluna demote to `single_choice` silently on a zero match while hard-failing the whole file on a partial match. Every one of those paths is wrong.

Replace all of them with one behaviour, identical across the four vendors.

During load, classify every question column. Collect, do not raise, every question that does not achieve a full scale match. After all columns are processed, if the collected set is non-empty, raise one `UnresolvedQuestionsError` carrying every entry.

**The exemption rule**, which governs whether this improves the tool or ruins it: a question column is only collected if it is not already accounted for. Declared demographics, reserved metadata columns and quality columns are exempt and never appear in the resolver. Questions already covered by a stored project override are exempt. Everything else that is a question column and is not a full scale match is collected, including questions that are genuinely lists, because the tool cannot tell a list from a scale it failed to match and must not guess. The analyst confirms each one once, the override persists, and subsequent loads of that project are silent.

Delete the categorical fallback in `classify_question_type` and the `single_choice` fallback behind the `any_label_matches_family` gate in Milieu and Toluna. Categorical remains a valid classification, but only as the outcome of an override, never as an inference. Remove the `UnresolvedScaleLabelsError` raise from `resolve_roles`'s load path, including its `next_action` text instructing the analyst to edit `scales.yaml`.

Each collected entry carries: variable, question text, ordered code and label pairs, and a reason derived from Task 4's match result. The reason must distinguish a partial match, naming the family and the labels that failed, from a no-match. Those two states need different decisions from the analyst and must not read alike.

**Acceptance:** all four vendors raise the same error type from a real load. A PureSpectrum load collects only the questions still unmatched after Task 3, and collects none of D1, D2, D3, QC2 or QC2Flag. A Rakuten load collects no demographics. Resolving every collected question and re-running produces a clean load. The Rakuten HC fixtures pass.

## Task 6: Compute and serialize the close-family hint

The frontend reads `entry.close_family_hint` (`surveytool/desktop/static/index.html:2134`) into a dedicated element. Nothing computes it and the field does not exist on the serialized object, so it renders empty always.

Populate it from Task 4's partial match result. Where the match was partial, the hint states the family and which labels did not match, in plain language. Where there was no match, the field is absent rather than empty, and the frontend renders nothing.

Add the field to `UnresolvedQuestion` and to its serialization in `surveytool/charts/errors.py:199-207`.

Two constraints carried from the approved design:
1. The hint is text only. It must not pre-select the corresponding option in the resolver, and this task must not add any code that does.
2. It is derived from deterministic pattern matching, not from similarity scoring, fuzzy distance or any inference about what the analyst probably means.

**Acceptance:** a partial-match question produces a hint naming the family and the failed labels. A no-match question produces no hint field. Nothing in the resolver becomes pre-selected.

## Task 7: Wire the non-substantive label list

`ToolConfig.nonsubstantive_labels` persists, round-trips through the settings endpoints, and is editable in the UI. `is_nonsubstantive_label()` (`surveytool/core/nonsubstantive.py:20-21`) ignores it entirely and matches a hardcoded six-pattern list. An analyst who adds a label sees it saved and believes it takes effect. It does not.

Give `is_nonsubstantive_label` a parameter for the project's configured label list, and thread the setting through to every call site: `rakuten.py:94`, `milieu.py:99,158,177`, `toluna.py:88,147`, `purespectrum.py:138`.

The hardcoded patterns become the default list rather than a floor. If an analyst removes a default label from their project's list, it is no longer treated as non-substantive. A configurable list that cannot be reduced is not configurable, and the current defaults were never a deliberate decision anyone signed off.

Changing this list must invalidate the current result and require a re-run, in the same way the exclude-from-base toggle does.

**Acceptance:** adding a custom label changes which responses are excluded from the base on the next run. Removing a default label does the same. The Rakuten fixtures pass with the default list.

## Task 8: Wire the loud halt on unclassified columns

`classify_columns()` and `UnclassifiedColumnError` (`surveytool/ingest/classify_columns.py:8-54`, `surveytool/core/column_classification.py:17-33`) implement the approved design and are called from nowhere but their own test. The live path, `build_column_classifications` (`surveytool/ingest/column_inventory.py:10-55`), places an unmatched column under `UNCLASSIFIED` and returns normally. The column is then visible only if the analyst opens a run summary panel that does not open by default.

Wire the halt into the load path. An unrecognised column stops the run with a structured error naming the column and its header text.

This is the one task in the set with no currently observed failure instance. The audit found no unclassified columns across all five fixtures. Wire it anyway.

Reconcile the two implementations rather than leaving both. One classification function, called from the load path, feeding the run summary. If `build_column_classifications` is the better base, move the halt into it and delete `classify_columns`. Do not leave a dead function behind.

**Acceptance:** an injected unrecognised column halts the load on all four vendors with a named error. All five fixtures load unchanged. Exactly one column classification implementation remains.

## Task 9: Declared-not-collected for canonical demographic categories — REQUIRES CONFIRMATION BEFORE RUNNING

Do not execute this task as part of the automated sequence. Stop after Task 8 and get Jodie's explicit confirmation. This task changes reported output.

`demographic_registry.py:80-94` enforces that every canonical category in a dimension is reachable from any vendor mapping that declares the dimension. Because `canonical.yaml`'s `age_band` requires `under_18`, and neither Toluna nor PureSpectrum has an under-18 band, both vendors lose the age dimension entirely.

Allow a vendor mapping to declare a canonical category as not collected, with a required free-text reason recorded in the YAML. A declared-not-collected category satisfies the reachability check. It is not silently dropped: it appears in the run summary as a stated gap, and any table or chart broken by that dimension carries a note that the category was not collected by this vendor.

Then enable `age_band` for PureSpectrum against D2 and for Toluna against column 2, each declaring `under_18` as not collected with the reason.

Before enabling Toluna, independently extract and inspect column 2's raw values from the fixture. The audit flagged that Toluna's exclusion reason rests on a code comment rather than a fresh extraction, including the claim about a single combined top bucket. If the top bucket genuinely cannot split into `55_64` and `65_plus`, declare those not collected as well rather than inventing a boundary.

**Acceptance:** registry load succeeds with the new declarations. An age-broken table on PureSpectrum renders ten bands and carries the not-collected note. Rakuten and Milieu behaviour is unchanged, and Milieu still declares no age dimension because it has no age question at all.

## Task 10: Test hygiene

`tests/test_purespectrum_fixture.py::test_purespectrum_real_file_loads_and_classifies_all_42_columns` runs two assertions and then calls `pytest.skip()` unconditionally in its own body, with a reason saying it awaits a fixture that is present in the repository. Delete it. The coverage it claims is genuinely provided by `test_desktop_run_summary.py::test_purespectrum_all_42_columns_classified`, which passes. Do not repair it into a second copy of a test that already exists.

The four skipped tests in `tests/test_traffic_law_fixture.py` await `rakuten_survey_traf_law_data.xlsx`. If the client-supplied fixture file is present in the repo root (check before starting), add it and make those tests real: S5 classifies binary, S6 classifies calendar frequency, the Q1 to Q10 block classifies agreement, and a top-two-box request on S5 raises. If the fixture is not present, leave these tests skipped with their current reason — do not fabricate the file.

Then add the two vendor files supplied alongside it, `rakuten_survey_wcs_data.xlsx` and `purespectrum_survey_wcs_data.xlsx`, to the conformance suite as structural fixtures, if present in the repo root. Both were reported as failing by the client and both must be covered by a standing test rather than by a manual check.

Add no numerical assertions for Milieu, Toluna or PureSpectrum. All three still lack a client-verified source, and the policy stated in `tests/test_conformance.py:335-339` — not testing against our own output as though it were ground truth — holds.

**Acceptance:** the phantom skip is gone. If the traffic law fixture is present, its four tests pass rather than skip and the suite's skip count drops accordingly. Every remaining skip names a fixture that genuinely does not exist.
