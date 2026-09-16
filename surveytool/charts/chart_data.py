from __future__ import annotations

from dataclasses import dataclass

from surveytool.charts.errors import MissingFindingsRow
from surveytool.charts.types import ChartSpec
from surveytool.charts import iter_chart_specs
from surveytool.core.model import CodeRole, Question
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


def _dist_trace(spec: ChartSpec, manual_order: list[str] | None = None) -> dict:
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


def _xbreak_trace(spec: ChartSpec) -> dict:
    rows = spec.rows
    bvar = spec.breakdown_variable

    seen: dict[str, FindingsRow] = {}
    for r in rows:
        if r.metric == spec.metric and r.breakdown_variable == bvar:
            if r.breakdown_level not in seen:
                seen[r.breakdown_level] = r

    if not seen:
        raise MissingFindingsRow(spec.qid, bvar, "*", spec.metric)

    levels = list(seen.keys())
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


def _means_trace(spec: ChartSpec, manual_order: list[str] | None = None) -> dict:
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

    labels, values = _apply_manual_order(labels, values, manual_order=manual_order)

    return {
        "labels": labels,
        "values": values,
        "cell_base": mr_list[0].cell_base,
    }


def build_chart_data(
    findings: list[FindingsRow],
    survey_id: str,
    questions: list[Question],
    display_orders: dict[str, list[str]] | None = None,
) -> list[ChartData]:
    """Build Plotly-ready chart data from the findings sheet.

    Mirrors render_charts()'s chart selection exactly (both consume
    iter_chart_specs) and reads exclusively from `findings` — never recomputes.
    Raises MissingFindingsRow if a required row is absent.
    """
    entries: list[ChartData] = []
    for spec in iter_chart_specs(findings, survey_id, questions):
        if spec.chart_type == "dist":
            trace = _dist_trace(spec, manual_order=(display_orders or {}).get(spec.qid))
        elif spec.chart_type == "xbreak":
            trace = _xbreak_trace(spec)
        else:
            trace = _means_trace(spec, manual_order=(display_orders or {}).get(spec.qid))

        entries.append(ChartData(
            chart_type=spec.chart_type,
            filename=spec.filename,
            qid=spec.qid,
            question_text=spec.question_text,
            breakdown_variable=spec.breakdown_variable,
            metric=spec.metric,
            trace=trace,
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
) -> list["ManifestEntry"]:
    """Plotly/kaleido equivalent of render_charts() (renderer.py's
    matplotlib path). Builds the same set of charts (from the same
    iter_chart_specs single source of truth) but through build_chart_data +
    build_legacy_figure + rasterize -- the identical figure-building code
    charts.js uses to draw the on-screen chart -- so the exported PNG can
    never visually drift from what's shown on screen, closing the gap
    render_charts()/charts.js's independent code paths left open.
    """
    from pathlib import Path as _Path
    from surveytool.charts.manifest import ManifestEntry, write_manifest
    from surveytool.charts.plotly_renderer import build_legacy_figure, rasterize
    from surveytool.charts.styles import get_style

    out_dir = _Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    chart_data_entries = build_chart_data(findings, survey_id, questions, display_orders=display_orders)
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

    write_manifest(entries, out_dir / "manifest.json")
    return entries
