"""
Run summary panel integration test (UI build prompt 7).

Confirms the /run-summary endpoint against real vendor fixtures: every
column in the file gets a classification (none silently missing), and the
PureSpectrum file's 42-column shape is fully accounted for per prompt 7's
stated verification.
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).parent.parent
RAKUTEN_PATH = ROOT / "rakuten_survey_support_measures_data.xlsx"
TOLUNA_PATH = ROOT / "toluna_survey_misinformation_data.xlsx"
MILIEU_PATH = ROOT / "milieu_survey_coe_data.csv"
PURESPECTRUM_PATH = ROOT / "purespectrum_survey_wcs_data.xlsx"

_XLSX_CT = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@pytest.fixture
def client():
    from surveytool.desktop.app import app
    return TestClient(app)


def _upload_and_get_summary(client, vendor: str, path: Path, content_type: str):
    survey_id = f"run-summary-{vendor}-{uuid.uuid4()}"
    with open(path, "rb") as f:
        response = client.post(
            "/api/upload",
            data={"vendor": vendor, "survey_id": survey_id},
            files={"file": (path.name, f, content_type)},
        )
    assert response.status_code == 200, response.text
    session_id = response.json()["session_id"]
    summary_response = client.get(f"/api/session/{session_id}/run-summary")
    assert summary_response.status_code == 200, summary_response.text
    return summary_response.json()


def test_purespectrum_all_42_columns_classified(client):
    if not PURESPECTRUM_PATH.exists():
        pytest.skip(f"{PURESPECTRUM_PATH.name} not found in project root")

    body = _upload_and_get_summary(client, "purespectrum", PURESPECTRUM_PATH, _XLSX_CT)
    assert len(body["columns"]) == 42
    for col in body["columns"]:
        assert col["classification"] != "unclassified", col

    status_col = next(c for c in body["columns"] if c["column"] == "status")
    assert status_col["classification"] == "metadata"
    assert status_col["question_type"] is None


@pytest.mark.parametrize(
    "vendor,path,content_type",
    [
        ("rakuten", RAKUTEN_PATH, _XLSX_CT),
        ("toluna", TOLUNA_PATH, _XLSX_CT),
        ("milieu", MILIEU_PATH, "text/csv"),
        ("purespectrum", PURESPECTRUM_PATH, _XLSX_CT),
    ],
)
def test_no_unclassified_columns_for_any_vendor(client, vendor, path, content_type):
    if not path.exists():
        pytest.skip(f"{path.name} not found in project root")

    body = _upload_and_get_summary(client, vendor, path, content_type)
    unclassified = [c["column"] for c in body["columns"] if c["classification"] == "unclassified"]
    assert unclassified == [], f"{vendor}: unclassified columns {unclassified}"


def test_run_summary_includes_quality_and_verification_statements(client):
    if not RAKUTEN_PATH.exists():
        pytest.skip(f"{RAKUTEN_PATH.name} not found in project root")

    body = _upload_and_get_summary(client, "rakuten", RAKUTEN_PATH, _XLSX_CT)
    assert body["quality_flag_statement"]
    assert body["verification_statement"]
    assert isinstance(body["override_resolutions"], list)
    assert isinstance(body["notices"], list)


def test_run_summary_not_available_before_upload(client):
    response = client.get("/api/session/nonexistent-session/run-summary")
    assert response.status_code == 404


def test_run_summary_lists_override_resolutions_with_timestamps(client):
    if not RAKUTEN_PATH.exists():
        pytest.skip(f"{RAKUTEN_PATH.name} not found in project root")

    survey_id = f"run-summary-override-{uuid.uuid4()}"
    with open(RAKUTEN_PATH, "rb") as f:
        upload_response = client.post(
            "/api/upload",
            data={"vendor": "rakuten", "survey_id": survey_id},
            files={"file": (RAKUTEN_PATH.name, f, _XLSX_CT)},
        )
    session_id = upload_response.json()["session_id"]

    resolve_response = client.post(
        f"/api/session/{session_id}/resolve",
        json={"resolutions": [{"variable": "Q1", "question_type": "categorical", "label_roles": {}}]},
    )
    assert resolve_response.status_code == 200, resolve_response.text
    new_session_id = resolve_response.json()["session_id"]

    body = client.get(f"/api/session/{new_session_id}/run-summary").json()
    resolutions = body["override_resolutions"]
    assert len(resolutions) == 1
    assert resolutions[0]["variable"] == "Q1"
    assert resolutions[0]["resolved_at"]
