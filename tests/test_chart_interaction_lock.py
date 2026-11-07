"""v4 feedback F2: no chart the app shows can be zoomed, panned, box/lasso
selected or legend-toggled, and no Plotly toolbar is shown -- Export PNG is
the only way to save an image.

Checked on the real Toluna file through the same endpoints the screen uses:
every Charts tab figure (/charts) and every permitted Cross-tab chart type,
with and without Swap axes (/breaks-figure).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).parent.parent
TOLUNA_PATH = ROOT / "toluna_survey_misinformation_data.xlsx"
STATIC = ROOT / "surveytool" / "desktop" / "static"
_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@pytest.fixture
def toluna_session():
    if not TOLUNA_PATH.exists():
        pytest.skip(f"{TOLUNA_PATH.name} not found in project root")
    from surveytool.desktop.app import app

    client = TestClient(app)
    with open(TOLUNA_PATH, "rb") as f:
        response = client.post(
            "/api/upload",
            data={"vendor": "toluna", "survey_id": "t"},
            files={"file": (TOLUNA_PATH.name, f, _XLSX_MIME)},
        )
    assert response.status_code == 200, response.text
    return client, response.json()["session_id"]


def _assert_locked(layout: dict, what: str) -> None:
    assert layout.get("dragmode") is False, f"{what}: drag can zoom/pan/select"
    legend = layout.get("legend", {})
    assert legend.get("itemclick") is False, f"{what}: legend click hides series"
    assert legend.get("itemdoubleclick") is False, f"{what}: legend double-click isolates series"
    axes = [k for k in layout if re.fullmatch(r"[xy]axis\d*", k)]
    for axis in axes:
        assert layout[axis].get("fixedrange") is True, f"{what}: {axis} range can change"


def test_every_charts_tab_figure_is_locked(toluna_session):
    client, session_id = toluna_session
    charts = client.get(f"/api/session/{session_id}/charts").json()
    charts = charts["charts"] if isinstance(charts, dict) else charts
    assert charts
    for chart in charts:
        layout = chart["figure"]["layout"]
        _assert_locked(layout, f"{chart['qid']}/{chart['chart_type']}")
        assert any(k.startswith("xaxis") for k in layout) and any(k.startswith("yaxis") for k in layout)


def test_every_crosstab_figure_is_locked(toluna_session):
    client, session_id = toluna_session
    crosstab = client.post(
        f"/api/session/{session_id}/crosstab",
        json={"break_spec": {"dimensions": ["gender"]}, "filter_spec": {"selections": {}}, "question_ids": ["6"]},
    )
    assert crosstab.status_code == 200, crosstab.text
    permitted = [p["chart_type"] for p in crosstab.json()[0]["permitted_charts"] if p["permitted"]]
    assert {"stacked_bar_100", "grouped_bar", "table"} <= set(permitted)

    for chart_type in permitted:
        for swap in (False, True):
            response = client.post(
                f"/api/session/{session_id}/breaks-figure",
                json={
                    "break_spec": {"dimensions": ["gender"]},
                    "filter_spec": {"selections": {}},
                    "chart_type": chart_type,
                    "question_id": "6",
                    "swap_axes": swap,
                },
            )
            assert response.status_code == 200, response.text
            _assert_locked(response.json()["figure"]["layout"], f"{chart_type} swap={swap}")


def test_screen_config_hides_the_toolbar_everywhere():
    """The mode bar is Plotly *config*, not figure layout, so it is set in
    JS. Every on-screen Plotly.newPlot/react call must pass the one shared
    read-only config."""
    charts_js = (STATIC / "charts.js").read_text(encoding="utf-8")
    config = re.search(r"const PLOTLY_SCREEN_CONFIG = Object\.freeze\(\{(.*?)\}\);", charts_js, re.S)
    assert config, "PLOTLY_SCREEN_CONFIG missing from charts.js"
    for setting in ("displayModeBar: false", "scrollZoom: false", "doubleClick: false"):
        assert setting in config.group(1)

    sources = {p.name: p.read_text(encoding="utf-8") for p in STATIC.glob("*.js")}
    sources["index.html"] = (STATIC / "index.html").read_text(encoding="utf-8")
    calls = 0
    for name, text in sources.items():
        for match in re.finditer(r"Plotly\.(newPlot|react)\((.*?)\);", text, re.S):
            calls += 1
            assert "PLOTLY_SCREEN_CONFIG" in match.group(2), f"{name}: Plotly.{match.group(1)} without the read-only config"
    assert calls == 2  # Charts tab + Cross-tab
