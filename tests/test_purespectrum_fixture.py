"""
PureSpectrum real-file integration tests (spec Prompt 9).

Task 5: a real, override-free load of this fixture now legitimately raises
UnresolvedQuestionsError for Q1, Q3, Q6, Q9, and D5 — the questions Task 3's
scale-library extension left unmatched (see that task's report). This
replaces the old test_purespectrum_real_file_loads_and_classifies_all_42_columns,
which called load() with no overrides and then unconditionally skipped itself
before asserting anything about the 42-column shape — a hard-coded skip
left over from before the fixture arrived, never updated once it did. That
test's implicit premise ("this loads cleanly") was the exact silent
categorical-fallback behaviour this task deletes, so it is rewritten here
to assert the real (and correct) behaviour instead of the old bug.

Task 9: D2 (age) is no longer in this set. vendor_purespectrum.yaml now maps
age_band to D2 (10 real codes folding into the 6 reachable canonical bands,
with under_18 declared not_collected — D2's codebook genuinely has no
under-18 band, verified directly from the Datamap sheet), so D2 is a
declared demographic source_column and exempt from the collector, the same
as D1/D3 already were.
"""
from pathlib import Path

import pytest

_ROOT = Path(__file__).parent.parent
_PURESPECTRUM_PATH = _ROOT / "purespectrum_survey_wcs_data.xlsx"

# The exact set of questions Task 3's report says remain unmatched against
# the real fixture after scales.yaml was extended. D2 was in this set before
# Task 9 mapped age_band for PureSpectrum; it is now a declared demographic
# (like D1/D3) and no longer appears here.
_EXPECTED_UNRESOLVED = {"Q1", "Q3", "Q6", "Q9", "D5"}


@pytest.mark.skipif(
    not _PURESPECTRUM_PATH.exists(),
    reason="purespectrum_survey_wcs_data.xlsx not found in project root — awaiting client fixture.",
)
def test_purespectrum_real_file_raises_unresolved_for_still_unmatched_questions():
    from surveytool.charts.errors import UnresolvedQuestionsError
    from surveytool.ingest.purespectrum import load

    with pytest.raises(UnresolvedQuestionsError) as exc_info:
        load(_PURESPECTRUM_PATH, "wcs")

    variables = {e.variable for e in exc_info.value.detail_entries}
    assert variables == _EXPECTED_UNRESOLVED

    # D1 (ethnicity), D2 (age_band, Task 9), and D3 (gender) are declared
    # demographics in vendor_purespectrum.yaml and must never appear in the
    # resolver.
    assert "D1" not in variables
    assert "D2" not in variables
    assert "D3" not in variables
    # QC2/QC2Flag are quality columns, excluded from question-building
    # entirely before classification ever runs.
    assert "QC2" not in variables
    assert "QC2Flag" not in variables


@pytest.mark.skipif(
    not _PURESPECTRUM_PATH.exists(),
    reason="purespectrum_survey_wcs_data.xlsx not found in project root — awaiting client fixture.",
)
def test_purespectrum_resolving_every_collected_question_loads_cleanly():
    """Acceptance demonstration: writing a categorical override for every
    question Task 5's collector raised on, then re-running the same load,
    must produce a clean load with no error — the override persists the
    analyst's one-time decision."""
    from datetime import datetime, timezone

    from surveytool.ingest.overrides import QuestionOverride
    from surveytool.ingest.purespectrum import load

    now = datetime.now(timezone.utc)
    overrides = {
        variable: QuestionOverride(
            variable=variable,
            question_type="categorical",
            label_roles={},
            resolved_at=now,
            library_version="test",
        )
        for variable in _EXPECTED_UNRESOLVED
    }

    survey = load(_PURESPECTRUM_PATH, "wcs", overrides)  # must not raise
    assert survey.n_raw > 0

    resolved_qids = {q.qid for q in survey.questions if q.qid in _EXPECTED_UNRESOLVED}
    assert resolved_qids == _EXPECTED_UNRESOLVED
    for q in survey.questions:
        if q.qid in _EXPECTED_UNRESOLVED:
            assert q.qtype.value == "categorical"


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
