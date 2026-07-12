"""
Fixture: non-substantive response handling.

5-point scale, 5 respondents. R5 selected "Prefer not to answer".
- R5 must be included in the percentage base (they were asked)
- R5 must be excluded from the mean calculation
"""
from surveytool.core.model import (
    CodeRole,
    Question,
    QuestionType,
    Response,
    ResponseState,
    ScaleCode,
)

QUESTION = Question(
    qid="q_ns",
    text="How satisfied are you with the service?",
    qtype=QuestionType.scale,
    labels=[
        ScaleCode(code=1, label="Very Satisfied", role=CodeRole.top, numeric_value=1),
        ScaleCode(code=2, label="Satisfied", role=CodeRole.top, numeric_value=2),
        ScaleCode(code=3, label="Neutral", role=CodeRole.neutral, numeric_value=3),
        ScaleCode(code=4, label="Dissatisfied", role=CodeRole.bottom, numeric_value=4),
        ScaleCode(code=5, label="Very Dissatisfied", role=CodeRole.bottom, numeric_value=5),
        ScaleCode(code=99, label="Prefer not to answer", role=CodeRole.nonsubstantive, numeric_value=None),
    ],
    scale_family="satisfaction",
)

RESPONSES = [
    Response(respondent_id="R1", qid="q_ns", raw_value=1, state=ResponseState.answered),
    Response(respondent_id="R2", qid="q_ns", raw_value=2, state=ResponseState.answered),
    Response(respondent_id="R3", qid="q_ns", raw_value=3, state=ResponseState.answered),
    Response(respondent_id="R4", qid="q_ns", raw_value=4, state=ResponseState.answered),
    Response(respondent_id="R5", qid="q_ns", raw_value=99, state=ResponseState.nonsubstantive),
]

# Base = all 5 respondents (they were all asked, including the non-substantive)
EXPECTED_BASE = 5

# Mean = mean of substantive answered numeric values only: (1+2+3+4)/4 = 2.5
EXPECTED_MEAN = (1 + 2 + 3 + 4) / 4  # 2.5
