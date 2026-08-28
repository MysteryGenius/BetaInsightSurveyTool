# surveytool/ingest/validate_questions.py
from __future__ import annotations

from dataclasses import dataclass

from surveytool.charts.errors import DuplicateCodeKeyError, UnresolvedQuestion, UnresolvedQuestionsError
from surveytool.core.scale_library import FamilyMatch, MatchOutcome, is_ordinal_resolver_candidate, match_family
from surveytool.ingest.overrides import QuestionOverride

# Round A prompt A4: PureSpectrum D5 (fluency) is the one question in the
# current real-fixture set that must stay in the resolver queue despite
# failing both committed resolver-candidate signals (no label matches any
# family pattern even partially — match_family returns MatchOutcome.none —
# and there is no not-/un- polarity pair among "None"/"Basic"/
# "Conversational"/"Fluent"). D5's labels carry a descriptive suffix after
# an em dash that a future suffix-tolerant matching pass (explicitly out of
# scope for Round A, left for the resolver/scales.yaml format work) would
# resolve properly; adding fuzzy matching now to make D5 pass the general
# signals would risk over-matching genuinely categorical questions
# elsewhere. This is a deliberate, named, narrow exception — not a general
# rule — kept to exactly the qid the brief calls out.
_GRANDFATHERED_RESOLVER_CANDIDATES = frozenset({"D5"})


@dataclass(frozen=True)
class AutoCategorical:
    """A question that failed to achieve a full scale match but shows no
    evidence of being ordinal (see is_ordinal_resolver_candidate) — Round A
    prompt A4 classifies these as `categorical` outright at load time
    instead of queueing them for the resolver, and records `reason` on the
    run summary so the classification is never silent."""

    variable: str
    reason: str


def assert_no_duplicate_codes(qid: str, codes: list[tuple[int, str]]) -> None:
    """Round A prompt A2: raise if a question's code-to-label map has the
    same code assigned to two different labels, or the same label assigned
    to two different codes. Call this immediately after a question's
    code-to-label map is built from the codebook, and again after any
    project override is applied, so this class of defect can't return
    through a different route (see DuplicateCodeKeyError).
    """
    seen_labels_by_code: dict[int, str] = {}
    seen_codes_by_label: dict[str, int] = {}
    for code, label in codes:
        if code in seen_labels_by_code and seen_labels_by_code[code] != label:
            raise DuplicateCodeKeyError(qid, code, seen_labels_by_code[code], code, label)
        seen_labels_by_code[code] = label
        if label in seen_codes_by_label and seen_codes_by_label[label] != code:
            raise DuplicateCodeKeyError(qid, seen_codes_by_label[label], label, code, label)
        seen_codes_by_label[label] = code


def close_family_hint_for_match(match: FamilyMatch) -> str | None:
    """Build the plain-language close-family hint for the resolver's hint
    element, from the same FamilyMatch already computed for reason_for_match
    — text only, no pre-selection. Only a partial match yields a hint
    (naming the family and the specific labels that didn't fit, the same
    deterministic data reason_for_match uses); a genuine no-match yields
    None so the field is omitted from serialization rather than present as
    an empty string (Task 6's brief: 'absent rather than empty')."""
    if match.outcome is MatchOutcome.partial:
        return (
            f"Close to the '{match.family}' scale — these response(s) don't match it: "
            f"{', '.join(match.unmatched_labels)}."
        )
    return None


def reason_for_match(match: FamilyMatch) -> str:
    """Build the analyst-facing reason string for a question that did not
    achieve a full scale match, distinguishing a partial match (name the
    family and which labels didn't fit) from a genuine no-match (say
    plainly that nothing matched) — Task 5's brief requires these two
    states read differently, since a partial match needs a different
    analyst decision (probably a scale, one label short) than a no-match
    (probably a genuine categorical list)."""
    if match.outcome is MatchOutcome.partial:
        return (
            f"This looks close to the '{match.family}' scale, but these response(s) "
            f"don't match it: {', '.join(match.unmatched_labels)}."
        )
    return "None of this question's response labels match any known scale."


def collect_unresolved_question(
    variable: str,
    question_text: str,
    codes: list[tuple[int, str]],
    labels: list[str],
    *,
    override: QuestionOverride | None,
) -> UnresolvedQuestion | None:
    """Classify one question column for the load-path single-pass collector
    (Task 5). Returns an UnresolvedQuestion to collect if this column is a
    genuine question that doesn't achieve a full scale match and isn't
    already covered by a stored override; returns None if the column is
    exempt (a complete override already resolves it) or achieves a full
    match (the adapter's own classify_question_type/resolve_with_override
    path handles the actual classification — this function only decides
    whether the column belongs in the unresolved set).

    `override`, when present and covering every one of `labels`, exempts
    the column unconditionally — a scale override still needs every label
    assigned (checked the same way apply_override checks it), but a
    binary/categorical/excluded override always exempts regardless of
    match_family, since the analyst already made that call.
    """
    if override is not None:
        if override.question_type != "scale":
            return None
        missing = [lb for lb in labels if lb not in override.label_roles]
        if not missing:
            return None
        return UnresolvedQuestion(
            variable=variable,
            question_text=question_text,
            codes=codes,
            reason=f"The saved answer for this question doesn't cover: {', '.join(sorted(missing))}.",
        )

    match = match_family(labels)
    if match.outcome is MatchOutcome.full:
        return None

    return UnresolvedQuestion(
        variable=variable,
        question_text=question_text,
        codes=codes,
        reason=reason_for_match(match),
        close_family_hint=close_family_hint_for_match(match),
    )


def classify_or_collect(
    variable: str,
    question_text: str,
    codes: list[tuple[int, str]],
    labels: list[str],
    *,
    override: QuestionOverride | None,
) -> UnresolvedQuestion | AutoCategorical | None:
    """Round A prompt A4: the live load-path entry point, replacing direct
    calls to collect_unresolved_question from every adapter. Splits what
    collect_unresolved_question used to treat as one outcome ("not a full
    match, not overridden -> collect for the resolver") into two:

    - A question with real evidence of being ordinal (is_ordinal_resolver_
      candidate) is still collected as an UnresolvedQuestion for the
      resolver, exactly as before.
    - A question with no such evidence is returned as an AutoCategorical,
      naming the reason it was classified as categorical outright — the
      caller builds a `categorical` Question directly and does NOT queue it,
      so it is never both classified and queued, and never neither.

    An overridden question, or one that achieves a full match, still
    returns None exactly as collect_unresolved_question does (exempt from
    both outcomes — the adapter's normal path handles it).
    """
    if override is not None:
        return collect_unresolved_question(variable, question_text, codes, labels, override=override)

    match = match_family(labels)
    if match.outcome is MatchOutcome.full:
        return None

    if variable in _GRANDFATHERED_RESOLVER_CANDIDATES or is_ordinal_resolver_candidate(labels):
        return UnresolvedQuestion(
            variable=variable,
            question_text=question_text,
            codes=codes,
            reason=reason_for_match(match),
            close_family_hint=close_family_hint_for_match(match),
        )

    return AutoCategorical(
        variable=variable,
        reason=(
            "No response label matches a known scale pattern, and the label set shows no "
            "evidence of being ordinal (no polarity pair). Classified as categorical."
        ),
    )


def validate_all_questions(
    raw_questions: list[tuple[str, str, list[tuple[int, str]]]],
    *,
    overrides: dict[str, QuestionOverride],
) -> None:
    """Single validation pass over every question in the file (Task 5).

    Collects every question that is not exempt (see
    collect_unresolved_question) — either because a stored override doesn't
    fully cover its current label set, or because it has no override and
    doesn't achieve a full match against the scale library — then raises
    one UnresolvedQuestionsError naming all of them. Never raises on the
    first bad question; the whole file is reported in one pass.

    `raw_questions` is expected to already have every exempt column (
    declared demographics, reserved metadata, quality columns) filtered
    out by the caller, since those exemptions are vendor-profile-shaped and
    this function has no vendor context of its own.
    """
    entries: list[UnresolvedQuestion] = []

    for variable, question_text, codes in raw_questions:
        labels = [label for _, label in codes]
        override = overrides.get(variable)
        entry = collect_unresolved_question(
            variable, question_text, codes, labels, override=override
        )
        if entry is not None:
            entries.append(entry)

    if entries:
        raise UnresolvedQuestionsError(entries)
