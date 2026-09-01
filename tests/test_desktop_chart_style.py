"""GUI chart-style endpoint integration tests (chart style selector).

Drops the real Toluna misinformation fixture through the desktop app's
upload endpoint, then exercises the new GET/PUT/DELETE
/api/projects/{survey_id}/chart-style/{qid} endpoints and confirms the
choice is picked up by the next /crosstab call.
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


def test_get_chart_style_is_none_when_nothing_saved(client):
    if not TOLUNA_PATH.exists():
        pytest.skip(f"{TOLUNA_PATH.name} not found in project root")
    survey_id = "style-default"
    _upload_toluna(client, survey_id)
    response = client.get(f"/api/projects/{survey_id}/chart-style/{_QID}")
    assert response.status_code == 200, response.text
    assert response.json() is None


def test_put_then_get_chart_style_round_trips(client):
    if not TOLUNA_PATH.exists():
        pytest.skip(f"{TOLUNA_PATH.name} not found in project root")
    survey_id = "style-roundtrip"
    _upload_toluna(client, survey_id)
    put_response = client.put(
        f"/api/projects/{survey_id}/chart-style/{_QID}",
        json={"style_name": "cool"},
    )
    assert put_response.status_code == 200, put_response.text
    assert put_response.json()["style_name"] == "cool"

    get_response = client.get(f"/api/projects/{survey_id}/chart-style/{_QID}")
    assert get_response.status_code == 200, get_response.text
    assert get_response.json()["style_name"] == "cool"


def test_put_unknown_style_name_is_refused(client):
    if not TOLUNA_PATH.exists():
        pytest.skip(f"{TOLUNA_PATH.name} not found in project root")
    survey_id = "style-unknown"
    _upload_toluna(client, survey_id)
    response = client.put(
        f"/api/projects/{survey_id}/chart-style/{_QID}",
        json={"style_name": "not_a_real_style"},
    )
    assert response.status_code == 400, response.text
    body = response.json()
    assert "chart style" in body["error"]["message"].lower() or "recognise" in body["error"]["message"].lower()

    get_response = client.get(f"/api/projects/{survey_id}/chart-style/{_QID}")
    assert get_response.json() is None


def test_delete_chart_style_resets_and_is_a_noop_when_nothing_saved(client):
    if not TOLUNA_PATH.exists():
        pytest.skip(f"{TOLUNA_PATH.name} not found in project root")
    survey_id = "style-delete"
    _upload_toluna(client, survey_id)

    response = client.delete(f"/api/projects/{survey_id}/chart-style/{_QID}")
    assert response.status_code == 200, response.text
    assert response.json() == {"reset": True}

    client.put(f"/api/projects/{survey_id}/chart-style/{_QID}", json={"style_name": "warm"})
    delete_response = client.delete(f"/api/projects/{survey_id}/chart-style/{_QID}")
    assert delete_response.status_code == 200, delete_response.text

    get_response = client.get(f"/api/projects/{survey_id}/chart-style/{_QID}")
    assert get_response.json() is None


def test_crosstab_picks_up_saved_chart_style(client):
    if not TOLUNA_PATH.exists():
        pytest.skip(f"{TOLUNA_PATH.name} not found in project root")
    survey_id = "style-crosstab"
    session_id = _upload_toluna(client, survey_id)

    client.put(f"/api/projects/{survey_id}/chart-style/{_QID}", json={"style_name": "high_contrast"})

    crosstab_response = client.post(
        f"/api/session/{session_id}/crosstab",
        json={"break_spec": {"dimensions": ["gender"]}, "filter_spec": {"selections": {}}, "question_ids": [_QID]},
    )
    assert crosstab_response.status_code == 200, crosstab_response.text
    result = crosstab_response.json()[0]
    assert result["chart_style"] == "high_contrast"


def test_crosstab_chart_style_is_none_when_nothing_saved(client):
    if not TOLUNA_PATH.exists():
        pytest.skip(f"{TOLUNA_PATH.name} not found in project root")
    survey_id = "style-crosstab-default"
    session_id = _upload_toluna(client, survey_id)

    crosstab_response = client.post(
        f"/api/session/{session_id}/crosstab",
        json={"break_spec": {"dimensions": ["gender"]}, "filter_spec": {"selections": {}}, "question_ids": [_QID]},
    )
    assert crosstab_response.status_code == 200, crosstab_response.text
    result = crosstab_response.json()[0]
    assert result["chart_style"] is None
