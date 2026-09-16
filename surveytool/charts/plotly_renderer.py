"""Plotly/kaleido renderer for the five breaks-and-filters chart types
(build plan section 11).

Scoped strictly to the five new chart types declared in
``surveytool.core.chart_validity.ChartType``
(``stacked_bar_100``/``diverging_stacked_bar``/``grouped_bar``/``net_bar``/
``table``). This module never touches ``surveytool/charts/renderer.py``'s
matplotlib rendering for the legacy ``dist``/``xbreak``/``means`` chart
types, and the two renderers are otherwise unrelated code paths that happen
to coexist in the same app.

Follows the same spec-builder/render separation ``chart_data.py`` /
``renderer.py`` already establish for the legacy charts: one pure
figure-builder function per chart type (``_stacked_bar_100_figure`` etc.),
each taking a ``QuestionResult`` and returning a ``plotly.graph_objects.Figure``
with no file I/O. ``build_figure`` dispatches to the right builder and is the
single place chart-type permission is enforced against
``QuestionResult.permitted_charts`` — a caller (the ``breaks-export``
endpoint) could also check this before calling in, but this module does not
trust that and re-checks itself, so an illegitimate chart_type can never
reach kaleido regardless of which layer forgot the check. ``rasterize``
performs the only file I/O in this module (the ``fig.write_image`` call).

Suppressed cells (``ColumnResult.band == Band.suppressed``, figures nulled by
``breaks_compute.py``) are rendered as labelled gaps: the cell's
``label_path`` and ``base_cell`` remain visible on the chart, but no bar
segment, net value or table row is fabricated for it — this mirrors the
build plan's "suppressed cells remain in the payload as cells... rendered as
labelled gaps," not silently dropped from the chart.
"""
from __future__ import annotations

import plotly.graph_objects as go

from surveytool.charts.errors import ErrorCode, SurveyToolError
from surveytool.charts.palette import assign_series_colours
from surveytool.charts.styles import ChartStyle, get_style
from surveytool.compute.breaks_compute import ColumnResult, QuestionResult
from surveytool.core.chart_validity import ChartType
from surveytool.core.precision import DISPLAY_PRECISION, format_percentage
from surveytool.core.suppression import Band
from surveytool.core.text_hygiene import wrap_text

# Brand palette, reused from renderer.py's conventions (module docstring
# point 3: visual consistency is a judgment call, not a hard requirement --
# these are close to but not required to exactly match _ROLE_COLOUR).
# _TEAL (formerly "#1B667D", hardcoded here) was retired in favour of
# style.palette[0] in _table_figure -- brand's palette[0] is this same
# value, so the default rendering is unchanged.
_GREY = "#9AA5A8"
_WARM = "#C4856A"
_SUPPRESSED_GREY = "#D0D0D0"

# Single source of truth for every percentage-bar tooltip (Round C4): no
# trace formats its own hover text independently, so a tooltip can never
# disagree with the panel figure's DISPLAY_PRECISION-rounded value.
#
# This reads Plotly's %{y}, the raw plotted y-value. That's correct for
# _stacked_bar_100_figure/_grouped_bar_figure/_net_bar_figure, whose traces'
# y IS the true percentage. It is NOT correct for _diverging_stacked_bar_figure,
# whose traces sign-flip and half-value y for layout purposes (see that
# function's own hovertemplate constant below) -- that function must never
# use this one.
_HOVER_TEMPLATE = f"%{{y:.{DISPLAY_PRECISION}f}}%%<extra>%{{fullData.name}}</extra>"

# _diverging_stacked_bar_figure-only hover template (Round C4 fix-wave
# Finding 1): that function's traces plot y = -true_pct for negative-polarity
# points and y = +-true_pct/2 for the neutral point's two half-traces, purely
# for bar-layout purposes -- %{y} on those traces would show a sign-flipped
# or halved number, which is a wrong value, not just a precision defect.
# Each of that function's traces instead carries the TRUE (unflipped,
# un-halved) percentage as `customdata`, and this template reads that.
_DIVERGING_HOVER_TEMPLATE = f"%{{customdata:.{DISPLAY_PRECISION}f}}%%<extra>%{{fullData.name}}</extra>"


def _header_text(
    question_result: QuestionResult,
    break_spec: list[str] | None,
    filter_spec: dict[str, list[str]] | None,
    chart_type: ChartType,
) -> str:
    """Build the export header block's text content.

    Composed into the Figure's title (point 3 of the brief) rather than a
    sidecar file, so it is genuinely visible in the rasterized image.
    """
    break_text = ", ".join(break_spec) if break_spec else "(none)"
    if filter_spec:
        filter_text = "; ".join(
            f"{dim}={','.join(values)}" for dim, values in filter_spec.items()
        )
    else:
        filter_text = "(none)"

    raw_lines = [
        question_result.question_text,
        (
            f"Break by: {break_text}  |  Filter by: {filter_text}  |  "
            f"Chart: {chart_type.value}"
        ),
        (
            f"Base total: {question_result.base_total:,}  |  "
            f"Base filtered: {question_result.base_filtered:,}"
        ),
    ]
    if question_result.display_order_is_manual:
        raw_lines.append("⚠ Response options manually reordered")
    wrapped_lines = []
    for line in raw_lines:
        wrapped_lines.extend(wrap_text(line, max_chars_per_line=90))
    return "<br>".join(wrapped_lines)


def wrap_axis_labels(labels: list[str], max_chars_per_line: int = 24) -> list[str]:
    """Wrap each category-axis label independently onto multiple lines via
    Plotly's native <br> tick-label break syntax, mirroring what
    renderer.py's _wrap_title/_compute_left_margin already do for the
    matplotlib path -- ported here so the shared on-screen/export Plotly
    layer gets the same treatment, rather than truncating or letting long
    labels overlap."""
    return ["<br>".join(wrap_text(label, max_chars_per_line=max_chars_per_line)) for label in labels]


def compute_axis_margin(
    labels: list[str],
    base_margin: int = 60,
    px_per_char: int = 7,
    px_per_line: int = 14,
) -> int:
    """Compute a margin (in pixels) sized to accommodate the widest/tallest
    wrapped label, so wrap_axis_labels' output is never clipped by a fixed
    margin. Unlike renderer.py's _compute_left_margin (which measures an
    actual rendered matplotlib text extent), this is a pure character-count
    estimate: Plotly's figure is serialized before any client render pass
    exists for this module to measure against, so an estimate errs generous
    rather than exact -- consistent with this module's existing "figure
    building has no file I/O, no rendering side effects" contract."""
    wrapped = wrap_axis_labels(labels)
    max_lines = max((w.count("<br>") + 1 for w in wrapped), default=1)
    max_line_chars = max((len(line) for w in wrapped for line in w.split("<br>")), default=0)
    estimated = int(max_line_chars * px_per_char * 0.3 + max_lines * px_per_line) + base_margin // 2
    return max(base_margin, estimated)


def _apply_header(
    fig: go.Figure,
    question_result: QuestionResult,
    break_spec: list[str] | None,
    filter_spec: dict[str, list[str]] | None,
    chart_type: ChartType,
    style: ChartStyle,
    axis_labels: list[str] | None = None,
) -> None:
    fig.update_layout(
        title={
            "text": _header_text(question_result, break_spec, filter_spec, chart_type),
            "x": 0.02,
            "xanchor": "left",
            "font": {"size": 13},
        },
        margin={"t": 140, "b": compute_axis_margin(axis_labels or [])},
        paper_bgcolor=style.background,
        plot_bgcolor=style.background,
        font={"color": style.font_color},
    )


def _column_display_label(column: ColumnResult) -> str:
    label = " / ".join(column.label_path) if column.label_path else "Total"
    if column.band is Band.suppressed:
        return f"{label} (suppressed, n={column.base_cell})"
    return label


def _stacked_bar_100_figure(question_result: QuestionResult, style: ChartStyle) -> go.Figure:
    """One 100%-stacked bar per column; segments = scale points.

    Percentages come straight from each ColumnResult.percentages. A
    suppressed column contributes no segments (its percentages are None) —
    it still gets an x position and a labelled gap, per the module
    docstring's suppression handling.
    """
    fig = go.Figure()
    x_labels = wrap_axis_labels([_column_display_label(c) for c in question_result.columns])
    colour_by_label = assign_series_colours(
        [point.label for point in question_result.scale_points],
        palette=style.palette,
    )

    for point in question_result.scale_points:
        code = str(point.code)
        y_values = []
        for column in question_result.columns:
            if column.percentages is None:
                y_values.append(0)
            else:
                y_values.append(column.percentages.get(code, 0.0))
        fig.add_trace(
            go.Bar(
                name=point.label,
                x=x_labels,
                y=y_values,
                marker_color=colour_by_label[point.label],
                hovertemplate=_HOVER_TEMPLATE,
            )
        )

    # Suppressed columns: overlay a flat grey "gap" bar at 100% so the column
    # position reads as withheld rather than as a genuine zero.
    gap_y = [
        100 if c.band is Band.suppressed else 0 for c in question_result.columns
    ]
    if any(gap_y):
        fig.add_trace(
            go.Bar(
                name="Suppressed (base too small)",
                x=x_labels,
                y=gap_y,
                marker_color=_SUPPRESSED_GREY,
                marker_pattern_shape="x",
            )
        )

    fig.update_layout(barmode="stack", yaxis_title="%", yaxis_range=[0, 100])
    return fig


def _diverging_stacked_bar_figure(question_result: QuestionResult, style: ChartStyle) -> go.Figure:
    """Bars diverging from 0: bottom-half points (by rank) extend left,
    top-half points extend right. An odd-length variant's exact-middle
    point (CodeRole.neutral) is rendered as its own centered segment
    straddling zero, half on each side, so it visually sits on the
    dividing line rather than stacking onto either wing. An even-length
    variant has no neutral point at all -- it divides cleanly at the
    midpoint with no straddling segment needed.
    """
    fig = go.Figure()
    x_labels = wrap_axis_labels([_column_display_label(c) for c in question_result.columns])
    colour_by_label = assign_series_colours(
        [point.label for point in question_result.scale_points],
        palette=style.palette,
    )

    for point in question_result.scale_points:
        code = str(point.code)
        if point.polarity == "neutral":
            # Straddle zero: half the value on each side, as two half-
            # magnitude traces sharing one legend name via one trace with
            # a symmetric base -- Plotly's relative stacking doesn't
            # support a single bar straddling zero directly, so split the
            # value in half and draw one negative-side and one positive-
            # side trace, both using this point's colour and label, with
            # showlegend suppressed on the second so it appears once.
            neg_half = []
            pos_half = []
            true_pct = []
            for column in question_result.columns:
                pct = 0.0 if column.percentages is None else column.percentages.get(code, 0.0)
                neg_half.append(-pct / 2.0)
                pos_half.append(pct / 2.0)
                true_pct.append(pct)
            # Both half-traces carry the FULL (un-halved) true percentage as
            # customdata: the tooltip must read the same true value on both
            # sides of the straddled bar, not half of it (Round C4 fix-wave
            # Finding 1).
            fig.add_trace(go.Bar(name=point.label, x=x_labels, y=neg_half, customdata=true_pct, marker_color=colour_by_label[point.label], hovertemplate=_DIVERGING_HOVER_TEMPLATE))
            fig.add_trace(go.Bar(name=point.label, x=x_labels, y=pos_half, customdata=true_pct, marker_color=colour_by_label[point.label], showlegend=False, hovertemplate=_DIVERGING_HOVER_TEMPLATE))
            continue

        sign = -1.0 if point.polarity == "negative" else 1.0
        y_values = []
        true_pct = []
        for column in question_result.columns:
            if column.percentages is None:
                y_values.append(0.0)
                true_pct.append(0.0)
            else:
                pct = column.percentages.get(code, 0.0)
                y_values.append(sign * pct)
                true_pct.append(pct)
        fig.add_trace(
            go.Bar(
                name=point.label,
                x=x_labels,
                y=y_values,
                customdata=true_pct,
                marker_color=colour_by_label[point.label],
                hovertemplate=_DIVERGING_HOVER_TEMPLATE,
            )
        )

    gap_extent = [
        (-100 if c.band is Band.suppressed else 0, 100 if c.band is Band.suppressed else 0)
        for c in question_result.columns
    ]
    if any(lo or hi for lo, hi in gap_extent):
        fig.add_trace(
            go.Bar(
                name="Suppressed (base too small)",
                x=x_labels,
                y=[hi for _, hi in gap_extent],
                base=[lo for lo, _ in gap_extent],
                marker_color=_SUPPRESSED_GREY,
                marker_pattern_shape="x",
            )
        )

    fig.update_layout(barmode="relative", yaxis_title="%")
    fig.add_hline(y=0, line_color="#888888", line_width=1)
    return fig


def _grouped_bar_figure(question_result: QuestionResult, style: ChartStyle) -> go.Figure:
    """Grouped bars: one group per column, one bar per scale point within
    the group. A suppressed column's group is emitted with zero-height bars
    plus an annotation, rather than omitted, so its x position still reads
    as a labelled gap.
    """
    fig = go.Figure()
    x_labels = wrap_axis_labels([_column_display_label(c) for c in question_result.columns])
    colour_by_label = assign_series_colours(
        [point.label for point in question_result.scale_points],
        palette=style.palette,
    )

    for point in question_result.scale_points:
        code = str(point.code)
        y_values = []
        for column in question_result.columns:
            if column.percentages is None:
                y_values.append(0.0)
            else:
                y_values.append(column.percentages.get(code, 0.0))
        fig.add_trace(
            go.Bar(
                name=point.label,
                x=x_labels,
                y=y_values,
                marker_color=colour_by_label[point.label],
                hovertemplate=_HOVER_TEMPLATE,
            )
        )

    for i, column in enumerate(question_result.columns):
        if column.band is Band.suppressed:
            fig.add_annotation(
                x=x_labels[i], y=1, yref="paper", showarrow=False,
                text="suppressed", font={"size": 10, "color": "#888888"},
                yshift=10,
            )

    fig.update_layout(barmode="group", yaxis_title="%")
    return fig


def _net_bar_figure(question_result: QuestionResult, style: ChartStyle) -> go.Figure:
    """Bars showing net (t2b/b2b) values per column, one trace per net.

    net_bar is permitted only when the question has >= 1 net (chart_validity
    rule); a suppressed column's nets are None and contributes a gap. Each
    net gets its own colour via assign_series_colours(style.palette), the
    same per-series colour-assignment convention the other three bar
    builders use, so a non-brand style's palette is visible here too.
    """
    fig = go.Figure()
    x_labels = wrap_axis_labels([_column_display_label(c) for c in question_result.columns])
    colour_by_label = assign_series_colours(
        [net_def.label for net_def in question_result.nets],
        palette=style.palette,
    )

    for net_def in question_result.nets:
        y_values = []
        for column in question_result.columns:
            if column.nets is None or net_def.net_id not in column.nets:
                y_values.append(0.0)
            else:
                y_values.append(column.nets[net_def.net_id].percentage)
        fig.add_trace(
            go.Bar(
                name=net_def.label,
                x=x_labels,
                y=y_values,
                marker_color=colour_by_label[net_def.label],
                hovertemplate=_HOVER_TEMPLATE,
            )
        )

    gap_y = [
        100 if c.band is Band.suppressed else 0 for c in question_result.columns
    ]
    if any(gap_y):
        fig.add_trace(
            go.Bar(
                name="Suppressed (base too small)",
                x=x_labels,
                y=gap_y,
                marker_color=_SUPPRESSED_GREY,
                marker_pattern_shape="x",
            )
        )

    fig.update_layout(barmode="group", yaxis_title="%")
    return fig


def _table_figure(question_result: QuestionResult, style: ChartStyle) -> go.Figure:
    """A Plotly table: rows = scale points, columns = cells, cell text =
    'count (pct%)'. Always buildable regardless of column count or scale
    polarity, matching table's "always permitted" status. Suppressed
    columns show a plain "suppressed" marker instead of fabricated figures.

    The header fill uses style.palette[0] (brand's first palette entry is
    "#1B667D", the same value this function hardcoded before the chart
    style feature, so this is byte-identical to the pre-feature default)
    and cells use style.background, so a
    non-brand style's colours are visible here too, consistent with how the
    three bar builders apply style to both background/font (via
    _apply_header) and palette.
    """
    header = ["Scale point"] + [_column_display_label(c) for c in question_result.columns]

    rows: list[list[str]] = []
    for point in question_result.scale_points:
        code = str(point.code)
        row = [point.label]
        for column in question_result.columns:
            if column.band is Band.suppressed or column.counts is None:
                row.append("suppressed")
            else:
                n = column.counts.get(code, 0)
                pct = column.percentages.get(code, 0.0) if column.percentages else 0.0
                row.append(f"{n} ({format_percentage(pct)})")
        rows.append(row)

    for net_def in question_result.nets:
        row = [net_def.label]
        for column in question_result.columns:
            if column.band is Band.suppressed or column.nets is None:
                row.append("suppressed")
            elif net_def.net_id in column.nets:
                net_result = column.nets[net_def.net_id]
                row.append(f"{net_result.count} ({format_percentage(net_result.percentage)})")
            else:
                row.append("—")
        rows.append(row)

    base_row = ["Base (n)"] + [str(c.base_cell) for c in question_result.columns]
    rows.append(base_row)

    columns_data = [
        [row[i] for row in rows] for i in range(len(header))
    ]

    fig = go.Figure(
        data=[
            go.Table(
                header={"values": header, "fill_color": style.palette[0], "font": {"color": "white"}},
                cells={"values": columns_data, "fill_color": style.background},
            )
        ]
    )
    return fig


_BUILDERS = {
    ChartType.stacked_bar_100: _stacked_bar_100_figure,
    ChartType.diverging_stacked_bar: _diverging_stacked_bar_figure,
    ChartType.grouped_bar: _grouped_bar_figure,
    ChartType.net_bar: _net_bar_figure,
    ChartType.table: _table_figure,
}


def build_figure(
    question_result: QuestionResult,
    chart_type: ChartType,
    *,
    break_spec: list[str] | None = None,
    filter_spec: dict[str, list[str]] | None = None,
) -> go.Figure:
    """Build the requested chart type's figure for a computed result.

    Enforces chart-type permission itself: raises SurveyToolError if
    `chart_type` is not `permitted=True` in `question_result.permitted_charts`
    (populated by `attach_chart_permissions`/`populate_permitted_charts`
    before this is called). This module does not trust the caller to have
    already checked -- an illegitimate chart_type can never reach
    `rasterize` regardless of which layer the caller enforces it in, because
    this is the layer that actually owns the check.

    `break_spec`/`filter_spec` are accepted for the header block only; the
    figure's data always comes from `question_result` alone.
    """
    permission = next(
        (p for p in question_result.permitted_charts if p.chart_type is chart_type),
        None,
    )
    if permission is None or not permission.permitted:
        reason = permission.reason if permission is not None else "not evaluated"
        raise SurveyToolError(
            ErrorCode.INTERNAL,
            "This chart type isn't available for the current selection.",
            detail=(
                f"chart_type={chart_type.value!r} is not permitted for question "
                f"{question_result.question_id!r} (reason={reason})."
            ),
            next_action="Choose a different chart type, or adjust Break by / Filter by.",
        )

    builder = _BUILDERS[chart_type]
    style = get_style(question_result.chart_style)
    fig = builder(question_result, style)
    axis_labels = [_column_display_label(c) for c in question_result.columns]
    _apply_header(fig, question_result, break_spec, filter_spec, chart_type, style, axis_labels=axis_labels)
    return fig


def rasterize(fig: go.Figure, path) -> None:
    """Write a built Figure to `path` via kaleido.

    The installed plotly/kaleido versions (plotly>=6, kaleido>=1.0) made
    kaleido the sole, default image engine: `Figure.write_image` no longer
    accepts (and warns on) an explicit `engine=` kwarg, so none is passed
    here. This is the only file I/O in this module.
    """
    fig.write_image(str(path))
