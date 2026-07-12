"""
Fixture: multi-response question.

10 respondents, 3 answer options. Each respondent may select multiple options.
Respondent base = 10 (those asked). Code percentages may exceed 100% in aggregate.
"""
from surveytool.core.model import (
    CodeRole,
    Question,
    QuestionType,
    Response,
    ResponseState,
    ScaleCode,
    Survey,
)

QUESTION = Question(
    qid="q_multi",
    text="Which of the following do you use? (Select all that apply)",
    qtype=QuestionType.multi_response,
    labels=[
        ScaleCode(code="A", label="Option A", role=CodeRole.top),
        ScaleCode(code="B", label="Option B", role=CodeRole.top),
        ScaleCode(code="C", label="Option C", role=CodeRole.top),
    ],
    multi_response_delimiter="; ",
)

# 10 respondents, all asked
# R1: A; B  R2: B; C  R3: A  R4: A; B; C  R5: C
# R6: A; B  R7: B     R8: A; C  R9: B; C  R10: A
# A: R1,R3,R4,R6,R8,R10 = 6  B: R1,R2,R4,R6,R7,R9 = 6  C: R2,R4,R5,R8,R9 = 5
# Base = 10. A%=60, B%=60, C%=50. Total = 170% (exceeds 100 in aggregate).

SELECTIONS: dict[str, list[str]] = {
    "R01": ["A", "B"],
    "R02": ["B", "C"],
    "R03": ["A"],
    "R04": ["A", "B", "C"],
    "R05": ["C"],
    "R06": ["A", "B"],
    "R07": ["B"],
    "R08": ["A", "C"],
    "R09": ["B", "C"],
    "R10": ["A"],
}

RESPONDENT_BASE = 10  # all asked

EXPECTED = {
    "A": 6 / 10 * 100,  # 60.0
    "B": 6 / 10 * 100,  # 60.0
    "C": 5 / 10 * 100,  # 50.0
}
EXPECTED_AGGREGATE_TOTAL = sum(EXPECTED.values())  # 170.0 > 100
