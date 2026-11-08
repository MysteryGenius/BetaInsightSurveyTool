"""v4 feedback F4: the on-screen Cross-tab and its PNG show the same legend,
the PNG carries no diagnostic header, and the screen shows that header in
plain English with no internal identifiers.

Real Toluna file, through the same endpoints the screen (/crosstab,
/breaks-figure) and the export (/breaks-export) use.
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
_IDENTIFIER = re.compile(r"\b[a-z0-9]+_[a-z0-9_]+\b")  # age_band, stacked_bar_100, 18_24 ...


@pytest.fixture
def toluna():
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


def _figure(client, session_id, chart_type, swap, break_dims=("age_band",), filters=None, qid="6"):
    response = client.post(
        f"/api/session/{session_id}/breaks-figure",
        json={
            "break_spec": {"dimensions": list(break_dims)},
            "filter_spec": {"selections": filters or {}},
            "chart_type": chart_type,
            "question_id": qid,
            "swap_axes": swap,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _crosstab(client, session_id, break_dims=("age_band",), filters=None, qid="6"):
    response = client.post(
        f"/api/session/{session_id}/crosstab",
        json={
            "break_spec": {"dimensions": list(break_dims)},
            "filter_spec": {"selections": filters or {}},
            "question_ids": [qid],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()[0]


# --- 1. legend parity ----------------------------------------------------------


@pytest.mark.parametrize("chart_type", ["stacked_bar_100", "diverging_stacked_bar", "grouped_bar"])
@pytest.mark.parametrize("swap", [False, True])
def test_figure_carries_its_legend_for_every_bar_type_and_swap(toluna, chart_type, swap):
    client, session_id = toluna
    fig = _figure(client, session_id, chart_type, swap)["figure"]
    assert fig["layout"].get("showlegend") is not False
    legend_names = {t["name"] for t in fig["data"] if t.get("showlegend", True) and t.get("name")}
    assert len(legend_names) >= 2, (chart_type, swap)


def test_screen_draws_the_served_layout_without_touching_the_legend():
    """The legend bug was a screen-only `showlegend: false` override; the
    screen must now pass the served layout to Plotly untouched."""
    breaks_js = (STATIC / "breaks.js").read_text(encoding="utf-8")
    assert "showlegend" not in breaks_js
    assert "Plotly.react(chartArea, fig.data, fig.layout, PLOTLY_SCREEN_CONFIG)" in breaks_js


def test_answer_colours_match_the_drawn_traces(toluna):
    client, session_id = toluna
    body = _figure(client, session_id, "grouped_bar", False)
    drawn = {t["name"]: t["marker"]["color"] for t in body["figure"]["data"]}
    assert body["answer_colours"] == drawn


def test_charts_tab_answer_colours_match_the_drawn_bars(toluna):
    client, session_id = toluna
    charts = client.get(f"/api/session/{session_id}/charts").json()["charts"]
    dist = next(c for c in charts if c["chart_type"] == "dist" and c["qid"] == "6")
    bar = dist["figure"]["data"][0]
    assert [dist["answer_colours"][label] for label in dist["trace"]["labels"]] == list(bar["marker"]["color"])


# --- 2/3. no header in the PNG ------------------------------------------------------


@pytest.mark.parametrize("chart_type", ["stacked_bar_100", "diverging_stacked_bar", "grouped_bar", "net_bar", "table"])
@pytest.mark.parametrize("swap", [False, True])
def test_exported_figure_has_no_header_text(toluna, chart_type, swap):
    client, session_id = toluna
    fig = _figure(client, session_id, chart_type, swap, filters={"ethnicity": ["chinese"]})["figure"]
    title = fig["layout"]["title"]["text"]
    assert title.replace("<br>", " ") == _crosstab(client, session_id)["question_text"]
    for diagnostic in ("Break by", "Filter by", "Chart:", "Base total", "Base filtered", "reordered"):
        assert diagnostic not in title
    annotations = " ".join(a.get("text", "") for a in fig["layout"].get("annotations", []))
    assert "Break by" not in annotations and "Base" not in annotations


# --- 4. plain-English header on screen ------------------------------------------------


def test_header_lines_are_plain_english(toluna):
    client, session_id = toluna
    qr = _crosstab(client, session_id, break_dims=("age_band",), filters={"ethnicity": ["chinese", "malay"]})
    assert qr["header_lines"] == [
        "Break by: Age band  |  Filter by: Ethnicity: Chinese, Malay",
        f"Base total: 1,000  |  Base filtered: {736 + 133:,}",
    ]
    for line in qr["header_lines"]:
        assert not _IDENTIFIER.search(line), line


def test_nested_break_header_reads_in_order(toluna):
    client, session_id = toluna
    qr = _crosstab(client, session_id, break_dims=("gender", "age_band"))
    assert qr["header_lines"][0] == "Break by: Gender, then Age band  |  Filter by: None"


def test_manual_reorder_warning_stays_on_screen(toluna):
    client, session_id = toluna
    labels = [p["label"] for p in _crosstab(client, session_id)["scale_points"]]
    put = client.put("/api/projects/t/display-order/6", json={"label_order": list(reversed(labels))})
    assert put.status_code == 200, put.text
    qr = _crosstab(client, session_id)
    assert qr["header_lines"][-1] == "⚠ Response options manually reordered"
    # ...and still never in the figure.
    title = _figure(client, session_id, "grouped_bar", False)["figure"]["layout"]["title"]["text"]
    assert "reordered" not in title


def test_screen_chart_type_wording_matches_server_labels():
    """The header's "Chart:" segment uses breaks.js chartTypeLabel, which
    must say exactly what CHART_TYPE_LABELS says."""
    from surveytool.core.chart_validity import CHART_TYPE_LABELS

    breaks_js = (STATIC / "breaks.js").read_text(encoding="utf-8")
    for chart_type, label in CHART_TYPE_LABELS.items():
        assert f'{chart_type.value}: "{label}"' in breaks_js


def test_refused_chart_tooltip_is_a_plain_message_not_a_code():
    from surveytool.core.chart_validity import ChartPermission, ChartType

    for code in ("SCALE_POLARITY_UNDECLARED", "COLUMN_COUNT_EXCEEDS_RENDER_LIMIT"):
        dumped = ChartPermission(chart_type=ChartType.grouped_bar, permitted=False, reason=code).model_dump()
        assert dumped["reason"] == code  # stable identifier the UI switches on
        assert dumped["message"] and not _IDENTIFIER.search(dumped["message"])
        assert code not in dumped["message"]
    breaks_js = (STATIC / "breaks.js").read_text(encoding="utf-8")
    assert "btn.title = perm.message" in breaks_js
    assert "btn.title = perm.reason" not in breaks_js


def test_static_files_are_always_revalidated():
    """Scripts must never be reused from cache unchecked: a stale
    chart_legend.js next to a new breaks.js breaks the Cross-tab."""
    from surveytool.desktop.app import app

    client = TestClient(app)
    for path in ("/", "/breaks.js", "/chart_legend.js", "/charts.js"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert response.headers.get("cache-control") == "no-cache", path
