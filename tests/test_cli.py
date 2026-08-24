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


@pytest.mark.parametrize("vendor", ["rakuten", "milieu"])
def test_vendor_loads_end_to_end_via_cli(vendor):
    path = VENDOR_FILES[vendor]
    if not path.exists():
        pytest.skip(f"{path.name} not found in project root")

    result = _run_cli("ingest", str(path), "--survey-id", "t", "--vendor", vendor)

    assert result.returncode == 0, result.stderr
    info = json.loads(result.stdout)
    assert info["n_raw"] > 0
    assert info["question_count"] > 0


def test_toluna_cli_ingest_raises_for_unresolved_age_column():
    """Task 5: Toluna's real fixture has column "2" (age_band) as a
    genuine demographic that vendor_toluna.yaml deliberately leaves
    unmapped (see test_breaks_conformance.py's docstring for why), so it
    is not exempt from the load-path collector and the file can no longer
    load cleanly without an override. The CLI has no --overrides flag (out
    of scope for this task — see the brief, which only covers the four
    vendor load() paths and the web app's resolver), so this now surfaces
    as a non-zero exit rather than a successful ingest.

    Note: the CLI's main() has no SurveyToolError handler at all (only
    FileNotFoundError/ValueError/NotImplementedError, see cli.py's main()),
    so this currently exits non-zero via an unhandled Python traceback
    rather than a plain-English CLI message — a pre-existing CLI gap this
    task's change newly exposes for Toluna specifically (any vendor error
    already crashed this way before this task; MISSING_SHEET, for
    instance, would have too). Fixing the CLI's error presentation is out
    of scope here; this test only asserts the load itself now correctly
    fails instead of silently building a categorical question for column
    "2"."""
    path = VENDOR_FILES["toluna"]
    if not path.exists():
        pytest.skip(f"{path.name} not found in project root")

    result = _run_cli("ingest", str(path), "--survey-id", "t", "--vendor", "toluna")

    assert result.returncode != 0
    assert "UnresolvedQuestionsError" in result.stderr


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
