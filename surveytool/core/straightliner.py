from __future__ import annotations

from surveytool.core.model import Question, QuestionType, Response, ResponseState


def detect_straightliners(
    responses: list[Response],
    questions: list[Question],
    question_set: list[str] | None = None,
) -> set[str]:
    """
    Return the set of respondent_ids who straight-lined across scale items.

    Default question set: all qtype=scale questions.
    Rule: zero variance across answered values for that set.
    Respondents with fewer than 2 answered items are excluded from flagging.
    """
    if question_set is None:
        scale_qids = {q.qid for q in questions if q.qtype is QuestionType.scale}
    else:
        scale_qids = set(question_set)

    # Build: respondent_id -> list of answered numeric values
    respondent_values: dict[str, list[int]] = {}
    for resp in responses:
        if resp.qid not in scale_qids:
            continue
        if resp.state is not ResponseState.answered:
            continue
        if not isinstance(resp.raw_value, int):
            continue
        respondent_values.setdefault(resp.respondent_id, []).append(resp.raw_value)

    flagged: set[str] = set()
    for rid, values in respondent_values.items():
        if len(values) < 2:
            continue
        if len(set(values)) == 1:
            flagged.add(rid)

    return flagged
