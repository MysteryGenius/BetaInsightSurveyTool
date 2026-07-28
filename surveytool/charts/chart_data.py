from __future__ import annotations

from dataclasses import dataclass

from surveytool.charts.errors import MissingFindingsRow
from surveytool.charts.renderer import _index_rows, _require_row
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


def _dist_trace(spec: ChartSpec) -> dict:
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


def _means_trace(spec: ChartSpec) -> dict:
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

    return {
        "labels": [mr.question_text for mr in mr_list],
        "values": [mr.value for mr in mr_list],
        "cell_base": mr_list[0].cell_base,
    }


def build_chart_data(
    findings: list[FindingsRow],
    survey_id: str,
    questions: list[Question],
) -> list[ChartData]:
    """Build Plotly-ready chart data from the findings sheet.

    Mirrors render_charts()'s chart selection exactly (both consume
    iter_chart_specs) and reads exclusively from `findings` — never recomputes.
    Raises MissingFindingsRow if a required row is absent.
    """
    entries: list[ChartData] = []
    for spec in iter_chart_specs(findings, survey_id, questions):
        if spec.chart_type == "dist":
            trace = _dist_trace(spec)
        elif spec.chart_type == "xbreak":
            trace = _xbreak_trace(spec)
        else:
            trace = _means_trace(spec)

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
