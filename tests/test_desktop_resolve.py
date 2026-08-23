"""
Resolver save/write/re-run integration test (UI build prompt 6).

Uploads the real Rakuten fixture, resolves one of its real scale questions
(Q1) to a different classification via the resolve endpoint, and confirms:
the override is written once, the re-run applies it immediately, and a
fresh upload under the same survey_id applies it again without prompting.
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).parent.parent
RAKUTEN_PATH = ROOT / "rakuten_survey_support_measures_data.xlsx"


@pytest.fixture
def client():
    from surveytool.desktop.app import app
    return TestClient(app)


def _upload(client, survey_id: str):
    with open(RAKUTEN_PATH, "rb") as f:
        return client.post(
            "/api/upload",
            data={"vendor": "rakuten", "survey_id": survey_id},
            files={"file": (RAKUTEN_PATH.name, f,
                             "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )


def test_resolve_writes_override_and_rerun_applies_it(client):
    if not RAKUTEN_PATH.exists():
        pytest.skip(f"{RAKUTEN_PATH.name} not found in project root")

    survey_id = f"resolve-test-{uuid.uuid4()}"
    upload_response = _upload(client, survey_id)
    assert upload_response.status_code == 200, upload_response.text
    session_id = upload_response.json()["session_id"]

    from surveytool.desktop.app import get_session
    session = get_session(session_id)
    q1 = next(q for q in session.survey.questions if q.qid == "Q1")
    assert q1.qtype.value == "scale"

    resolve_response = client.post(
        f"/api/session/{session_id}/resolve",
        json={
            "resolutions": [
                {"variable": "Q1", "question_type": "categorical", "label_roles": {}},
            ]
        },
    )
    assert resolve_response.status_code == 200, resolve_response.text
    body = resolve_response.json()
    assert body["session_id"] == session_id

    session_after = get_session(session_id)
    q1_after = next(q for q in session_after.survey.questions if q.qid == "Q1")
    assert q1_after.qtype.value == "categorical"

    # A fresh upload under the same survey_id applies the override again,
    # with no resolver prompt needed.
    second_upload = _upload(client, survey_id)
    assert second_upload.status_code == 200, second_upload.text
    second_session = get_session(second_upload.json()["session_id"])
    q1_second = next(q for q in second_session.survey.questions if q.qid == "Q1")
    assert q1_second.qtype.value == "categorical"


def test_resolve_scale_override_applies_label_roles(client):
    if not RAKUTEN_PATH.exists():
        pytest.skip(f"{RAKUTEN_PATH.name} not found in project root")

    survey_id = f"resolve-scale-test-{uuid.uuid4()}"
    upload_response = _upload(client, survey_id)
    session_id = upload_response.json()["session_id"]

    from surveytool.desktop.app import get_session
    session = get_session(session_id)
    q1 = next(q for q in session.survey.questions if q.qid == "Q1")
    substantive_labels = [sc.label for sc in q1.labels if sc.role.value != "nonsubstantive"]
    assert len(substantive_labels) >= 2

    label_roles = {lb: "top" for lb in substantive_labels}
    label_roles[substantive_labels[-1]] = "bottom"

    resolve_response = client.post(
        f"/api/session/{session_id}/resolve",
        json={"resolutions": [{"variable": "Q1", "question_type": "scale", "label_roles": label_roles}]},
    )
    assert resolve_response.status_code == 200, resolve_response.text

    session_after = get_session(session_id)
    q1_after = next(q for q in session_after.survey.questions if q.qid == "Q1")
    assert q1_after.qtype.value == "scale"
    roles_by_label = {sc.label: sc.role.value for sc in q1_after.labels}
    assert roles_by_label[substantive_labels[-1]] == "bottom"
    assert roles_by_label[substantive_labels[0]] == "top"


def test_resolve_incomplete_scale_override_rejected(client):
    if not RAKUTEN_PATH.exists():
        pytest.skip(f"{RAKUTEN_PATH.name} not found in project root")

    survey_id = f"resolve-incomplete-test-{uuid.uuid4()}"
    upload_response = _upload(client, survey_id)
    session_id = upload_response.json()["session_id"]

    resolve_response = client.post(
        f"/api/session/{session_id}/resolve",
        json={"resolutions": [{"variable": "Q1", "question_type": "scale", "label_roles": {}}]},
    )
    assert resolve_response.status_code == 400
    body = resolve_response.json()
    assert body["error"]["code"] == "UNRESOLVED_SCALE_LABELS"

    from surveytool.desktop.app import get_session
    session_after = get_session(session_id)
    q1_after = next(q for q in session_after.survey.questions if q.qid == "Q1")
    assert q1_after.qtype.value == "scale"


def test_upload_rejects_path_traversal_survey_id(client):
    if not RAKUTEN_PATH.exists():
        pytest.skip(f"{RAKUTEN_PATH.name} not found in project root")

    with open(RAKUTEN_PATH, "rb") as f:
        response = client.post(
            "/api/upload",
            data={"vendor": "rakuten", "survey_id": "../../../../tmp/evil"},
            files={"file": (RAKUTEN_PATH.name, f,
                             "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )

    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "CONFIG_INVALID"


def test_resolve_excluded_classification(client):
    if not RAKUTEN_PATH.exists():
        pytest.skip(f"{RAKUTEN_PATH.name} not found in project root")

    survey_id = f"resolve-excluded-test-{uuid.uuid4()}"
    upload_response = _upload(client, survey_id)
    session_id = upload_response.json()["session_id"]

    resolve_response = client.post(
        f"/api/session/{session_id}/resolve",
        json={"resolutions": [{"variable": "Q1", "question_type": "excluded", "label_roles": {}}]},
    )
    assert resolve_response.status_code == 200, resolve_response.text

    from surveytool.desktop.app import get_session
    session_after = get_session(session_id)
    q1_after = next(q for q in session_after.survey.questions if q.qid == "Q1")
    assert q1_after.qtype.value == "excluded"
    assert q1_after.base_eligible is False
