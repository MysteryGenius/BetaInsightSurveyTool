# surveytool/ingest/validate_questions.py
from __future__ import annotations

from surveytool.charts.errors import UnresolvedQuestion, UnresolvedQuestionsError
from surveytool.core.scale_library import FamilyMatch, MatchOutcome, match_family
from surveytool.ingest.overrides import QuestionOverride


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
