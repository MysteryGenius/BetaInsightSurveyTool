"""
CLI vendor-dispatch tests.

Confirms each vendor loads end to end through the CLI's public entry point,
and that omitting --vendor fails with a clear message rather than guessing.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent

VENDOR_FILES = {
    "rakuten": ROOT / "rakuten_survey_support_measures_data.xlsx",
    "milieu": ROOT / "milieu_survey_coe_data.csv",
    "toluna": ROOT / "toluna_survey_misinformation_data.xlsx",
}


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", "from surveytool.cli import main; main()", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize("vendor", ["rakuten", "milieu", "toluna"])
def test_vendor_loads_end_to_end_via_cli(vendor):
    path = VENDOR_FILES[vendor]
    if not path.exists():
        pytest.skip(f"{path.name} not found in project root")

    result = _run_cli("ingest", str(path), "--survey-id", "t", "--vendor", vendor)

    assert result.returncode == 0, result.stderr
    info = json.loads(result.stdout)
    assert info["n_raw"] > 0
    assert info["question_count"] > 0


def test_missing_vendor_exits_with_clear_message_not_guess():
    path = VENDOR_FILES["rakuten"]
    if not path.exists():
        pytest.skip(f"{path.name} not found in project root")

    result = _run_cli("ingest", str(path), "--survey-id", "t")

    assert result.returncode != 0
    assert "--vendor" in result.stderr
    assert "Traceback" not in result.stderr


def test_significance_flag_exits_cleanly_not_implemented():
    path = VENDOR_FILES["rakuten"]
    if not path.exists():
        pytest.skip(f"{path.name} not found in project root")

    result = _run_cli(
        "findings", str(path), "--survey-id", "t", "--vendor", "rakuten", "--significance", "95",
    )

    assert result.returncode == 2
    assert "not yet implemented" in result.stderr
    assert "Traceback" not in result.stderr
