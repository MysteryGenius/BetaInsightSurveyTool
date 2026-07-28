"""
GUI file-drop integration test.

Drops a real vendor file through the desktop app's upload endpoint and
confirms the full pipeline runs: findings are built and the canonical
respondent-level DataFrame is retained in session. Uses the real Rakuten
fixture already used by test_cli.py/test_findings.py/test_compute.py; no
fixture is fabricated. If the fixture is absent the test is skipped, not
faked.
"""
from __future__ import annotations

from pathlib import Path

import openpyxl
import pandas as pd
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


def test_drop_real_rakuten_file_runs_full_pipeline_and_retains_dataframe(client):
    if not RAKUTEN_PATH.exists():
        pytest.skip(f"{RAKUTEN_PATH.name} not found in project root")

    with open(RAKUTEN_PATH, "rb") as f:
        response = client.post(
            "/api/upload",
            data={"vendor": "rakuten", "survey_id": "t"},
            files={"file": (RAKUTEN_PATH.name, f,
                             "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["question_count"] > 0
    assert body["n_raw"] > 0

    from surveytool.desktop.app import get_session
    session = get_session(body["session_id"])
    assert session is not None
    assert isinstance(session.respondent_frame, pd.DataFrame)
    assert len(session.respondent_frame) == session.survey.n_raw


def test_drop_real_milieu_file_runs_full_pipeline_and_retains_dataframe(client):
    if not MILIEU_PATH.exists():
        pytest.skip(f"{MILIEU_PATH.name} not found in project root")

    with open(MILIEU_PATH, "rb") as f:
        response = client.post(
            "/api/upload",
            data={"vendor": "milieu", "survey_id": "t"},
            files={"file": (MILIEU_PATH.name, f, "text/csv")},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["question_count"] > 0
    assert body["n_raw"] > 0

    from surveytool.desktop.app import get_session
    session = get_session(body["session_id"])
    assert session is not None
    assert isinstance(session.respondent_frame, pd.DataFrame)
    assert len(session.respondent_frame) == session.survey.n_raw


def test_drop_real_toluna_file_runs_full_pipeline_and_retains_dataframe(client):
    if not TOLUNA_PATH.exists():
        pytest.skip(f"{TOLUNA_PATH.name} not found in project root")

    with open(TOLUNA_PATH, "rb") as f:
        response = client.post(
            "/api/upload",
            data={"vendor": "toluna", "survey_id": "t"},
            files={"file": (TOLUNA_PATH.name, f,
                             "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["question_count"] > 0
    assert body["n_raw"] > 0

    from surveytool.desktop.app import get_session
    session = get_session(body["session_id"])
    assert session is not None
    assert isinstance(session.respondent_frame, pd.DataFrame)
    assert len(session.respondent_frame) == session.survey.n_raw


def test_missing_vendor_choice_is_a_loud_plain_error_not_a_traceback(client):
    if not RAKUTEN_PATH.exists():
        pytest.skip(f"{RAKUTEN_PATH.name} not found in project root")

    with open(RAKUTEN_PATH, "rb") as f:
        response = client.post(
            "/api/upload",
            data={"vendor": "not-a-vendor", "survey_id": "t"},
            files={"file": (RAKUTEN_PATH.name, f,
                             "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )

    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "VENDOR_MISMATCH"
    assert "Traceback" not in body["error"]["message"]
    assert "not-a-vendor" in body["error"]["detail"]


def test_toluna_file_with_rakuten_selected_is_vendor_mismatch_not_missing_sheet(client):
    if not TOLUNA_PATH.exists():
        pytest.skip(f"{TOLUNA_PATH.name} not found in project root")

    with open(TOLUNA_PATH, "rb") as f:
        response = client.post(
            "/api/upload",
            data={"vendor": "rakuten", "survey_id": "t"},
            files={"file": (TOLUNA_PATH.name, f,
                             "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )

    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "VENDOR_MISMATCH"
    assert "Toluna" in body["error"]["message"]
    assert "Rakuten" in body["error"]["message"]


def test_rakuten_file_with_toluna_selected_is_vendor_mismatch_not_file_unreadable(client):
    if not RAKUTEN_PATH.exists():
        pytest.skip(f"{RAKUTEN_PATH.name} not found in project root")

    with open(RAKUTEN_PATH, "rb") as f:
        response = client.post(
            "/api/upload",
            data={"vendor": "toluna", "survey_id": "t"},
            files={"file": (RAKUTEN_PATH.name, f,
                             "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )

    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "VENDOR_MISMATCH"
    assert "Rakuten" in body["error"]["message"]
    assert "Toluna" in body["error"]["message"]


def test_real_rakuten_file_with_datamap_renamed_is_still_missing_sheet(client, tmp_path):
    """A genuinely mishandled real file (not a vendor swap) must still hit MISSING_SHEET."""
    if not RAKUTEN_PATH.exists():
        pytest.skip(f"{RAKUTEN_PATH.name} not found in project root")

    wb = openpyxl.load_workbook(RAKUTEN_PATH)
    wb["Datamap"].title = "DatamapX"
    mangled_path = tmp_path / "rakuten_datamap_renamed.xlsx"
    wb.save(mangled_path)
    wb.close()

    with open(mangled_path, "rb") as f:
        response = client.post(
            "/api/upload",
            data={"vendor": "rakuten", "survey_id": "t"},
            files={"file": (mangled_path.name, f,
                             "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )

    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "MISSING_SHEET"
