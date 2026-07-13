from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path


_VENDORS = ("rakuten", "milieu", "toluna")


def _load_survey(file: Path, survey_id: str, vendor: str):
    if vendor == "rakuten":
        from surveytool.ingest.rakuten import load
    elif vendor == "milieu":
        from surveytool.ingest.milieu import load
    elif vendor == "toluna":
        from surveytool.ingest.toluna import load
    else:
        raise ValueError(f"Unknown vendor {vendor!r}. Choose from: {', '.join(_VENDORS)}")
    return load(file, survey_id)


def _exclude_ids(survey, include_straightliners: bool) -> set[str]:
    if include_straightliners:
        return set()
    from surveytool.core.straightliner import detect_straightliners
    return detect_straightliners(survey.responses, survey.questions)


def _load_figures(path: Path) -> dict[str, float]:
    text = path.read_text(encoding="utf-8")
    if path.suffix in (".yaml", ".yml"):
        import yaml
        raw = yaml.safe_load(text)
    else:
        raw = json.loads(text)
    return {str(k): float(v) for k, v in raw.items()}


def _run_reconcile(findings, figures_path: Path) -> int:
    from surveytool.findings.reconcile import reconcile
    written = _load_figures(figures_path)
    mismatches = reconcile(findings, written)
    if mismatches:
        for m in mismatches:
            delta_str = f"{m.delta:+.1f}" if m.delta is not None else "n/a"
            key = f"{m.qid}|{m.breakdown_variable}|{m.breakdown_level}|{m.metric}"
            print(
                f"MISMATCH  {key}  written={m.written_value}  "
                f"computed={m.computed_value}  delta={delta_str}",
                file=sys.stderr,
            )
        return 1
    print(f"OK  {len(written)} figures checked")
    return 0


def _cmd_ingest(args: argparse.Namespace) -> int:
    file = Path(args.file)
    survey = _load_survey(file, args.survey_id, args.vendor)
    info = {
        "id": survey.id,
        "n_raw": survey.n_raw,
        "n_analysis": survey.n_analysis,
        "question_count": len(survey.questions),
    }
    print(json.dumps(info, indent=2))
    return 0


def _cmd_findings(args: argparse.Namespace) -> int:
    from surveytool.findings.sheet import build_findings_sheet
    file = Path(args.file)
    survey = _load_survey(file, args.survey_id, args.vendor)
    excluded = _exclude_ids(survey, args.include_straightliners)
    findings = build_findings_sheet(survey, exclude_respondent_ids=excluded or None)

    if args.significance is not None:
        raise NotImplementedError(
            "significance testing not yet implemented; "
            "use --significance once the two-proportion z-test is available"
        )

    out = open(args.out, "w", newline="", encoding="utf-8") if args.out else sys.stdout
    try:
        writer = csv.writer(out)
        writer.writerow([
            "survey_id", "qid", "question_text", "breakdown_variable",
            "breakdown_level", "cell_base", "metric", "value", "convention",
        ])
        for row in findings:
            writer.writerow([
                row.survey_id, row.qid, row.question_text,
                row.breakdown_variable, row.breakdown_level,
                row.cell_base, row.metric, row.value, row.convention,
            ])
    finally:
        if args.out:
            out.close()

    if args.reconcile:
        return _run_reconcile(findings, Path(args.reconcile))
    return 0


def _cmd_charts(args: argparse.Namespace) -> int:
    from surveytool.charts import render_charts
    from surveytool.findings.sheet import build_findings_sheet
    file = Path(args.file)
    survey = _load_survey(file, args.survey_id, args.vendor)
    excluded = _exclude_ids(survey, args.include_straightliners)
    findings = build_findings_sheet(survey, exclude_respondent_ids=excluded or None)

    if args.significance is not None:
        raise NotImplementedError(
            "significance testing not yet implemented; "
            "use --significance once the two-proportion z-test is available"
        )

    out_dir = Path(args.out_dir)
    render_charts(findings, out_dir, args.survey_id, survey.questions)
    manifest_path = out_dir / "manifest.json"
    print(str(manifest_path))

    if args.reconcile:
        return _run_reconcile(findings, Path(args.reconcile))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="surveytool",
        description="Survey analysis tool — ingest, findings, charts.",
    )
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    sub.required = True

    def _add_common(p: argparse.ArgumentParser, *, reconcile: bool = False) -> None:
        p.add_argument("file", metavar="FILE", help="Vendor data file (.xlsx or .csv)")
        p.add_argument("--survey-id", required=True, metavar="ID", help="Survey identifier")
        p.add_argument(
            "--vendor",
            required=True,
            choices=_VENDORS,
            help="Vendor adapter to use for this file.",
        )
        p.add_argument(
            "--include-straightliners",
            action="store_true",
            default=False,
            help="Keep straightline respondents in the analysis base (default: exclude them)",
        )
        p.add_argument(
            "--significance",
            metavar="LEVEL",
            default=None,
            help="Significance level for two-proportion z-test (95 or 90). Not yet implemented.",
        )
        if reconcile:
            p.add_argument(
                "--reconcile",
                metavar="FIGURES_FILE",
                default=None,
                help="YAML/JSON file of written figures to check against the findings sheet.",
            )

    # ingest
    p_ingest = sub.add_parser("ingest", help="Load a survey file and print metadata.")
    _add_common(p_ingest)

    # findings
    p_findings = sub.add_parser("findings", help="Compute and export the findings sheet as CSV.")
    _add_common(p_findings, reconcile=True)
    p_findings.add_argument(
        "--out", metavar="FILE", default=None,
        help="Write CSV to FILE instead of stdout.",
    )

    # charts
    p_charts = sub.add_parser("charts", help="Render chart PNGs and manifest.")
    _add_common(p_charts, reconcile=True)
    p_charts.add_argument(
        "--out-dir", required=True, metavar="DIR",
        help="Output directory for PNGs and manifest.json.",
    )

    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    try:
        if args.command == "ingest":
            code = _cmd_ingest(args)
        elif args.command == "findings":
            code = _cmd_findings(args)
        elif args.command == "charts":
            code = _cmd_charts(args)
        else:
            parser.print_help()
            code = 2
    except FileNotFoundError as exc:
        print(f"Error: file not found — {exc.filename}", file=sys.stderr)
        code = 2
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        code = 2
    except NotImplementedError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        code = 2

    sys.exit(code)
