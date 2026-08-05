"""plotly_renderer.py tests (build plan section 11 / Task 9).

Section A: synthetic QuestionResult fixtures -- one figure-spec test per
           chart type (trace types/structure only, no rendering), header
           block presence, suppressed-cell gap rendering, and the
           chart-type-permission enforcement build_figure owns.
Section B: real kaleido round-trip -- write_image actually produces a
           non-empty PNG file for at least one chart type.
Section C: the POST .../breaks-export endpoint, covered in
           tests/test_desktop_breaks_api.py (upload/session plumbing lives
           there already); this file does not duplicate those endpoint tests.
"""
from __future__ import annotations

from pathlib import Path

import plotly.graph_objects as go
import pytest

from surveytool.charts.errors import ErrorCode, SurveyToolError
from surveytool.charts.plotly_renderer import build_figure, rasterize
from surveytool.compute.breaks_compute import (
    ColumnResult,
    NetDefinition,
    NetResult,
    QuestionResult,
    ScalePoint,
)
from surveytool.core.chart_validity import ChartPermission, ChartType
from surveytool.core.suppression import Band


# ── Section A: synthetic fixtures ───────────────────────────────────────────


def _scale_points() -> list[ScalePoint]:
    return [
        ScalePoint(code=1, label="Strongly disagree", order=0, polarity="negative"),
        ScalePoint(code=2, label="Disagree", order=1, polarity="negative"),
        ScalePoint(code=3, label="Neutral", order=2, polarity="neutral"),
        ScalePoint(code=4, label="Agree", order=3, polarity="positive"),
        ScalePoint(code=5, label="Strongly agree", order=4, polarity="positive"),
    ]


def _ok_column(key: str, label: str, base: int = 100) -> ColumnResult:
    return ColumnResult(
        key=[["gender", key]],
        label_path=[label],
        base_cell=base,
        base_valid=base,
        n_invalid=0,
        band=Band.ok,
        counts={"1": 10, "2": 15, "3": 20, "4": 30, "5": 25},
        percentages={"1": 10.0, "2": 15.0, "3": 20.0, "4": 30.0, "5": 25.0},
        nets={
            "t2b": NetResult(count=55, percentage=55.0, base_valid=base),
            "b2b": NetResult(count=25, percentage=25.0, base_valid=base),
        },
    )


def _suppressed_column(key: str, label: str, base: int = 5) -> ColumnResult:
    return ColumnResult(
        key=[["gender", key]],
        label_path=[label],
        base_cell=base,
        base_valid=None,
        n_invalid=None,
        band=Band.suppressed,
        counts=None,
        percentages=None,
        nets=None,
    )


def _permitted_all() -> list[ChartPermission]:
    return [
        ChartPermission(chart_type=ct, permitted=True) for ct in ChartType
    ]


def _question_result(
    columns: list[ColumnResult],
    permitted_charts: list[ChartPermission] | None = None,
    scale_id: str | None = "agreement",
    nets: list[NetDefinition] | None = None,
) -> QuestionResult:
    qr = QuestionResult(
        question_id="Q1",
        question_text="Synthetic scale question Q1",
        scale_id=scale_id,
        scale_points=_scale_points(),
        nets=nets if nets is not None else [
            NetDefinition(net_id="t2b", label="Top 2 Box", member_codes=[4, 5]),
            NetDefinition(net_id="b2b", label="Bottom 2 Box", member_codes=[1, 2]),
        ],
        base_total=500,
        base_filtered=200,
        columns=columns,
    )
    qr.permitted_charts = (
        permitted_charts if permitted_charts is not None else _permitted_all()
    )
    return qr


@pytest.fixture
def question_result() -> QuestionResult:
    return _question_result([_ok_column("male", "Male"), _ok_column("female", "Female")])


@pytest.fixture
def question_result_with_suppressed_cell() -> QuestionResult:
    return _question_result(
        [_ok_column("male", "Male"), _suppressed_column("female", "Female", base=5)]
    )


# --- one figure-spec test per chart type ------------------------------------


def test_stacked_bar_100_figure_has_one_trace_per_scale_point(question_result):
    fig = build_figure(question_result, ChartType.stacked_bar_100)
    assert isinstance(fig, go.Figure)
    bar_traces = [t for t in fig.data if isinstance(t, go.Bar)]
    # 5 scale points, no suppressed columns so no extra gap trace.
    assert len(bar_traces) == 5
    assert fig.layout.barmode == "stack"
    for trace, point in zip(bar_traces, question_result.scale_points):
        assert trace.name == point.label
        assert list(trace.x) == ["Male", "Female"]


def test_diverging_stacked_bar_figure_signs_by_polarity(question_result):
    fig = build_figure(question_result, ChartType.diverging_stacked_bar)
    bar_traces = [t for t in fig.data if isinstance(t, go.Bar)]
    assert len(bar_traces) == 5
    by_name = {t.name: t for t in bar_traces}
    # negative-polarity points extend into negative y.
    assert all(v <= 0 for v in by_name["Strongly disagree"].y)
    assert all(v <= 0 for v in by_name["Disagree"].y)
    # positive-polarity points extend into positive y.
    assert all(v >= 0 for v in by_name["Agree"].y)
    assert all(v >= 0 for v in by_name["Strongly agree"].y)


def test_grouped_bar_figure_uses_group_mode(question_result):
    fig = build_figure(question_result, ChartType.grouped_bar)
    assert fig.layout.barmode == "group"
    bar_traces = [t for t in fig.data if isinstance(t, go.Bar)]
    assert len(bar_traces) == 5


def test_net_bar_figure_has_one_trace_per_net(question_result):
    fig = build_figure(question_result, ChartType.net_bar)
    bar_traces = [t for t in fig.data if isinstance(t, go.Bar)]
    assert {t.name for t in bar_traces} == {"Top 2 Box", "Bottom 2 Box"}
    t2b = next(t for t in bar_traces if t.name == "Top 2 Box")
    assert list(t2b.y) == [55.0, 55.0]


def test_table_figure_is_always_buildable_even_with_undeclared_polarity():
    """table is exempt from every other constraint per chart_validity."""
    qr = _question_result(
        [_ok_column("male", "Male")],
        permitted_charts=[
            ChartPermission(chart_type=ct, permitted=(ct is ChartType.table))
            for ct in ChartType
        ],
        scale_id=None,
        nets=[],
    )
    fig = build_figure(qr, ChartType.table)
    assert isinstance(fig, go.Figure)
    assert isinstance(fig.data[0], go.Table)
    header = list(fig.data[0].header.values)
    assert header[0] == "Scale point"


# --- header block ------------------------------------------------------------


def test_header_block_present_in_figure_title(question_result):
    fig = build_figure(
        question_result,
        ChartType.table,
        break_spec=["gender"],
        filter_spec={"age_band": ["18-24"]},
    )
    title_text = fig.layout.title.text
    assert title_text is not None
    assert "gender" in title_text
    assert "age_band" in title_text
    assert "18-24" in title_text
    assert str(question_result.base_total) in title_text
    assert str(question_result.base_filtered) in title_text
    assert "table" in title_text


def test_header_block_present_without_break_or_filter(question_result):
    fig = build_figure(question_result, ChartType.table)
    title_text = fig.layout.title.text
    assert "(none)" in title_text


# --- suppressed cells: labelled gaps, not fabricated/omitted -----------------


def test_suppressed_cell_is_labelled_gap_in_stacked_bar(
    question_result_with_suppressed_cell,
):
    fig = build_figure(question_result_with_suppressed_cell, ChartType.stacked_bar_100)
    # The suppressed column is still present as an x position, labelled.
    bar_traces = [t for t in fig.data if isinstance(t, go.Bar)]
    x_labels = list(bar_traces[0].x)
    assert len(x_labels) == 2
    assert any("suppressed" in label for label in x_labels)
    # No fabricated percentages for the suppressed column: every real
    # scale-point trace reports 0 at that x position.
    for trace in bar_traces:
        if trace.name == "Suppressed (base too small)":
            continue
        assert trace.y[1] == 0.0
    # A distinct gap trace exists and is the only one carrying data there.
    gap_trace = next(t for t in bar_traces if t.name == "Suppressed (base too small)")
    assert gap_trace.y[1] == 100
    assert gap_trace.y[0] == 0


def test_suppressed_cell_is_labelled_gap_in_table(question_result_with_suppressed_cell):
    fig = build_figure(question_result_with_suppressed_cell, ChartType.table)
    table = fig.data[0]
    columns_data = table.cells.values
    # Second data column (index 2, after "Scale point" and "Male") is Female.
    female_column = columns_data[2]
    assert all(cell == "suppressed" for cell in female_column[:5])  # 5 scale points


def test_suppressed_cell_is_labelled_gap_in_net_bar(question_result_with_suppressed_cell):
    fig = build_figure(question_result_with_suppressed_cell, ChartType.net_bar)
    bar_traces = [t for t in fig.data if isinstance(t, go.Bar)]
    t2b = next(t for t in bar_traces if t.name == "Top 2 Box")
    assert t2b.y[1] == 0.0  # no fabricated net value for the suppressed column
    gap_trace = next(t for t in bar_traces if t.name == "Suppressed (base too small)")
    assert gap_trace.y[1] == 100


# --- chart-type-permission enforcement (build_figure owns this check) -------


def test_build_figure_raises_when_chart_type_not_permitted():
    qr = _question_result(
        [_ok_column("male", "Male")],
        permitted_charts=[
            ChartPermission(
                chart_type=ChartType.diverging_stacked_bar,
                permitted=False,
                reason="SCALE_POLARITY_UNDECLARED",
            ),
            ChartPermission(chart_type=ChartType.table, permitted=True),
        ],
    )
    with pytest.raises(SurveyToolError) as exc_info:
        build_figure(qr, ChartType.diverging_stacked_bar)
    assert exc_info.value.code is ErrorCode.INTERNAL
    assert "diverging_stacked_bar" in exc_info.value.detail


def test_build_figure_raises_when_chart_type_absent_from_permitted_charts():
    qr = _question_result([_ok_column("male", "Male")], permitted_charts=[])
    with pytest.raises(SurveyToolError):
        build_figure(qr, ChartType.table)


def test_build_figure_succeeds_when_permitted(question_result):
    fig = build_figure(question_result, ChartType.table)
    assert isinstance(fig, go.Figure)


# ── Section B: real kaleido round-trip ──────────────────────────────────────


def test_rasterize_writes_a_nonempty_png(question_result, tmp_path):
    fig = build_figure(question_result, ChartType.table)
    out_path = tmp_path / "chart.png"
    rasterize(fig, out_path)
    assert out_path.exists()
    assert out_path.stat().st_size > 0
    # A real PNG starts with the PNG magic bytes.
    assert out_path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_rasterize_stacked_bar_100_round_trip(question_result, tmp_path):
    fig = build_figure(question_result, ChartType.stacked_bar_100)
    out_path = tmp_path / "stacked.png"
    rasterize(fig, out_path)
    assert out_path.exists()
    assert out_path.stat().st_size > 0
