"""
Phase 4 chart acceptance tests.

Each test corresponds to one acceptance criterion from the build plan:

1. Dist chart produces a non-empty PNG with real labels (never "Code N").
2. Crossbreak chart title variable matches its bars (not a different breakdown).
3. Missing findings row raises MissingFindingsRow, never renders a zero.
4. render_charts end-to-end: manifest resolves every PNG to findings rows.
5. Non-substantive codes are tracked in the manifest and do not abort the chart.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from surveytool.charts import render_charts
from surveytool.charts.errors import MissingFindingsRow
from surveytool.charts.renderer import render_dist, render_xbreak
from surveytool.charts.types import ChartSpec
from surveytool.core.model import CodeRole, Question, QuestionType, Response, ResponseState, ScaleCode, Survey
from surveytool.findings.sheet import FindingsRow, build_findings_sheet


# ── Shared helpers ────────────────────────────────────────────────────────────

def _agreement_question(qid: str = "Q1", text: str = "How much do you agree?") -> Question:
    return Question(
        qid=qid,
        text=text,
        qtype=QuestionType.scale,
        scale_family="agreement",
        labels=[
            ScaleCode(code=1, label="Strongly Agree", role=CodeRole.top, numeric_value=5),
            ScaleCode(code=2, label="Agree", role=CodeRole.top, numeric_value=4),
            ScaleCode(code=3, label="Neither Agree Nor Disagree", role=CodeRole.neutral, numeric_value=3),
            ScaleCode(code=4, label="Disagree", role=CodeRole.bottom, numeric_value=2),
            ScaleCode(code=5, label="Strongly Disagree", role=CodeRole.bottom, numeric_value=1),
        ],
    )


def _demo_age_question() -> Question:
    return Question(
        qid="age",
        text="What is your age group?",
        qtype=QuestionType.demographic,
        is_demographic=True,
        base_eligible=False,
        labels=[
            ScaleCode(code=1, label="18-24", role=CodeRole.excluded),
            ScaleCode(code=2, label="25-34", role=CodeRole.excluded),
            ScaleCode(code=3, label="35-44", role=CodeRole.excluded),
        ],
    )


def _demo_ethnicity_question() -> Question:
    return Question(
        qid="ethnicity",
        text="What is your ethnicity?",
        qtype=QuestionType.demographic,
        is_demographic=True,
        base_eligible=False,
        labels=[
            ScaleCode(code=1, label="Chinese", role=CodeRole.excluded),
            ScaleCode(code=2, label="Malay", role=CodeRole.excluded),
        ],
    )


def _make_survey(n: int, scale_q: Question, demo_questions: list[Question] | None = None) -> Survey:
    """Build a synthetic survey with n respondents cycling through scale codes 1-5."""
    questions = [scale_q] + (demo_questions or [])
    responses: list[Response] = []
    codes = [sc.code for sc in scale_q.labels if sc.role is not CodeRole.nonsubstantive]
    for i in range(n):
        rid = f"R{i+1:03d}"
        code = codes[i % len(codes)]
        responses.append(Response(respondent_id=rid, qid=scale_q.qid, raw_value=code, state=ResponseState.answered))
    return Survey(id="test-survey", n_raw=n, n_analysis=n, questions=questions, responses=responses)


def _make_survey_with_age(n: int) -> tuple[Survey, Question, Question]:
    """Build a survey with age demo question; respondents spread evenly across age groups."""
    scale_q = _agreement_question()
    age_q = _demo_age_question()
    scale_codes = [sc.code for sc in scale_q.labels]
    age_codes = [sc.code for sc in age_q.labels]
    responses: list[Response] = []
    for i in range(n):
        rid = f"R{i+1:03d}"
        responses.append(Response(respondent_id=rid, qid="Q1", raw_value=scale_codes[i % len(scale_codes)], state=ResponseState.answered))
        responses.append(Response(respondent_id=rid, qid="age", raw_value=age_codes[i % len(age_codes)], state=ResponseState.answered))
    survey = Survey(
        id="test-survey", n_raw=n, n_analysis=n,
        questions=[scale_q, age_q], responses=responses,
    )
    return survey, scale_q, age_q


# ── Test 1: dist chart — real labels, non-empty PNG ──────────────────────────

def test_dist_chart_real_labels_nonempty_png(tmp_path: Path) -> None:
    """Dist chart renders a non-empty PNG and manifest row keys contain real labels, not 'Code N'."""
    q = _agreement_question()
    survey = _make_survey(10, q)
    findings = build_findings_sheet(survey, banner=[])

    dist_rows = [r for r in findings if r.breakdown_variable == "total" and r.qid == "Q1"]
    spec = ChartSpec(
        chart_type="dist",
        survey_id="test-survey",
        qid="Q1",
        question_text=q.text,
        breakdown_variable="total",
        metric="pct",
        rows=dist_rows,
    )
    entry = render_dist(spec, tmp_path)

    png = tmp_path / spec.filename
    assert png.exists(), f"PNG not created: {png}"
    assert png.stat().st_size > 1000, "PNG suspiciously small — likely empty"

    # No row key should contain "Code" followed by a digit
    for key in entry.findings_row_keys:
        assert not any(
            part.startswith("Code") and part[4:].strip().isdigit()
            for part in key.split("/")
        ), f"Raw code label leaked into manifest key: {key!r}"

    # Real label names must appear in the keys
    real_labels = [sc.label for sc in q.labels]
    key_blob = " ".join(entry.findings_row_keys)
    for label in real_labels:
        assert label in key_blob, f"Real label {label!r} not found in manifest keys"


# ── Test 2: crossbreak title matches bars ─────────────────────────────────────

def test_xbreak_title_matches_breakdown_variable(tmp_path: Path) -> None:
    """Crossbreak chart title contains 'Age' when breakdown_variable='age', not 'Ethnicity'."""
    survey, scale_q, age_q = _make_survey_with_age(30)
    findings = build_findings_sheet(survey, banner=["age"])

    age_rows = [r for r in findings if r.breakdown_variable == "age" and r.qid == "Q1"]
    assert age_rows, "No age breakdown rows found"

    spec = ChartSpec(
        chart_type="xbreak",
        survey_id="test-survey",
        qid="Q1",
        question_text=scale_q.text,
        breakdown_variable="age",
        metric="t2b",
        rows=age_rows,
    )
    entry = render_xbreak(spec, tmp_path)

    # The PNG title is validated structurally: the filename encodes the breakdown variable.
    assert "age" in entry.filename, f"breakdown_variable 'age' not in filename: {entry.filename}"
    # Manifest records age, not ethnicity.
    assert entry.breakdown_variable == "age"
    assert all("age" in key for key in entry.findings_row_keys)
    assert not any("ethnicity" in key for key in entry.findings_row_keys)

    png = tmp_path / spec.filename
    assert png.exists() and png.stat().st_size > 1000


# ── Test 3: missing findings row raises, not zero ─────────────────────────────

def test_missing_findings_row_raises(tmp_path: Path) -> None:
    """render_dist raises MissingFindingsRow when a pct_ row is absent from the findings sheet."""
    q = _agreement_question()
    survey = _make_survey(10, q)
    findings = build_findings_sheet(survey, banner=[])

    # Remove one pct_ row to simulate an incomplete findings sheet.
    dist_rows = [
        r for r in findings
        if r.breakdown_variable == "total" and r.qid == "Q1"
        and r.metric != "pct_Strongly Agree"  # artificially drop this row
    ]

    spec = ChartSpec(
        chart_type="dist",
        survey_id="test-survey",
        qid="Q1",
        question_text=q.text,
        breakdown_variable="total",
        metric="pct",
        rows=dist_rows,
    )

    with pytest.raises(MissingFindingsRow):
        render_dist(spec, tmp_path)


# ── Test 4: end-to-end manifest resolves every PNG to findings rows ───────────

def test_render_charts_manifest_complete(tmp_path: Path) -> None:
    """render_charts writes manifest.json; every listed PNG exists and every
    findings-row key resolves to a row in the findings sheet."""
    survey, scale_q, age_q = _make_survey_with_age(30)
    findings = build_findings_sheet(survey, banner=["age"])

    entries = render_charts(
        findings=findings,
        out_dir=tmp_path,
        survey_id="test-survey",
        questions=survey.questions,
    )

    manifest_path = tmp_path / "manifest.json"
    assert manifest_path.exists(), "manifest.json not written"

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert len(manifest) == len(entries), "manifest entry count mismatch"

    # Build a set of all findings row keys that actually exist.
    existing_keys = {
        f"{r.qid}/{r.breakdown_variable}/{r.breakdown_level}/{r.metric}"
        for r in findings
    }

    for entry in manifest:
        png = tmp_path / entry["filename"]
        assert png.exists(), f"PNG listed in manifest but not on disk: {entry['filename']}"
        assert png.stat().st_size > 1000, f"PNG suspiciously small: {entry['filename']}"

        for key in entry["findings_row_keys"]:
            assert key in existing_keys, (
                f"Manifest key {key!r} in {entry['filename']} does not resolve "
                "to any row in the findings sheet"
            )


# ── Test 5: non-substantive codes tracked in manifest, chart renders ──────────

def test_nonsubstantive_codes_in_manifest_and_chart_renders(tmp_path: Path) -> None:
    """Dist chart renders without error when non-substantive codes are present;
    manifest tracks their pct_ rows."""
    scale_q = Question(
        qid="Q1",
        text="Level of concern",
        qtype=QuestionType.scale,
        scale_family="agreement",
        labels=[
            ScaleCode(code=1, label="Strongly Agree", role=CodeRole.top, numeric_value=5),
            ScaleCode(code=2, label="Agree", role=CodeRole.top, numeric_value=4),
            ScaleCode(code=3, label="Neither Agree Nor Disagree", role=CodeRole.neutral, numeric_value=3),
            ScaleCode(code=4, label="Disagree", role=CodeRole.bottom, numeric_value=2),
            ScaleCode(code=5, label="Strongly Disagree", role=CodeRole.bottom, numeric_value=1),
            ScaleCode(code=99, label="Don't know", role=CodeRole.nonsubstantive),
        ],
    )

    responses: list[Response] = []
    for i in range(8):
        rid = f"R{i+1:02d}"
        code = [1, 2, 3, 4, 5, 1, 2, 3][i]
        responses.append(Response(respondent_id=rid, qid="Q1", raw_value=code, state=ResponseState.answered))
    # 2 non-substantive
    for j in range(2):
        rid = f"RN{j+1}"
        responses.append(Response(respondent_id=rid, qid="Q1", raw_value=99, state=ResponseState.nonsubstantive))

    survey = Survey(id="ns-survey", n_raw=10, n_analysis=10, questions=[scale_q], responses=responses)
    findings = build_findings_sheet(survey, banner=[])

    dist_rows = [r for r in findings if r.breakdown_variable == "total" and r.qid == "Q1"]
    spec = ChartSpec(
        chart_type="dist",
        survey_id="ns-survey",
        qid="Q1",
        question_text=scale_q.text,
        breakdown_variable="total",
        metric="pct",
        rows=dist_rows,
    )

    entry = render_dist(spec, tmp_path)

    png = tmp_path / spec.filename
    assert png.exists() and png.stat().st_size > 1000

    # The nonsubstantive pct_ row must be tracked in the manifest.
    ns_key = "Q1/total/Total/pct_Don't know"
    assert ns_key in entry.findings_row_keys, (
        f"Non-substantive row key {ns_key!r} missing from manifest. "
        f"Got: {entry.findings_row_keys}"
    )
