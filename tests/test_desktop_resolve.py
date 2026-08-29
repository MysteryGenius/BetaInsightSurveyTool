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


def test_resolve_with_explicit_ranks_persists_and_applies(client):
    """A resolver save that supplies label_ranks explicitly must persist
    those exact ranks (not the position-based backfill apply_override uses
    for a rank-less override) and the re-run session's Question must carry
    them.

    Before this fix, ResolvedQuestionPayload had no label_ranks field, so
    Pydantic silently dropped any label_ranks the client sent — the
    override was written with label_ranks=None and fell through to
    apply_override's position-based backfill instead of using what was
    actually submitted.
    """
    if not RAKUTEN_PATH.exists():
        pytest.skip(f"{RAKUTEN_PATH.name} not found in project root")

    survey_id = f"resolve-explicit-ranks-test-{uuid.uuid4()}"
    upload_response = _upload(client, survey_id)
    session_id = upload_response.json()["session_id"]

    from surveytool.desktop.app import get_session
    session = get_session(session_id)
    q1 = next(q for q in session.survey.questions if q.qid == "Q1")
    substantive_labels = [sc.label for sc in q1.labels if sc.role.value != "nonsubstantive"]
    assert len(substantive_labels) >= 3

    # Assign roles the "wrong way round" relative to label order, and ranks
    # that deliberately do NOT match the position-based backfill
    # apply_override would otherwise compute, so passing this test proves
    # the explicit ranks were actually used, not silently regenerated.
    label_roles = {lb: "top" for lb in substantive_labels}
    label_roles[substantive_labels[0]] = "bottom"
    n = len(substantive_labels)
    # Reverse rank order: first label (bottom) gets the highest rank number
    # here on purpose -- this is a deliberately unusual assignment that a
    # position-based backfill (bottom group first, ascending) would never
    # produce, so a match against it proves the explicit ranks won.
    label_ranks = {lb: n - i for i, lb in enumerate(substantive_labels)}

    resolve_response = client.post(
        f"/api/session/{session_id}/resolve",
        json={
            "resolutions": [
                {
                    "variable": "Q1",
                    "question_type": "scale",
                    "label_roles": label_roles,
                    "label_ranks": label_ranks,
                }
            ]
        },
    )
    assert resolve_response.status_code == 200, resolve_response.text

    # Persisted override on disk carries the exact submitted ranks.
    from surveytool.ingest.overrides import load_overrides
    from surveytool.desktop.app import _project_overrides_path
    saved = load_overrides(_project_overrides_path(survey_id))
    assert saved.overrides["Q1"].label_ranks == label_ranks

    # The re-run session's Question carries those same ranks, not a
    # position-based backfill.
    session_after = get_session(session_id)
    q1_after = next(q for q in session_after.survey.questions if q.qid == "Q1")
    assert q1_after.qtype.value == "scale"
    rank_by_label = {sc.label: sc.rank for sc in q1_after.labels if sc.label in label_ranks}
    assert rank_by_label == label_ranks


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


def test_resolve_scale_override_collapsing_two_codes_onto_one_label_rejected(client):
    """Round A prompt A2 acceptance: applying an override that would
    collapse two codes onto one label raises at write time, before
    anything is persisted. A real vendor file has no such question after
    prompt A1's fix (that was exactly the bug it removed), so this exercises
    the guard by giving the real Rakuten Q1 question a duplicate label under
    two different codes in memory, then calling the real /resolve endpoint
    — same code path an analyst's save goes through, just with the one
    input shape that can no longer occur naturally in a loaded file."""
    if not RAKUTEN_PATH.exists():
        pytest.skip(f"{RAKUTEN_PATH.name} not found in project root")

    survey_id = f"resolve-duplicate-code-test-{uuid.uuid4()}"
    upload_response = _upload(client, survey_id)
    session_id = upload_response.json()["session_id"]

    from surveytool.core.model import ScaleCode
    from surveytool.desktop.app import get_session
    session = get_session(session_id)
    q1 = next(q for q in session.survey.questions if q.qid == "Q1")
    substantive = [sc for sc in q1.labels if sc.role.value != "nonsubstantive"]
    assert len(substantive) >= 2
    # Give the last label the same code as the first, so two different
    # labels ("code -> label" pairs) collide on that one code.
    q1.labels = [
        ScaleCode(code=sc.code, label=sc.label, role=sc.role, numeric_value=sc.numeric_value)
        for sc in substantive[:-1]
    ] + [
        ScaleCode(
            code=substantive[0].code,
            label=substantive[-1].label,
            role=substantive[-1].role,
            numeric_value=substantive[-1].numeric_value,
        )
    ]

    label_roles = {sc.label: "top" for sc in q1.labels}
    label_roles[q1.labels[-1].label] = "bottom"

    from surveytool.ingest.overrides import load_overrides
    from surveytool.desktop.app import _project_overrides_path
    before = load_overrides(_project_overrides_path(survey_id))

    resolve_response = client.post(
        f"/api/session/{session_id}/resolve",
        json={"resolutions": [{"variable": "Q1", "question_type": "scale", "label_roles": label_roles}]},
    )
    assert resolve_response.status_code == 400, resolve_response.text
    body = resolve_response.json()
    assert body["error"]["code"] == "DUPLICATE_CODE_KEY"

    after = load_overrides(_project_overrides_path(survey_id))
    assert after == before  # nothing was persisted


PURESPECTRUM_PATH = ROOT / "purespectrum_survey_wcs_data.xlsx"
_PS_XLSX_CT = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def test_purespectrum_upload_unresolved_produces_a_resolvable_session(client):
    """Round A prompt A8 acceptance: load purespectrum_survey_wcs_data.xlsx,
    resolve D5, save, and get a completed run with D5 treated as a scale.

    Before this fix, an override-free upload that raised
    UnresolvedQuestionsError never created any session at all — the
    resolver panel the client showed had a session_id nowhere to send
    /resolve requests to, and Confirm and Save failed with "No file has
    been uploaded yet." This confirms the working hypothesis directly: the
    upload response's error body now carries a session_id a PendingSession
    was actually registered under, and /resolve against that session_id
    succeeds and re-runs the file with the override applied."""
    if not PURESPECTRUM_PATH.exists():
        pytest.skip(f"{PURESPECTRUM_PATH.name} not found in project root")

    survey_id = f"a8-purespectrum-{uuid.uuid4()}"
    with open(PURESPECTRUM_PATH, "rb") as f:
        upload_response = client.post(
            "/api/upload",
            data={"vendor": "purespectrum", "survey_id": survey_id},
            files={"file": (PURESPECTRUM_PATH.name, f, _PS_XLSX_CT)},
        )
    assert upload_response.status_code == 400, upload_response.text
    body = upload_response.json()
    assert body["error"]["code"] == "UNRESOLVED_SCALE_LABELS"
    unresolved_variables = {e["variable"] for e in body["error"]["detail_entries"]}
    assert unresolved_variables == {"D5"}

    # The critical assertion: the error body carries a session_id a
    # PendingSession actually exists under (not absent, not null).
    session_id = body["error"]["session_id"]
    assert session_id

    from surveytool.desktop.app import _PENDING_SESSIONS, get_session
    assert get_session(session_id) is None  # no full Session yet
    assert session_id in _PENDING_SESSIONS

    d5_entry = next(e for e in body["error"]["detail_entries"] if e["variable"] == "D5")
    d5_labels = [label for _code, label in d5_entry["codes"]]
    label_roles = {
        d5_labels[0]: "bottom",
        d5_labels[1]: "neutral",
        d5_labels[2]: "neutral",
        d5_labels[3]: "top",
    }

    resolve_response = client.post(
        f"/api/session/{session_id}/resolve",
        json={"resolutions": [{"variable": "D5", "question_type": "scale", "label_roles": label_roles}]},
    )
    assert resolve_response.status_code == 200, resolve_response.text
    resolved_body = resolve_response.json()
    assert resolved_body["session_id"] == session_id

    completed_session = get_session(session_id)
    assert completed_session is not None
    d5_question = next(q for q in completed_session.survey.questions if q.qid == "D5")
    assert d5_question.qtype.value == "scale"
    assert session_id not in _PENDING_SESSIONS


def test_purespectrum_saved_override_persists_on_subsequent_load(client):
    """Round A prompt A8 acceptance: the saved override persists and is
    applied on a subsequent load of the same survey ID."""
    if not PURESPECTRUM_PATH.exists():
        pytest.skip(f"{PURESPECTRUM_PATH.name} not found in project root")

    survey_id = f"a8-persist-{uuid.uuid4()}"
    with open(PURESPECTRUM_PATH, "rb") as f:
        upload_response = client.post(
            "/api/upload",
            data={"vendor": "purespectrum", "survey_id": survey_id},
            files={"file": (PURESPECTRUM_PATH.name, f, _PS_XLSX_CT)},
        )
    session_id = upload_response.json()["error"]["session_id"]

    resolve_response = client.post(
        f"/api/session/{session_id}/resolve",
        json={"resolutions": [{"variable": "D5", "question_type": "categorical", "label_roles": {}}]},
    )
    assert resolve_response.status_code == 200, resolve_response.text

    with open(PURESPECTRUM_PATH, "rb") as f:
        second_upload = client.post(
            "/api/upload",
            data={"vendor": "purespectrum", "survey_id": survey_id},
            files={"file": (PURESPECTRUM_PATH.name, f, _PS_XLSX_CT)},
        )
    assert second_upload.status_code == 200, second_upload.text

    from surveytool.desktop.app import get_session
    second_session = get_session(second_upload.json()["session_id"])
    d5_second = next(q for q in second_session.survey.questions if q.qid == "D5")
    assert d5_second.qtype.value == "categorical"


def test_confirm_and_save_never_presents_a_panel_with_no_session(client):
    """Round A prompt A8 acceptance: Confirm and Save never presents a
    state where the panel is open and no session exists. Every
    UnresolvedQuestionsError from /api/upload must carry a session_id a
    PendingSession is actually registered under, for every vendor whose
    real fixture is present — the resolver panel is only ever shown off
    this same error body."""
    from surveytool.desktop.app import _PENDING_SESSIONS

    if PURESPECTRUM_PATH.exists():
        survey_id = f"a8-panel-check-{uuid.uuid4()}"
        with open(PURESPECTRUM_PATH, "rb") as f:
            response = client.post(
                "/api/upload",
                data={"vendor": "purespectrum", "survey_id": survey_id},
                files={"file": (PURESPECTRUM_PATH.name, f, _PS_XLSX_CT)},
            )
        assert response.status_code == 400
        body = response.json()
        if body["error"]["code"] == "UNRESOLVED_SCALE_LABELS":
            assert body["error"]["session_id"] in _PENDING_SESSIONS
