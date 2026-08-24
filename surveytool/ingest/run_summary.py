from __future__ import annotations

from collections import Counter
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from surveytool.core.column_classification import ColumnClassification
from surveytool.core.demographic_registry import NotCollectedEntry
from surveytool.ingest.overrides import OverrideNotice
from surveytool.ingest.vendor_profile import VendorProfile


class RunSummary(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    column_classifications: dict[str, ColumnClassification]
    classification_counts: dict[ColumnClassification, int]
    disposition_counts: dict[str, int]
    quality_flag_statement: str
    verification_statement: str
    straightliner_statement: str
    demographic_gap_statement: str
    override_resolutions: list[dict]
    notices: list[str]


def _quality_flag_statement(profile: VendorProfile) -> str:
    if profile.quality_flag_column is None:
        return (
            f"{profile.vendor_id} supplies no quality flag column. "
            "Straightliner exclusion based on a vendor-supplied flag is unavailable for this file; "
            "straightliner detection based on response variance is still available."
        )
    return (
        f"Quality flag column '{profile.quality_flag_column}' is available from {profile.vendor_id}."
    )


def _verification_statement(profile: VendorProfile, verification_sheet_used: bool) -> str:
    if profile.verification_sheet is None:
        return f"{profile.vendor_id} supplies no verification sheet. Topline figures are not cross-checked against a vendor tabulation."
    if verification_sheet_used:
        return f"Verification sheet '{profile.verification_sheet}' was present and used."
    return f"Verification sheet '{profile.verification_sheet}' is expected for {profile.vendor_id} but was not used for this run."


def _straightliner_statement(count: int, action: str) -> str:
    if count == 0:
        return "No respondents were flagged as straightliners."
    if action == "exclude":
        return f"{count} respondent(s) were flagged as straightliners and excluded from the base."
    return f"{count} respondent(s) were flagged as straightliners and kept in the base."


def _demographic_gap_statement(not_collected: list[NotCollectedEntry]) -> str:
    """Task 9: always-present, plain-English statement of every declared
    not-collected category for this vendor, following the same
    always-present-statement pattern as _straightliner_statement /
    _quality_flag_statement / _verification_statement above. Never silent
    when a gap exists, and explicit when there is none."""
    if not not_collected:
        return "This vendor's demographic mappings collect every canonical category with no declared gaps."
    parts = [
        f"{entry.dimension_label} — '{entry.category_label}' was not collected by this vendor: {entry.reason}"
        for entry in not_collected
    ]
    return " ".join(parts)


def build_run_summary(
    *,
    profile: VendorProfile,
    column_classifications: dict[str, ColumnClassification],
    status_values: list[str],
    override_notices: list[OverrideNotice],
    overrides_applied: list[tuple[str, datetime]],
    verification_sheet_used: bool = False,
    straightliner_count: int = 0,
    straightliner_action: str = "keep",
    not_collected: list[NotCollectedEntry] | None = None,
) -> RunSummary:
    classification_counts = dict(Counter(column_classifications.values()))
    disposition_counts = dict(Counter(status_values))

    return RunSummary(
        column_classifications=column_classifications,
        classification_counts=classification_counts,
        disposition_counts=disposition_counts,
        quality_flag_statement=_quality_flag_statement(profile),
        verification_statement=_verification_statement(profile, verification_sheet_used),
        straightliner_statement=_straightliner_statement(straightliner_count, straightliner_action),
        demographic_gap_statement=_demographic_gap_statement(not_collected or []),
        override_resolutions=[{"variable": v, "resolved_at": ts} for v, ts in overrides_applied],
        notices=[n.message for n in override_notices],
    )
