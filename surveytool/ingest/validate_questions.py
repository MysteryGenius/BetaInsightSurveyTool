# surveytool/ingest/validate_questions.py
from __future__ import annotations

from surveytool.charts.errors import UnresolvedQuestion, UnresolvedQuestionsError
from surveytool.ingest.overrides import QuestionOverride


def validate_all_questions(
    raw_questions: list[tuple[str, str, list[tuple[int, str]]]],
    *,
    overrides: dict[str, QuestionOverride],
) -> None:
    """Single validation pass over every question in the file.

    Collects every question whose project override is incomplete (declares
    question_type='scale' but doesn't assign every substantive label a
    role), then raises one UnresolvedQuestionsError naming all of them.
    Questions with no override, or a complete override, pass silently —
    classify_question_type (Phase 2) already handles the no-override case
    without raising, since CATEGORICAL is a legitimate outcome.
    """
    entries: list[UnresolvedQuestion] = []

    for variable, question_text, codes in raw_questions:
        override = overrides.get(variable)
        if override is None:
            continue
        if override.question_type != "scale":
            continue
        substantive_labels = {label for _, label in codes}
        assigned_labels = set(override.label_roles.keys())
        missing = substantive_labels - assigned_labels
        if missing:
            entries.append(
                UnresolvedQuestion(
                    variable=variable,
                    question_text=question_text,
                    codes=codes,
                    reason=f"Override declares this a scale but does not assign a role to: {sorted(missing)}.",
                )
            )

    if entries:
        raise UnresolvedQuestionsError(entries)
