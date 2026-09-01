from datetime import datetime, timezone
from pathlib import Path

import pytest

from surveytool.ingest.chart_style import (
    ChartStyleChoice,
    ProjectChartStyles,
    load_chart_styles,
    write_chart_style,
    delete_chart_style,
    CorruptedChartStyleFileError,
)
from surveytool.charts.errors import UnknownChartStyleError


def test_load_chart_styles_returns_empty_for_missing_file(tmp_path):
    result = load_chart_styles(tmp_path / "does_not_exist.yaml")
    assert result.styles == {}


def test_write_then_load_round_trips(tmp_path):
    path = tmp_path / "styles.yaml"
    choice = ChartStyleChoice(variable="Q7", style_name="cool", saved_at=datetime.now(timezone.utc))
    write_chart_style(path, choice)
    loaded = load_chart_styles(path)
    assert loaded.styles["Q7"].style_name == "cool"


def test_write_overwrites_existing_entry_for_same_variable(tmp_path):
    path = tmp_path / "styles.yaml"
    first = ChartStyleChoice(variable="Q7", style_name="cool", saved_at=datetime.now(timezone.utc))
    second = ChartStyleChoice(variable="Q7", style_name="warm", saved_at=datetime.now(timezone.utc))
    write_chart_style(path, first)
    write_chart_style(path, second)
    loaded = load_chart_styles(path)
    assert loaded.styles["Q7"].style_name == "warm"


def test_write_rejects_unknown_style_name(tmp_path):
    path = tmp_path / "styles.yaml"
    choice = ChartStyleChoice(variable="Q7", style_name="not_a_real_style", saved_at=datetime.now(timezone.utc))
    with pytest.raises(UnknownChartStyleError):
        write_chart_style(path, choice)
    # Nothing was written.
    assert load_chart_styles(path).styles == {}


def test_delete_chart_style_is_a_noop_when_nothing_saved(tmp_path):
    path = tmp_path / "styles.yaml"
    delete_chart_style(path, "Q7")  # must not raise
    assert load_chart_styles(path).styles == {}


def test_delete_chart_style_removes_entry(tmp_path):
    path = tmp_path / "styles.yaml"
    write_chart_style(path, ChartStyleChoice(variable="Q7", style_name="cool", saved_at=datetime.now(timezone.utc)))
    delete_chart_style(path, "Q7")
    assert load_chart_styles(path).styles == {}


def test_corrupted_file_raises_rather_than_silently_resetting(tmp_path):
    path = tmp_path / "styles.yaml"
    path.write_text("not: [valid, yaml: structure for this model", encoding="utf-8")
    with pytest.raises(CorruptedChartStyleFileError):
        load_chart_styles(path)
