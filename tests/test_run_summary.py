from datetime import datetime, timezone

from surveytool.core.column_classification import ColumnClassification
from surveytool.ingest.overrides import OverrideNotice
from surveytool.ingest.run_summary import RunSummary, build_run_summary
from surveytool.ingest.vendor_profile import PURESPECTRUM_PROFILE, RAKUTEN_PROFILE


def test_purespectrum_summary_states_no_quality_flag_and_no_verification():
    summary = build_run_summary(
        profile=PURESPECTRUM_PROFILE,
        column_classifications={"record": ColumnClassification.METADATA, "Q1": ColumnClassification.QUESTION},
        status_values=[],
        override_notices=[],
        overrides_applied=[],
    )
    assert isinstance(summary, RunSummary)
    assert "no quality flag" in summary.quality_flag_statement.lower()
    assert "no" in summary.verification_statement.lower() and "sheet" in summary.verification_statement.lower()


def test_rakuten_summary_names_flag_and_confirms_hc_sheet_used():
    summary = build_run_summary(
        profile=RAKUTEN_PROFILE,
        column_classifications={"record": ColumnClassification.METADATA, "FLAG": ColumnClassification.QUALITY, "Q1": ColumnClassification.QUESTION},
        status_values=[],
        override_notices=[],
        overrides_applied=[],
        verification_sheet_used=True,
    )
    assert "FLAG" in summary.quality_flag_statement
    assert "HC" in summary.verification_statement


def test_summary_lists_all_columns_for_both_vendors():
    cols = {"record": ColumnClassification.METADATA, "Q1": ColumnClassification.QUESTION, "S1": ColumnClassification.DEMOGRAPHIC}
    summary = build_run_summary(
        profile=RAKUTEN_PROFILE, column_classifications=cols, status_values=[], override_notices=[], overrides_applied=[],
    )
    assert set(summary.column_classifications.keys()) == set(cols.keys())
    assert summary.classification_counts[ColumnClassification.METADATA] == 1
    assert summary.classification_counts[ColumnClassification.QUESTION] == 1
    assert summary.classification_counts[ColumnClassification.DEMOGRAPHIC] == 1


def test_summary_includes_override_resolutions_and_notices():
    now = datetime.now(timezone.utc)
    summary = build_run_summary(
        profile=RAKUTEN_PROFILE,
        column_classifications={},
        status_values=[],
        override_notices=[OverrideNotice(variable="Q3", message="Q3 now also matches the library.")],
        overrides_applied=[("Q3", now)],
    )
    assert summary.override_resolutions == [{"variable": "Q3", "resolved_at": now}]
    assert summary.notices == ["Q3 now also matches the library."]


def test_summary_reports_disposition_counts():
    summary = build_run_summary(
        profile=RAKUTEN_PROFILE,
        column_classifications={},
        status_values=["complete", "complete", "screened_out", "complete"],
        override_notices=[],
        overrides_applied=[],
    )
    assert summary.disposition_counts == {"complete": 3, "screened_out": 1}
