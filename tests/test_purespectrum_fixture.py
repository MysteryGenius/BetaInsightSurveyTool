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

Round A, prompt A1: Q9 is no longer in this set either. Before A1, the
Datamap reader silently absorbed Q10's unbracketed block into Q9 (Q10's
header line "Q10: ..." has no brackets, so the old reader's strict
"[qid]:"-only header rule never recognised it as a new block), leaving Q9
with 6 codes (its real 4 plus Q10's "Unchecked"/"Checked" pair) including a
duplicate code 1 ("Very worried" vs "Checked") that made it fail scale
classification. A1 fixed the header rule to also recognise an unbracketed
"qid: text" line as a block header when the next non-blank line is a
"Values:"/open-response marker, so Q10 is now parsed as its own block and
Q9 classifies cleanly as a 4-code `worry` scale.
"""
from pathlib import Path

import pytest

_ROOT = Path(__file__).parent.parent
_PURESPECTRUM_PATH = _ROOT / "purespectrum_survey_wcs_data.xlsx"

# The exact set of questions Task 3's report says remain unmatched against
# the real fixture after scales.yaml was extended. D2 was in this set before
# Task 9 mapped age_band for PureSpectrum; it is now a declared demographic
# (like D1/D3) and no longer appears here. Q9 was in this set only because of
# the A1 Datamap-parsing bug described above; with that fixed it classifies
# as a scale and is no longer unresolved.
#
# Round A prompt A4: Q1, Q3, and Q6 are also no longer in this set. All
# three are genuinely categorical (a 3-way awareness question, a view with
# "No view/preference", and a yes/yes/no effort question) with no evidence
# of being ordinal — no label matches a scale pattern, and no not-/un-
# polarity pair exists in any of their label sets. A4 classifies them as
# `categorical` directly at load time instead of queueing them for the
# resolver, since presenting a question that was never going to be a scale
# in the same panel as a genuine miss (like the real A1/A3 defects) trains
# an analyst to click through it without looking. D5 (fluency) is the sole
# survivor: it fails the same two signals but is a deliberate, named
# exception (see validate_questions._GRANDFATHERED_RESOLVER_CANDIDATES) —
# its labels carry a descriptive suffix a future suffix-tolerant matching
# pass would resolve, out of scope for Round A.
_EXPECTED_UNRESOLVED = {"D5"}


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
    # Round A prompt A4: Q1, Q3, Q6 are genuinely categorical (no scale
    # evidence at all) and must classify directly, never reach the
    # resolver queue.
    assert "Q1" not in variables
    assert "Q3" not in variables
    assert "Q6" not in variables


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


@pytest.mark.skipif(
    not _PURESPECTRUM_PATH.exists(),
    reason="purespectrum_survey_wcs_data.xlsx not found in project root — awaiting client fixture.",
)
def test_purespectrum_q4_neutral_dont_know_label_stays_neutral_on_real_load():
    """Final-review Finding 2 regression, at the real load() level (not just
    the is_nonsubstantive_label unit level): PureSpectrum's real Q4 label
    "Neutral/don't know enough to say" (curly apostrophe) must resolve to
    CodeRole.neutral, not CodeRole.nonsubstantive, on BOTH the CLI-equivalent
    default path (nonsubstantive_labels=None) and the desktop app's real
    configured-list path (ToolConfig()'s default nonsubstantive_labels) — so
    the two entry points can't silently disagree on Q4's base."""
    from datetime import datetime, timezone

    from surveytool.core.config import ToolConfig
    from surveytool.core.model import CodeRole
    from surveytool.ingest.overrides import QuestionOverride
    from surveytool.ingest.purespectrum import load

    now = datetime.now(timezone.utc)
    overrides = {
        variable: QuestionOverride(
            variable=variable, question_type="categorical", label_roles={},
            resolved_at=now, library_version="test",
        )
        for variable in _EXPECTED_UNRESOLVED
    }

    def _q4_role(nonsubstantive_labels):
        survey = load(_PURESPECTRUM_PATH, "wcs", overrides, nonsubstantive_labels)
        q4 = next(q for q in survey.questions if q.qid == "Q4")
        neutral_label = next(sc for sc in q4.labels if "don" in sc.label.lower())
        return neutral_label.role

    assert _q4_role(None) is CodeRole.neutral
    assert _q4_role(ToolConfig().nonsubstantive_labels) is CodeRole.neutral


@pytest.mark.skipif(
    not _PURESPECTRUM_PATH.exists(),
    reason="purespectrum_survey_wcs_data.xlsx not found in project root — awaiting client fixture.",
)
def test_purespectrum_datamap_finds_29_blocks():
    """Round A prompt A1 acceptance: the Datamap reader finds 29 question
    blocks in the real fixture, not the pre-fix 27 — Q10 and D4 write their
    block headers without brackets ("Q10: ...", "D4: ...") and were
    previously absorbed into the preceding block (Q9, QC2Flag) instead of
    starting new ones."""
    import openpyxl

    from surveytool.ingest.datamap_reader import DatamapReader
    from surveytool.ingest.vendor_profile import PURESPECTRUM_PROFILE

    wb = openpyxl.load_workbook(_PURESPECTRUM_PATH, read_only=True, data_only=True)
    try:
        ws = wb[PURESPECTRUM_PROFILE.codebook_sheet]
        col0_lines = []
        for row in ws.iter_rows(values_only=True):
            col0 = row[0] if len(row) > 0 else None
            if col0 and isinstance(col0, str) and col0.strip():
                col0_lines.append(col0.strip())
    finally:
        wb.close()

    def _is_marker(cell: str) -> bool:
        return cell.startswith("Values:") or cell.startswith("Open numeric") or cell.startswith("Open text")

    headers = sum(
        1
        for i, cell in enumerate(col0_lines)
        if not _is_marker(cell) and i + 1 < len(col0_lines) and _is_marker(col0_lines[i + 1])
    )
    assert headers == 29


@pytest.mark.skipif(
    not _PURESPECTRUM_PATH.exists(),
    reason="purespectrum_survey_wcs_data.xlsx not found in project root — awaiting client fixture.",
)
def test_purespectrum_q9_and_qc2flag_no_longer_absorb_q10_and_d4_rows():
    """Round A prompt A1 acceptance: Q9 has exactly its own 4 labels (the
    `worry` scale) and classifies without an override; QC2Flag has exactly
    its own 2 labels (Pass/Fail). Before A1, Q9 absorbed Q10's "Unchecked"/
    "Checked" pair (6 labels, duplicate code 1) and QC2Flag absorbed D4's."""
    from surveytool.ingest.purespectrum import load

    overrides = _overrides_for(_EXPECTED_UNRESOLVED)
    survey = load(_PURESPECTRUM_PATH, "wcs", overrides)

    q9 = next(q for q in survey.questions if q.qid == "Q9")
    assert [sc.label for sc in q9.labels] == [
        "Very worried", "Somewhat worried", "Not very worried", "Not worried at all",
    ]
    assert q9.qtype.value == "scale"
    assert q9.scale_family == "worry"

    assert not any(q.qid == "QC2Flag" for q in survey.questions)


@pytest.mark.skipif(
    not _PURESPECTRUM_PATH.exists(),
    reason="purespectrum_survey_wcs_data.xlsx not found in project root — awaiting client fixture.",
)
def test_purespectrum_q10_and_d4_built_as_multi_select_with_real_labels():
    """Round A prompt A1 acceptance: Q10 is a multi-select with 8 options
    backed by Q10r1..Q10r8, D4 is a multi-select with 7 options backed by
    D4r1..D4r7, and both carry the Datamap's real vendor-supplied option
    labels rather than the pre-fix column-name placeholders."""
    from surveytool.core.model import QuestionType
    from surveytool.ingest.purespectrum import load

    overrides = _overrides_for(_EXPECTED_UNRESOLVED)
    survey = load(_PURESPECTRUM_PATH, "wcs", overrides)

    q10 = next(q for q in survey.questions if q.qid == "Q10")
    assert q10.qtype is QuestionType.multi_response
    assert [sc.code for sc in q10.labels] == [f"Q10r{i}" for i in range(1, 9)]
    assert all(label not in (f"Q10r{i}" for i in range(1, 9)) for label in (sc.label for sc in q10.labels))
    assert q10.labels[0].label == "Loss of language / dialect itself"

    d4 = next(q for q in survey.questions if q.qid == "D4")
    assert d4.qtype is QuestionType.multi_response
    assert [sc.code for sc in d4.labels] == [f"D4r{i}" for i in range(1, 8)]
    assert d4.labels[0].label == "Hokkien"

    n_q10_responses = sum(1 for r in survey.responses if r.qid == "Q10")
    n_d4_responses = sum(1 for r in survey.responses if r.qid == "D4")
    assert n_q10_responses == survey.n_raw
    assert n_d4_responses == survey.n_raw


def _overrides_for(variables):
    from datetime import datetime, timezone

    from surveytool.ingest.overrides import QuestionOverride

    now = datetime.now(timezone.utc)
    return {
        variable: QuestionOverride(
            variable=variable, question_type="categorical", label_roles={},
            resolved_at=now, library_version="test",
        )
        for variable in variables
    }
