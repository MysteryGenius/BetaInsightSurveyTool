"""
Chart acceptance tests.

Data-shape acceptance criteria (missing rows, manifest, non-substantive
handling, labels) now live in tests/test_chart_data.py, exercised against
the Plotly-based chart_data.py path. This file covers the legacy-figure
Plotly rendering layer (build_legacy_figure) that superseded the deleted
matplotlib renderer.py.
"""
from __future__ import annotations


# ── Plotly-based legacy figure builder (Item A) ──────────────────────────────

def _dist_chart_data():
    from surveytool.charts.chart_data import ChartData
    return ChartData(
        chart_type="dist", filename="t__Q1__dist__total.png", qid="Q1",
        question_text="How satisfied are you?", breakdown_variable="total", metric="pct",
        trace={
            "labels": ["Dissatisfied", "Neutral", "Satisfied"],
            "values": [10.0, 20.0, 70.0],
            "n": [10, 20, 70],
            "role": ["bottom", "neutral", "top"],
            "cell_base": 100, "mean": 4.1, "t2b": 70.0,
        },
    )


def _xbreak_chart_data():
    from surveytool.charts.chart_data import ChartData
    return ChartData(
        chart_type="xbreak", filename="t__Q1__xbreak__region.png", qid="Q1",
        question_text="How satisfied are you?", breakdown_variable="region", metric="t2b",
        trace={"levels": ["North", "South"], "values": [65.0, 75.0], "n": [50, 50],
               "metric": "t2b", "is_pct": True},
    )


def _means_chart_data():
    from surveytool.charts.chart_data import ChartData
    return ChartData(
        chart_type="means", filename="t__all__means__total.png", qid="Q1",
        question_text="Q1", breakdown_variable="total", metric="mean",
        trace={"labels": ["Q1", "Q2"], "values": [4.1, 3.8], "cell_base": 100},
    )


def test_build_legacy_figure_dist_has_one_bar_trace_with_all_labels():
    from surveytool.charts.plotly_renderer import build_legacy_figure
    from surveytool.charts.styles import DEFAULT_STYLE

    fig = build_legacy_figure(_dist_chart_data(), DEFAULT_STYLE)
    assert len(fig.data) == 1
    assert list(fig.data[0].x) == [10.0, 20.0, 70.0]


def test_build_legacy_figure_xbreak_bars_by_level():
    from surveytool.charts.plotly_renderer import build_legacy_figure
    from surveytool.charts.styles import DEFAULT_STYLE

    fig = build_legacy_figure(_xbreak_chart_data(), DEFAULT_STYLE)
    assert list(fig.data[0].x) == ["North", "South"]
    assert list(fig.data[0].y) == [65.0, 75.0]


def test_build_legacy_figure_means_horizontal_bar():
    from surveytool.charts.plotly_renderer import build_legacy_figure
    from surveytool.charts.styles import DEFAULT_STYLE

    fig = build_legacy_figure(_means_chart_data(), DEFAULT_STYLE)
    assert list(fig.data[0].y) == ["Q1", "Q2"]
    assert list(fig.data[0].x) == [4.1, 3.8]


def test_build_legacy_figure_applies_response_colour_override():
    from surveytool.charts.plotly_renderer import build_legacy_figure
    from surveytool.charts.styles import DEFAULT_STYLE

    fig = build_legacy_figure(
        _dist_chart_data(), DEFAULT_STYLE, response_colours={"Satisfied": "#FF00FF"}
    )
    colours = fig.data[0].marker.color
    labels = _dist_chart_data().trace["labels"]
    assert colours[labels.index("Satisfied")] == "#FF00FF"


def test_build_legacy_figure_applies_non_brand_style_background():
    from surveytool.charts.plotly_renderer import build_legacy_figure
    from surveytool.charts.styles import STYLE_REGISTRY

    fig = build_legacy_figure(_dist_chart_data(), STYLE_REGISTRY["cool"])
    assert fig.layout.paper_bgcolor == STYLE_REGISTRY["cool"].background
