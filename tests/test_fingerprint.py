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


def test_purespectrum_shaped_file_under_rakuten_selection_names_purespectrum():
    """Rakuten's signature ({A1, Datamap} / {record, uuid}) is a strict
    subset of PureSpectrum's ({A1, Datamap} / {record, uuid, date, status,
    dtrack}). A file that satisfies PureSpectrum's fuller signature also
    trivially satisfies Rakuten's — but PureSpectrum is the more specific,
    better explanation for the file, so selecting rakuten against this
    input must raise and name purespectrum, not silently pass."""
    with pytest.raises(VendorMismatchError) as exc_info:
        check_fingerprint(
            "rakuten",
            sheet_names=frozenset({"A1", "Datamap"}),
            column_names=frozenset({"record", "uuid", "date", "status", "dtrack"}),
        )
    assert exc_info.value.matched_vendor == "purespectrum"


def test_vendor_with_no_declared_signature_never_raises():
    """Milieu declares an empty signature (sniffed by CSV header regex, not
    sheet/column names). _signature_matches's vacuous-match guard means an
    empty signature can never 'match' anything, including its own file — so
    check_fingerprint must special-case this and always pass, rather than
    raising VENDOR_MISMATCH on every genuine Milieu upload."""
    check_fingerprint(
        "milieu",
        sheet_names=frozenset(),
        column_names=frozenset({"[Q1]: Some milieu-style header"}),
    )  # must not raise


def test_rakuten_own_real_file_still_matches_rakuten_with_no_raise():
    """A genuine Rakuten file (only record/uuid, no PureSpectrum-only
    columns) must still pass under rakuten selection: Rakuten's signature
    is the unique matching (and thus unique most-specific-among-matches)
    profile for this input."""
    check_fingerprint(
        "rakuten",
        sheet_names=frozenset({"A1", "Datamap", "HC"}),
        column_names=frozenset({"record", "uuid", "S1"}),
    )  # must not raise
