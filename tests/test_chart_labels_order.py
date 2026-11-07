"""v4 feedback F3: Charts tab order, wrapped titles, measure labels and the
mean score axis, checked on the figures /charts serves (the same figures
Export PNG rasterizes), using the real vendor files.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).parent.parent
TOLUNA_PATH = ROOT / "toluna_survey_misinformation_data.xlsx"
MILIEU_PATH = ROOT / "milieu_survey_coe_data.csv"
_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _charts(path: Path, vendor: str, mime: str) -> list[dict]:
    if not path.exists():
        pytest.skip(f"{path.name} not found in project root")
    from surveytool.desktop.app import app

    client = TestClient(app)
    with open(path, "rb") as f:
        response = client.post(
            "/api/upload", data={"vendor": vendor, "survey_id": "t"}, files={"file": (path.name, f, mime)}
        )
    assert response.status_code == 200, response.text
    session_id = response.json()["session_id"]
    charts = client.get(f"/api/session/{session_id}/charts")
    assert charts.status_code == 200, charts.text
    return charts.json()["charts"]


@pytest.fixture(scope="module")
def toluna_charts():
    return _charts(TOLUNA_PATH, "toluna", _XLSX_MIME)


def _chart(charts, chart_type, qid=None, breakdown=None):
    return next(
        c for c in charts
        if c["chart_type"] == chart_type
        and (qid is None or c["qid"] == qid)
        and (breakdown is None or c["breakdown_variable"] == breakdown)
    )


def _plain(label: str) -> str:
    """A wrapped tick label back to its text (drops <br> and small-font spans)."""
    label = re.sub(r"<br><span[^>]*>.*?</span>", "", label)
    return label.replace("<br>", " ")


def _title_lines(layout: dict) -> tuple[list[str], list[str]]:
    lines = layout["title"]["text"].split("<br>")
    title = [line for line in lines if not line.startswith("<span")]
    sub = [re.sub(r"<[^>]+>", "", line) for line in lines if line.startswith("<span")]
    return title, sub


# --- 1. order ----------------------------------------------------------------


def _bars_top_to_bottom(chart) -> list[str]:
    fig = chart["figure"]
    y = [_plain(v) for v in fig["data"][0]["y"]]
    assert fig["layout"]["yaxis"]["autorange"] == "reversed"  # first trace item drawn at top
    return y


def _wrapped_text(label: str) -> str:
    return " ".join(label.split())


def test_age_dist_reads_18_24_first_and_matches_list(toluna_charts):
    chart = _chart(toluna_charts, "dist", "2")
    labels = chart["trace"]["labels"]  # the list beneath the chart
    assert labels[0] == "18-24 years old"
    assert labels == [
        "18-24 years old", "25-34 years old", "35-44 years old", "45-54 years old", "55 years old and above",
    ]
    assert _bars_top_to_bottom(chart) == [_wrapped_text(label) for label in labels]


def test_gender_dist_follows_registry_order(toluna_charts):
    chart = _chart(toluna_charts, "dist", "1")
    assert chart["trace"]["labels"] == ["Male", "Female"]
    assert _bars_top_to_bottom(chart) == ["Male", "Female"]


def test_ethnicity_order_is_registry_order_everywhere(toluna_charts):
    """Registry (canonical.yaml) order, as chosen for this round: Chinese,
    Malay, Indian, Others -- in the ethnicity dist chart and every
    by-ethnicity chart."""
    expected = ["Chinese", "Malay", "Indian", "Others"]
    assert _chart(toluna_charts, "dist", "3")["trace"]["labels"] == expected
    xbreaks = [c for c in toluna_charts if c["chart_type"] == "xbreak" and c["breakdown_variable"] == "ethnicity"]
    assert len(xbreaks) == 7
    for chart in xbreaks:
        assert chart["trace"]["levels"] == expected
        assert [_plain(x) for x in chart["figure"]["data"][0]["x"]] == expected


def test_scale_dist_puts_positive_end_at_top(toluna_charts):
    chart = _chart(toluna_charts, "dist", "7_online_social_media")
    expected = ["Very Likely", "Likely", "Neutral / Neither Likely nor Unlikely", "Unlikely", "Very Unlikely"]
    assert chart["trace"]["labels"] == expected
    assert _bars_top_to_bottom(chart) == [_wrapped_text(label) for label in expected]


def test_every_horizontal_chart_bar_order_equals_list_order(toluna_charts):
    for chart in toluna_charts:
        if chart["chart_type"] not in ("dist", "means"):
            continue
        assert _bars_top_to_bottom(chart) == [_wrapped_text(label) for label in chart["trace"]["labels"]], chart["qid"]


# --- 2. titles -----------------------------------------------------------------


def test_titles_wrap_and_keep_every_word(toluna_charts):
    for chart in toluna_charts:
        layout = chart["figure"]["layout"]
        title, sub = _title_lines(layout)
        assert all(len(line) <= 64 for line in title), chart["qid"]
        assert all(len(line) <= 88 for line in sub), chart["qid"]
        expected_title = "Mean score comparison" if chart["chart_type"] == "means" else chart["question_text"]
        assert " ".join(title) == " ".join(expected_title.split())
        # Top margin leaves room for every title and subtitle line.
        assert layout["margin"]["t"] >= 24 * len(title) + 17 * len(sub)


def test_long_pofma_title_is_wrapped_not_cut(toluna_charts):
    chart = _chart(toluna_charts, "dist", "9")
    title, _ = _title_lines(chart["figure"]["layout"])
    assert len(title) >= 2
    assert title[-1].endswith("misinformation/falsehoods?")


# --- 3. measure labelling --------------------------------------------------------


def test_by_ethnicity_chart_states_the_net_and_unit(toluna_charts):
    chart = _chart(toluna_charts, "xbreak", "6", "ethnicity")
    assert chart["subtitle"] == "% Extremely able to + Somewhat able to, by ethnicity"
    _, sub = _title_lines(chart["figure"]["layout"])
    assert " ".join(sub) == chart["subtitle"]
    assert chart["figure"]["layout"]["yaxis"]["title"]["text"] == "% of respondents"


def test_net_subtitle_comes_from_the_compute_core(toluna_charts):
    """Every by-ethnicity subtitle equals compute.frequency.describe_net for
    that question -- the same top-role set t2b sums."""
    from surveytool.compute.frequency import describe_net
    from surveytool.ingest import toluna

    survey = toluna.load(TOLUNA_PATH, "t")
    questions = {q.qid: q for q in survey.questions}
    for chart in toluna_charts:
        if chart["chart_type"] == "xbreak":
            assert chart["subtitle"] == f"% {describe_net(questions[chart['qid']], 't2b')}, by ethnicity"


def test_every_chart_has_subtitle_and_value_axis_title(toluna_charts):
    for chart in toluna_charts:
        assert chart["subtitle"], chart["qid"]
        layout = chart["figure"]["layout"]
        axis = "yaxis" if chart["chart_type"] == "xbreak" else "xaxis"
        assert layout[axis]["title"]["text"], (chart["qid"], chart["chart_type"])


# --- 4. mean score chart -----------------------------------------------------------


def test_means_axis_starts_at_scale_minimum(toluna_charts):
    layout = _chart(toluna_charts, "means")["figure"]["layout"]
    assert layout["xaxis"]["range"] == [1, 5]
    assert layout["xaxis"]["tickvals"] == [1, 2, 3, 4, 5]


def test_means_labels_wrap_at_30_and_margin_fits_longest_line(toluna_charts):
    fig = _chart(toluna_charts, "means")["figure"]
    lines = [line for label in fig["data"][0]["y"] for line in label.split("<br>") if not line.startswith("<span")]
    assert max(len(line) for line in lines) <= 30
    assert fig["layout"]["margin"]["l"] >= max(len(line) for line in lines) * 7
    # Height gives each wrapped label its lines, so labels can't overlap.
    total_lines = sum(len(label.split("<br>")) for label in fig["data"][0]["y"])
    plot_height = fig["layout"]["height"] - fig["layout"]["margin"]["t"] - fig["layout"]["margin"]["b"]
    assert plot_height >= total_lines * 16


def test_means_mixed_scales_label_each_items_endpoints(toluna_charts):
    """Toluna's mean chart mixes four scale families, so each item carries
    its own 1 and 5 labels (from the question's rank-1 and rank-5 answers)."""
    chart = _chart(toluna_charts, "means")
    y = chart["figure"]["data"][0]["y"]
    assert "1 = Extremely unable to · 5 = Extremely able to" in y[0]
    assert "1 = Very Unlikely · 5 = Very Likely" in y[1]
    axis_title = chart["figure"]["layout"]["xaxis"]["title"]["text"]
    assert axis_title.replace("<br>", " ") == "Mean score (1 = lowest, 5 = highest point of each question's scale)"


def test_means_shared_scale_labels_the_axis_endpoints():
    charts = _charts(MILIEU_PATH, "milieu", "text/csv")
    chart = _chart(charts, "means")
    axis_title = chart["figure"]["layout"]["xaxis"]["title"]["text"]
    assert axis_title.replace("<br>", " ") == "Mean score (1 = Strongly Disagree, 5 = Strongly Agree)"
    assert all("<span" not in label for label in chart["figure"]["data"][0]["y"])


def test_missing_scale_endpoint_is_a_plain_error_naming_the_question():
    """A real Toluna question with its top-rank answer removed (the only
    way to reach this state from real data) must stop with a message that
    names the question, never draw an axis from a guess."""
    if not TOLUNA_PATH.exists():
        pytest.skip(f"{TOLUNA_PATH.name} not found in project root")
    from surveytool.charts.chart_data import _scale_endpoints
    from surveytool.charts.errors import SurveyToolError
    from surveytool.ingest import toluna

    question = next(q for q in toluna.load(TOLUNA_PATH, "t").questions if q.qid == "8")
    broken = question.model_copy(update={"labels": [sc for sc in question.labels if sc.rank != 5]})
    with pytest.raises(SurveyToolError) as exc_info:
        _scale_endpoints(broken)
    assert question.text in exc_info.value.message
    assert exc_info.value.next_action
