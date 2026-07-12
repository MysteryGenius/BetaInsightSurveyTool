"""
Fixture: routed question bases on asked respondents.

10 respondents total. The question is only asked to those who said
"Yes, I own a car" on a prior question. 6 of 10 own a car; the
question base must be 6, not 10.
"""
from surveytool.core.model import (
    CodeRole,
    Question,
    QuestionType,
    Response,
    ResponseState,
    ScaleCode,
)

SCREENER_QID = "q_car_owner"
ROUTED_QID = "q_car_satisfaction"

ROUTED_QUESTION = Question(
    qid=ROUTED_QID,
    text="How satisfied are you with your car?",
    qtype=QuestionType.scale,
    labels=[
        ScaleCode(code=1, label="Very Satisfied", role=CodeRole.top, numeric_value=1),
        ScaleCode(code=2, label="Satisfied", role=CodeRole.top, numeric_value=2),
        ScaleCode(code=3, label="Neutral", role=CodeRole.neutral, numeric_value=3),
        ScaleCode(code=4, label="Dissatisfied", role=CodeRole.bottom, numeric_value=4),
        ScaleCode(code=5, label="Very Dissatisfied", role=CodeRole.bottom, numeric_value=5),
    ],
    asked_base="q_car_owner == 1",
    scale_family="satisfaction",
)

# 6 respondents own a car (asked), 4 do not (not_asked)
RESPONSES = [
    Response(respondent_id="R01", qid=ROUTED_QID, raw_value=1, state=ResponseState.answered),
    Response(respondent_id="R02", qid=ROUTED_QID, raw_value=2, state=ResponseState.answered),
    Response(respondent_id="R03", qid=ROUTED_QID, raw_value=3, state=ResponseState.answered),
    Response(respondent_id="R04", qid=ROUTED_QID, raw_value=2, state=ResponseState.answered),
    Response(respondent_id="R05", qid=ROUTED_QID, raw_value=1, state=ResponseState.answered),
    Response(respondent_id="R06", qid=ROUTED_QID, raw_value=4, state=ResponseState.answered),
    Response(respondent_id="R07", qid=ROUTED_QID, raw_value=None, state=ResponseState.not_asked),
    Response(respondent_id="R08", qid=ROUTED_QID, raw_value=None, state=ResponseState.not_asked),
    Response(respondent_id="R09", qid=ROUTED_QID, raw_value=None, state=ResponseState.not_asked),
    Response(respondent_id="R10", qid=ROUTED_QID, raw_value=None, state=ResponseState.not_asked),
]

TOTAL_N = 10
EXPECTED_BASE = 6  # those asked, not total N
