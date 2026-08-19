import pytest

from surveytool.ingest.vendor_profile import (
    MILIEU_PROFILE,
    RAKUTEN_PROFILE,
    TOLUNA_PROFILE,
    VendorProfile,
    get_vendor_profile,
)


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


def test_rakuten_profile_matches_current_constants():
    p = RAKUTEN_PROFILE
    assert p.vendor_id == "rakuten"
    assert p.data_sheet == "A1"
    assert p.codebook_sheet == "Datamap"
    assert p.reserved_metadata_columns == frozenset({"record", "uuid", "uid"})
    assert p.quality_columns == frozenset({"FLAG"})
    assert p.quality_flag_column == "FLAG"
    assert p.verification_sheet == "HC"
    assert p.date_format is None
    assert p.multiselect_column_pattern is None
    assert p.other_specify_suffix is None
    assert get_vendor_profile("rakuten") is p


def test_milieu_profile_matches_current_constants():
    p = MILIEU_PROFILE
    assert p.vendor_id == "milieu"
    assert p.data_sheet is None
    assert p.codebook_sheet is None
    assert p.reserved_metadata_columns == frozenset({"profile_id"})
    assert p.quality_columns == frozenset()
    assert p.quality_flag_column is None
    assert p.verification_sheet is None
    assert get_vendor_profile("milieu") is p


def test_toluna_profile_matches_current_constants():
    p = TOLUNA_PROFILE
    assert p.vendor_id == "toluna"
    assert p.data_sheet == "RespondentData.Text"
    assert p.codebook_sheet is None
    assert p.reserved_metadata_columns == frozenset({"respid"})
    assert p.quality_columns == frozenset()
    assert p.quality_flag_column is None
    assert p.verification_sheet is None
    assert get_vendor_profile("toluna") is p
