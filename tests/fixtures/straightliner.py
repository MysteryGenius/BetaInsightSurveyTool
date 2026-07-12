"""
Fixture: straightliner detection.

10 respondents, 4 scale questions.
R01, R05, R08 straight-line (all same value across all 4 questions).
The remaining 7 show variance.
"""
from surveytool.core.model import CodeRole, Question, QuestionType, Response, ResponseState, ScaleCode

SCALE_LABELS = [
    ScaleCode(code=1, label="Strongly Agree", role=CodeRole.top, numeric_value=1),
    ScaleCode(code=2, label="Agree", role=CodeRole.top, numeric_value=2),
    ScaleCode(code=3, label="Neutral", role=CodeRole.neutral, numeric_value=3),
    ScaleCode(code=4, label="Disagree", role=CodeRole.bottom, numeric_value=4),
    ScaleCode(code=5, label="Strongly Disagree", role=CodeRole.bottom, numeric_value=5),
]

QUESTIONS = [
    Question(qid="sq1", text="Item 1", qtype=QuestionType.scale, labels=SCALE_LABELS, scale_family="agreement"),
    Question(qid="sq2", text="Item 2", qtype=QuestionType.scale, labels=SCALE_LABELS, scale_family="agreement"),
    Question(qid="sq3", text="Item 3", qtype=QuestionType.scale, labels=SCALE_LABELS, scale_family="agreement"),
    Question(qid="sq4", text="Item 4", qtype=QuestionType.scale, labels=SCALE_LABELS, scale_family="agreement"),
]

# (respondent_id, sq1, sq2, sq3, sq4)
_DATA = [
    ("R01", 3, 3, 3, 3),   # straight-liner
    ("R02", 1, 2, 3, 4),   # varies
    ("R03", 2, 3, 2, 4),   # varies
    ("R04", 1, 1, 2, 1),   # varies (not all same)
    ("R05", 5, 5, 5, 5),   # straight-liner
    ("R06", 2, 3, 4, 2),   # varies
    ("R07", 1, 2, 1, 3),   # varies
    ("R08", 2, 2, 2, 2),   # straight-liner
    ("R09", 3, 4, 3, 2),   # varies
    ("R10", 1, 3, 5, 2),   # varies
]

RESPONSES: list[Response] = []
for rid, v1, v2, v3, v4 in _DATA:
    for qid, val in zip(["sq1", "sq2", "sq3", "sq4"], [v1, v2, v3, v4]):
        RESPONSES.append(
            Response(respondent_id=rid, qid=qid, raw_value=val, state=ResponseState.answered)
        )

EXPECTED_FLAGGED = {"R01", "R05", "R08"}
