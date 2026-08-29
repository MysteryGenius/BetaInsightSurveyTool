"""GUI display-order endpoint integration tests (Round C3).

Drops the real Toluna misinformation fixture through the desktop app's
upload endpoint, then exercises the new GET/PUT/DELETE
/api/projects/{survey_id}/display-order/{qid} endpoints and confirms the
manual reorder is picked up by the next /crosstab call -- and, critically,
that reordering never changes any computed figure (t2b/b2b/mean).
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).parent.parent
TOLUNA_PATH = ROOT / "toluna_survey_misinformation_data.xlsx"

_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

_QID = "7_local_mainstream_media"


@pytest.fixture
def client():
    from surveytool.desktop.app import app
    return TestClient(app)


def _upload_toluna(client, survey_id: str) -> str:
    with open(TOLUNA_PATH, "rb") as f:
        response = client.post(
            "/api/upload",
            data={"vendor": "toluna", "survey_id": survey_id},
            files={"file": (TOLUNA_PATH.name, f, _XLSX_MIME)},
        )
    assert response.status_code == 200, response.text
    return response.json()["session_id"]


def test_get_display_order_is_none_when_nothing_saved(client):
    survey_id = "c3-display-order-default"
    _upload_toluna(client, survey_id)
    response = client.get(f"/api/projects/{survey_id}/display-order/{_QID}")
    assert response.status_code == 200, response.text
    assert response.json() is None


def test_put_then_get_display_order_round_trips(client):
    survey_id = "c3-display-order-roundtrip"
    _upload_toluna(client, survey_id)
    label_order = [
        "Likely", "Very Likely", "Neutral / Neither Likely nor Unlikely",
        "Unlikely", "Very Unlikely",
    ]
    put_response = client.put(
        f"/api/projects/{survey_id}/display-order/{_QID}",
        json={"label_order": label_order},
    )
    assert put_response.status_code == 200, put_response.text
    assert put_response.json()["label_order"] == label_order

    get_response = client.get(f"/api/projects/{survey_id}/display-order/{_QID}")
    assert get_response.status_code == 200, get_response.text
    assert get_response.json()["label_order"] == label_order


def test_delete_display_order_resets_and_is_a_noop_when_nothing_saved(client):
    survey_id = "c3-display-order-delete"
    _upload_toluna(client, survey_id)

    # No-op delete when nothing was saved yet.
    response = client.delete(f"/api/projects/{survey_id}/display-order/{_QID}")
    assert response.status_code == 200, response.text
    assert response.json() == {"reset": True}

    client.put(
        f"/api/projects/{survey_id}/display-order/{_QID}",
        json={"label_order": ["A", "B"]},
    )
    delete_response = client.delete(f"/api/projects/{survey_id}/display-order/{_QID}")
    assert delete_response.status_code == 200, delete_response.text

    get_response = client.get(f"/api/projects/{survey_id}/display-order/{_QID}")
    assert get_response.json() is None


def test_reordering_toluna_likelihood_question_preserves_top_two_box(client):
    """C3's core acceptance: reordering never changes any figure.

    Toluna question 7 ("local mainstream media" likelihood item) has a
    known aggregate t2b of 50.2 (computed directly via
    compute_question_stats over the whole population). Because
    compute_breaks_crosstab always slices into break-dimension cells (an
    empty break_spec yields zero columns in this codebase -- there is no
    synthetic 'Total' cell), this test breaks by gender and confirms each
    gender cell's t2b/b2b figures are bit-for-bit identical before and
    after a manual reorder, then confirms delete resets scale_points back
    to rank order.
    """
    if not TOLUNA_PATH.exists():
        pytest.skip(f"{TOLUNA_PATH.name} not found in project root")

    survey_id = "c3-display-order-acceptance"
    session_id = _upload_toluna(client, survey_id)

    manual_order = [
        "Likely", "Very Likely", "Neutral / Neither Likely nor Unlikely",
        "Unlikely", "Very Unlikely",
    ]

    # Baseline figures (before any reorder) to diff against.
    baseline_response = client.post(
        f"/api/session/{session_id}/crosstab",
        json={
            "break_spec": {"dimensions": ["gender"]},
            "filter_spec": {"selections": {}},
            "question_ids": [_QID],
        },
    )
    assert baseline_response.status_code == 200, baseline_response.text
    baseline_result = baseline_response.json()[0]
    assert baseline_result["display_order_is_manual"] is False
    baseline_nets_by_column = {
        tuple(c["label_path"]): c["nets"] for c in baseline_result["columns"]
    }
    baseline_scale_labels = [p["label"] for p in baseline_result["scale_points"]]
    assert baseline_scale_labels == [
        "Very Unlikely", "Unlikely", "Neutral / Neither Likely nor Unlikely",
        "Likely", "Very Likely",
    ]

    reorder_response = client.put(
        f"/api/projects/{survey_id}/display-order/{_QID}",
        json={"label_order": manual_order},
    )
    assert reorder_response.status_code == 200, reorder_response.text

    crosstab_response = client.post(
        f"/api/session/{session_id}/crosstab",
        json={
            "break_spec": {"dimensions": ["gender"]},
            "filter_spec": {"selections": {}},
            "question_ids": [_QID],
        },
    )
    assert crosstab_response.status_code == 200, crosstab_response.text
    result = crosstab_response.json()[0]

    assert result["display_order_is_manual"] is True
    reordered_scale_labels = [p["label"] for p in result["scale_points"]]
    assert reordered_scale_labels == manual_order

    # The load-bearing assertion: every column's t2b/b2b figures are
    # unchanged by the reorder.
    reordered_nets_by_column = {
        tuple(c["label_path"]): c["nets"] for c in result["columns"]
    }
    assert reordered_nets_by_column == baseline_nets_by_column

    # Spot-check the known aggregate figure directly against
    # compute_question_stats over the whole survey (unaffected by any
    # break/display-order concern at all).
    from surveytool.compute.frequency import compute_question_stats
    from surveytool.desktop.app import get_session

    session = get_session(session_id)
    question = next(q for q in session.survey.questions if q.qid == _QID)
    responses = [r for r in session.survey.responses if r.qid == _QID]
    stats = compute_question_stats(question, responses)
    assert round(stats.t2b, 1) == 50.2

    reset_response = client.delete(f"/api/projects/{survey_id}/display-order/{_QID}")
    assert reset_response.status_code == 200, reset_response.text

    crosstab_after_reset = client.post(
        f"/api/session/{session_id}/crosstab",
        json={
            "break_spec": {"dimensions": ["gender"]},
            "filter_spec": {"selections": {}},
            "question_ids": [_QID],
        },
    )
    assert crosstab_after_reset.status_code == 200, crosstab_after_reset.text
    result_after = crosstab_after_reset.json()[0]
    assert result_after["display_order_is_manual"] is False
    scale_point_labels_after = [p["label"] for p in result_after["scale_points"]]
    assert scale_point_labels_after == [
        "Very Unlikely", "Unlikely", "Neutral / Neither Likely nor Unlikely",
        "Likely", "Very Likely",
    ]
