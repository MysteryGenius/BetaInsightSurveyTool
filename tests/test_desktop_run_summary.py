"""
Run summary panel integration test (UI build prompt 7).

Confirms the /run-summary endpoint against real vendor fixtures: every
column in the file gets a classification (none silently missing), and the
PureSpectrum file's 42-column shape is fully accounted for per prompt 7's
stated verification.

Task 5: PureSpectrum's real fixture has questions that don't achieve a full
scale match and aren't declared demographics — an override-free /api/upload
of it now correctly 400s with UnresolvedQuestionsError (see
test_desktop_upload_purespectrum_unresolved.py ... actually asserted right
here, see test_purespectrum_upload_without_overrides_returns_unresolved_questions
below) instead of silently building categorical questions for all of them.
The 42-columns/no-unclassified assertions below now resolve those via the
real /resolve endpoint first, mirroring how an analyst actually clears the
resolver, then assert the same shape on the resulting clean run.

Task 9: D2 (age) is no longer in the unresolved set. vendor_purespectrum.yaml
now maps age_band to D2 (under_18 declared not_collected), so D2 is a
declared demographic source_column and exempt from the collector, the same
as D1/D3 already were. Similarly, Toluna's column "2" is now a declared
demographic source_column (age_band, with under_18/55_64/65_plus declared
not_collected), so it no longer needs the pre-seeded override
_seed_toluna_age_override used to provide before this file loads cleanly.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).parent.parent
RAKUTEN_PATH = ROOT / "rakuten_survey_support_measures_data.xlsx"
TOLUNA_PATH = ROOT / "toluna_survey_misinformation_data.xlsx"
MILIEU_PATH = ROOT / "milieu_survey_coe_data.csv"
PURESPECTRUM_PATH = ROOT / "purespectrum_survey_wcs_data.xlsx"

_XLSX_CT = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# The exact set Task 3's report leaves unmatched in the real PureSpectrum
# fixture (see tests/test_purespectrum_fixture.py for the load-level guard
# on this same set). D2 was in this set before Task 9 mapped age_band for
# PureSpectrum; it is now a declared demographic and no longer appears here.
# Q9 was in this set only because of the Round A prompt A1 Datamap-parsing
# bug (Q10's unbracketed block header was silently absorbed into Q9,
# corrupting its code list); A1 fixed the block-header rule so Q9 now
# classifies cleanly as a `worry` scale and is no longer unresolved.
# Q1/Q3/Q6 are also no longer in this set: Round A prompt A4 classifies
# them as `categorical` directly at load time (no scale evidence at all —
# no matching label, no polarity pair) instead of queueing them for the
# resolver. D5 is the sole survivor, grandfathered in per A4's committed
# decision (see validate_questions._GRANDFATHERED_RESOLVER_CANDIDATES).
_PURESPECTRUM_UNRESOLVED = ("D5",)


@pytest.fixture
def client():
    from surveytool.desktop.app import app
    return TestClient(app)


def _upload(client, vendor: str, path: Path, content_type: str, survey_id: str | None = None):
    survey_id = survey_id or f"run-summary-{vendor}-{uuid.uuid4()}"
    with open(path, "rb") as f:
        return client.post(
            "/api/upload",
            data={"vendor": vendor, "survey_id": survey_id},
            files={"file": (path.name, f, content_type)},
        )


def _upload_and_get_summary(client, vendor: str, path: Path, content_type: str):
    """Upload with no overrides. Toluna's column "2" (age_band) is now a
    declared demographic source_column in vendor_toluna.yaml (Task 9), so
    it no longer needs a pre-seeded override. For PureSpectrum, only valid
    to call this once the six genuinely-unmatched questions have already
    been resolved for this survey_id (see _upload_purespectrum_resolved
    below) — an override-free PureSpectrum upload now 400s (Task 5)."""
    survey_id = f"run-summary-{vendor}-{uuid.uuid4()}"
    response = _upload(client, vendor, path, content_type, survey_id)
    assert response.status_code == 200, response.text
    session_id = response.json()["session_id"]
    summary_response = client.get(f"/api/session/{session_id}/run-summary")
    assert summary_response.status_code == 200, summary_response.text
    return summary_response.json()


def _upload_purespectrum_resolved(client):
    """Upload the real PureSpectrum fixture, resolve the six questions
    Task 5's collector raises on (as categorical, via the real /resolve
    endpoint — the same round trip an analyst performs), and return the
    resolved session's run-summary body. Demonstrates the acceptance
    criterion: resolving every collected question and re-running produces
    a clean load."""
    survey_id = f"run-summary-purespectrum-{uuid.uuid4()}"
    upload_response = _upload(client, "purespectrum", PURESPECTRUM_PATH, _XLSX_CT, survey_id)
    assert upload_response.status_code == 400, upload_response.text
    body = upload_response.json()
    assert body["error"]["code"] == "UNRESOLVED_SCALE_LABELS"
    unresolved_variables = {e["variable"] for e in body["error"]["detail_entries"]}
    assert unresolved_variables == set(_PURESPECTRUM_UNRESOLVED)

    # No session was created by the failed upload — resolve via a plain
    # write of the overrides file is not exposed pre-session, so drive the
    # same file through the low-level loader with overrides applied, then
    # go through the ordinary upload path a second time; the second
    # upload succeeds because the persisted overrides now cover every
    # collected question for this survey_id.
    from surveytool.desktop.app import _project_overrides_path
    from surveytool.ingest.overrides import QuestionOverride, write_override

    overrides_path = _project_overrides_path(survey_id)
    now = datetime.now(timezone.utc)
    for variable in _PURESPECTRUM_UNRESOLVED:
        write_override(
            overrides_path,
            QuestionOverride(
                variable=variable,
                question_type="categorical",
                label_roles={},
                resolved_at=now,
                library_version="test",
            ),
        )

    resolved_upload = _upload(client, "purespectrum", PURESPECTRUM_PATH, _XLSX_CT, survey_id)
    assert resolved_upload.status_code == 200, resolved_upload.text
    session_id = resolved_upload.json()["session_id"]
    summary_response = client.get(f"/api/session/{session_id}/run-summary")
    assert summary_response.status_code == 200, summary_response.text
    return summary_response.json()


def test_purespectrum_upload_without_overrides_returns_unresolved_questions(client):
    """The acceptance-criteria demonstration for a real PureSpectrum load:
    an override-free upload raises UnresolvedQuestionsError naming exactly
    D5, and none of the exempt columns (D1/D2/D3 declared demographics,
    QC2/QC2Flag quality columns, or Q1/Q3/Q6 which Round A prompt A4
    classifies as categorical directly rather than queueing)."""
    if not PURESPECTRUM_PATH.exists():
        pytest.skip(f"{PURESPECTRUM_PATH.name} not found in project root")

    response = _upload(client, "purespectrum", PURESPECTRUM_PATH, _XLSX_CT)
    assert response.status_code == 400, response.text
    body = response.json()
    assert body["error"]["code"] == "UNRESOLVED_SCALE_LABELS"
    variables = {e["variable"] for e in body["error"]["detail_entries"]}
    assert variables == set(_PURESPECTRUM_UNRESOLVED)
    assert "D1" not in variables
    assert "D2" not in variables
    assert "D3" not in variables
    assert "QC2" not in variables
    assert "QC2Flag" not in variables
    assert "Q1" not in variables
    assert "Q3" not in variables
    assert "Q6" not in variables


def test_purespectrum_all_42_columns_classified(client):
    if not PURESPECTRUM_PATH.exists():
        pytest.skip(f"{PURESPECTRUM_PATH.name} not found in project root")

    body = _upload_purespectrum_resolved(client)
    assert len(body["columns"]) == 42
    for col in body["columns"]:
        assert col["classification"] != "unclassified", col

    status_col = next(c for c in body["columns"] if c["column"] == "status")
    assert status_col["classification"] == "metadata"
    assert status_col["question_type"] is None


def test_purespectrum_run_summary_lists_auto_categorical_questions_with_reasons(client):
    """Round A prompt A4 acceptance: the run summary lists every question
    Round A classified as categorical outright (Q1, Q3, Q6 — no scale
    evidence at all) together with its recorded reason, so the
    classification is never silent. D5, which stays in the resolver via the
    grandfather exception, must not appear in this list — it's a real
    resolver entry, not an auto-categorical one."""
    if not PURESPECTRUM_PATH.exists():
        pytest.skip(f"{PURESPECTRUM_PATH.name} not found in project root")

    body = _upload_purespectrum_resolved(client)
    categorical = {c["variable"]: c["reason"] for c in body["categorical_classifications"]}
    assert set(categorical.keys()) == {"Q1", "Q3", "Q6"}
    for reason in categorical.values():
        assert reason and "no evidence" in reason.lower()


@pytest.mark.parametrize(
    "vendor,path,content_type",
    [
        ("rakuten", RAKUTEN_PATH, _XLSX_CT),
        ("toluna", TOLUNA_PATH, _XLSX_CT),
        ("milieu", MILIEU_PATH, "text/csv"),
    ],
)
def test_no_unclassified_columns_for_any_vendor(client, vendor, path, content_type):
    if not path.exists():
        pytest.skip(f"{path.name} not found in project root")

    body = _upload_and_get_summary(client, vendor, path, content_type)
    unclassified = [c["column"] for c in body["columns"] if c["classification"] == "unclassified"]
    assert unclassified == [], f"{vendor}: unclassified columns {unclassified}"


def test_no_unclassified_columns_for_purespectrum_once_resolved(client):
    if not PURESPECTRUM_PATH.exists():
        pytest.skip(f"{PURESPECTRUM_PATH.name} not found in project root")

    body = _upload_purespectrum_resolved(client)
    unclassified = [c["column"] for c in body["columns"] if c["classification"] == "unclassified"]
    assert unclassified == [], f"purespectrum: unclassified columns {unclassified}"


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


# ── Task B4: mean_newly_available flag (Toluna/Milieu only) ───────────────


def test_toluna_run_summary_flags_q7_mean_newly_available(client):
    """Round B4: Toluna supplies no vendor numeric code for its scale
    questions, so a mean was never computable before Round B's rank-based
    mean. Q7 (test_toluna_q7_local_mainstream_media_rank_and_netting in
    test_conformance.py) has a real, non-null mean (3.387) -- it must be
    flagged here as newly available."""
    if not TOLUNA_PATH.exists():
        pytest.skip(f"{TOLUNA_PATH.name} not found in project root")

    body = _upload_and_get_summary(client, "toluna", TOLUNA_PATH, _XLSX_CT)
    flagged = {e["variable"] for e in body["mean_newly_available"]}
    assert "7_local_mainstream_media" in flagged


def test_rakuten_run_summary_never_flags_mean_newly_available(client):
    """Rakuten supplies a real vendor numeric code for its scale questions,
    so it already had *a* mean before Round B (Round B only corrected which
    order that mean uses, never introduced the concept for the first time)
    -- the flag must never fire for it."""
    if not RAKUTEN_PATH.exists():
        pytest.skip(f"{RAKUTEN_PATH.name} not found in project root")

    body = _upload_and_get_summary(client, "rakuten", RAKUTEN_PATH, _XLSX_CT)
    assert body["mean_newly_available"] == []


def test_purespectrum_run_summary_never_flags_mean_newly_available():
    """Same reasoning as Rakuten: PureSpectrum already had a vendor numeric
    code, so it already had a mean before Round B.

    Exercised at the unit level (surveytool.desktop.app's own helper)
    rather than through the full upload+resolve HTTP round trip:
    PureSpectrum's real fixture has genuinely unresolved questions
    (test_purespectrum_upload_without_overrides_returns_unresolved_questions
    above) that require the /resolve endpoint round trip
    (_upload_purespectrum_resolved) to clear first, and that flow is broken
    independent of this task (see the pre-existing failures in
    tests/test_desktop_resolve.py::test_purespectrum_upload_unresolved_produces_a_resolvable_session
    and friends) -- this test does not need that machinery to prove the
    mean_newly_available logic itself never fires for PureSpectrum."""
    if not PURESPECTRUM_PATH.exists():
        pytest.skip(f"{PURESPECTRUM_PATH.name} not found in project root")

    from surveytool.desktop.app import _mean_newly_available_entries
    from surveytool.findings.sheet import build_findings_sheet
    from surveytool.ingest.purespectrum import load

    overrides_path_survey_id = f"ps-mean-unit-{uuid.uuid4()}"
    from surveytool.desktop.app import _project_overrides_path
    from surveytool.ingest.overrides import QuestionOverride, write_override

    now = datetime.now(timezone.utc)
    overrides_path = _project_overrides_path(overrides_path_survey_id)
    for variable in _PURESPECTRUM_UNRESOLVED:
        write_override(
            overrides_path,
            QuestionOverride(
                variable=variable, question_type="categorical", label_roles={},
                resolved_at=now, library_version="test",
            ),
        )
    from surveytool.ingest.overrides import load_overrides
    overrides = load_overrides(overrides_path).overrides

    survey = load(PURESPECTRUM_PATH, "ps_wcs", overrides)
    findings = build_findings_sheet(survey)
    entries = _mean_newly_available_entries("purespectrum", survey, findings)
    assert entries == []
