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
        # rank 1 = bottom of the scale everywhere in this codebase, so rank
        # ascends from "Very Dissatisfied" (bottom, rank 1) up to "Very
        # Satisfied" (top, rank 5) -- the reverse of numeric_value/code,
        # which follow the vendor's own top-to-bottom response order and
        # are unrelated to rank.
        ScaleCode(code=1, label="Very Satisfied", role=CodeRole.top, numeric_value=1, rank=5),
        ScaleCode(code=2, label="Satisfied", role=CodeRole.top, numeric_value=2, rank=4),
        ScaleCode(code=3, label="Neutral", role=CodeRole.neutral, numeric_value=3, rank=3),
        ScaleCode(code=4, label="Dissatisfied", role=CodeRole.bottom, numeric_value=4, rank=2),
        ScaleCode(code=5, label="Very Dissatisfied", role=CodeRole.bottom, numeric_value=5, rank=1),
        ScaleCode(code=99, label="Prefer not to answer", role=CodeRole.nonsubstantive, numeric_value=None, rank=None),
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

# Mean = mean of substantive answered responses' RANK (not numeric_value/
# code) -- R1..R4 selected codes 1-4 ("Very Satisfied" rank 5, "Satisfied"
# rank 4, "Neutral" rank 3, "Dissatisfied" rank 2), so (5+4+3+2)/4 = 3.5.
# Minor #6 fix: ranks were previously assigned in the same top-to-bottom
# order as code/numeric_value (rank 1 = "Very Satisfied"/top), contradicting
# this codebase's rank-1-is-bottom convention; EXPECTED_MEAN is updated
# here to match the corrected, convention-consistent rank assignment above.
EXPECTED_MEAN = (5 + 4 + 3 + 2) / 4  # 3.5
