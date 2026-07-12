from __future__ import annotations

import textwrap
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.figure import Figure

from surveytool.charts.errors import MissingFindingsRow
from surveytool.charts.manifest import ManifestEntry, _row_key
from surveytool.charts.types import ChartSpec
from surveytool.core.model import CodeRole
from surveytool.findings.sheet import FindingsRow

# ── Brand palette ────────────────────────────────────────────────────────────
_CREAM = "#F4F1EA"
_TEAL = "#1B667D"
_GREY = "#9AA5A8"
_WARM = "#C4856A"
_NONSUBST = "#D0D0D0"
_WORDMARK_ALPHA = 0.35

_ROLE_COLOUR: dict[CodeRole | None, str] = {
    CodeRole.top: _TEAL,
    CodeRole.neutral: _GREY,
    CodeRole.bottom: _WARM,
    CodeRole.nonsubstantive: _NONSUBST,
    CodeRole.excluded: _NONSUBST,
    None: _GREY,
}

# Human-readable breakdown variable labels for chart titles.
# Extensible: add entries here or pass a custom dict to render_* functions.
_BREAKDOWN_LABELS: dict[str, str] = {
    "total": "Total",
    "age": "Age",
    "ethnicity": "Ethnicity",
    "gender": "Gender",
    "income": "Income",
    "education": "Education",
    "region": "Region",
}


def _breakdown_label(breakdown_variable: str) -> str:
    return _BREAKDOWN_LABELS.get(breakdown_variable.lower(), breakdown_variable.title())


def _apply_theme(fig: Figure, ax) -> None:
    fig.patch.set_facecolor(_CREAM)
    ax.set_facecolor(_CREAM)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#CCCCCC")
    ax.spines["bottom"].set_color("#CCCCCC")
    ax.tick_params(colors="#444444")
    fig.text(
        0.98, 0.98, "Beta Insight",
        ha="right", va="top",
        fontsize=8, color=_TEAL, alpha=_WORDMARK_ALPHA,
        transform=fig.transFigure,
    )


def _wrap_title(ax, text: str, max_chars: int = 70, base_fontsize: float = 11.0) -> None:
    lines = textwrap.wrap(text, width=max_chars)
    title_text = "\n".join(lines)
    fontsize = base_fontsize if len(lines) <= 2 else max(9.0, base_fontsize - 1.5)
    ax.set_title(title_text, fontsize=fontsize, color="#222222", pad=10, loc="left")


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


# ── Distribution chart ────────────────────────────────────────────────────────

def render_dist(spec: ChartSpec, out_dir: Path) -> ManifestEntry:
    """Horizontal bar chart: one bar per scale code at a single breakdown level.

    Non-substantive codes are shown in a separate muted group below a divider.
    Raises MissingFindingsRow if any expected pct_ or n_ row is absent.
    """
    rows = spec.rows
    idx = _index_rows(rows)

    # Determine breakdown level — all rows share the same level for dist charts.
    levels = {r.breakdown_level for r in rows}
    if len(levels) != 1:
        raise ValueError(
            f"render_dist expects rows from a single breakdown level; got {levels}"
        )
    level = next(iter(levels))
    bvar = spec.breakdown_variable

    # Collect pct_ rows in order, split by role.
    pct_rows = [r for r in rows if r.metric.startswith("pct_") and r.convention == "pct"]
    if not pct_rows:
        raise MissingFindingsRow(spec.qid, bvar, level, "pct_*")

    # Cross-check: every n_<label> row implies a pct_<label> row must be present.
    # If any pct_ is missing while its n_ exists, the findings sheet is incomplete.
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

    # Validate all needed rows exist; also fetch n_ to build labels.
    findings_keys: list[str] = []
    bar_data: list[tuple[str, float, int, CodeRole | None]] = []  # (label, pct, n, role)

    for group in (substantive, nonsubstantive):
        for pr in group:
            label = pr.metric[len("pct_"):]
            n_metric = f"n_{label}"
            n_row = _require_row(idx, level, bvar, n_metric, spec.qid)
            pct_row = _require_row(idx, level, bvar, pr.metric, spec.qid)
            if pct_row.value is None:
                raise MissingFindingsRow(spec.qid, bvar, level, pr.metric)
            bar_data.append((label, pct_row.value, int(n_row.value or 0), pr.role))
            findings_keys.append(_row_key(spec.qid, bvar, level, pr.metric))
            findings_keys.append(_row_key(spec.qid, bvar, level, n_metric))

    # Build y positions — substantive group, gap, nonsubstantive group.
    n_subst = len(substantive)
    n_ns = len(nonsubstantive)
    total_bars = n_subst + n_ns
    gap = 0.6 if n_ns else 0
    height = 0.55
    fig_height = max(3.5, total_bars * 0.55 + 1.5 + gap)
    fig, ax = plt.subplots(figsize=(9, fig_height))

    y_positions = []
    # substantive bars at top (reverse so first code is at top)
    for i in range(n_subst):
        y_positions.append(n_subst - 1 - i + n_ns + gap + 1)
    # nonsubstantive bars at bottom
    for i in range(n_ns):
        y_positions.append(n_ns - 1 - i)

    for (label, pct, n, role), y in zip(bar_data, y_positions):
        colour = _ROLE_COLOUR.get(role, _GREY)
        ax.barh(y, pct, height=height, color=colour, zorder=2)
        bar_label = f"{pct:.1f}%  (n={n:,})"
        ax.text(
            pct + 0.5, y, bar_label,
            va="center", ha="left", fontsize=9, color="#333333"
        )
        ax.text(
            -0.5, y, label,
            va="center", ha="right", fontsize=9, color="#333333"
        )

    # Divider line between substantive and nonsubstantive groups.
    if n_ns and n_subst:
        divider_y = n_ns + gap / 2
        ax.axhline(divider_y, color="#CCCCCC", linewidth=0.8, linestyle="--", zorder=1)
        ax.text(
            ax.get_xlim()[1] * 0.5 if ax.get_xlim()[1] > 0 else 50,
            divider_y + 0.1,
            "Non-substantive responses",
            ha="center", va="bottom", fontsize=7.5, color="#888888",
        )

    # Caption with mean and base.
    mean_row = idx.get((level, bvar, "mean"))
    t2b_row = idx.get((level, bvar, "t2b"))
    caption_parts = []
    if t2b_row and t2b_row.value is not None:
        caption_parts.append(f"T2B: {t2b_row.value:.1f}%")
        findings_keys.append(_row_key(spec.qid, bvar, level, "t2b"))
    if mean_row and mean_row.value is not None:
        caption_parts.append(f"Mean: {mean_row.value:.2f}")
        findings_keys.append(_row_key(spec.qid, bvar, level, "mean"))
    cell_base = pct_rows[0].cell_base
    caption_parts.append(f"Base n = {cell_base:,}")
    ax.set_xlabel("  |  ".join(caption_parts), fontsize=9, color="#555555", labelpad=10)

    ax.set_yticks([])
    ax.set_xlim(left=-18, right=min(110, max(p for _, p, _, _ in bar_data) + 20))
    ax.xaxis.set_visible(False)

    title = spec.question_text
    if bvar != "total":
        title = f"{title} — {_breakdown_label(bvar)}: {level}"
    _wrap_title(ax, title)
    _apply_theme(fig, ax)

    out_path = out_dir / spec.filename
    fig.savefig(out_path, dpi=150, bbox_inches="tight", facecolor=_CREAM)
    plt.close(fig)

    return ManifestEntry(
        filename=spec.filename,
        qid=spec.qid,
        question_text=spec.question_text,
        breakdown_variable=bvar,
        metric=spec.metric,
        findings_row_keys=list(dict.fromkeys(findings_keys)),
    )


# ── Crossbreak chart ──────────────────────────────────────────────────────────

def render_xbreak(spec: ChartSpec, out_dir: Path) -> ManifestEntry:
    """Vertical bar chart: one bar per breakdown level for a single metric.

    Title is built from spec.breakdown_variable, not from bar labels, ensuring
    the title variable always matches the bars.
    Raises MissingFindingsRow if metric row absent for any level.
    """
    rows = spec.rows
    bvar = spec.breakdown_variable

    # Collect one row per breakdown level (ordered as they appear in findings).
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

    fig, ax = plt.subplots(figsize=(max(6, len(levels) * 1.4), 5))

    x = range(len(levels))
    bars = ax.bar(x, values, color=_TEAL, width=0.55, zorder=2)

    for xi, (val, base) in enumerate(zip(values, bases)):
        label_str = f"{val:.1f}{'%' if is_pct else ''}"
        ax.text(xi, val + max(values) * 0.01, label_str,
                ha="center", va="bottom", fontsize=9, color="#222222")
        ax.text(xi, -max(values) * 0.06, f"n={base:,}",
                ha="center", va="top", fontsize=8, color="#666666")

    ax.set_xticks(list(x))
    ax.set_xticklabels(levels, fontsize=9, color="#333333")
    ax.set_ylim(bottom=0, top=max(values) * 1.2)
    ax.yaxis.set_visible(False)

    # Title: breakdown_variable resolves to human label; never derived from bar labels.
    bvar_label = _breakdown_label(bvar)
    metric_label = spec.metric.upper() if spec.metric in ("t2b", "b2b", "mean") else spec.metric
    title = f"{spec.question_text} by {bvar_label} ({metric_label})"
    _wrap_title(ax, title)
    _apply_theme(fig, ax)

    findings_keys = [
        _row_key(spec.qid, bvar, lv, spec.metric) for lv in levels
    ]

    out_path = out_dir / spec.filename
    fig.savefig(out_path, dpi=150, bbox_inches="tight", facecolor=_CREAM)
    plt.close(fig)

    return ManifestEntry(
        filename=spec.filename,
        qid=spec.qid,
        question_text=spec.question_text,
        breakdown_variable=bvar,
        metric=spec.metric,
        findings_row_keys=findings_keys,
    )


# ── Mean-score comparison chart ───────────────────────────────────────────────

def render_means(spec: ChartSpec, out_dir: Path) -> ManifestEntry:
    """Horizontal bar chart comparing mean scores across multiple questions.

    One bar per question; all at breakdown_variable="total", metric="mean".
    Raises MissingFindingsRow if a mean row is absent for any question.
    """
    rows = spec.rows
    bvar = spec.breakdown_variable  # always "total" for means chart

    # Group rows by qid, expecting one mean row per qid.
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

    values = [mr.value for mr in mr_list]
    labels = []
    for mr in mr_list:
        short = textwrap.shorten(mr.question_text, width=60, placeholder="…")
        labels.append(short)

    fig_height = max(3.5, len(qids) * 0.65 + 1.5)
    fig, ax = plt.subplots(figsize=(9, fig_height))

    y = range(len(qids))
    ax.barh(list(y), values, height=0.5, color=_TEAL, zorder=2)

    for yi, val in enumerate(values):
        ax.text(val + 0.05, yi, f"{val:.2f}", va="center", ha="left",
                fontsize=9, color="#333333")

    ax.set_yticks(list(y))
    ax.set_yticklabels(labels, fontsize=9, color="#333333")
    ax.set_xlim(left=0, right=max(values) * 1.25)
    ax.xaxis.set_visible(False)

    cell_base = mr_list[0].cell_base
    ax.set_xlabel(f"Base n = {cell_base:,}", fontsize=9, color="#555555", labelpad=8)

    _wrap_title(ax, "Mean score comparison")
    _apply_theme(fig, ax)

    findings_keys = [
        _row_key(q, bvar, "Total", "mean") for q in qids
    ]

    out_path = out_dir / spec.filename
    fig.savefig(out_path, dpi=150, bbox_inches="tight", facecolor=_CREAM)
    plt.close(fig)

    return ManifestEntry(
        filename=spec.filename,
        qid=spec.qid,
        question_text=spec.question_text,
        breakdown_variable=bvar,
        metric="mean",
        findings_row_keys=findings_keys,
    )
