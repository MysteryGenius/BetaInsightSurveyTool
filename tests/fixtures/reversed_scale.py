"""
Fixture: reversed-coded scale.

A 5-point agreement scale where code 1 = Strongly Agree (top box)
and code 5 = Strongly Disagree (bottom box). The roles must be resolved
from the label, not from the code value order.
"""
from surveytool.core.model import CodeRole, Question, QuestionType, ScaleCode

LABELS = [
    "Strongly Agree",
    "Agree",
    "Neither Agree Nor Disagree",
    "Disagree",
    "Strongly Disagree",
]

# Code 1 is the top box, code 5 is the bottom — reversed from "high = top" assumption
SCALE_CODES = [
    ScaleCode(code=1, label="Strongly Agree", role=CodeRole.top, numeric_value=1),
    ScaleCode(code=2, label="Agree", role=CodeRole.top, numeric_value=2),
    ScaleCode(code=3, label="Neither Agree Nor Disagree", role=CodeRole.neutral, numeric_value=3),
    ScaleCode(code=4, label="Disagree", role=CodeRole.bottom, numeric_value=4),
    ScaleCode(code=5, label="Strongly Disagree", role=CodeRole.bottom, numeric_value=5),
]

QUESTION = Question(
    qid="q_reversed",
    text="I am satisfied with the outcome.",
    qtype=QuestionType.scale,
    labels=SCALE_CODES,
    scale_direction="descending",  # high code = bottom
    scale_family="agreement",
)
