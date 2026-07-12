# Beta Insight Survey Analysis Tool — v1 Build Plan (rev 3)

Status: ready to build, and now checked against real files from all three vendors.
This revision folds in what the Milieu and Toluna files revealed, corrects one
default that the real data proved wrong, and adds a human-verified golden fixture
set.

## 1. What the tool does

Given one vendor data file, produce a **findings sheet** (the single source of
truth) holding every computed figure, and a folder of **chart PNGs** rendered only
from that sheet. No language model touches the numbers. Every run is identical.

## 2. Scope of "agnostic": now checked, not assumed

Rev 2 said agnosticism had to be earned against real Milieu and Toluna files. Those
files are now in hand, and the canonical model survives them, with additions noted
below. The three vendors are genuinely different:

- **Rakuten**: xlsx with `A1`, `HC`, and `Datamap` sheets. Numeric codes plus a
  separate codebook sheet. Question-code prefix varies by survey (Q1..Q7 in one,
  A1..A6 in another). A vendor straightliner `FLAG` is present in some surveys and
  absent in others.
- **Milieu**: a single CSV with text labels, no codebook. Question id, type, and
  text are embedded in the column header (`[q8]: Multi-select - ...`). Multi-select
  answers are joined in one cell with "; ". Real routing exists (a multi-select is
  blank for the 433 respondents it was not asked). Labels carry whitespace noise
  (one value is "Yes, I own a car " with a trailing space).
- **Toluna**: a single xlsx sheet `RespondentData.Text`, text labels, headers of
  the form `N : stem? sub-item`. Grid questions repeat the same number across
  columns, distinguished by the sub-item suffix. It uses four different labelled
  scales (ability, likelihood, importance, effectiveness), none of which contain
  the word "agree".

Toluna alone is proof that role assignment cannot come from code position or from
the word "agree". The model handles all three because roles come from a scale
library keyed on label meaning, and because the model already carries
multi-response, grids, and an asked-base. The conformance suite is what keeps this
true as adapters are added.

## 3. Policy decisions, locked

| Item | Decision | Rationale |
| --- | --- | --- |
| Straightliner handling | **Per project, not universal. Default is keep (base = total answering).** The tool computes straightlining in-tool so exclusion can be applied to any vendor, but does not exclude unless the project's convention says to. | The real data proved there is no single right answer. The human-verified support-measures figures are on base 1000 with no exclusion, and that file has no `FLAG` at all. The social-mobility report excluded straightliners (base 927). One default cannot match both, so it is a per-project switch. |
| Percentage base | **Total Answering**, including non-substantive codes, over those asked. For a routed question the base is those asked, not the whole sample. | Milieu's routed multi-select bases on 567, not 1000. |
| Mean scores | **Substantive codes only.** | A non-substantive answer has no scale position. |
| Netting | **Top-two-box and bottom-two-box are the reporting unit.** Never report a single extreme box as the headline. | The evaluation doc flags reporting only "strongly disagree" (5.7%) as an error, and the flagship error is quoting 42% agree while dropping 11.1% strongly agree, when the correct figure is 53.1%. |
| Source of truth for questions | **The data file's own codebook or headers**, never an external questionnaire. | The questionnaire on file describes a different survey than the data. |
| Default banner | **Age and ethnicity.** Others supported, off by default. Config, not code. Demographic categories differ by vendor (Milieu has Caucasian; Rakuten does not), so levels are read from data. | Matches the reports. |
| Reconciliation | **First-class feature, not optional.** The tool compares a set of written figures against the findings sheet and flags mismatches. | The client already does this by hand. The evaluation doc is a manual reconcile. Automating it is core value. |
| Significance testing | **Out of scope.** Clean seam for a two-proportion z-test at 95 and 90. | No test groups defined in the data. |
| Rounding | **One decimal, half up, presentation only.** | Standard. |
| Branding | Charts teal `#1B667D` on cream `#F4F1EA`, corner wordmark. | Sampled from the logo. |

## 4. The commitments that make it vendor-agnostic

### 4.1 Roles come from label meaning, never code position
Resolved in this order: explicit per-question override; else a match of the
normalised label set against the scale library; else fail loudly. Never "the high
numbers are the top box".

### 4.2 A scale library, sized to the real data
Ships with at least: agreement, satisfaction, likelihood, importance,
effectiveness, ability, and frequency, plus a generic 0-to-10. Each declares top,
neutral, and bottom by label, independent of code and direction. It must recognise
the "Neutral / Neither X nor Y" midpoint pattern the real files use. Adding a family
is data, not code.

### 4.3 An open set of non-substantive codes
Label patterns (Prefer not to answer, Don't know, Not applicable, Refused, No
opinion), declared numeric sentinels, and out-of-range codes. Unmatched codes warn
and are surfaced, never folded silently into a base.

### 4.4 The canonical model represents what actually varies
Arbitrary scale length and direction; text or numeric coding; multi-response
(delimited in one cell, bases on respondents, may exceed 100 percent); grids (a set
of scale sub-items sharing a stem, tracked as a group); numeric-open and text-open;
and an asked-base with routing. Three response states stay distinct: not-asked,
item-missing, non-substantive.

### 4.5 Straightlining is computed in-tool
Default question set is all ordinal scale items in the analysis block, rule is zero
variance across that set. Reproduces the vendor `FLAG` exactly on the social-
mobility file (73 rows). Default action is keep; exclude is a per-project switch.

### 4.6 Input hygiene is the adapter's job
Trim whitespace on labels before grouping, normalise obvious label noise, and
report anything that does not resolve. Milieu's trailing-space label is the worked
example.

### 4.7 The conformance suite is the contract
Every adapter's canonical output must pass one suite: reversed-coded scale resolves
from labels; multi-response bases on respondents and may exceed 100; non-substantive
stays in the percentage base but out of means; a routed question bases on those
asked; unknown labels fail loudly; grids group by stem; straightliner reproduces a
known set. Adding a vendor means going green against this, not editing compute.

## 5. Canonical schema

- **Survey**: id, n_raw, n_analysis, date_range, base_policy.
- **Question**: qid, text, qtype (`scale`, `single_choice`, `multi_response`,
  `numeric_open`, `text_open`, `demographic`), labels, roles, and for scales the
  length and direction; for multi-response the member codes; a `grid_group` id for
  grid sub-items; `asked_base` predicate; is_demographic; base_eligible.
- **Responses**: respondent table distinguishing not-asked, item-missing, and
  non-substantive, with vendor quality flags kept only as cross-checks.
- **Banner**: demographic questions used as crossbreaks; levels read from data.

## 6. Pipeline and phases

Phases 0 to 5 build the engine and the Rakuten path. Phases 6 and 7 add the other
two vendors, and are now concrete because the files exist.

- **Phase 0**: canonical model, config, scale library, non-substantive registry,
  in-tool straightliner, input-hygiene helpers, and the conformance suite. No vendor
  code. Gate: suite green on synthetic fixtures.
- **Phase 1**: Rakuten adapter (Datamap plus A1). Gate: passes conformance; on
  social-mobility yields 1000 respondents, Q7 a length-6 scale with one
  non-substantive code, straightliner reproduces 73.
- **Phase 2**: compute on Total, validated against the `HC` tab (base 1000). Gate:
  Q1 agree 64.6%, neutral 28.3%.
- **Phase 3**: crossbreaks and the findings sheet, plus the reconcile pass.
  Validated against both verified surveys (see section 7). Gate: all golden and
  negative fixtures pass, reconcile flags the seeded errors.
- **Phase 4**: usable chart graphics, findings-sheet driven. Gate: real labels, no
  "Code N", no zero-filled bars, title variable matches bars, manifest resolves
  every PNG to findings rows.
- **Phase 5**: CLI and property tests.
- **Phase 6**: Milieu adapter (CSV, header-typed, multi-select, routing,
  whitespace). Gate: passes conformance; the routed multi-select bases on 567; grid
  items resolve on the agreement scale.
- **Phase 7**: Toluna adapter (single text sheet, `N : stem? sub-item` headers,
  grids by shared number, four named scales). Gate: passes conformance; grids group
  correctly; all four scales resolve from labels.

If Phase 6 or 7 forces a change below the adapter layer, stop and treat it as a
canonical-model gap, not a patch.

## 7. Golden fixtures, from human-verified sources

Social-mobility (verified report, straightliners excluded, base 927):
Q1 agree 67.4%, neutral 25.2%; age 25-34 = 67.8%, 35-44 = 69.3%; Chinese 68.1%,
Malay 62.0%, Indian 72.7%, Other 61.8%; Q7 agree 57.1%, mean 3.5. On base 1000 (HC
tab) Q1 agree is 64.6%. Negative fixtures: report's Chinese 61.8% (correct 68.1%)
and Q7 mean 3.4 (correct 3.5).

Support-measures (evaluation doc, base 1000, no exclusion):
Q1 concern T2B 87.3%, mean 4.27, B2B 2.3%; concern mean by age rises with age,
youngest 3.90, then 4.23, 4.24, 4.25, 4.45, oldest 4.48. Q2 vouchers T2B 74.9%
(50.2 + 24.7), mean 3.93. Q3 insufficiency T2B 23.7%, B2B 41.5%, mean 2.73. Q4
reaching-vulnerable T2B 49.9%, mean 3.39. Q5 government-confidence T2B 53.1% (42.0 +
11.1), mean 3.44.

Negative fixtures from the AI decks, all encoded with a comment on the source error:
government confidence is 53.1%, not the 42% the decks reported (they dropped the
11.1% who strongly agree); reaching-vulnerable is 49.9%, not "one in two"; highest
concern is the 65+ group at 4.48, not "middle-aged" or "ages 30-49". These are the
exact error classes the tool removes.

## 8. Stack

Python, pandas, openpyxl, matplotlib, scipy or statsmodels (for the sig-test seam),
pydantic, pyyaml, pytest. Read xlsx with openpyxl `read_only=True` and
`iter_rows(values_only=True)`; do not trust `ws.max_row` in read-only mode. Read
Milieu with pandas or the csv module, encoding `utf-8-sig`.

## 9. Out of scope

Significance testing, editable or vector charts, narrative generation, any model in
the compute path, weighting (surveys are pre-balanced at n=1000).
