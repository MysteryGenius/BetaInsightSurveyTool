import pytest

from surveytool.core.model import CodeRole, Question, QuestionType, ScaleCode
from surveytool.core.netting_gate import NettingNotAllowedError, require_scale_for_netting


def test_question_type_has_binary_and_categorical():
    assert QuestionType.binary.value == "binary"
    assert QuestionType.categorical.value == "categorical"


def test_require_scale_for_netting_passes_for_scale():
    q = Question(
        qid="Q1",
        text="Agreement",
        qtype=QuestionType.scale,
        labels=[
            ScaleCode(code=1, label="Agree", role=CodeRole.top, numeric_value=1),
            ScaleCode(code=2, label="Disagree", role=CodeRole.bottom, numeric_value=2),
        ],
        scale_family="agreement",
    )
    require_scale_for_netting(q, "top_two_box")  # must not raise


def test_require_scale_for_netting_raises_for_binary():
    q = Question(
        qid="S5",
        text="Do you drive?",
        qtype=QuestionType.binary,
        labels=[
            ScaleCode(code=1, label="Yes", role=CodeRole.excluded, numeric_value=1),
            ScaleCode(code=2, label="No", role=CodeRole.excluded, numeric_value=2),
        ],
    )
    with pytest.raises(NettingNotAllowedError) as exc_info:
        require_scale_for_netting(q, "top_two_box")
    assert "S5" in str(exc_info.value)


def test_require_scale_for_netting_raises_for_categorical():
    q = Question(
        qid="Q1",
        text="Which region?",
        qtype=QuestionType.categorical,
        labels=[
            ScaleCode(code=1, label="North", role=CodeRole.excluded, numeric_value=1),
            ScaleCode(code=2, label="South", role=CodeRole.excluded, numeric_value=2),
            ScaleCode(code=3, label="East", role=CodeRole.excluded, numeric_value=3),
        ],
    )
    with pytest.raises(NettingNotAllowedError):
        require_scale_for_netting(q, "top_box")
