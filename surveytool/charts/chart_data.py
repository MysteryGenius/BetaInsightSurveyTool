from __future__ import annotations

from dataclasses import dataclass

from surveytool.charts.errors import ErrorCode, MissingFindingsRow, SurveyToolError
from surveytool.charts.types import ChartSpec
from surveytool.charts import iter_chart_specs
from surveytool.compute.frequency import describe_net
from surveytool.core.model import CodeRole, Question
from surveytool.core.natural_order import ChartOrders
from surveytool.core.scale_library import variant_point_count
from surveytool.findings.sheet import FindingsRow


@dataclass
class ChartData:
    chart_type: str
    filename: str
    qid: str
    question_text: str
    breakdown_variable: str
    metric: str
    trace: dict
    # What the chart plots, in plain English (v4 feedback F3), and the unit
    # on its value axis. Built here from the compute core's definitions,
    # never in the renderer.
    subtitle: str = ""
    value_axis_title: str = ""


def _index_rows(rows: list[FindingsRow]) -> dict[tuple[str, str, str], FindingsRow]:
    """Key: (breakdown_level, breakdown_variable, metric) → row."""
    return {(r.breakdown_level, r.breakdown_variable, r.metric): r for r in rows}


def _require_row(
    idx: dict,
    breakdown_level: str,
    breakdown_variable: str,
    metric: str,
    qid: str,
) -> FindingsRow:
    key = (breakdown_level, breakdown_variable, metric)
    row = idx.get(key)
    if row is None:
        raise MissingFindingsRow(qid, breakdown_variable, breakdown_level, metric)
    return row


def _apply_manual_order(labels: list[str], *parallel: list, manual_order: list[str] | None) -> tuple:
    """Reorder `labels` (and every list in `parallel`, index-for-index) to
    match `manual_order`. Labels not present in `manual_order` are appended
    in their original relative order, so a stale manual order (referring to
    a label no longer present) never drops a label silently."""
    if not manual_order:
        return (labels, *parallel)
    order_index = {label: i for i, label in enumerate(manual_order)}
    n = len(labels)
    indices = sorted(range(n), key=lambda i: (order_index.get(labels[i], n), i))
    reordered_labels = [labels[i] for i in indices]
    reordered_parallel = tuple([lst[i] for i in indices] for lst in parallel)
    return (reordered_labels, *reordered_parallel)


def _sort_by(items: list, label_of, order: list[str] | None) -> list:
    """Stable sort of `items` into `order` (by label); labels not in it keep
    their relative order, after the ones that are."""
    if not order:
        return items
    index = {label: i for i, label in enumerate(order)}
    return sorted(items, key=lambda it: index.get(label_of(it), len(order)))


def _dist_trace(
    spec: ChartSpec,
    manual_order: list[str] | None = None,
    natural_order: list[str] | None = None,
) -> dict:
    rows = spec.rows
    idx = _index_rows(rows)

    levels = {r.breakdown_level for r in rows}
    level = next(iter(levels))
    bvar = spec.breakdown_variable

    pct_rows = [r for r in rows if r.metric.startswith("pct_") and r.convention == "pct"]
    if not pct_rows:
        raise MissingFindingsRow(spec.qid, bvar, level, "pct_*")

    pct_metrics = {r.metric for r in pct_rows}
    for r in rows:
        if r.metric.startswith("n_") and r.convention == "n":
            expected_pct = "pct_" + r.metric[len("n_"):]
            if expected_pct not in pct_metrics:
                raise MissingFindingsRow(spec.qid, bvar, level, expected_pct)

    substantive: list[FindingsRow] = []
    nonsubstantive: list[FindingsRow] = []
    for pr in pct_rows:
        if pr.role is CodeRole.nonsubstantive:
            nonsubstantive.append(pr)
        else:
            substantive.append(pr)

    labels: list[str] = []
    values: list[float] = []
    n: list[int] = []
    roles: list[str | None] = []

    def pct_label(pr: FindingsRow) -> str:
        return pr.metric[len("pct_"):]

    substantive = _sort_by(substantive, pct_label, natural_order)
    nonsubstantive = _sort_by(nonsubstantive, pct_label, natural_order)

    for group in (substantive, nonsubstantive):
        for pr in group:
            label = pr.metric[len("pct_"):]
            n_metric = f"n_{label}"
            n_row = _require_row(idx, level, bvar, n_metric, spec.qid)
            pct_row = _require_row(idx, level, bvar, pr.metric, spec.qid)
            if pct_row.value is None:
                raise MissingFindingsRow(spec.qid, bvar, level, pr.metric)
            labels.append(label)
            values.append(pct_row.value)
            n.append(int(n_row.value or 0))
            roles.append(pr.role.value if pr.role is not None else None)

    mean_row = idx.get((level, bvar, "mean"))
    t2b_row = idx.get((level, bvar, "t2b"))

    labels, values, n, roles = _apply_manual_order(labels, values, n, roles, manual_order=manual_order)

    return {
        "labels": labels,
        "values": values,
        "n": n,
        "role": roles,
        "cell_base": pct_rows[0].cell_base,
        "mean": mean_row.value if mean_row and mean_row.value is not None else None,
        "t2b": t2b_row.value if t2b_row and t2b_row.value is not None else None,
    }


def _xbreak_trace(spec: ChartSpec, level_order: list[str] | None = None) -> dict:
    rows = spec.rows
    bvar = spec.breakdown_variable

    seen: dict[str, FindingsRow] = {}
    for r in rows:
        if r.metric == spec.metric and r.breakdown_variable == bvar:
            if r.breakdown_level not in seen:
                seen[r.breakdown_level] = r

    if not seen:
        raise MissingFindingsRow(spec.qid, bvar, "*", spec.metric)

    levels = _sort_by(list(seen.keys()), lambda lv: lv, level_order)
    metric_rows = [seen[lv] for lv in levels]

    for lv, mr in zip(levels, metric_rows):
        if mr.value is None:
            raise MissingFindingsRow(spec.qid, bvar, lv, spec.metric)

    values = [mr.value for mr in metric_rows]
    bases = [mr.cell_base for mr in metric_rows]
    is_pct = spec.metric in ("t2b", "b2b") or spec.metric.startswith("pct_")

    return {
        "levels": levels,
        "values": values,
        "n": bases,
        "metric": spec.metric,
        "is_pct": is_pct,
    }


def _scale_endpoints(question: Question) -> tuple[int, str, str]:
    """(point count, rank-1 label, top-rank label) for a scale question,
    from scales.yaml. A mean score is the average rank, so the scale runs
    from 1 to the point count. Raises a plain-English error naming the
    question when scales.yaml can't supply the range or the question has
    no answer label at either end."""
    points = variant_point_count(question.scale_family, question.scale_variant)
    by_rank = {sc.rank: sc.label for sc in question.labels if sc.rank is not None}
    if points is None or 1 not in by_rank or points not in by_rank:
        raise SurveyToolError(
            ErrorCode.INTERNAL,
            f"The mean score chart can't be drawn because the scale for question "
            f"\"{question.text}\" has no defined lowest or highest point.",
            detail=(
                f"qid={question.qid!r}, scale={question.scale_family}.{question.scale_variant}, "
                f"points in scales.yaml={points}, ranks present={sorted(by_rank)}"
            ),
            next_action=(
                "Check this question's answer options match a complete scale in the scale "
                "library (scales.yaml), or set it to a different question type, then run again."
            ),
        )
    return points, by_rank[1], by_rank[points]


def _means_trace(
    spec: ChartSpec,
    manual_order: list[str] | None = None,
    questions_by_qid: dict[str, Question] | None = None,
) -> dict:
    rows = spec.rows
    bvar = spec.breakdown_variable

    mean_rows: dict[str, FindingsRow] = {}
    for r in rows:
        if r.metric == "mean" and r.breakdown_variable == bvar:
            if r.qid not in mean_rows:
                mean_rows[r.qid] = r

    if not mean_rows:
        raise MissingFindingsRow(spec.qid, bvar, "Total", "mean")

    qids = list(mean_rows.keys())
    mr_list = [mean_rows[q] for q in qids]

    for q, mr in zip(qids, mr_list):
        if mr.value is None:
            raise MissingFindingsRow(q, bvar, "Total", "mean")

    labels = [mr.question_text for mr in mr_list]
    values = [mr.value for mr in mr_list]
    endpoints = [_scale_endpoints((questions_by_qid or {})[q]) for q in qids]

    point_counts = {pc for pc, _, _ in endpoints}
    if len(point_counts) > 1:
        raise SurveyToolError(
            ErrorCode.INTERNAL,
            "The mean score chart can't put these questions on one axis because their "
            "scales have different numbers of points.",
            detail="; ".join(f"{q}: {pc} points" for q, (pc, _, _) in zip(qids, endpoints)),
            next_action="Compare these questions' mean scores separately; a shared axis would misstate them.",
        )

    labels, values, endpoints = _apply_manual_order(labels, values, endpoints, manual_order=manual_order)

    return {
        "labels": labels,
        "values": values,
        "cell_base": mr_list[0].cell_base,
        "scale_min": 1,
        "scale_max": point_counts.pop(),
        # (lowest-point label, highest-point label) per item, in label order.
        "endpoints": [(low, high) for _, low, high in endpoints],
    }


def _measure_text(spec: ChartSpec, trace: dict, question: Question | None) -> tuple[str, str]:
    """(subtitle, value-axis title) saying exactly what a chart plots.

    Net charts take their wording from the compute core's own net
    membership (describe_net), so the subtitle can't drift from the figure.
    """
    if spec.chart_type == "dist":
        return "% of respondents giving each answer", "% of respondents"
    if spec.chart_type == "xbreak":
        if spec.metric in ("t2b", "b2b") and question is not None:
            return f"% {describe_net(question, spec.metric)}, by {spec.breakdown_variable}", "% of respondents"
        if spec.metric == "mean" and question is not None:
            points, low, high = _scale_endpoints(question)
            return (
                f"Mean score (1 = {low}, {points} = {high}), by {spec.breakdown_variable}",
                "Mean score",
            )
        return f"{spec.metric}, by {spec.breakdown_variable}", spec.metric
    # Survey-wide mean score comparison.
    low_high = set(trace["endpoints"])
    top = trace["scale_max"]
    if len(low_high) == 1:
        low, high = low_high.pop()
        axis = f"Mean score (1 = {low}, {top} = {high})"
    else:
        axis = f"Mean score (1 = lowest, {top} = highest point of each question's scale)"
    return f"Average answer on each question's {top}-point scale", axis


def build_chart_data(
    findings: list[FindingsRow],
    survey_id: str,
    questions: list[Question],
    display_orders: dict[str, list[str]] | None = None,
    orders: ChartOrders | None = None,
) -> list[ChartData]:
    """Build Plotly-ready chart data from the findings sheet.

    Chart selection comes from iter_chart_specs, the single source of truth
    every chart-producing path consumes, and this reads exclusively from
    `findings` — never recomputes. Raises MissingFindingsRow if a required
    row is absent.
    """
    orders = orders or ChartOrders()
    questions_by_qid = {q.qid: q for q in questions}
    entries: list[ChartData] = []
    for spec in iter_chart_specs(findings, survey_id, questions):
        if spec.chart_type == "dist":
            trace = _dist_trace(
                spec,
                manual_order=(display_orders or {}).get(spec.qid),
                natural_order=orders.by_qid.get(spec.qid),
            )
        elif spec.chart_type == "xbreak":
            trace = _xbreak_trace(spec, level_order=orders.by_breakdown.get(spec.breakdown_variable))
        else:
            trace = _means_trace(
                spec,
                manual_order=(display_orders or {}).get(spec.qid),
                questions_by_qid=questions_by_qid,
            )
        subtitle, value_axis_title = _measure_text(spec, trace, questions_by_qid.get(spec.qid))

        entries.append(ChartData(
            chart_type=spec.chart_type,
            filename=spec.filename,
            qid=spec.qid,
            question_text=spec.question_text,
            breakdown_variable=spec.breakdown_variable,
            metric=spec.metric,
            trace=trace,
            subtitle=subtitle,
            value_axis_title=value_axis_title,
        ))

    return entries


def render_charts_plotly(
    findings: list[FindingsRow],
    out_dir: Path,
    survey_id: str,
    questions: list[Question],
    display_orders: dict[str, list[str]] | None = None,
    chart_styles: dict[str, str] | None = None,
    response_colours: dict[str, dict[str, str]] | None = None,
    chart_filter=None,
    orders: ChartOrders | None = None,
) -> list["ManifestEntry"]:
    """Render every legacy chart to a PNG via Plotly/kaleido.

    Builds the charts from the iter_chart_specs single source of truth
    through build_chart_data + build_legacy_figure + rasterize. That is the
    identical figure-building code the on-screen chart draws from --
    /api/session/{id}/charts serves build_legacy_figure's serialized output
    and charts.js renders it verbatim -- so the exported PNG cannot visually
    drift from what's shown on screen. This replaced the retired matplotlib
    renderer, whose independent code path was exactly where that drift used
    to come from.
    """
    from pathlib import Path as _Path
    import uuid

    from surveytool.charts.manifest import (
        ManifestEntry,
        charts_manifest_record,
        load_manifest,
        merge_manifest,
    )
    from surveytool.charts.plotly_renderer import build_legacy_figure, rasterize
    from surveytool.charts.styles import get_style

    out_dir = _Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    # Read the shared manifest first: an unreadable one stops the export
    # before any PNG is written, rather than after.
    load_manifest(out_dir)

    chart_data_entries = build_chart_data(
        findings, survey_id, questions, display_orders=display_orders, orders=orders
    )
    entries: list[ManifestEntry] = []
    for chart in chart_data_entries:
        if chart_filter is not None:
            # chart_filter is written against ChartSpec (qid/chart_type/breakdown_variable);
            # ChartData carries the same three fields, so the same predicate applies unchanged.
            if not chart_filter(chart):
                continue
        style = get_style((chart_styles or {}).get(chart.qid))
        colours = (response_colours or {}).get(chart.qid)
        fig = build_legacy_figure(chart, style, response_colours=colours)
        out_path = out_dir / chart.filename
        rasterize(fig, out_path)
        entries.append(ManifestEntry(
            filename=chart.filename, qid=chart.qid, question_text=chart.question_text,
            breakdown_variable=chart.breakdown_variable, metric=chart.metric,
            findings_row_keys=[],  # Plotly path renders from ChartData, not FindingsRow directly; row provenance is not tracked per-entry here, matching build_chart_data's own contract of not re-deriving row keys.
        ))

    # Merge, never rewrite: the Cross-tab exports into the same folder and
    # its entries must survive a Charts tab export.
    export_id = uuid.uuid4().hex
    merge_manifest(out_dir, [charts_manifest_record(e, export_id) for e in entries])
    return entries
