# Beta Insight: Core Build Plan

## Vendor extension and label resolution

Approved context: `beta-insight-vendor-extension-context.md` (C1 to C20, A1 to A7).

Scope: compute core and backend only. UI work is covered in the separate UI build plan.

---

## 1. Objective

Three outcomes:

1. PureSpectrum loads and reports as a first-class vendor.
2. Questions that are not nettable scales are classified correctly instead of failing.
3. Unresolved questions are surfaced completely, in one pass, and are resolvable without editing repository files.

---

## 2. Sequencing principle

The first two steps are behaviour-preserving refactors on the current known-good codebase. Every existing test must pass unchanged after each. Only from step 3 onward does behaviour change. This ordering means that if the round is cut short, the codebase is never left in a half-migrated state.

PureSpectrum is deliberately late in the sequence. It is the visible client outcome, but adding it before the classification and typing work is done would mean building the new vendor against the model we are replacing.

---

## 3. Work breakdown

### Phase 1: Vendor profile model (prompts 1 to 2)

Introduce a declarative vendor profile carrying everything that currently varies between adapters: sheet resolution, reserved metadata columns, quality flag column and coding, verification sheet, date formats, multi-select and other-specify patterns, and a fingerprint signature.

Declare profiles for all four vendors. Rakuten, Milieu and Toluna profiles describe existing behaviour exactly. Nothing changes at runtime.

Extract a shared datamap-format base reader and migrate Rakuten onto it. Milieu and Toluna remain on their existing readers behind the unchanged adapter interface (A1). Do not touch them.

**Exit condition:** full existing test suite passes with no test modifications.

### Phase 2: Classification and typing (prompts 3 to 5)

Assign every column exactly one classification on load: question, demographic, metadata, quality, open-end, unclassified. Reserved metadata columns come from the vendor profile, which removes the `status` failure at its root.

Introduce question types. Scale is netted. Binary and categorical are not, and failing to match a scale family stops being an error for them (C9, C10).

Normalise labels before matching: unicode folding, case folding, whitespace collapse. Add the binary, calendar frequency and intensity families to `scales.yaml`.

**Exit condition:** both attached Rakuten files load without error. The traffic law file classifies S5 as binary, S6 as calendar frequency, and all Q1 to Q10 as agreement scales.

### Phase 3: Validation and overrides (prompts 6 to 8)

Replace fail-at-first-question with a single validation pass producing one structured error object listing every unresolved question grouped with its full label set (C8).

Add the project-level overrides file: schema, read, precedence over the shared library, and audit fields. The core applies overrides deterministically. The core does not create them. Creation is the resolver's job, in the UI.

Add non-substantive response handling with the per-project exclude setting, and make the base explicit on every affected output (C16).

**Exit condition:** an override file resolving a question causes that question to report correctly on re-run, with the override recorded in the run summary.

### Phase 4: PureSpectrum and reporting (prompts 9 to 11)

Add the PureSpectrum profile and the fingerprint pre-check across all four vendors. Build the run summary object carrying the column inventory, quality flag availability, and verification status. Extend the Phase 0 conformance suite to four vendors.

**Exit condition:** `purespectrum_survey_wcs_data.xlsx` loads, classifies all 42 columns, and produces a run summary stating that no quality flag is available and that topline figures are not cross-checked.

---

## 4. Constraints carried from the approved context

- No LLM involvement anywhere in this work. All matching is deterministic string comparison.
- No synthetic fixtures. The PureSpectrum fixture asserts structure only until Leonard supplies a tabulation (C19).
- Loud failure. An unclassified column halts the run with a plain-English explanation. It is never skipped.
- Milieu and Toluna adapters are not modified. Their profiles describe current behaviour and nothing more.
- Straightliner exclusion stays per-project configurable. Where a vendor supplies no quality flag, the run summary says so rather than reporting a clean sample by omission (C20).

---

## 5. Risk register

**R1. Refactor regression on Rakuten.** Mitigated by the behaviour-preserving exit condition on Phase 1 and by the existing golden fixtures drawn from the `HC` sheets.

**R2. Over-broad metadata registry.** A reserved column list that is too aggressive would silently drop a real question. Mitigated by C6: the run summary lists every column and its classification, so a misclassified question is visible rather than absent.

**R3. Categorical ordering.** Categorical questions have no inherent order. The default is response value order, not count order, because value order is the order the vendor defined and is stable across cuts. Count order is available as a project setting.

**R4. Override drift.** Project overrides could diverge from the shared library over time. Mitigated by recording the library version in the override file and surfacing a notice when a question resolved by override would now match a library family.

**R5. PureSpectrum numerical accuracy is unverified.** Accepted knowingly (C19). Mitigated by the caveat in the run summary and by keeping the verification request live with Leonard.

---

## 6. Definition of done

1. All three attached files load without error under their correct vendor selection.
2. Selecting the wrong vendor produces an error naming the vendor the file appears to be.
3. Every column in every file carries a classification, visible in the run summary.
4. Unresolved questions are reported together, once, with full label sets.
5. An override file resolves a question deterministically on re-run.
6. The conformance suite covers four vendors and passes.
7. No existing Rakuten, Milieu or Toluna output changes numerically. Verified against the `HC` fixtures.
