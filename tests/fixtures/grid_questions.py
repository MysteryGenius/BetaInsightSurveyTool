"""
Fixture: grid questions share a grid_group id.

Three sub-items share the stem "How important is it that the government...".
They must all carry the same grid_group and be retrievable as a group.
"""
from surveytool.core.model import CodeRole, Question, QuestionType, ScaleCode

GRID_GROUP_ID = "grid_gov_importance"

COMMON_LABELS = [
    ScaleCode(code=1, label="Very Important", role=CodeRole.top, numeric_value=1),
    ScaleCode(code=2, label="Important", role=CodeRole.top, numeric_value=2),
    ScaleCode(code=3, label="Neutral", role=CodeRole.neutral, numeric_value=3),
    ScaleCode(code=4, label="Not Important", role=CodeRole.bottom, numeric_value=4),
    ScaleCode(code=5, label="Not At All Important", role=CodeRole.bottom, numeric_value=5),
]

GRID_QUESTIONS = [
    Question(
        qid="q_gov_1",
        text="How important is it that the government... provides healthcare",
        qtype=QuestionType.scale,
        labels=COMMON_LABELS,
        grid_group=GRID_GROUP_ID,
        scale_family="importance",
    ),
    Question(
        qid="q_gov_2",
        text="How important is it that the government... provides education",
        qtype=QuestionType.scale,
        labels=COMMON_LABELS,
        grid_group=GRID_GROUP_ID,
        scale_family="importance",
    ),
    Question(
        qid="q_gov_3",
        text="How important is it that the government... ensures housing",
        qtype=QuestionType.scale,
        labels=COMMON_LABELS,
        grid_group=GRID_GROUP_ID,
        scale_family="importance",
    ),
]

UNRELATED_QUESTION = Question(
    qid="q_other",
    text="How satisfied are you overall?",
    qtype=QuestionType.scale,
    labels=[
        ScaleCode(code=1, label="Very Satisfied", role=CodeRole.top, numeric_value=1),
        ScaleCode(code=2, label="Satisfied", role=CodeRole.top, numeric_value=2),
        ScaleCode(code=3, label="Neutral", role=CodeRole.neutral, numeric_value=3),
        ScaleCode(code=4, label="Dissatisfied", role=CodeRole.bottom, numeric_value=4),
        ScaleCode(code=5, label="Very Dissatisfied", role=CodeRole.bottom, numeric_value=5),
    ],
    grid_group=None,
    scale_family="satisfaction",
)

ALL_QUESTIONS = GRID_QUESTIONS + [UNRELATED_QUESTION]
