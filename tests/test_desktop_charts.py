"""
GUI interactive-chart and PNG-export integration tests.

Drops a real vendor file through the desktop app's upload endpoint, then
exercises the new /charts (JSON) and /export (PNG) endpoints. Uses the same
real Rakuten fixture already used by test_desktop_upload.py/test_findings.py;
no fixture is fabricated. If the fixture is absent the test is skipped.
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


def test_charts_endpoint_matches_session_findings(client):
    """The /charts JSON must equal the same session.findings the pipeline already
    computed — the endpoint must not recompute or diverge from it in any way."""
    if not RAKUTEN_PATH.exists():
        pytest.skip(f"{RAKUTEN_PATH.name} not found in project root")

    session_id = _upload(client)
    response = client.get(f"/api/session/{session_id}/charts")

    assert response.status_code == 200, response.text
    charts = response.json()["charts"]
    dist_q1 = next(c for c in charts if c["chart_type"] == "dist" and c["qid"] == "Q1")

    from surveytool.desktop.app import get_session
    session = get_session(session_id)
    idx = {
        (r.qid, r.breakdown_variable, r.breakdown_level, r.metric): r
        for r in session.findings
    }
    expected_t2b = idx[("Q1", "total", "Total", "t2b")]
    expected_mean = idx[("Q1", "total", "Total", "mean")]

    assert dist_q1["trace"]["t2b"] == pytest.approx(expected_t2b.value)
    assert dist_q1["trace"]["mean"] == pytest.approx(expected_mean.value)
    assert dist_q1["trace"]["cell_base"] == expected_t2b.cell_base


def _upload_milieu(client) -> str:
    with open(MILIEU_PATH, "rb") as f:
        response = client.post(
            "/api/upload",
            data={"vendor": "milieu", "survey_id": "t"},
            files={"file": (MILIEU_PATH.name, f, "text/csv")},
        )
    assert response.status_code == 200, response.text
    return response.json()["session_id"]


def test_charts_endpoint_matches_session_findings_for_milieu(client):
    """Same contract as the Rakuten test above, against the real Milieu file."""
    if not MILIEU_PATH.exists():
        pytest.skip(f"{MILIEU_PATH.name} not found in project root")

    session_id = _upload_milieu(client)
    response = client.get(f"/api/session/{session_id}/charts")

    assert response.status_code == 200, response.text
    charts = response.json()["charts"]
    dist_q10 = next(c for c in charts if c["chart_type"] == "dist" and c["qid"] == "q10")

    from surveytool.desktop.app import get_session
    session = get_session(session_id)
    idx = {
        (r.qid, r.breakdown_variable, r.breakdown_level, r.metric): r
        for r in session.findings
    }
    expected_t2b = idx[("q10", "total", "Total", "t2b")]
    expected_mean = idx[("q10", "total", "Total", "mean")]

    assert dist_q10["trace"]["t2b"] == pytest.approx(expected_t2b.value)
    assert dist_q10["trace"]["mean"] == pytest.approx(expected_mean.value)
    assert dist_q10["trace"]["cell_base"] == expected_t2b.cell_base


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


def test_charts_endpoint_matches_session_findings_for_toluna(client):
    """Same contract as the Rakuten test above, against the real Toluna file."""
    if not TOLUNA_PATH.exists():
        pytest.skip(f"{TOLUNA_PATH.name} not found in project root")

    session_id = _upload_toluna(client)
    response = client.get(f"/api/session/{session_id}/charts")

    assert response.status_code == 200, response.text
    charts = response.json()["charts"]
    dist_q6 = next(c for c in charts if c["chart_type"] == "dist" and c["qid"] == "6")

    from surveytool.desktop.app import get_session
    session = get_session(session_id)
    idx = {
        (r.qid, r.breakdown_variable, r.breakdown_level, r.metric): r
        for r in session.findings
    }
    expected_t2b = idx[("6", "total", "Total", "t2b")]
    expected_mean = idx[("6", "total", "Total", "mean")]

    assert dist_q6["trace"]["t2b"] == pytest.approx(expected_t2b.value)
    assert dist_q6["trace"]["mean"] == pytest.approx(expected_mean.value)
    assert dist_q6["trace"]["cell_base"] == expected_t2b.cell_base


def test_charts_endpoint_unknown_session_is_404(client):
    response = client.get("/api/session/does-not-exist/charts")
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "NO_SESSION"
    assert "Traceback" not in body["error"]["message"]


def test_export_endpoint_matches_direct_render_charts_output(client, tmp_path):
    if not RAKUTEN_PATH.exists():
        pytest.skip(f"{RAKUTEN_PATH.name} not found in project root")

    session_id = _upload(client)

    endpoint_dir = tmp_path / "via_endpoint"
    response = client.post(
        f"/api/session/{session_id}/export",
        data={"out_dir": str(endpoint_dir)},
    )
    assert response.status_code == 200, response.text
    exported = set(response.json()["exported"])

    from surveytool.charts import render_charts
    from surveytool.desktop.app import get_session

    session = get_session(session_id)
    direct_dir = tmp_path / "direct"
    direct_entries = render_charts(
        session.findings, direct_dir, session.survey.id, session.survey.questions
    )
    direct_filenames = {e.filename for e in direct_entries}

    assert exported == direct_filenames

    for filename in direct_filenames:
        endpoint_bytes = (endpoint_dir / filename).read_bytes()
        direct_bytes = (direct_dir / filename).read_bytes()
        assert endpoint_bytes == direct_bytes, f"{filename} differs between export endpoint and direct render_charts()"


def test_export_endpoint_unknown_session_is_404(client, tmp_path):
    response = client.post(
        "/api/session/does-not-exist/export",
        data={"out_dir": str(tmp_path)},
    )
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "NO_SESSION"
    assert "Traceback" not in body["error"]["message"]


def test_export_endpoint_single_chart_matches_direct_render(client, tmp_path):
    if not RAKUTEN_PATH.exists():
        pytest.skip(f"{RAKUTEN_PATH.name} not found in project root")

    session_id = _upload(client)

    from surveytool.charts import iter_chart_specs, render_charts
    from surveytool.desktop.app import get_session

    session = get_session(session_id)
    spec = next(iter_chart_specs(session.findings, session.survey.id, session.survey.questions))

    endpoint_dir = tmp_path / "via_endpoint"
    response = client.post(
        f"/api/session/{session_id}/export",
        data={
            "out_dir": str(endpoint_dir),
            "qid": spec.qid,
            "chart_type": spec.chart_type,
            "breakdown_variable": spec.breakdown_variable,
        },
    )
    assert response.status_code == 200, response.text
    exported = response.json()["exported"]
    assert exported == [spec.filename]

    direct_dir = tmp_path / "direct"
    direct_entries = render_charts(
        session.findings,
        direct_dir,
        session.survey.id,
        session.survey.questions,
        chart_filter=lambda s: (
            s.qid == spec.qid
            and s.chart_type == spec.chart_type
            and s.breakdown_variable == spec.breakdown_variable
        ),
    )
    assert len(direct_entries) == 1

    endpoint_bytes = (endpoint_dir / spec.filename).read_bytes()
    direct_bytes = (direct_dir / spec.filename).read_bytes()
    assert endpoint_bytes == direct_bytes


def test_export_endpoint_single_chart_no_match_is_structured_error(client, tmp_path):
    if not RAKUTEN_PATH.exists():
        pytest.skip(f"{RAKUTEN_PATH.name} not found in project root")

    session_id = _upload(client)

    response = client.post(
        f"/api/session/{session_id}/export",
        data={
            "out_dir": str(tmp_path),
            "qid": "does-not-exist",
            "chart_type": "dist",
            "breakdown_variable": "total",
        },
    )
    assert response.status_code != 200
    body = response.json()
    assert "error" in body
    assert "Traceback" not in body["error"]["message"]
