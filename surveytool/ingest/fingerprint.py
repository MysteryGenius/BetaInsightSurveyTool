from __future__ import annotations

from surveytool.charts.errors import ErrorCode, SurveyToolError
from surveytool.ingest.vendor_profile import (
    MILIEU_PROFILE,
    PURESPECTRUM_PROFILE,
    RAKUTEN_PROFILE,
    TOLUNA_PROFILE,
    VendorProfile,
    get_vendor_profile,
)

_ALL_PROFILES: list[VendorProfile] = [RAKUTEN_PROFILE, MILIEU_PROFILE, TOLUNA_PROFILE, PURESPECTRUM_PROFILE]


class VendorMismatchError(SurveyToolError):
    """Raised when a loaded file's sheets/columns don't match the selected
    vendor's signature. Names the vendor the file appears to be, only when
    exactly one other registered profile matches — vendor selection stays
    authoritative; this never auto-switches the selection."""

    def __init__(self, selected_vendor: str, matched_vendor: str | None) -> None:
        self.selected_vendor = selected_vendor
        self.matched_vendor = matched_vendor
        if matched_vendor is not None:
            message = f"This file doesn't look like a {selected_vendor} export — it looks like {matched_vendor}."
            detail = f"Selected vendor {selected_vendor!r} signature did not match; {matched_vendor!r} signature did."
            next_action = f"Select {matched_vendor} as the vendor, or confirm this is really a {selected_vendor} file."
        else:
            message = f"This file doesn't look like a {selected_vendor} export."
            detail = f"Selected vendor {selected_vendor!r} signature did not match, and no other registered vendor matched either."
            next_action = "Check the vendor setting, or pick a different file."
        super().__init__(ErrorCode.VENDOR_MISMATCH, message, detail=detail, next_action=next_action)


def _signature_matches(profile: VendorProfile, sheet_names: frozenset[str], column_names: frozenset[str]) -> bool:
    """A profile 'matches' only if it declares at least one real signature
    element AND every declared element is present in the file. A profile
    with a wholly empty signature (e.g. Milieu, which is sniffed by CSV
    header regex rather than by sheet/column names — see VendorProfile
    Task 2) declares nothing to check, so it must never be treated as a
    vacuous match: without this guard, an empty signature would match any
    file, silently absorbing every mismatch scan into a 'multiple matches
    -> no vendor named' result instead of correctly naming the one real
    match. This is a load-bearing correctness fix, not a style choice —
    verified by tracing test_mismatch_naming_exactly_one_other_vendor
    (selecting rakuten against Toluna-shaped input must name 'toluna', not
    silently swallow the match because Milieu's empty signature also
    'matched')."""
    sig = profile.signature
    if sig is None:
        return False
    if not sig.expected_sheets and not sig.expected_columns:
        return False
    sheets_ok = not sig.expected_sheets or sig.expected_sheets.issubset(sheet_names)
    columns_ok = not sig.expected_columns or sig.expected_columns.issubset(column_names)
    return sheets_ok and columns_ok


def check_fingerprint(
    selected_vendor: str,
    *,
    sheet_names: frozenset[str],
    column_names: frozenset[str],
) -> None:
    """Check a loaded file against the selected vendor's signature. Raises
    VendorMismatchError on mismatch. Never auto-switches — the caller's
    vendor selection is unaffected either way; this only decides whether to
    raise."""
    selected_profile = get_vendor_profile(selected_vendor)
    if _signature_matches(selected_profile, sheet_names, column_names):
        return

    matches = [
        p.vendor_id
        for p in _ALL_PROFILES
        if p.vendor_id != selected_vendor and _signature_matches(p, sheet_names, column_names)
    ]
    matched_vendor = matches[0] if len(matches) == 1 else None
    raise VendorMismatchError(selected_vendor, matched_vendor)
