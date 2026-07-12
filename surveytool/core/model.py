from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Literal

from pydantic import BaseModel, model_validator


class QuestionType(str, Enum):
    scale = "scale"
    single_choice = "single_choice"
    multi_response = "multi_response"
    numeric_open = "numeric_open"
    text_open = "text_open"
    demographic = "demographic"


class CodeRole(str, Enum):
    top = "top"
    neutral = "neutral"
    bottom = "bottom"
    nonsubstantive = "nonsubstantive"
    excluded = "excluded"


class ResponseState(str, Enum):
    answered = "answered"
    not_asked = "not_asked"
    item_missing = "item_missing"
    nonsubstantive = "nonsubstantive"


class ScaleCode(BaseModel):
    code: str | int
    label: str
    role: CodeRole
    numeric_value: int | None = None


class Question(BaseModel):
    qid: str
    text: str
    qtype: QuestionType
    labels: list[ScaleCode] = []
    scale_direction: Literal["ascending", "descending"] | None = None
    grid_group: str | None = None
    asked_base: str = "ALL"
    is_demographic: bool = False
    base_eligible: bool = True
    multi_response_delimiter: str | None = None
    scale_family: str | None = None

    @model_validator(mode="after")
    def _scale_must_have_top_and_bottom(self) -> "Question":
        if self.qtype is not QuestionType.scale:
            return self
        roles = {sc.role for sc in self.labels}
        missing = []
        if CodeRole.top not in roles:
            missing.append("top")
        if CodeRole.bottom not in roles:
            missing.append("bottom")
        if missing:
            raise ValueError(
                f"Scale question {self.qid!r} is missing role(s): {missing}. "
                "Assign roles from the scale library before constructing."
            )
        return self


class Response(BaseModel):
    respondent_id: str
    qid: str
    raw_value: str | int | None = None
    state: ResponseState
    vendor_flag: str | None = None


class Survey(BaseModel):
    id: str
    n_raw: int
    n_analysis: int
    date_range: tuple[date, date] | None = None
    base_policy: str = "total_answering"
    questions: list[Question] = []
    responses: list[Response] = []
