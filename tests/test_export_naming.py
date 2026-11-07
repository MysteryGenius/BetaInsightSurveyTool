"""Cross-tab export filenames, collision rule and shared manifest (v4 feedback F1).

Pure-function tests: the names and collision decisions are computed from
strings and the files present in tmp_path, so no survey data is involved.
The end-to-end export behaviour on the real Toluna file is covered in
tests/test_desktop_breaks_api.py.
"""
from __future__ import annotations

import json

import pytest

from surveytool.charts.errors import SurveyToolError
from surveytool.charts.export_naming import (
    crosstab_export_identity,
    crosstab_export_stem,
    resolve_export_filename,
)
from surveytool.charts.manifest import load_manifest, merge_manifest


# --- filenames --------------------------------------------------------------


def test_stem_single_break_matches_brief_example():
    assert crosstab_export_stem("5", "grouped_bar", False, ["gender"], {}) == "5_grouped_bar_by-gender"


def test_stem_underscored_dimension_is_hyphenated():
    assert crosstab_export_stem("6", "stacked_bar_100", False, ["age_band"], None) == (
        "6_stacked_bar_100_by-age-band"
    )


def test_stem_nested_break_joins_dimensions_in_spec_order():
    assert crosstab_export_stem("6", "table", False, ["gender", "age_band"], {}) == (
        "6_table_by-gender-and-age-band"
    )


def test_stem_filter_segments_are_sorted_and_multi_value():
    stem = crosstab_export_stem(
        "6", "table", False, ["gender"],
        {"ethnicity": ["malay", "chinese"], "age_band": ["18_24"]},
    )
    assert stem == "6_table_by-gender_filter-age-band-18-24_filter-ethnicity-chinese+malay"


def test_stem_empty_filter_selection_is_ignored():
    assert crosstab_export_stem("6", "table", False, ["gender"], {"ethnicity": []}) == "6_table_by-gender"


def test_stem_swapped_suffix():
    assert crosstab_export_stem("q8", "grouped_bar", True, ["car_ownership"], {}) == (
        "q8_grouped_bar_by-car-ownership_swapped"
    )


def test_stems_differ_by_break():
    by_age = crosstab_export_stem("6", "grouped_bar", False, ["age_band"], {})
    by_gender = crosstab_export_stem("6", "grouped_bar", False, ["gender"], {})
    assert by_age != by_gender


# --- collision rule ---------------------------------------------------------


def _identity(**overrides):
    base = dict(survey_id="s", question_id="6", chart_type="table", swapped=False,
                break_dims=["gender"], filter_spec={})
    base.update(overrides)
    return crosstab_export_identity(**base)


def test_free_name_is_used_as_is(tmp_path):
    assert resolve_export_filename(tmp_path, "a", _identity(), {}, set()) == ("a.png", False)


def test_identical_earlier_export_is_overwritten(tmp_path):
    (tmp_path / "a.png").write_bytes(b"x")
    manifest = {"a.png": {"filename": "a.png", "identity": _identity()}}
    assert resolve_export_filename(tmp_path, "a", _identity(), manifest, set()) == ("a.png", True)


def test_different_earlier_export_gets_numbered_suffix(tmp_path):
    (tmp_path / "a.png").write_bytes(b"x")
    manifest = {"a.png": {"filename": "a.png", "identity": _identity(survey_id="other")}}
    assert resolve_export_filename(tmp_path, "a", _identity(), manifest, set()) == ("a_2.png", False)


def test_file_unknown_to_manifest_is_never_overwritten(tmp_path):
    (tmp_path / "a.png").write_bytes(b"x")
    (tmp_path / "a_2.png").write_bytes(b"x")
    assert resolve_export_filename(tmp_path, "a", _identity(), {}, set()) == ("a_3.png", False)


def test_name_already_written_in_this_export_gets_suffix(tmp_path):
    (tmp_path / "a.png").write_bytes(b"x")
    manifest = {"a.png": {"filename": "a.png", "identity": _identity()}}
    assert resolve_export_filename(tmp_path, "a", _identity(), manifest, {"a.png"}) == ("a_2.png", False)


def test_identical_suffixed_earlier_export_is_reused(tmp_path):
    (tmp_path / "a.png").write_bytes(b"x")
    (tmp_path / "a_2.png").write_bytes(b"x")
    manifest = {
        "a.png": {"filename": "a.png", "identity": _identity(survey_id="other")},
        "a_2.png": {"filename": "a_2.png", "identity": _identity()},
    }
    assert resolve_export_filename(tmp_path, "a", _identity(), manifest, set()) == ("a_2.png", True)


# --- manifest ---------------------------------------------------------------


def test_merge_manifest_accumulates_and_upserts(tmp_path):
    merge_manifest(tmp_path, [{"filename": "a.png", "source": "crosstab", "v": 1}])
    merge_manifest(tmp_path, [{"filename": "b.png", "source": "charts"},
                              {"filename": "a.png", "source": "crosstab", "v": 2}])
    loaded = load_manifest(tmp_path)
    assert set(loaded) == {"a.png", "b.png"}
    assert loaded["a.png"]["v"] == 2
    assert json.loads((tmp_path / "manifest.json").read_text())["files"]
    assert not (tmp_path / "manifest.json.tmp").exists()


def test_legacy_flat_list_manifest_is_read_as_charts_entries(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps([{"filename": "old.png", "qid": "1"}]))
    assert load_manifest(tmp_path)["old.png"]["source"] == "charts"


@pytest.mark.parametrize("content", ["{not json", json.dumps({"files": [{"no": "name"}]}), "42"])
def test_unreadable_manifest_is_a_plain_error(tmp_path, content):
    (tmp_path / "manifest.json").write_text(content)
    with pytest.raises(SurveyToolError) as exc_info:
        load_manifest(tmp_path)
    assert "manifest.json" in exc_info.value.message
    assert exc_info.value.next_action
