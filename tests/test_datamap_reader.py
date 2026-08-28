import pytest

from surveytool.ingest.datamap_reader import DatamapMalformedLineError, DatamapReader, DatamapReaderError
from surveytool.ingest.vendor_profile import PURESPECTRUM_PROFILE, RAKUTEN_PROFILE


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
    text, codes, qtype_hint, options = codebook["Q1"]
    assert text == "How satisfied are you?"
    assert codes == [(1, "Very satisfied"), (2, "Neutral"), (3, "Very dissatisfied")]
    assert qtype_hint is None
    assert options == []


def test_datamap_reader_open_response_no_codes():
    codebook_ws = _FakeWorksheet([
        ("[Q2]: Please describe your experience", None, None),
        ("Open text", None, None),
        (None, None, None),
    ])
    reader = DatamapReader(RAKUTEN_PROFILE)
    codebook = reader.read_codebook(codebook_ws)
    assert "Q2" in codebook
    text, codes, qtype_hint, options = codebook["Q2"]
    assert text == "Please describe your experience"
    assert codes == []
    assert qtype_hint == "open_text"
    assert options == []


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


def test_datamap_reader_unbracketed_header_recognised_by_lookahead():
    """Round A prompt A1: PureSpectrum writes some multi-select question
    headers without brackets (e.g. "Q10: text" rather than "[Q10]: text").
    The reader must still recognise this as a new block header — not
    silently append its rows to the preceding block — because the next
    non-blank column A line is a 'Values:' continuation marker."""
    codebook_ws = _FakeWorksheet([
        ("[Q9]: How worried are you?", None, None),
        ("Values: 1-4", None, None),
        (None, 1, "Very worried"),
        (None, 2, "Not worried at all"),
        (None, None, None),
        ("Q10: Which of these worry you?", None, None),
        ("Values: 0-1", None, None),
        (None, 0, "Unchecked"),
        (None, 1, "Checked"),
        (None, "[Q10r1]", "Loss of language"),
        (None, "[Q10r2]", "Loss of customs"),
        (None, None, None),
    ])
    reader = DatamapReader(PURESPECTRUM_PROFILE)
    codebook = reader.read_codebook(codebook_ws)

    assert "Q9" in codebook
    q9_text, q9_codes, _hint, _opts = codebook["Q9"]
    assert q9_codes == [(1, "Very worried"), (2, "Not worried at all")]

    assert "Q10" in codebook
    q10_text, q10_codes, q10_hint, q10_options = codebook["Q10"]
    assert q10_text == "Which of these worry you?"
    assert q10_codes == [(0, "Unchecked"), (1, "Checked")]
    assert q10_hint is None
    assert q10_options == [("Q10r1", "Loss of language"), ("Q10r2", "Loss of customs")]


def test_datamap_reader_bare_word_colon_prefix_not_treated_as_header_shape():
    """A 'Values:' line itself must never be mistaken for a block header —
    the header rule can't simply widen to 'any word followed by a colon',
    because 'Values:' matches that shape too."""
    codebook_ws = _FakeWorksheet([
        ("[Q1]: A question", None, None),
        ("Values: 1-2", None, None),
        (None, 1, "Yes"),
        (None, 2, "No"),
        (None, None, None),
    ])
    reader = DatamapReader(PURESPECTRUM_PROFILE)
    codebook = reader.read_codebook(codebook_ws)
    assert set(codebook.keys()) == {"Q1"}


def test_datamap_reader_malformed_column_a_line_raises_with_row_and_content():
    """Requirement 4: any non-blank column A line that is neither a
    recognised block header nor a recognised continuation marker must raise,
    naming the row number and literal cell content — not be silently
    absorbed into the preceding block (the historical Q9/Q10 bug)."""
    codebook_ws = _FakeWorksheet([
        ("[Q1]: A question", None, None),
        ("Values: 1-2", None, None),
        (None, 1, "Yes"),
        (None, 2, "No"),
        ("Some stray note that is not a header or marker", None, None),
        (None, None, None),
    ])
    reader = DatamapReader(PURESPECTRUM_PROFILE)
    with pytest.raises(DatamapMalformedLineError) as exc_info:
        reader.read_codebook(codebook_ws)
    assert "5" in str(exc_info.value)
    assert "Some stray note" in str(exc_info.value)


def test_datamap_reader_malformed_code_row_raises():
    """A row that is neither a numeric code mapping nor a bracketed
    option-definition row must raise rather than being silently dropped —
    this was the exact mechanism that discarded Q10's [Q10rN] option rows
    before A1 and made Q9 present only 6 of its real labels."""
    codebook_ws = _FakeWorksheet([
        ("Q10: Which of these worry you?", None, None),
        ("Values: 0-1", None, None),
        (None, 0, "Unchecked"),
        (None, "not-a-code-or-ref", "Something"),
        (None, None, None),
    ])
    reader = DatamapReader(PURESPECTRUM_PROFILE)
    with pytest.raises(DatamapMalformedLineError) as exc_info:
        reader.read_codebook(codebook_ws)
    assert "4" in str(exc_info.value)
