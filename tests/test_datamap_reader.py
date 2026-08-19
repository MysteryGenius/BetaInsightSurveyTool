import pytest

from surveytool.ingest.datamap_reader import DatamapReader, DatamapReaderError
from surveytool.ingest.vendor_profile import RAKUTEN_PROFILE


class _FakeCell:
    def __init__(self, value):
        self.value = value


class _FakeWorksheet:
    """Minimal stand-in for an openpyxl worksheet: iter_rows(values_only=True)."""

    def __init__(self, rows: list[tuple]):
        self._rows = rows

    def iter_rows(self, values_only: bool = True):
        assert values_only
        for row in self._rows:
            yield row


def test_datamap_reader_normal_entry():
    codebook_ws = _FakeWorksheet([
        ("[Q1]: How satisfied are you?", None, None),
        ("Values: 1-3", None, None),
        (None, 1, "Very satisfied"),
        (None, 2, "Neutral"),
        (None, 3, "Very dissatisfied"),
        (None, None, None),
    ])
    reader = DatamapReader(RAKUTEN_PROFILE)
    codebook = reader.read_codebook(codebook_ws)
    assert "Q1" in codebook
    text, codes, qtype_hint = codebook["Q1"]
    assert text == "How satisfied are you?"
    assert codes == [(1, "Very satisfied"), (2, "Neutral"), (3, "Very dissatisfied")]
    assert qtype_hint is None


def test_datamap_reader_open_response_no_codes():
    codebook_ws = _FakeWorksheet([
        ("[Q2]: Please describe your experience", None, None),
        ("Open text", None, None),
        (None, None, None),
    ])
    reader = DatamapReader(RAKUTEN_PROFILE)
    codebook = reader.read_codebook(codebook_ws)
    assert "Q2" in codebook
    text, codes, qtype_hint = codebook["Q2"]
    assert text == "Please describe your experience"
    assert codes == []
    assert qtype_hint == "open_text"


def test_datamap_reader_malformed_entry_raises_structured_error():
    codebook_ws = _FakeWorksheet([
        ("[Q3]: Malformed question", None, None),
        ("Values: 1-3", None, None),
        # no code rows follow — malformed
        ("[Q4]: Next question", None, None),
        ("Values: 1-2", None, None),
        (None, 1, "Yes"),
        (None, 2, "No"),
        (None, None, None),
    ])
    reader = DatamapReader(RAKUTEN_PROFILE)
    with pytest.raises(DatamapReaderError) as exc_info:
        reader.read_codebook(codebook_ws)
    assert "Q3" in str(exc_info.value)
