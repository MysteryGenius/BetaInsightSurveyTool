"""
Tests for the Survey -> respondent-level DataFrame converter.

This is a pure reshape: one row per respondent_id, one column per qid,
values taken as-is from Response.raw_value. No netting, no scoring.
"""
from __future__ import annotations

import pandas as pd

from surveytool.core.model import Response, ResponseState, Survey
from surveytool.core.respondent_frame import to_respondent_frame


def _survey(responses: list[Response]) -> Survey:
    return Survey(id="t", n_raw=len({r.respondent_id for r in responses}),
                  n_analysis=len({r.respondent_id for r in responses}),
                  questions=[], responses=responses)


def test_pivots_long_responses_to_wide_respondent_rows():
    survey = _survey([
        Response(respondent_id="r1", qid="q1", raw_value="A", state=ResponseState.answered),
        Response(respondent_id="r1", qid="q2", raw_value=5, state=ResponseState.answered),
        Response(respondent_id="r2", qid="q1", raw_value="B", state=ResponseState.answered),
        Response(respondent_id="r2", qid="q2", raw_value=3, state=ResponseState.answered),
    ])

    frame = to_respondent_frame(survey)

    assert isinstance(frame, pd.DataFrame)
    assert list(frame.index) == ["r1", "r2"]
    assert set(frame.columns) == {"q1", "q2"}
    assert frame.loc["r1", "q1"] == "A"
    assert frame.loc["r1", "q2"] == 5
    assert frame.loc["r2", "q1"] == "B"
    assert frame.loc["r2", "q2"] == 3


def test_missing_response_is_null_not_dropped():
    survey = _survey([
        Response(respondent_id="r1", qid="q1", raw_value="A", state=ResponseState.answered),
        Response(respondent_id="r1", qid="q2", raw_value=5, state=ResponseState.answered),
        Response(respondent_id="r2", qid="q1", raw_value="B", state=ResponseState.answered),
    ])

    frame = to_respondent_frame(survey)

    assert "r2" in frame.index
    assert pd.isna(frame.loc["r2", "q2"])
