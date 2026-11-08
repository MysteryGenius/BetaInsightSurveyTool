"""v4 feedback F6: no respondent silently drops out of a Cross-tab break.

For every break-by variable, the column n values plus any stated exclusion
equal the base -- checked on the real vendor files. Toluna's combined
"55 years old and above" answer is now its own "55 and above" column, so
its age bands sum to 1,000.
"""
from __future__ import annotations

import itertools
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).parent.parent
TOLUNA_PATH = ROOT / "toluna_survey_misinformation_data.xlsx"
VENDOR_FILES = [
    ("toluna", "toluna_survey_misinformation_data.xlsx"),
    ("rakuten", "rakuten_survey_support_measures_data.xlsx"),
    ("rakuten", "rakuten_survey_chn_clans_data.xlsx"),
    ("milieu", "milieu_survey_coe_data.csv"),
    ("purespectrum", "purespectrum_survey_wcs_data.xlsx"),
]


def _upload(client, vendor, filename):
    path = ROOT / filename
    if not path.exists():
        pytest.skip(f"{filename} not found in project root")
    with open(path, "rb") as f:
        response = client.post(
            "/api/upload",
            data={"vendor": vendor, "survey_id": f"x-{vendor}"},
            files={"file": (filename, f, "application/octet-stream")},
        )
    assert response.status_code == 200, response.text
    return response.json()["session_id"]


def _crosstab(client, session_id, dims, filters=None):
    question = client.get(f"/api/session/{session_id}/demographics").json()["questions"][0]["qid"]
    response = client.post(
        f"/api/session/{session_id}/crosstab",
        json={
            "break_spec": {"dimensions": list(dims)},
            "filter_spec": {"selections": filters or {}},
            "question_ids": [question],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()[0]


def _break_dims(session_id, vendor):
    from surveytool.desktop.app import get_session

    registry = get_session(session_id).registry
    return [
        d for d in registry.dimensions_for_vendor(vendor)
        if not registry.canonical.dimensions[d].multi_select  # multi-select can't be a break
    ]


@pytest.fixture
def client():
    from surveytool.desktop.app import app

    return TestClient(app)


# --- the invariant, on every real vendor file ------------------------------------------


@pytest.mark.parametrize("vendor,filename", VENDOR_FILES, ids=[f for _, f in VENDOR_FILES])
def test_columns_plus_stated_exclusions_equal_the_base(client, vendor, filename):
    session_id = _upload(client, vendor, filename)
    dims = _break_dims(session_id, vendor)
    for spec in [(d,) for d in dims] + list(itertools.combinations(dims, 2)):
        qr = _crosstab(client, session_id, spec)
        columns = sum(col["base_cell"] for col in qr["columns"])
        assert columns + qr["excluded_from_columns"] == qr["base_filtered"], spec
        if qr["excluded_from_columns"]:
            assert qr["exclusion_reasons"], spec
            assert f"Not in any column: {qr['excluded_from_columns']:,}" in qr["header_lines"][1], spec


def test_toluna_age_bands_sum_to_1000_with_a_55_and_above_column(client):
    session_id = _upload(client, "toluna", TOLUNA_PATH.name)
    qr = _crosstab(client, session_id, ("age_band",))
    bands = {col["label_path"][0]: col["base_cell"] for col in qr["columns"]}
    assert bands == {"18-24": 100, "25-34": 221, "35-44": 241, "45-54": 224, "55 and above": 214}
    assert sum(bands.values()) == 1000 == qr["base_filtered"]
    assert qr["excluded_from_columns"] == 0
    assert qr["header_lines"][1] == "Base total: 1,000  |  Base filtered: 1,000"


def test_toluna_no_break_variable_excludes_anyone(client):
    session_id = _upload(client, "toluna", TOLUNA_PATH.name)
    for dim in _break_dims(session_id, "toluna"):
        assert _crosstab(client, session_id, (dim,))["excluded_from_columns"] == 0, dim


# --- an exclusion is stated, never silent ---------------------------------------------


def test_an_unplaceable_answer_is_counted_and_explained(tmp_path):
    """Reproduce the original fault with real data: the real Toluna file
    under Toluna's pre-F6 mapping (55+ answer mapped to nothing). The 214
    respondents must now be counted and explained beside the base."""
    if not TOLUNA_PATH.exists():
        pytest.skip(f"{TOLUNA_PATH.name} not found in project root")
    import yaml

    from surveytool.charts.crosstab_header import crosstab_header_lines
    from surveytool.compute.breaks_compute import compute_breaks_crosstab
    from surveytool.core.config import ToolConfig
    from surveytool.core.demographic_registry import _BUNDLED_DIR, load_registry
    from surveytool.core.respondent_frame import to_respondent_frame
    from surveytool.ingest import toluna

    reg_dir = tmp_path / "demographics"
    shutil.copytree(_BUNDLED_DIR, reg_dir, ignore=shutil.ignore_patterns("__pycache__", "*.py"))
    mapping = yaml.safe_load((reg_dir / "vendor_toluna.yaml").read_text(encoding="utf-8"))
    age = mapping["dimensions"]["age_band"]
    del age["value_map"]["55 years old and above"]
    age["not_collected"]["55_plus"] = {
        "reason": "pre-F6 mapping", "ambiguous_raw_values": ["55 years old and above"],
    }
    (reg_dir / "vendor_toluna.yaml").write_text(yaml.safe_dump(mapping), encoding="utf-8")

    survey = toluna.load(TOLUNA_PATH, "t")
    vendor_paths = {p.stem[len("vendor_"):]: p for p in reg_dir.glob("vendor_*.yaml")}
    registry = load_registry(reg_dir / "canonical.yaml", vendor_paths, surveys={"toluna": survey})
    frame = to_respondent_frame(survey)
    result = compute_breaks_crosstab(
        frame, survey, ["age_band"], {}, ["6"], registry, "toluna", ToolConfig()
    )[0]

    assert result.excluded_from_columns == 214
    assert sum(c.base_cell for c in result.columns) + 214 == result.base_filtered == 1000
    assert result.exclusion_reasons == [
        "214 gave an answer to the age band question that doesn't fit any age band group"
    ]
    base_line = crosstab_header_lines(result, ["age_band"], {}, registry)[1]
    assert base_line == (
        "Base total: 1,000  |  Base filtered: 1,000  |  Not in any column: 214 "
        "(214 gave an answer to the age band question that doesn't fit any age band group)"
    )


# --- combined band: filters, run summary, manifest --------------------------------------


def test_filtering_by_55_and_above_selects_55_64_and_65_plus_on_rakuten(client):
    session_id = _upload(client, "rakuten", "rakuten_survey_support_measures_data.xlsx")
    by_age = _crosstab(client, session_id, ("age_band",))
    older = sum(c["base_cell"] for c in by_age["columns"] if c["label_path"][0] in ("55-64", "65+"))
    assert older > 0
    filtered = _crosstab(client, session_id, ("gender",), filters={"age_band": ["55_plus"]})
    assert filtered["base_filtered"] == older
    assert "Filter by: Age band: 55 and above" in filtered["header_lines"][0]


def test_run_summary_says_55_64_and_65_plus_cannot_be_separated(client):
    session_id = _upload(client, "toluna", TOLUNA_PATH.name)
    items = client.get(f"/api/session/{session_id}/run-summary").json()["guardrail_items"]
    assert (
        "Age band: '55-64' and '65+' were not collected. This file's oldest age answer is one "
        "combined \"55 years old and above\" group, shown as the 55 and above band, so 55-64 "
        "and 65+ can't be separated."
    ) in items


def test_export_manifest_records_exclusions(client, tmp_path):
    import json

    session_id = _upload(client, "toluna", TOLUNA_PATH.name)
    response = client.post(
        f"/api/session/{session_id}/breaks-export",
        json={
            "break_spec": {"dimensions": ["age_band"]},
            "filter_spec": {"selections": {}},
            "chart_type": "table",
            "question_id": "6",
            "out_dir": str(tmp_path),
        },
    )
    assert response.status_code == 200, response.text
    entry = json.loads((tmp_path / "manifest.json").read_text())["files"][0]
    assert entry["excluded_from_columns"] == 0 and entry["exclusion_reasons"] == []
