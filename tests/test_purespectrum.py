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
