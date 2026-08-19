from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class VendorProfile:
    """Declarative description of everything that varies between vendor
    adapters: sheet resolution, reserved/quality columns, date and
    multiselect conventions, and fingerprint signature.

    ``quality_flag_column`` and ``verification_sheet`` are nullable and, as
    of Phase 1, unused by any adapter — they exist so Rakuten's profile can
    name ``FLAG`` and the ``HC`` sheet declaratively without any adapter
    behaviour depending on it yet.
    """

    vendor_id: str
    data_sheet: str | None
    codebook_sheet: str | None
    reserved_metadata_columns: frozenset[str]
    quality_columns: frozenset[str]
    quality_flag_column: str | None
    quality_flag_pass_value: str | None
    quality_flag_fail_value: str | None
    verification_sheet: str | None
    date_format: str | None
    multiselect_column_pattern: str | None
    other_specify_suffix: str | None
    signature: "VendorSignature | None"


@dataclass(frozen=True)
class VendorSignature:
    """Expected sheet names and a small set of expected column names, used
    by the Phase 4 fingerprint pre-check to detect a file loaded under the
    wrong vendor selection."""

    expected_sheets: frozenset[str] = field(default_factory=frozenset)
    expected_columns: frozenset[str] = field(default_factory=frozenset)


_REGISTRY: dict[str, VendorProfile] = {}


def register_vendor_profile(profile: VendorProfile) -> None:
    _REGISTRY[profile.vendor_id] = profile


def get_vendor_profile(vendor_id: str) -> VendorProfile:
    return _REGISTRY[vendor_id]
