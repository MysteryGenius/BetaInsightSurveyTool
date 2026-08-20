"""
PureSpectrum real-file integration tests (spec Prompt 9). Skipped until the
client supplies purespectrum_survey_wcs_data.xlsx — do not fabricate this
fixture's content; a synthetic stand-in could pass while the real file's
shape diverges, which is exactly the silent-failure mode this whole plan
exists to close.
"""
from pathlib import Path

import pytest

_ROOT = Path(__file__).parent.parent
_PURESPECTRUM_PATH = _ROOT / "purespectrum_survey_wcs_data.xlsx"


@pytest.mark.skipif(
    not _PURESPECTRUM_PATH.exists(),
    reason="purespectrum_survey_wcs_data.xlsx not found in project root — awaiting client fixture.",
)
def test_purespectrum_real_file_loads_and_classifies_all_42_columns():
    from surveytool.ingest.purespectrum import load

    survey = load(_PURESPECTRUM_PATH, "wcs")
    assert survey.n_raw > 0
    # 42-column assertion requires classify_columns wired against the real
    # header — fill in once the file's actual header is known.
    pytest.skip("Awaiting purespectrum_survey_wcs_data.xlsx to confirm the real 42-column header shape.")


@pytest.mark.skipif(
    not _PURESPECTRUM_PATH.exists(),
    reason="purespectrum_survey_wcs_data.xlsx not found in project root — awaiting client fixture.",
)
def test_purespectrum_file_under_rakuten_selection_names_purespectrum():
    import openpyxl

    from surveytool.ingest.fingerprint import VendorMismatchError, check_fingerprint

    wb = openpyxl.load_workbook(_PURESPECTRUM_PATH, read_only=True, data_only=True)
    sheet_names = frozenset(wb.sheetnames)
    ws = wb[wb.sheetnames[0]]
    header = next(ws.iter_rows(values_only=True))
    column_names = frozenset(str(h) for h in header if h is not None)
    wb.close()

    with pytest.raises(VendorMismatchError) as exc_info:
        check_fingerprint("rakuten", sheet_names=sheet_names, column_names=column_names)
    assert exc_info.value.matched_vendor == "purespectrum"
