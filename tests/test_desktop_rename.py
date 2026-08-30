"""
Rename-survey-id integration test (Round C, Task C5).

Renaming a survey_id must migrate every per-survey-keyed file (overrides,
settings, display order) to the new key in one atomic operation: refuse
(never merge) onto an existing survey_id, and if migration can't complete
partway through, roll every already-moved file back so the old survey_id
is left 100% intact.

Follows test_desktop_upload.py's/test_desktop_resolve.py's fixture/client
conventions: a bare TestClient fixture, real Rakuten fixture file, and
survey_id-scoped uploads. Storage dirs (_OVERRIDES_DIR, _DISPLAY_ORDER_DIR)
are isolated into tmp_path by the autouse fixture in tests/conftest.py, so
tests here don't need to manage that themselves.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).parent.parent
RAKUTEN_PATH = ROOT / "rakuten_survey_support_measures_data.xlsx"


@pytest.fixture
def client():
    from surveytool.desktop.app import app
    return TestClient(app)


@pytest.fixture(autouse=True)
def _isolated_settings_storage(tmp_path: Path, monkeypatch):
    """_SETTINGS_DIR (unlike _OVERRIDES_DIR/_DISPLAY_ORDER_DIR) is not
    covered by tests/conftest.py's autouse isolation fixture -- it lives
    under the OS temp dir already, but that directory is shared and
    accumulates real files across the whole suite's history with no
    per-test cleanup. This rename test module writes settings files keyed
    by short, human-chosen ids ('old_id', 'new_id', 'id_a', 'id_b') that
    could collide with a leftover file from a previous run, so give it its
    own tmp_path-scoped settings dir too."""
    from surveytool.desktop import app as appmod

    monkeypatch.setattr(appmod, "_SETTINGS_DIR", tmp_path / "settings")


def _upload(client, survey_id: str):
    with open(RAKUTEN_PATH, "rb") as f:
        return client.post(
            "/api/upload",
            data={"vendor": "rakuten", "survey_id": survey_id},
            files={"file": (RAKUTEN_PATH.name, f,
                             "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )


def _resolve_q1_to_categorical(client, session_id: str):
    return client.post(
        f"/api/session/{session_id}/resolve",
        json={
            "resolutions": [
                {"variable": "Q1", "question_type": "categorical", "label_roles": {}},
            ]
        },
    )


@pytest.fixture
def uploaded_session_with_overrides(client):
    """Uploads the real Rakuten fixture under survey_id 'old_id' and saves
    an override for Q1 via the resolve endpoint, mirroring
    test_desktop_resolve.py's test_resolve_writes_override_and_rerun_applies_it.
    """
    if not RAKUTEN_PATH.exists():
        pytest.skip(f"{RAKUTEN_PATH.name} not found in project root")

    upload_response = _upload(client, "old_id")
    assert upload_response.status_code == 200, upload_response.text
    session_id = upload_response.json()["session_id"]

    resolve_response = _resolve_q1_to_categorical(client, session_id)
    assert resolve_response.status_code == 200, resolve_response.text

    return session_id


@pytest.fixture
def two_uploaded_sessions(client):
    """Uploads the real Rakuten fixture under two distinct survey_ids,
    'id_a' and 'id_b', each with a saved override, so a rename of one onto
    the other's id is a genuine collision against real saved data."""
    if not RAKUTEN_PATH.exists():
        pytest.skip(f"{RAKUTEN_PATH.name} not found in project root")

    upload_a = _upload(client, "id_a")
    assert upload_a.status_code == 200, upload_a.text
    session_a = upload_a.json()["session_id"]
    resolve_a = _resolve_q1_to_categorical(client, session_a)
    assert resolve_a.status_code == 200, resolve_a.text

    upload_b = _upload(client, "id_b")
    assert upload_b.status_code == 200, upload_b.text
    session_b = upload_b.json()["session_id"]
    resolve_b = _resolve_q1_to_categorical(client, session_b)
    assert resolve_b.status_code == 200, resolve_b.text

    return session_a, session_b


def test_rename_migrates_overrides_and_reload_still_applies(client, uploaded_session_with_overrides):
    response = client.post("/api/projects/old_id/rename", json={"new_survey_id": "new_id"})
    assert response.status_code == 200, response.text

    from surveytool.desktop.app import _project_overrides_path
    from surveytool.ingest.overrides import load_overrides

    assert not _project_overrides_path("old_id").exists()
    new_overrides = load_overrides(_project_overrides_path("new_id"))
    assert len(new_overrides.overrides) > 0

    # A fresh upload under the new id applies the migrated override with no
    # resolver prompt needed -- proof the migration is functionally real,
    # not just a file on disk that nothing reads.
    second_upload = _upload(client, "new_id")
    assert second_upload.status_code == 200, second_upload.text
    from surveytool.desktop.app import get_session
    second_session = get_session(second_upload.json()["session_id"])
    q1_second = next(q for q in second_session.survey.questions if q.qid == "Q1")
    assert q1_second.qtype.value == "categorical"


def test_rename_migrates_display_order(client, uploaded_session_with_overrides):
    """Round C3's per-survey display-order store must migrate too, not just
    overrides -- this is the third per-survey-keyed directory the brief
    calls out explicitly."""
    from datetime import datetime, timezone

    from surveytool.desktop.app import _project_display_order_path
    from surveytool.ingest.display_order import DisplayOrder, write_display_order

    order = DisplayOrder(
        variable="Q1", label_order=["b", "a"], is_manual=True, saved_at=datetime.now(timezone.utc)
    )
    write_display_order(_project_display_order_path("old_id"), order)

    response = client.post("/api/projects/old_id/rename", json={"new_survey_id": "new_id"})
    assert response.status_code == 200, response.text

    assert not _project_display_order_path("old_id").exists()

    from surveytool.ingest.display_order import load_display_orders
    orders = load_display_orders(_project_display_order_path("new_id"))
    assert orders.orders["Q1"].label_order == ["b", "a"]


def test_rename_onto_existing_survey_id_is_refused(client, two_uploaded_sessions):
    response = client.post("/api/projects/id_a/rename", json={"new_survey_id": "id_b"})
    assert response.status_code == 400
    body = response.json()
    message = body["error"]["message"].lower()
    assert "already" in message or "exists" in message

    # Original must be untouched -- refusal never merges the two.
    from surveytool.desktop.app import _project_overrides_path
    from surveytool.ingest.overrides import load_overrides

    assert _project_overrides_path("id_a").exists()
    assert _project_overrides_path("id_b").exists()
    a_overrides = load_overrides(_project_overrides_path("id_a"))
    b_overrides = load_overrides(_project_overrides_path("id_b"))
    assert len(a_overrides.overrides) > 0
    assert len(b_overrides.overrides) > 0


def test_rename_with_invalid_new_id_is_refused_and_leaves_original_intact(client, uploaded_session_with_overrides):
    response = client.post("/api/projects/old_id/rename", json={"new_survey_id": "not valid! id"})
    assert response.status_code == 400

    from surveytool.desktop.app import _project_overrides_path
    from surveytool.ingest.overrides import load_overrides

    assert _project_overrides_path("old_id").exists()
    old_overrides = load_overrides(_project_overrides_path("old_id"))
    assert len(old_overrides.overrides) > 0


def test_rename_with_invalid_old_id_is_refused(client):
    """The old survey_id in the URL path is also validated -- a malformed
    old id (e.g. containing path-traversal characters) must be rejected
    before any filesystem lookup happens, exactly like every other
    survey_id-keyed endpoint."""
    response = client.post("/api/projects/not%20valid/rename", json={"new_survey_id": "new_id"})
    assert response.status_code == 400


def test_rename_rollback_on_mid_migration_failure_leaves_original_intact(client, uploaded_session_with_overrides, monkeypatch):
    """Simulates a failure partway through the multi-file migration (the
    second file's rename raises OSError) and confirms every file already
    moved is moved back -- the old survey_id must be left 100% intact with
    nothing left behind under the new id. This is the whole point of the
    atomic-migration guarantee, so it must be exercised by an actual
    simulated failure, not just asserted in a docstring.
    """
    from surveytool.desktop.app import _project_overrides_path, _project_settings_path
    from surveytool.core.config import ToolConfig
    from surveytool.desktop.app import _save_project_settings
    from surveytool.ingest.overrides import load_overrides

    # Give old_id a second per-survey file (settings) so there are at least
    # two files to migrate -- the failure is simulated on the second rename
    # call, after the first has already succeeded, so a genuine rollback of
    # an already-moved file is exercised.
    _save_project_settings("old_id", ToolConfig())
    assert _project_settings_path("old_id").exists()

    original_rename = Path.rename
    call_count = {"n": 0}

    def flaky_rename(self, target):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise OSError("simulated failure on second file migration")
        return original_rename(self, target)

    monkeypatch.setattr(Path, "rename", flaky_rename)

    response = client.post("/api/projects/old_id/rename", json={"new_survey_id": "new_id"})
    assert response.status_code == 500, response.text
    body = response.json()
    assert "error" in body

    monkeypatch.setattr(Path, "rename", original_rename)

    # Old id must be 100% intact: both files still present with their
    # original content.
    assert _project_overrides_path("old_id").exists()
    assert _project_settings_path("old_id").exists()
    old_overrides = load_overrides(_project_overrides_path("old_id"))
    assert len(old_overrides.overrides) > 0

    # New id must have nothing left behind from the partial migration.
    assert not _project_overrides_path("new_id").exists()
    assert not _project_settings_path("new_id").exists()
