import pytest

from surveytool.ingest.vendor_profile import VendorProfile


def test_vendor_profile_quality_flag_and_verification_sheet_default_none():
    profile = VendorProfile(
        vendor_id="test_vendor",
        data_sheet=None,
        codebook_sheet=None,
        reserved_metadata_columns=frozenset(),
        quality_columns=frozenset(),
        quality_flag_column=None,
        quality_flag_pass_value=None,
        quality_flag_fail_value=None,
        verification_sheet=None,
        date_format=None,
        multiselect_column_pattern=None,
        other_specify_suffix=None,
        signature=None,
    )
    assert profile.quality_flag_column is None
    assert profile.verification_sheet is None
    assert profile.vendor_id == "test_vendor"


def test_vendor_profile_is_frozen():
    profile = VendorProfile(
        vendor_id="test_vendor",
        data_sheet=None,
        codebook_sheet=None,
        reserved_metadata_columns=frozenset(),
        quality_columns=frozenset(),
        quality_flag_column=None,
        quality_flag_pass_value=None,
        quality_flag_fail_value=None,
        verification_sheet=None,
        date_format=None,
        multiselect_column_pattern=None,
        other_specify_suffix=None,
        signature=None,
    )
    import dataclasses
    with pytest.raises(dataclasses.FrozenInstanceError):
        profile.vendor_id = "changed"
