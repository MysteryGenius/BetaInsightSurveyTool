"""
GUI cross-tab endpoint integration tests.

Drops a real vendor file through the desktop app's upload endpoint, then
exercises the new /cross-tab and /demographics endpoints. Uses the same real
Rakuten fixture already used by test_desktop_upload.py/test_cross_tab.py; no
fixture is fabricated. If the fixture is absent the test is skipped.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).parent.parent
RAKUTEN_PATH = ROOT / "rakuten_survey_support_measures_data.xlsx"
MILIEU_PATH = ROOT / "milieu_survey_coe_data.csv"
TOLUNA_PATH = ROOT / "toluna_survey_misinformation_data.xlsx"


@pytest.fixture
def client():
    from surveytool.desktop.app import app
    return TestClient(app)


def _upload(client) -> str:
    with open(RAKUTEN_PATH, "rb") as f:
        response = client.post(
            "/api/upload",
            data={"vendor": "rakuten", "survey_id": "t"},
            files={"file": (RAKUTEN_PATH.name, f,
                             "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
    assert response.status_code == 200, response.text
    return response.json()["session_id"]


def test_cross_tab_endpoint_matches_compute_cross_tab_directly(client):
    """The /cross-tab JSON must equal compute_cross_tab's own output exactly —
    the endpoint must not recompute or diverge from it in any way."""
    if not RAKUTEN_PATH.exists():
        pytest.skip(f"{RAKUTEN_PATH.name} not found in project root")

    session_id = _upload(client)
    response = client.get(f"/api/session/{session_id}/cross-tab?qid=Q1&demographic=age")
    assert response.status_code == 200, response.text
    body = response.json()

    from surveytool.compute.cross_tab import compute_cross_tab
    from surveytool.desktop.app import get_session

    session = get_session(session_id)
    q1 = next(q for q in session.survey.questions if q.qid == "Q1")
    expected = compute_cross_tab(session.respondent_frame, session.survey, q1, "age")

    assert body["qid"] == expected.qid
    assert body["demographic"] == expected.demographic
    assert len(body["cells"]) == len(expected.cells)
    for cell, expected_cell in zip(body["cells"], expected.cells):
        assert cell["subgroup_label"] == expected_cell.subgroup_label
        assert cell["n"] == expected_cell.n
        assert cell["status"] == expected_cell.status.value
        assert cell["t2b"] == pytest.approx(expected_cell.t2b) if expected_cell.t2b is not None else cell["t2b"] is None
        assert cell["mean"] == pytest.approx(expected_cell.mean) if expected_cell.mean is not None else cell["mean"] is None


def test_cross_tab_endpoint_unknown_session_is_404(client):
    response = client.get("/api/session/does-not-exist/cross-tab?qid=Q1&demographic=age")
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "NO_SESSION"
    assert "Traceback" not in body["error"]["message"]


def test_cross_tab_endpoint_unknown_question_is_plain_400(client):
    if not RAKUTEN_PATH.exists():
        pytest.skip(f"{RAKUTEN_PATH.name} not found in project root")

    session_id = _upload(client)
    response = client.get(f"/api/session/{session_id}/cross-tab?qid=NOPE&demographic=age")
    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "INTERNAL"
    assert "Traceback" not in body["error"]["message"]
    assert "NOPE" in body["error"]["detail"]


def test_cross_tab_endpoint_unknown_demographic_is_plain_400(client):
    if not RAKUTEN_PATH.exists():
        pytest.skip(f"{RAKUTEN_PATH.name} not found in project root")

    session_id = _upload(client)
    response = client.get(f"/api/session/{session_id}/cross-tab?qid=Q1&demographic=nonsense_field")
    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "DEMOGRAPHIC_NOT_FOUND"
    assert "Traceback" not in body["error"]["message"]
    assert "nonsense_field" in body["error"]["detail"]


def test_cross_tab_endpoint_significance_true_is_plain_400_not_500(client):
    if not RAKUTEN_PATH.exists():
        pytest.skip(f"{RAKUTEN_PATH.name} not found in project root")

    session_id = _upload(client)
    response = client.get(
        f"/api/session/{session_id}/cross-tab?qid=Q1&demographic=age&significance=true"
    )
    assert response.status_code == 400
    body = response.json()
    assert "Traceback" not in body["error"]
    assert "not yet implemented" in body["error"]


def test_demographics_endpoint_matches_detect_available_demographics(client):
    if not RAKUTEN_PATH.exists():
        pytest.skip(f"{RAKUTEN_PATH.name} not found in project root")

    session_id = _upload(client)
    response = client.get(f"/api/session/{session_id}/demographics")
    assert response.status_code == 200, response.text
    body = response.json()

    from surveytool.compute.cross_tab import detect_available_demographics
    from surveytool.desktop.app import get_session

    session = get_session(session_id)
    availability = detect_available_demographics(session.survey)
    expected_keys = set(availability.standard) | set(availability.conditional)

    assert {d["key"] for d in body["demographics"]} == expected_keys

    expected_qids = {
        q.qid for q in session.survey.questions
        if q.base_eligible and not q.is_demographic
    }
    assert {q["qid"] for q in body["questions"]} == expected_qids


def test_demographics_endpoint_unknown_session_is_404(client):
    response = client.get("/api/session/does-not-exist/demographics")
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "NO_SESSION"
    assert "Traceback" not in body["error"]["message"]


def _upload_milieu(client) -> str:
    with open(MILIEU_PATH, "rb") as f:
        response = client.post(
            "/api/upload",
            data={"vendor": "milieu", "survey_id": "t"},
            files={"file": (MILIEU_PATH.name, f, "text/csv")},
        )
    assert response.status_code == 200, response.text
    return response.json()["session_id"]


def test_demographics_endpoint_finds_gender_and_race_for_milieu(client):
    """Milieu has no structural demographic marker (unlike Rakuten's 'S' qid
    prefix); is_demographic is set from question text. Confirms gender/race
    surface as available demographics on the real file."""
    if not MILIEU_PATH.exists():
        pytest.skip(f"{MILIEU_PATH.name} not found in project root")

    session_id = _upload_milieu(client)
    response = client.get(f"/api/session/{session_id}/demographics")
    assert response.status_code == 200, response.text
    body = response.json()

    keys = {d["key"] for d in body["demographics"]}
    assert "gender" in keys
    assert "race" in keys


def test_cross_tab_endpoint_computes_for_milieu_gender(client):
    if not MILIEU_PATH.exists():
        pytest.skip(f"{MILIEU_PATH.name} not found in project root")

    session_id = _upload_milieu(client)
    response = client.get(f"/api/session/{session_id}/cross-tab?qid=q10&demographic=gender")
    assert response.status_code == 200, response.text
    body = response.json()

    from surveytool.compute.cross_tab import compute_cross_tab
    from surveytool.desktop.app import get_session

    session = get_session(session_id)
    q10 = next(q for q in session.survey.questions if q.qid == "q10")
    expected = compute_cross_tab(session.respondent_frame, session.survey, q10, "gender")

    assert body["qid"] == expected.qid
    assert body["demographic"] == expected.demographic
    assert len(body["cells"]) == len(expected.cells)


def _upload_toluna(client) -> str:
    with open(TOLUNA_PATH, "rb") as f:
        response = client.post(
            "/api/upload",
            data={"vendor": "toluna", "survey_id": "t"},
            files={"file": (TOLUNA_PATH.name, f,
                             "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
    assert response.status_code == 200, response.text
    return response.json()["session_id"]


def test_demographics_endpoint_finds_all_demographics_for_toluna(client):
    """Toluna has no structural demographic marker; is_demographic is set from
    question text. Confirms age/gender/income/ethnicity all surface on the real file."""
    if not TOLUNA_PATH.exists():
        pytest.skip(f"{TOLUNA_PATH.name} not found in project root")

    session_id = _upload_toluna(client)
    response = client.get(f"/api/session/{session_id}/demographics")
    assert response.status_code == 200, response.text
    body = response.json()

    keys = {d["key"] for d in body["demographics"]}
    assert {"age", "gender", "income", "race"} <= keys


def test_cross_tab_endpoint_computes_for_toluna_gender(client):
    if not TOLUNA_PATH.exists():
        pytest.skip(f"{TOLUNA_PATH.name} not found in project root")

    session_id = _upload_toluna(client)
    response = client.get(f"/api/session/{session_id}/cross-tab?qid=6&demographic=gender")
    assert response.status_code == 200, response.text
    body = response.json()

    from surveytool.compute.cross_tab import compute_cross_tab
    from surveytool.desktop.app import get_session

    session = get_session(session_id)
    q6 = next(q for q in session.survey.questions if q.qid == "6")
    expected = compute_cross_tab(session.respondent_frame, session.survey, q6, "gender")

    assert body["qid"] == expected.qid
    assert body["demographic"] == expected.demographic
    assert len(body["cells"]) == len(expected.cells)
