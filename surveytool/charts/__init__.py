from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from surveytool.charts.manifest import ManifestEntry, write_manifest
from surveytool.charts.renderer import render_dist, render_means, render_xbreak
from surveytool.charts.types import ChartSpec
from surveytool.core.model import Question, QuestionType
from surveytool.findings.sheet import FindingsRow

__all__ = ["render_charts"]

_SCALE_TYPES = frozenset({QuestionType.scale, QuestionType.single_choice})


def render_charts(
    findings: list[FindingsRow],
    out_dir: Path,
    survey_id: str,
    questions: list[Question],
    write_manifest_file: bool = True,
) -> list[ManifestEntry]:
    """Render all chart PNGs from the findings sheet.

    Emits:
    - One dist chart per (scale/single_choice question × breakdown_level for "total").
    - One xbreak chart per (scale question × non-total breakdown_variable).
    - One means chart per survey (all scale questions, total, mean metric).

    Never recomputes — reads exclusively from `findings`.
    Raises MissingFindingsRow if a required row is absent.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    q_by_id: dict[str, Question] = {q.qid: q for q in questions}

    # Group findings rows by (qid, breakdown_variable).
    groups: dict[tuple[str, str], list[FindingsRow]] = defaultdict(list)
    for row in findings:
        groups[(row.qid, row.breakdown_variable)].append(row)

    entries: list[ManifestEntry] = []

    # Rows for the survey-wide means comparison chart.
    means_rows: list[FindingsRow] = []

    for (qid, bvar), rows in groups.items():
        question = q_by_id.get(qid)
        if question is None or not question.base_eligible:
            continue

        is_scale = question.qtype in _SCALE_TYPES
        q_text = rows[0].question_text

        if bvar == "total":
            spec = ChartSpec(
                chart_type="dist",
                survey_id=survey_id,
                qid=qid,
                question_text=q_text,
                breakdown_variable=bvar,
                metric="pct",
                rows=rows,
            )
            entries.append(render_dist(spec, out_dir))

            if is_scale:
                for r in rows:
                    if r.metric == "mean" and r.value is not None:
                        means_rows.append(r)
                        break

        else:
            if not is_scale:
                continue
            has_t2b = any(r.metric == "t2b" for r in rows)
            metric = "t2b" if has_t2b else "mean"
            spec = ChartSpec(
                chart_type="xbreak",
                survey_id=survey_id,
                qid=qid,
                question_text=q_text,
                breakdown_variable=bvar,
                metric=metric,
                rows=rows,
            )
            entries.append(render_xbreak(spec, out_dir))

    # Survey-wide means comparison chart.
    if means_rows:
        anchor = means_rows[0]
        means_spec = _MeansSpec(
            chart_type="means",
            survey_id=survey_id,
            qid=anchor.qid,
            question_text=anchor.question_text,
            breakdown_variable="total",
            metric="mean",
            rows=means_rows,
            _override_filename=f"{survey_id}__all__means__total.png",
        )
        entries.append(render_means(means_spec, out_dir))

    if write_manifest_file:
        write_manifest(entries, out_dir / "manifest.json")

    return entries


class _MeansSpec(ChartSpec):
    """ChartSpec with an overridden filename for the survey-wide means chart."""

    def __init__(self, *args, _override_filename: str, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        object.__setattr__(self, "_override_filename", _override_filename)

    @property
    def filename(self) -> str:
        return self._override_filename  # type: ignore[attr-defined]
