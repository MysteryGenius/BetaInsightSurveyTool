"""
GUI breaks-and-filters endpoint integration tests (build plan sections 10/12).

Drops real vendor files through the desktop app's upload endpoint, then
exercises the four new /demographics/registry, /projection, /crosstab and
/breaks-export routes. Uses the same real fixtures as test_desktop_crosstab.py;
no fixture is fabricated. If a fixture is absent the test is skipped.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).parent.parent
RAKUTEN_PATH = ROOT / "rakuten_survey_support_measures_data.xlsx"
MILIEU_PATH = ROOT / "milieu_survey_coe_data.csv"
TOLUNA_PATH = ROOT / "toluna_survey_misinformation_data.xlsx"

_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@pytest.fixture
def client():
    from surveytool.desktop.app import app
    return TestClient(app)


def _upload(client) -> str:
    with open(RAKUTEN_PATH, "rb") as f:
        response = client.post(
            "/api/upload",
            data={"vendor": "rakuten", "survey_id": "t"},
            files={"file": (RAKUTEN_PATH.name, f, _XLSX_MIME)},
        )
    assert response.status_code == 200, response.text
    return response.json()["session_id"]


def _upload_milieu(client) -> str:
    with open(MILIEU_PATH, "rb") as f:
        response = client.post(
            "/api/upload",
            data={"vendor": "milieu", "survey_id": "t"},
            files={"file": (MILIEU_PATH.name, f, "text/csv")},
        )
    assert response.status_code == 200, response.text
    return response.json()["session_id"]


def _upload_toluna(client) -> str:
    with open(TOLUNA_PATH, "rb") as f:
        response = client.post(
            "/api/upload",
            data={"vendor": "toluna", "survey_id": "t"},
            files={"file": (TOLUNA_PATH.name, f, _XLSX_MIME)},
        )
    assert response.status_code == 200, response.text
    return response.json()["session_id"]


# --- upload wiring ---------------------------------------------------------


def test_upload_stores_vendor_and_registry_on_session(client):
    if not RAKUTEN_PATH.exists():
        pytest.skip(f"{RAKUTEN_PATH.name} not found in project root")

    session_id = _upload(client)

    from surveytool.core.demographic_registry import ResolvedRegistry
    from surveytool.desktop.app import get_session

    session = get_session(session_id)
    assert session.vendor == "rakuten"
    assert isinstance(session.registry, ResolvedRegistry)
    # Every vendor mapping is resolved, not just the uploaded one.
    assert set(session.registry.vendors) == {"rakuten", "milieu", "toluna"}


def test_upload_hard_fails_when_registry_cannot_load(client, monkeypatch):
    """Registry load failure must fail the whole upload, not silently create a
    session with no registry. Forced via a canonical.yaml path that declares a
    dimension the real vendor mappings reference but cannot reach."""
    if not RAKUTEN_PATH.exists():
        pytest.skip(f"{RAKUTEN_PATH.name} not found in project root")

    import surveytool.desktop.app as app_module
    from surveytool.charts.errors import CanonicalCategoryUnreachableError

    def _boom(vendor, survey):
        raise CanonicalCategoryUnreachableError("rakuten", "gender", "nonbinary")

    monkeypatch.setattr(app_module, "_load_session_registry", _boom)

    before = set(app_module._SESSIONS)
    with open(RAKUTEN_PATH, "rb") as f:
        response = client.post(
            "/api/upload",
            data={"vendor": "rakuten", "survey_id": "t"},
            files={"file": (RAKUTEN_PATH.name, f, _XLSX_MIME)},
        )

    assert response.status_code >= 400
    body = response.json()
    assert body["error"]["code"] == "CANONICAL_CATEGORY_UNREACHABLE"
    assert "Traceback" not in body["error"]["message"]
    # No partial session was created.
    assert set(app_module._SESSIONS) == before


# --- GET .../demographics/registry -----------------------------------------


def test_registry_endpoint_is_complete_for_rakuten(client):
    """The registry payload is the UI's sole pill-list source, so every
    canonical dimension and every category must be present, with the
    vendor's availability recorded rather than the dimension pruned."""
    if not RAKUTEN_PATH.exists():
        pytest.skip(f"{RAKUTEN_PATH.name} not found in project root")

    session_id = _upload(client)
    response = client.get(f"/api/session/{session_id}/demographics/registry")
    assert response.status_code == 200, response.text
    body = response.json()

    from surveytool.desktop.app import get_session

    session = get_session(session_id)
    canonical = session.registry.canonical.dimensions
    vendor_dims = session.registry.dimensions_for_vendor("rakuten")

    assert body["vendor"] == "rakuten"
    by_name = {d["dimension"]: d for d in body["dimensions"]}
    assert set(by_name) == set(canonical)

    for name, canonical_dim in canonical.items():
        payload_dim = by_name[name]
        assert payload_dim["label"] == canonical_dim.label
        assert payload_dim["multi_select"] == canonical_dim.multi_select
        assert payload_dim["available"] == (name in vendor_dims)
        if name in vendor_dims:
            assert payload_dim["source_column"] == vendor_dims[name].source_column
        else:
            assert payload_dim["source_column"] is None

        # Full category list, nothing pruned, all four fields present.
        assert len(payload_dim["categories"]) == len(canonical_dim.categories)
        for payload_cat, canonical_cat in zip(
            payload_dim["categories"], canonical_dim.categories
        ):
            assert payload_cat["value"] == canonical_cat.value
            assert payload_cat["label"] == canonical_cat.label
            assert payload_cat["order"] == canonical_cat.order
            assert payload_cat["non_response"] == canonical_cat.non_response


def test_registry_endpoint_marks_multi_select_dimension(client):
    if not MILIEU_PATH.exists():
        pytest.skip(f"{MILIEU_PATH.name} not found in project root")

    session_id = _upload_milieu(client)
    response = client.get(f"/api/session/{session_id}/demographics/registry")
    assert response.status_code == 200, response.text
    body = response.json()

    by_name = {d["dimension"]: d for d in body["dimensions"]}
    assert body["vendor"] == "milieu"
    assert by_name["car_ownership_reasons"]["multi_select"] is True
    assert by_name["gender"]["multi_select"] is False


def test_registry_endpoint_unknown_session_is_404(client):
    response = client.get("/api/session/does-not-exist/demographics/registry")
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "NO_SESSION"
    assert "Traceback" not in body["error"]["message"]


# --- POST .../projection ---------------------------------------------------


def test_projection_endpoint_matches_project_directly(client):
    if not RAKUTEN_PATH.exists():
        pytest.skip(f"{RAKUTEN_PATH.name} not found in project root")

    session_id = _upload(client)
    response = client.post(
        f"/api/session/{session_id}/projection",
        json={"break_spec": {"dimensions": ["gender"]}, "filter_spec": {"selections": {}}},
    )
    assert response.status_code == 200, response.text
    body = response.json()

    from surveytool.core.break_filter import BreakSpec, FilterSpec
    from surveytool.core.config import ToolConfig
    from surveytool.core.projection import project
    from surveytool.desktop.app import get_session

    session = get_session(session_id)
    expected = project(
        BreakSpec(dimensions=["gender"]),
        FilterSpec(selections={}),
        session.survey,
        session.respondent_frame,
        session.registry,
        "rakuten",
        ToolConfig(),
    )

    assert body == expected.model_dump(mode="json")
    assert body["errors"] == []
    assert body["base_total"] == len(session.respondent_frame)
    assert body["cell_count"] == 2
    assert {c["label_path"][0] for c in body["cells"]} == {"Male", "Female"}


def test_projection_endpoint_nested_break_and_filter(client):
    if not RAKUTEN_PATH.exists():
        pytest.skip(f"{RAKUTEN_PATH.name} not found in project root")

    session_id = _upload(client)
    response = client.post(
        f"/api/session/{session_id}/projection",
        json={
            "break_spec": {"dimensions": ["gender", "age_band"]},
            "filter_spec": {"selections": {"ethnicity": ["chinese"]}},
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["errors"] == []
    assert body["base_filtered"] < body["base_total"]
    assert body["cell_count"] == len(body["cells"])
    assert [d["dimension"] for d in body["break_dimensions"]] == ["gender", "age_band"]
    for cell in body["cells"]:
        assert [pair[0] for pair in cell["key"]] == ["gender", "age_band"]
        assert cell["band"] in {"ok", "low_base", "suppressed"}


def test_projection_endpoint_invalid_spec_is_200_with_errors(client):
    """A validation failure travels in-band in Projection.errors — the UI
    re-runs projection on every pill change, so an in-progress selection must
    not surface as a 4xx."""
    if not RAKUTEN_PATH.exists():
        pytest.skip(f"{RAKUTEN_PATH.name} not found in project root")

    session_id = _upload(client)
    response = client.post(
        f"/api/session/{session_id}/projection",
        json={
            "break_spec": {"dimensions": ["gender", "gender"]},
            "filter_spec": {"selections": {}},
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert len(body["errors"]) == 1
    assert body["errors"][0]["code"] == "DUPLICATE_BREAK_DIMENSION"
    assert body["cells"] == []
    assert body["cell_count"] == 0
    assert body["chart_render_permitted"] is False
    # base_total does not depend on validation and is still populated.
    assert body["base_total"] > 0


def test_projection_endpoint_unknown_dimension_is_200_with_errors(client):
    if not RAKUTEN_PATH.exists():
        pytest.skip(f"{RAKUTEN_PATH.name} not found in project root")

    session_id = _upload(client)
    response = client.post(
        f"/api/session/{session_id}/projection",
        json={
            "break_spec": {"dimensions": ["not_a_dimension"]},
            "filter_spec": {"selections": {}},
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["errors"][0]["code"] == "DEMOGRAPHIC_NOT_IN_REGISTRY"


def test_projection_endpoint_unknown_session_is_404(client):
    response = client.post(
        "/api/session/does-not-exist/projection",
        json={"break_spec": {"dimensions": ["gender"]}, "filter_spec": {"selections": {}}},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NO_SESSION"


# --- POST .../crosstab -----------------------------------------------------


def test_crosstab_endpoint_populates_permitted_charts(client):
    """permitted_charts is left empty by compute_breaks_crosstab; this endpoint
    is what joins it to chart_validity. Proves the wiring ran."""
    if not RAKUTEN_PATH.exists():
        pytest.skip(f"{RAKUTEN_PATH.name} not found in project root")

    session_id = _upload(client)
    response = client.post(
        f"/api/session/{session_id}/crosstab",
        json={
            "break_spec": {"dimensions": ["gender"]},
            "filter_spec": {"selections": {}},
            "question_ids": ["Q1"],
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()

    from surveytool.core.chart_validity import ChartType

    assert len(body) == 1
    result = body[0]
    assert result["question_id"] == "Q1"
    assert result["permitted_charts"], "permitted_charts must not be the empty placeholder"
    assert {p["chart_type"] for p in result["permitted_charts"]} == {
        ct.value for ct in ChartType
    }
    for permission in result["permitted_charts"]:
        assert isinstance(permission["permitted"], bool)
    # table is always permitted (exempt from the render ceiling).
    table = next(p for p in result["permitted_charts"] if p["chart_type"] == "table")
    assert table["permitted"] is True


def test_crosstab_endpoint_matches_compute_plus_permissions(client):
    if not RAKUTEN_PATH.exists():
        pytest.skip(f"{RAKUTEN_PATH.name} not found in project root")

    session_id = _upload(client)
    response = client.post(
        f"/api/session/{session_id}/crosstab",
        json={
            "break_spec": {"dimensions": ["gender"]},
            "filter_spec": {"selections": {}},
            "question_ids": ["Q1"],
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()

    from surveytool.compute.breaks_compute import compute_breaks_crosstab
    from surveytool.core.breaks_payload import attach_chart_permissions
    from surveytool.core.config import ToolConfig
    from surveytool.desktop.app import get_session

    session = get_session(session_id)
    config = ToolConfig()
    expected = attach_chart_permissions(
        compute_breaks_crosstab(
            session.respondent_frame, session.survey, ["gender"], {},
            ["Q1"], session.registry, "rakuten", config,
        ),
        config,
    )

    assert body == [r.model_dump(mode="json") for r in expected]


def test_crosstab_endpoint_column_shape_matches_section_10(client):
    if not RAKUTEN_PATH.exists():
        pytest.skip(f"{RAKUTEN_PATH.name} not found in project root")

    session_id = _upload(client)
    response = client.post(
        f"/api/session/{session_id}/crosstab",
        json={
            "break_spec": {"dimensions": ["gender"]},
            "filter_spec": {"selections": {}},
            "question_ids": ["Q1"],
        },
    )
    assert response.status_code == 200, response.text
    result = response.json()[0]

    assert set(result) >= {
        "question_id", "question_text", "scale_id", "scale_points", "nets",
        "base_total", "base_filtered", "columns", "permitted_charts",
    }
    assert len(result["columns"]) == 2
    for column in result["columns"]:
        assert set(column) >= {
            "key", "label_path", "base_cell", "base_valid", "n_invalid", "band",
            "counts", "percentages", "nets", "significance", "significance_basis",
        }
        # The two significance fields ship now and are always null (section 10).
        assert column["significance"] is None
        assert column["significance_basis"] is None


def test_crosstab_endpoint_defaults_to_all_base_eligible_questions(client):
    if not RAKUTEN_PATH.exists():
        pytest.skip(f"{RAKUTEN_PATH.name} not found in project root")

    session_id = _upload(client)
    response = client.post(
        f"/api/session/{session_id}/crosstab",
        json={"break_spec": {"dimensions": ["gender"]}, "filter_spec": {"selections": {}}},
    )
    assert response.status_code == 200, response.text
    body = response.json()

    from surveytool.desktop.app import get_session

    session = get_session(session_id)
    expected_qids = [
        q.qid for q in session.survey.questions
        if q.base_eligible and not q.is_demographic
    ]
    assert [r["question_id"] for r in body] == expected_qids
    assert expected_qids  # the fixture really does have such questions
    for result in body:
        assert result["permitted_charts"]


def test_crosstab_endpoint_invalid_spec_is_4xx(client):
    """Unlike projection, crosstab must refuse an invalid spec: it validates
    before computing, since compute_breaks_crosstab does not validate itself."""
    if not RAKUTEN_PATH.exists():
        pytest.skip(f"{RAKUTEN_PATH.name} not found in project root")

    session_id = _upload(client)
    response = client.post(
        f"/api/session/{session_id}/crosstab",
        json={
            "break_spec": {"dimensions": ["gender", "gender"]},
            "filter_spec": {"selections": {}},
            "question_ids": ["Q1"],
        },
    )
    assert 400 <= response.status_code < 500, response.text
    body = response.json()
    assert body["error"]["code"] == "DUPLICATE_BREAK_DIMENSION"
    assert "Traceback" not in body["error"]["message"]


def test_crosstab_endpoint_dimension_in_break_and_filter_is_4xx(client):
    if not RAKUTEN_PATH.exists():
        pytest.skip(f"{RAKUTEN_PATH.name} not found in project root")

    session_id = _upload(client)
    response = client.post(
        f"/api/session/{session_id}/crosstab",
        json={
            "break_spec": {"dimensions": ["gender"]},
            "filter_spec": {"selections": {"gender": ["male"]}},
            "question_ids": ["Q1"],
        },
    )
    assert 400 <= response.status_code < 500, response.text
    assert response.json()["error"]["code"] == "DIMENSION_IN_BREAK_AND_FILTER"


def test_crosstab_endpoint_multiselect_break_is_4xx(client):
    if not MILIEU_PATH.exists():
        pytest.skip(f"{MILIEU_PATH.name} not found in project root")

    session_id = _upload_milieu(client)
    response = client.post(
        f"/api/session/{session_id}/crosstab",
        json={
            "break_spec": {"dimensions": ["car_ownership_reasons"]},
            "filter_spec": {"selections": {}},
        },
    )
    assert 400 <= response.status_code < 500, response.text
    assert response.json()["error"]["code"] == "MULTISELECT_BREAK_REJECTED"


def test_crosstab_endpoint_unknown_session_is_404(client):
    response = client.post(
        "/api/session/does-not-exist/crosstab",
        json={"break_spec": {"dimensions": ["gender"]}, "filter_spec": {"selections": {}}},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NO_SESSION"


def test_crosstab_endpoint_computes_for_toluna(client):
    if not TOLUNA_PATH.exists():
        pytest.skip(f"{TOLUNA_PATH.name} not found in project root")

    session_id = _upload_toluna(client)
    response = client.post(
        f"/api/session/{session_id}/crosstab",
        json={
            "break_spec": {"dimensions": ["gender"]},
            "filter_spec": {"selections": {}},
            "question_ids": ["6"],
        },
    )
    assert response.status_code == 200, response.text
    result = response.json()[0]
    assert result["question_id"] == "6"
    assert result["permitted_charts"]
    assert len(result["columns"]) >= 1


# --- POST .../breaks-export ------------------------------------------------


def test_breaks_export_endpoint_is_not_yet_implemented(client):
    if not RAKUTEN_PATH.exists():
        pytest.skip(f"{RAKUTEN_PATH.name} not found in project root")

    session_id = _upload(client)
    response = client.post(
        f"/api/session/{session_id}/breaks-export",
        json={
            "break_spec": {"dimensions": ["gender"]},
            "filter_spec": {"selections": {}},
            "chart_type": "stacked_bar_100",
            "question_id": "Q1",
        },
    )
    assert response.status_code == 400, response.text
    body = response.json()
    assert "not yet implemented" in body["error"]
    assert "Traceback" not in body["error"]


def test_breaks_export_endpoint_unknown_session_is_404(client):
    response = client.post(
        "/api/session/does-not-exist/breaks-export",
        json={
            "break_spec": {"dimensions": ["gender"]},
            "filter_spec": {"selections": {}},
            "chart_type": "table",
            "question_id": "Q1",
        },
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NO_SESSION"


def test_breaks_export_endpoint_rejects_unknown_chart_type(client):
    if not RAKUTEN_PATH.exists():
        pytest.skip(f"{RAKUTEN_PATH.name} not found in project root")

    session_id = _upload(client)
    response = client.post(
        f"/api/session/{session_id}/breaks-export",
        json={
            "break_spec": {"dimensions": ["gender"]},
            "filter_spec": {"selections": {}},
            "chart_type": "pie",
            "question_id": "Q1",
        },
    )
    assert response.status_code == 422, response.text


# --- regression: pre-existing endpoints unchanged --------------------------


def test_legacy_demographics_and_cross_tab_still_work(client):
    """The legacy single-break UI's endpoints must be untouched by this work."""
    if not RAKUTEN_PATH.exists():
        pytest.skip(f"{RAKUTEN_PATH.name} not found in project root")

    session_id = _upload(client)

    demographics = client.get(f"/api/session/{session_id}/demographics")
    assert demographics.status_code == 200, demographics.text
    body = demographics.json()
    assert set(body) == {"demographics", "questions"}
    assert "age" in {d["key"] for d in body["demographics"]}

    cross_tab = client.get(f"/api/session/{session_id}/cross-tab?qid=Q1&demographic=age")
    assert cross_tab.status_code == 200, cross_tab.text
    assert set(cross_tab.json()) == {"qid", "question_text", "demographic", "cells"}


def test_legacy_chart_export_endpoint_still_reachable(client, tmp_path):
    """POST .../export is the pre-existing matplotlib export; the new breaks
    export deliberately took a different path so as not to shadow it."""
    if not RAKUTEN_PATH.exists():
        pytest.skip(f"{RAKUTEN_PATH.name} not found in project root")

    session_id = _upload(client)
    response = client.post(
        f"/api/session/{session_id}/export",
        data={"out_dir": str(tmp_path)},
    )
    assert response.status_code == 200, response.text
    assert "exported" in response.json()
