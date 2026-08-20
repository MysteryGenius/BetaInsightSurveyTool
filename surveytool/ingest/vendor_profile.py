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


RAKUTEN_PROFILE = VendorProfile(
    vendor_id="rakuten",
    data_sheet="A1",
    codebook_sheet="Datamap",
    reserved_metadata_columns=frozenset({"record", "uuid", "uid"}),
    quality_columns=frozenset({"FLAG"}),
    quality_flag_column="FLAG",
    quality_flag_pass_value=None,
    quality_flag_fail_value=None,
    verification_sheet="HC",
    date_format=None,
    multiselect_column_pattern=None,
    other_specify_suffix=None,
    signature=VendorSignature(
        expected_sheets=frozenset({"A1", "Datamap"}),
        expected_columns=frozenset({"record", "uuid"}),
    ),
)

MILIEU_PROFILE = VendorProfile(
    vendor_id="milieu",
    data_sheet=None,
    codebook_sheet=None,
    reserved_metadata_columns=frozenset({"profile_id"}),
    quality_columns=frozenset(),
    quality_flag_column=None,
    quality_flag_pass_value=None,
    quality_flag_fail_value=None,
    verification_sheet=None,
    date_format=None,
    multiselect_column_pattern=None,
    other_specify_suffix=None,
    signature=VendorSignature(),
)

TOLUNA_PROFILE = VendorProfile(
    vendor_id="toluna",
    data_sheet="RespondentData.Text",
    codebook_sheet=None,
    reserved_metadata_columns=frozenset({"respid"}),
    quality_columns=frozenset(),
    quality_flag_column=None,
    quality_flag_pass_value=None,
    quality_flag_fail_value=None,
    verification_sheet=None,
    date_format=None,
    multiselect_column_pattern=None,
    other_specify_suffix=None,
    signature=VendorSignature(
        expected_sheets=frozenset({"RespondentData.Text"}),
        expected_columns=frozenset({"respid"}),
    ),
)

PURESPECTRUM_PROFILE = VendorProfile(
    vendor_id="purespectrum",
    data_sheet="A1",
    codebook_sheet="Datamap",
    reserved_metadata_columns=frozenset({
        "record", "uuid", "date", "status", "dtrack", "qtime", "start_date", "transaction_id",
    }),
    # QC2 / QC2Flag classify as QUALITY per spec Prompt 9 and are excluded
    # from question tables. Pass/fail coding is unconfirmed by the vendor —
    # quality_flag_column stays None so nothing implements filtering on an
    # unverified coding. This is a deliberate, marked placeholder, not an
    # oversight: see quality_flag_pass_value/fail_value below.
    quality_columns=frozenset({"QC2", "QC2Flag"}),
    quality_flag_column=None,  # PLACEHOLDER: PureSpectrum's QC2/QC2Flag pass/fail coding is unconfirmed by the vendor. Do not implement filtering on it until confirmed.
    quality_flag_pass_value=None,
    quality_flag_fail_value=None,
    verification_sheet=None,
    date_format=None,
    multiselect_column_pattern=r"^Q10r[1-8]$",
    other_specify_suffix="oe",
    signature=VendorSignature(
        expected_sheets=frozenset({"A1", "Datamap"}),
        expected_columns=frozenset({"record", "uuid", "date", "status", "dtrack"}),
    ),
)

register_vendor_profile(RAKUTEN_PROFILE)
register_vendor_profile(MILIEU_PROFILE)
register_vendor_profile(TOLUNA_PROFILE)
register_vendor_profile(PURESPECTRUM_PROFILE)
