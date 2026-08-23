"""
Regression tests from the code-review pass on the UI build (prompts 1-9).

Two real bugs, both in override handling for Milieu/Toluna (the two
adapters that hand-roll override dispatch instead of using
resolve_with_override, unlike Rakuten/PureSpectrum):

1. Milieu's Grid Single-select branch called _build_scale_question
   unconditionally whenever *any* override existed, regardless of
   override.question_type — a binary/categorical override on a grid
   question raised IncompleteOverrideError instead of applying.
2. Milieu and Toluna's non-scale override branch always built
   QuestionType.single_choice, discarding whether the analyst actually
   chose "binary" or "categorical" in the resolver.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from surveytool.core.model import QuestionType
from surveytool.ingest.overrides import QuestionOverride

ROOT = Path(__file__).parent.parent
MILIEU_PATH = ROOT / "milieu_survey_coe_data.csv"
TOLUNA_PATH = ROOT / "toluna_survey_misinformation_data.xlsx"


def _override(variable: str, question_type: str) -> QuestionOverride:
    return QuestionOverride(
        variable=variable,
        question_type=question_type,
        label_roles={},
        resolved_at=datetime.now(timezone.utc),
        library_version="test",
    )


@pytest.mark.parametrize("question_type", ["binary", "categorical"])
def test_milieu_grid_question_accepts_non_scale_override(question_type):
    """A Milieu grid item overridden to binary/categorical must not raise
    IncompleteOverrideError — the old code always routed grid items through
    _build_scale_question regardless of the override's actual type."""
    if not MILIEU_PATH.exists():
        pytest.skip(f"{MILIEU_PATH.name} not found in project root")

    from surveytool.ingest.milieu import load

    survey = load(MILIEU_PATH, "probe", overrides={"q10": _override("q10", question_type)})
    question = next(q for q in survey.questions if q.qid == "q10")
    assert question.qtype.value == question_type


@pytest.mark.parametrize("question_type", ["binary", "categorical"])
def test_milieu_non_scale_override_preserves_chosen_qtype(question_type):
    """Milieu's Single-select branch must build the override's real
    question_type, not always single_choice."""
    if not MILIEU_PATH.exists():
        pytest.skip(f"{MILIEU_PATH.name} not found in project root")

    from surveytool.ingest.milieu import load

    survey = load(MILIEU_PATH, "probe")
    single_select_qid = next(
        q.qid for q in survey.questions if q.qtype == QuestionType.single_choice
    )

    survey_with_override = load(
        MILIEU_PATH, "probe", overrides={single_select_qid: _override(single_select_qid, question_type)}
    )
    question = next(q for q in survey_with_override.questions if q.qid == single_select_qid)
    assert question.qtype.value == question_type


@pytest.mark.parametrize("question_type", ["binary", "categorical"])
def test_toluna_non_scale_override_preserves_chosen_qtype(question_type):
    """Toluna's non-scale override branch must build the override's real
    question_type, not always single_choice."""
    if not TOLUNA_PATH.exists():
        pytest.skip(f"{TOLUNA_PATH.name} not found in project root")

    from surveytool.ingest.toluna import load

    survey = load(TOLUNA_PATH, "probe")
    single_choice_qid = next(
        q.qid for q in survey.questions if q.qtype == QuestionType.single_choice
    )

    survey_with_override = load(
        TOLUNA_PATH, "probe", overrides={single_choice_qid: _override(single_choice_qid, question_type)}
    )
    question = next(q for q in survey_with_override.questions if q.qid == single_choice_qid)
    assert question.qtype.value == question_type
