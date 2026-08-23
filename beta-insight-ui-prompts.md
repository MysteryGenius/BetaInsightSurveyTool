# Beta Insight: UI Prompt Set

## Sequenced prompts for Claude Code

Execute after the core prompt set has landed and its tests pass. The resolver depends on core prompt 6 (structured error object) and core prompt 7 (override write function). Do not start before those exist.

Each prompt begins with a discovery step. Module and template paths are not assumed.

---

## Prompt 1: Vendor dropdown and mismatch message

Locate the file load screen template and its supporting JS. Add PureSpectrum to the vendor dropdown as a first-class option, ordered alphabetically with the others. No beta or provisional label.

Then handle the fingerprint mismatch error from the core. When the selected vendor does not match the dropped file, render the core's message, which names the vendor the file appears to be where the core could identify one.

Do not change the dropdown selection programmatically. Do not offer a one-click switch. The analyst re-selects and re-drops. Vendor selection is an auditable act and must stay deliberate.

Verify by dropping the PureSpectrum file with Rakuten selected, and confirming the message names PureSpectrum and the dropdown is unchanged.

---

## Prompt 2: Error card rewrite

Locate the error card component. It currently renders a single message and a single label set, as in the two screenshots in the client feedback.

Rewrite it against the structured error object from core prompt 6. Its detail carries a list of unresolved questions, each with a variable name, question text, ordered code and label pairs, and a failure reason.

Render the count in the heading, then each question as its own block showing the variable, the question text, and its labels. Long label sets truncate with an expand control rather than being cut silently.

Remove the line instructing the analyst to add labels to the scale library or check the vendor setting. Replace the next action with a single button reading "Resolve these questions", wired in the next prompt.

Keep the existing card styling. Do not restyle.

Verify with a file producing three unresolved questions: one card, three blocks, count in the heading, no mention of a scale library or YAML.

---

## Prompt 3: Resolver shell and navigation

Build the resolver screen. It opens from the error card button and receives the list of unresolved questions.

One question per view. Show progress as a position in the set, for example question 2 of 5. Provide back navigation to a previously answered question, and forward navigation only once the current question is answered.

Render the question text and the full ordered label set with codes visible. Codes matter because two labels can read alike and the analyst needs to see which value each maps to.

Exiting the resolver before finishing discards nothing already answered in this session but writes nothing either. Nothing is written until the final save in prompt 6. State this on the exit confirmation.

No classification controls yet. This prompt builds the shell, the navigation and the question rendering only.

---

## Prompt 4: Classification picker

Add the classification choice to each resolver view. Four options, in this order and worded exactly like this:

- This is a scale, and I want to net it
- This is a yes or no question
- This is a list of options
- Leave this question out of reporting

No option is selected by default. The analyst must make an explicit choice before forward navigation enables.

Below each option, one line of plain description: what it means for how the question is reported. For the scale option, state that a further step will follow to assign each label.

Where the core supplied a close-family hint, render it above the options as text, for example: the labels in this question look similar to the agreement scale. Do not pre-select the corresponding option and do not visually emphasise it beyond ordinary text.

Verify that no option is pre-selected, forward is disabled until a choice is made, and the hint appears without selecting anything.

---

## Prompt 5: Scale label assignment

When the analyst chooses the scale option, present each label in file order with a three-way assignment: top, neutral or bottom.

Every label must be assigned. No default assignment, no partial save, no "assign the rest automatically" action. Forward navigation stays disabled until all labels are assigned.

Show a running count of assigned labels against the total.

Add one validation before allowing forward: at least one label assigned to top and at least one to bottom. A scale with no bottom is not a scale, and would produce a net that reads as valid but is not. Where the validation fails, explain that in plain language and name what is missing.

Verify with the traffic law S5 labels: assigning both Yes and No to top blocks forward with an explanation.

---

## Prompt 6: Save, write and re-run

On completing the last question, show a summary of every decision: variable, question text, chosen classification, and for scale questions the full label assignment. The analyst confirms from this screen.

On confirm, call the core's validated override write function once with the whole set. The UI does not write the file and does not construct the override schema by hand. If the core rejects any entry, show the core's error and return the analyst to the offending question with their other answers intact.

On successful write, re-run the file load automatically and land the analyst on the result.

Verify: resolving all unresolved questions in the PureSpectrum file writes one override file, the re-run succeeds, and re-loading the same file later applies the overrides without prompting again.

---

## Prompt 7: Run summary panel, column inventory

Build the run summary panel from the core's run summary object. Render the column inventory as a table: column name, question text where present, classification, and question type where applicable.

Group by classification with counts in the group headings. Questions first, then demographics, then quality, metadata and open-ends.

Render disposition counts from the status column as a small standalone block, clearly separated from the question tables so it cannot be mistaken for survey results.

The panel is available from the result screen. It does not open automatically.

Verify against the PureSpectrum file: all 42 columns appear, each with a classification, and the status column appears under metadata rather than as a question.

---

## Prompt 8: Quality and verification statements

Add two statements to the run summary panel, rendered whenever the panel is open, including when there is nothing unusual to report.

Quality flag availability. For a vendor with a flag, name the column and state that straightliner exclusion is available. For PureSpectrum, state that this vendor supplies no quality flag and straightliner exclusion is therefore unavailable for this file.

Verification status. For Rakuten, state that the vendor verification sheet was present and used. For PureSpectrum, state that no vendor verification sheet was present, so topline figures have not been cross-checked against a vendor tabulation.

Style both as standing statements in the panel's normal text treatment. Do not style them as warnings, do not use a red or amber treatment, and do not render them conditionally on something being wrong. A caveat that only appears on exception gets read as an alarm and dismissed. One that is always present gets read as a fact.

Also render the list of questions resolved by project override, with their timestamps, and any notices the core raised.

Verify both vendors produce both statements.

---

## Prompt 9: Non-substantive response settings

Add the project settings controls for non-substantive responses: an editable list of labels defaulting to prefer not to say, don't know, and not applicable, and a toggle for excluding them from the base, defaulting to off.

Beside the toggle, one line stating plainly what changes: excluding these responses removes them from the base, so every percentage in the report is calculated on a smaller number of people and will read higher.

Changing either setting invalidates the current result and requires a re-run. Say so at the point of change rather than letting a stale result sit on screen next to a changed setting.

Ensure the base appears on every table and chart regardless of the toggle state. That comes from the core, so this prompt only confirms it renders.

Verify with the traffic law S7 question: toggling the setting on and re-running produces a lower base and higher percentages, with the base visible in both states.
