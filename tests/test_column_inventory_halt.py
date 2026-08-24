"""
Task 8: the halt on an unrecognized column, wired into
build_column_classifications (the live load-path function; the previously
dead classify_columns()/UnclassifiedColumnError-raising sibling has been
retired and folded into this one).

For each of the four vendors, this loads the real fixture through the same
functions the desktop app's load path calls (load(), column_qid_map(),
get_vendor_profile()), injects one bogus extra column into the header that
matches no vendor profile membership and no parsed Question, and confirms
build_column_classifications raises UnclassifiedColumnError naming that
column — proving the halt actually fires, not just that it compiles.

A companion test per vendor confirms the *unmodified* real header still
classifies cleanly (no halt, no UNCLASSIFIED) — guarding against an
overly strict reconciliation rejecting real, legitimately-classified
columns.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from surveytool.core.column_classification import ColumnClassification, UnclassifiedColumnError
from surveytool.ingest.column_inventory import build_column_classifications
from surveytool.ingest.overrides import QuestionOverride
from surveytool.ingest.vendor_profile import get_vendor_profile

ROOT = Path(__file__).parent.parent
RAKUTEN_PATH = ROOT / "rakuten_survey_support_measures_data.xlsx"
TOLUNA_PATH = ROOT / "toluna_survey_misinformation_data.xlsx"
MILIEU_PATH = ROOT / "milieu_survey_coe_data.csv"
PURESPECTRUM_PATH = ROOT / "purespectrum_survey_wcs_data.xlsx"

_PURESPECTRUM_UNRESOLVED = ("D2", "Q1", "Q3", "Q6", "Q9", "D5")

_BOGUS_COLUMN = "TotallyUnrecognizedColumnXYZ"


def _purespectrum_overrides() -> dict[str, QuestionOverride]:
    now = datetime.now(timezone.utc)
    return {
        variable: QuestionOverride(
            variable=variable,
            question_type="categorical",
            label_roles={},
            resolved_at=now,
            library_version="test",
        )
        for variable in _PURESPECTRUM_UNRESOLVED
    }


def _load_rakuten():
    from surveytool.ingest.rakuten import column_qid_map, load

    survey = load(RAKUTEN_PATH, "halt-test-rakuten", {}, None)
    header, qid_by_column = column_qid_map(RAKUTEN_PATH)
    profile = get_vendor_profile("rakuten")
    return header, qid_by_column, survey, profile


def _load_milieu():
    from surveytool.ingest.milieu import column_qid_map, load

    survey = load(MILIEU_PATH, "halt-test-milieu", {}, None)
    header, qid_by_column = column_qid_map(MILIEU_PATH)
    profile = get_vendor_profile("milieu")
    return header, qid_by_column, survey, profile


def _load_toluna():
    from surveytool.ingest.toluna import column_qid_map, load

    # Task 9: column "2" (age_band) is now a declared demographic
    # source_column in vendor_toluna.yaml, exempt from the load-path
    # collector — no override needed (contrast with the Task 5-era
    # override this helper used before age_band was mapped).
    survey = load(TOLUNA_PATH, "halt-test-toluna", {}, None)
    header, qid_by_column = column_qid_map(TOLUNA_PATH, {}, None)
    profile = get_vendor_profile("toluna")
    return header, qid_by_column, survey, profile


def _load_purespectrum():
    from surveytool.ingest.purespectrum import column_qid_map, load

    overrides = _purespectrum_overrides()
    survey = load(PURESPECTRUM_PATH, "halt-test-purespectrum", overrides, None)
    header, qid_by_column = column_qid_map(PURESPECTRUM_PATH)
    profile = get_vendor_profile("purespectrum")
    return header, qid_by_column, survey, profile


_VENDOR_LOADERS = {
    "rakuten": (_load_rakuten, RAKUTEN_PATH),
    "milieu": (_load_milieu, MILIEU_PATH),
    "toluna": (_load_toluna, TOLUNA_PATH),
    "purespectrum": (_load_purespectrum, PURESPECTRUM_PATH),
}


@pytest.mark.parametrize("vendor", ["rakuten", "milieu", "toluna", "purespectrum"])
def test_injected_unrecognized_column_halts_load(vendor):
    """Injecting a bogus extra column into a real fixture's header must
    raise UnclassifiedColumnError naming that column, for every vendor."""
    loader, path = _VENDOR_LOADERS[vendor]
    if not path.exists():
        pytest.skip(f"{path.name} not found in project root")

    header, qid_by_column, survey, profile = loader()
    injected_header = [*header, _BOGUS_COLUMN]

    with pytest.raises(UnclassifiedColumnError) as exc_info:
        build_column_classifications(injected_header, qid_by_column, survey, profile)

    assert exc_info.value.column == _BOGUS_COLUMN
    assert exc_info.value.header_text == _BOGUS_COLUMN
    assert _BOGUS_COLUMN in exc_info.value.message or _BOGUS_COLUMN in (exc_info.value.detail or "")


@pytest.mark.parametrize("vendor", ["rakuten", "milieu", "toluna", "purespectrum"])
def test_real_fixture_header_classifies_without_halting(vendor):
    """The unmodified real header for each vendor must classify cleanly:
    no exception, and no column left UNCLASSIFIED. Guards against an
    overly strict reconciliation rejecting real, legitimately-classified
    columns."""
    loader, path = _VENDOR_LOADERS[vendor]
    if not path.exists():
        pytest.skip(f"{path.name} not found in project root")

    header, qid_by_column, survey, profile = loader()

    result = build_column_classifications(header, qid_by_column, survey, profile)

    assert set(result.values()).issubset(set(ColumnClassification))
    assert ColumnClassification.UNCLASSIFIED not in result.values()
    # Every non-None header column got a classification.
    expected_columns = {c for c in header if c is not None}
    assert set(result.keys()) == expected_columns
