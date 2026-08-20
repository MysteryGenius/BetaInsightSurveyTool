from surveytool.ingest.purespectrum import parse_codebook


class _FakeWorksheet:
    def __init__(self, rows: list[tuple]):
        self._rows = rows

    def iter_rows(self, values_only: bool = True):
        assert values_only
        for row in self._rows:
            yield row


def test_purespectrum_skips_quality_columns_in_codebook():
    codebook_ws = _FakeWorksheet([
        ("[QC2]: Quality check", None, None),
        ("Values: 1-2", None, None),
        (None, 1, "Pass"),
        (None, 2, "Fail"),
        ("[Q1]: How satisfied are you?", None, None),
        ("Values: 1-2", None, None),
        (None, 1, "Satisfied"),
        (None, 2, "Dissatisfied"),
        (None, None, None),
    ])
    questions = parse_codebook(codebook_ws)
    qids = {q.qid for q in questions}
    assert "QC2" not in qids
    assert "Q1" in qids


def test_purespectrum_ascending_scale_computes_scale_direction():
    """Code 1 = bottom-box label, code 5 = top-box label: the natural
    'high code = top' ordering, so direction must resolve to ascending."""
    codebook_ws = _FakeWorksheet([
        ("[Q2]: How satisfied are you with the product?", None, None),
        ("Values: 1-5", None, None),
        (None, 1, "Strongly Disagree"),
        (None, 2, "Disagree"),
        (None, 3, "Neither Agree Nor Disagree"),
        (None, 4, "Agree"),
        (None, 5, "Strongly Agree"),
        (None, None, None),
    ])
    questions = parse_codebook(codebook_ws)
    q2 = next(q for q in questions if q.qid == "Q2")
    assert q2.qtype.name == "scale"
    assert q2.scale_direction == "ascending"


def test_purespectrum_reversed_scale_computes_scale_direction():
    """Reversed coding, mirroring tests/fixtures/reversed_scale.py: code 1
    = top-box label ('Strongly Agree'), code 5 = bottom-box label
    ('Strongly Disagree'). Direction must be resolved from the label
    meaning, not code magnitude, giving descending."""
    codebook_ws = _FakeWorksheet([
        ("[Q3]: How satisfied are you with the product?", None, None),
        ("Values: 1-5", None, None),
        (None, 1, "Strongly Agree"),
        (None, 2, "Agree"),
        (None, 3, "Neither Agree Nor Disagree"),
        (None, 4, "Disagree"),
        (None, 5, "Strongly Disagree"),
        (None, None, None),
    ])
    questions = parse_codebook(codebook_ws)
    q3 = next(q for q in questions if q.qid == "Q3")
    assert q3.qtype.name == "scale"
    assert q3.scale_direction == "descending"
