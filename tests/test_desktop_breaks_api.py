"""
GUI breaks-and-filters endpoint integration tests (build plan sections 10/12).

Drops real vendor files through the desktop app's upload endpoint, then
exercises the four new /demographics/registry, /projection, /crosstab and
/breaks-export routes. Uses the same real fixtures as test_desktop_crosstab.py;
no fixture is fabricated. If a fixture is absent the test is skipped.
"""
from __future__ import annotations

import tempfile
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
    # Task 9: column "2" (age_band) is now a declared demographic
    # source_column in vendor_toluna.yaml, exempt from the load-path
    # collector — no override needed (contrast with the Task 5-era
    # override this helper used before age_band was mapped).
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
    assert set(session.registry.vendors) == {"rakuten", "milieu", "toluna", "purespectrum"}


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


def test_breaks_export_endpoint_saves_png_into_out_dir(client, tmp_path):
    """"Export current chart" must actually save the PNG into the chosen
    export folder -- returning it as a response body left the analyst with
    a success message and no file."""
    if not RAKUTEN_PATH.exists():
        pytest.skip(f"{RAKUTEN_PATH.name} not found in project root")

    session_id = _upload(client)
    response = client.post(
        f"/api/session/{session_id}/breaks-export",
        json={
            "break_spec": {"dimensions": ["gender"]},
            "filter_spec": {"selections": {}},
            "chart_type": "table",
            "question_id": "Q1",
            "out_dir": str(tmp_path),
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body == {"filename": "Q1-table.png", "out_dir": str(tmp_path)}
    saved = tmp_path / body["filename"]
    assert saved.exists() and saved.stat().st_size > 0


def test_breaks_export_swapped_writes_swapped_filename(client, tmp_path):
    if not MILIEU_PATH.exists():
        pytest.skip(f"{MILIEU_PATH.name} not found in project root")

    session_id = _upload_milieu(client)
    response = client.post(
        f"/api/session/{session_id}/breaks-export",
        json={**_q8_figure_body(), "out_dir": str(tmp_path)},
    )
    assert response.status_code == 200, response.text
    assert response.json()["filename"] == "q8-grouped_bar-swapped.png"
    assert (tmp_path / "q8-grouped_bar-swapped.png").stat().st_size > 0


def test_breaks_export_unwritable_folder_is_plain_error(client, tmp_path):
    if not RAKUTEN_PATH.exists():
        pytest.skip(f"{RAKUTEN_PATH.name} not found in project root")

    blocker = tmp_path / "file"
    blocker.write_text("x")
    session_id = _upload(client)
    response = client.post(
        f"/api/session/{session_id}/breaks-export",
        json={
            "break_spec": {"dimensions": ["gender"]},
            "filter_spec": {"selections": {}},
            "chart_type": "table",
            "question_id": "Q1",
            "out_dir": str(blocker / "sub"),
        },
    )
    assert response.status_code == 500, response.text
    error = response.json()["error"]
    assert error["code"] == "INTERNAL"
    assert error["message"] == "The export could not be saved to the chosen location."


def test_breaks_export_endpoint_unknown_session_is_404(client):
    response = client.post(
        "/api/session/does-not-exist/breaks-export",
        json={
            "break_spec": {"dimensions": ["gender"]},
            "filter_spec": {"selections": {}},
            "chart_type": "table",
            "question_id": "Q1",
            "out_dir": tempfile.gettempdir(),
        },
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NO_SESSION"


def test_breaks_export_endpoint_rejects_unpermitted_chart_type(client):
    """diverging_stacked_bar is refused for a question whose scale family has
    no declared polarity (Toluna question 5) — build_figure must not render
    something chart_validity said wasn't legitimate."""
    if not TOLUNA_PATH.exists():
        pytest.skip(f"{TOLUNA_PATH.name} not found in project root")

    session_id = _upload_toluna(client)
    response = client.post(
        f"/api/session/{session_id}/breaks-export",
        json={
            "break_spec": {"dimensions": ["gender"]},
            "filter_spec": {"selections": {}},
            "chart_type": "diverging_stacked_bar",
            "question_id": "5",
            "out_dir": tempfile.gettempdir(),
        },
    )
    assert response.status_code >= 400, response.text
    body = response.json()
    assert "error" in body
    assert "Traceback" not in str(body)


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
            "out_dir": tempfile.gettempdir(),
        },
    )
    assert response.status_code == 422, response.text


# --- POST .../breaks-figure ------------------------------------------------


def _q8_figure_body(chart_type: str = "grouped_bar", swap_axes: bool = True) -> dict:
    return {
        "break_spec": {"dimensions": ["car_ownership"]},
        "filter_spec": {"selections": {}},
        "chart_type": chart_type,
        "question_id": "q8",
        "swap_axes": swap_axes,
    }


def test_breaks_figure_equals_build_figure_for_styled_swapped_question(client):
    """The figure served for the screen must be exactly the one the export
    rasterizes -- same colours, wrapped ticks, margins -- for a styled,
    colour-overridden, swapped question."""
    if not MILIEU_PATH.exists():
        pytest.skip(f"{MILIEU_PATH.name} not found in project root")

    import json

    from surveytool.charts.plotly_renderer import build_figure
    from surveytool.core.breaks_models import BreakSpec, FilterSpec
    from surveytool.core.chart_validity import ChartType
    from surveytool.desktop.app import _compute_breaks_results, get_session

    session_id = _upload_milieu(client)
    session = get_session(session_id)
    crosstab = client.post(
        f"/api/session/{session_id}/crosstab",
        json={"break_spec": {"dimensions": ["car_ownership"]}, "filter_spec": {"selections": {}}, "question_ids": ["q8"]},
    ).json()
    first_label = crosstab[0]["scale_points"][0]["label"]
    put = client.put(
        f"/api/projects/{session.survey.id}/chart-style/q8",
        json={"style_name": "cool", "response_colours": {first_label: "#1B667D"}},
    )
    assert put.status_code == 200, put.text

    served = client.post(f"/api/session/{session_id}/breaks-figure", json=_q8_figure_body())
    assert served.status_code == 200, served.text

    question_result = _compute_breaks_results(
        session, BreakSpec(dimensions=["car_ownership"]), FilterSpec(), ["q8"]
    )[0]
    expected = build_figure(
        question_result, ChartType.grouped_bar,
        break_spec=["car_ownership"], filter_spec={}, swap_axes=True,
    ).to_plotly_json()
    assert served.json()["figure"] == json.loads(json.dumps(expected, default=str))


def test_breaks_figure_swapped_q8_has_distinct_colours_per_car_ownership_group(client):
    """Leonard's case: q8 x Car ownership with axes swapped must show each
    group in its own colour, with long answer labels wrapped."""
    if not MILIEU_PATH.exists():
        pytest.skip(f"{MILIEU_PATH.name} not found in project root")

    session_id = _upload_milieu(client)
    response = client.post(f"/api/session/{session_id}/breaks-figure", json=_q8_figure_body())
    assert response.status_code == 200, response.text
    traces = response.json()["figure"]["data"]
    assert len(traces) >= 2
    colours = [t["marker"]["color"] for t in traces]
    assert len(set(colours)) == len(colours)
    assert any("<br>" in tick for tick in traces[0]["x"])


def test_breaks_figure_rejects_unpermitted_chart_type(client):
    if not MILIEU_PATH.exists():
        pytest.skip(f"{MILIEU_PATH.name} not found in project root")

    session_id = _upload_milieu(client)
    response = client.post(
        f"/api/session/{session_id}/breaks-figure",
        json=_q8_figure_body(chart_type="net_bar", swap_axes=False),
    )
    assert response.status_code >= 400, response.text
    assert response.json()["error"]["code"] == "INTERNAL"


# --- POST .../breaks-export-bulk --------------------------------------------


def test_breaks_export_bulk_writes_one_png_per_question_id(client, tmp_path):
    if not RAKUTEN_PATH.exists():
        pytest.skip(f"{RAKUTEN_PATH.name} not found in project root")

    session_id = _upload(client)
    out_dir = tmp_path / "bulk"

    response = client.post(
        f"/api/session/{session_id}/breaks-export-bulk",
        json={
            "break_spec": {"dimensions": ["gender"]},
            "filter_spec": {"selections": {}},
            "chart_type": "table",
            "question_ids": ["Q1", "Q2"],
            "out_dir": str(out_dir),
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert {e["question_id"] for e in body["exported"]} == {"Q1", "Q2"}
    assert body["skipped"] == []
    for entry in body["exported"]:
        assert (out_dir / entry["filename"]).exists()
        assert (out_dir / entry["filename"]).stat().st_size > 0


@pytest.mark.parametrize(
    "fixture_path, uploader",
    [
        (RAKUTEN_PATH, _upload),
        (MILIEU_PATH, _upload_milieu),
        (TOLUNA_PATH, _upload_toluna),
    ],
    ids=["rakuten", "milieu", "toluna"],
)
def test_breaks_export_bulk_skips_questions_that_do_not_support_the_chart_type(
    client, tmp_path, fixture_path, uploader
):
    """A chart type only some questions support must not abort the batch.

    The "Export all" button sends every base-eligible question at whatever
    chart type is currently on screen, so a survey nearly always contains
    some question that can't render as that type. Those are reported as
    `skipped`; every question that CAN render still gets its PNG.

    Run across every onboarded vendor's real data because the original defect
    (a 500 that exported nothing) reproduced on Milieu/Toluna for
    net_bar/diverging_stacked_bar while the only existing bulk test used
    `table`, which every question always permits — which is precisely what
    masked it.
    """
    if not fixture_path.exists():
        pytest.skip(f"{fixture_path.name} not found in project root")

    session_id = uploader(client)

    crosstab = client.post(
        f"/api/session/{session_id}/crosstab",
        json={"break_spec": {"dimensions": ["gender"]}, "filter_spec": {"selections": {}}},
    )
    assert crosstab.status_code == 200, crosstab.text
    results = crosstab.json()

    # Find a chart type that at least one question permits and at least one
    # refuses, so the batch genuinely mixes both outcomes.
    def permitted_types(qr):
        return {p["chart_type"] for p in qr["permitted_charts"] if p["permitted"]}

    mixed_type = None
    for candidate in ("net_bar", "diverging_stacked_bar", "grouped_bar", "stacked_bar_100"):
        allows = [qr["question_id"] for qr in results if candidate in permitted_types(qr)]
        refuses = [qr["question_id"] for qr in results if candidate not in permitted_types(qr)]
        if allows and refuses:
            mixed_type = (candidate, allows, refuses)
            break
    if mixed_type is None:
        pytest.skip("no chart type in this fixture is permitted for some questions and not others")

    chart_type, allows, refuses = mixed_type
    out_dir = tmp_path / "bulk-mixed"

    response = client.post(
        f"/api/session/{session_id}/breaks-export-bulk",
        json={
            "break_spec": {"dimensions": ["gender"]},
            "filter_spec": {"selections": {}},
            "chart_type": chart_type,
            "question_ids": allows + refuses,
            "out_dir": str(out_dir),
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert {e["question_id"] for e in body["exported"]} == set(allows)
    assert {s["question_id"] for s in body["skipped"]} == set(refuses)
    for entry in body["exported"]:
        assert (out_dir / entry["filename"]).stat().st_size > 0
    for skip in body["skipped"]:
        assert skip["reason"], "a skipped question must carry a reason"


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
    """POST .../export is the legacy Charts tab's own export (now Plotly-based,
    like the breaks export); the breaks export deliberately took a different
    path so as not to shadow it."""
    if not RAKUTEN_PATH.exists():
        pytest.skip(f"{RAKUTEN_PATH.name} not found in project root")

    session_id = _upload(client)
    response = client.post(
        f"/api/session/{session_id}/export",
        data={"out_dir": str(tmp_path)},
    )
    assert response.status_code == 200, response.text
    assert "exported" in response.json()
