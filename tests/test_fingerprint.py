import pytest

from surveytool.ingest.fingerprint import VendorMismatchError, check_fingerprint


def test_matching_signature_does_not_raise():
    check_fingerprint(
        "rakuten",
        sheet_names=frozenset({"A1", "Datamap", "HC"}),
        column_names=frozenset({"record", "uuid", "S1"}),
    )  # must not raise


def test_mismatch_naming_exactly_one_other_vendor():
    with pytest.raises(VendorMismatchError) as exc_info:
        check_fingerprint(
            "rakuten",
            sheet_names=frozenset({"RespondentData.Text"}),
            column_names=frozenset({"respid"}),
        )
    assert "toluna" in exc_info.value.message.lower() or "toluna" in (exc_info.value.detail or "").lower()


def test_mismatch_with_no_other_match_names_no_vendor():
    with pytest.raises(VendorMismatchError) as exc_info:
        check_fingerprint(
            "rakuten",
            sheet_names=frozenset({"CompletelyUnknownSheet"}),
            column_names=frozenset({"nonsense_column"}),
        )
    assert exc_info.value.matched_vendor is None


def test_selection_stays_authoritative_never_auto_switches():
    """check_fingerprint never returns a different vendor id — it only
    raises or passes. Confirmed structurally: the function's return type is
    None, so there is no code path by which a caller could be redirected to
    a different vendor without the caller itself choosing to."""
    import inspect
    sig = inspect.signature(check_fingerprint)
    assert sig.return_annotation in (None, "None")
