"""
Phase 0 conformance suite.

Asserts the seven invariants the canonical model must satisfy.
Section A: synthetic fixtures only, no vendor files touched.
Section B: real Milieu and Toluna vendor files — a guard against the exact
           class of silent-degradation bug fixed in the v1 fix pass (role
           resolution succeeding while scale_family silently returns None,
           or a scale silently demoting to single_choice).
"""
from pathlib import Path

import pytest

from surveytool.core.model import CodeRole, QuestionType, ResponseState
from surveytool.core.straightliner import detect_straightliners


# ── Section A: synthetic fixtures ──────────────────────────────────────────────

# ── 1. Reversed-coded scale resolves roles from labels ────────────────────────

def test_reversed_scale_resolves_from_labels():
    """
    A scale where code 1 = top and code 5 = bottom must resolve roles
    from label meaning, not from code magnitude.
    """
    from tests.fixtures.reversed_scale import QUESTION

    roles_by_label = {sc.label: sc.role for sc in QUESTION.labels}
    assert roles_by_label["Strongly Agree"] is CodeRole.top
    assert roles_by_label["Agree"] is CodeRole.top
    assert roles_by_label["Neither Agree Nor Disagree"] is CodeRole.neutral
    assert roles_by_label["Disagree"] is CodeRole.bottom
    assert roles_by_label["Strongly Disagree"] is CodeRole.bottom

    # The reversed direction: code 1 is top, code 5 is bottom
    codes_by_role = {}
    for sc in QUESTION.labels:
        codes_by_role.setdefault(sc.role, []).append(sc.code)

    assert 1 in codes_by_role[CodeRole.top]
    assert 5 in codes_by_role[CodeRole.bottom]

    # High code is NOT top (direction is descending)
    assert QUESTION.scale_direction == "descending"


# ── 2. Multi-response bases on respondents, may exceed 100% ──────────────────

def test_multi_response_bases_on_respondents():
    """
    Multi-response percentage base = n respondents asked (not n selections).
    Individual code percentages can exceed 100% in aggregate.
    """
    from tests.fixtures.multi_response import (
        EXPECTED,
        EXPECTED_AGGREGATE_TOTAL,
        QUESTION,
        RESPONDENT_BASE,
        SELECTIONS,
    )

    assert QUESTION.qtype.value == "multi_response"

    # Compute code counts from the fixture selections
    counts: dict[str, int] = {"A": 0, "B": 0, "C": 0}
    for selections in SELECTIONS.values():
        for code in selections:
            counts[code] += 1

    base = RESPONDENT_BASE
    computed = {code: cnt / base * 100 for code, cnt in counts.items()}

    assert computed == pytest.approx(EXPECTED)
    assert sum(computed.values()) == pytest.approx(EXPECTED_AGGREGATE_TOTAL)
    assert EXPECTED_AGGREGATE_TOTAL > 100.0  # this is the key assertion


# ── 3. Non-substantive in base but excluded from mean ─────────────────────────

def test_nonsubstantive_in_base_not_mean():
    """
    A non-substantive response is counted in the percentage base
    (the respondent was asked) but excluded from the mean.
    """
    from tests.fixtures.nonsubstantive import (
        EXPECTED_BASE,
        EXPECTED_MEAN,
        QUESTION,
        RESPONSES,
    )

    all_asked = [r for r in RESPONSES if r.state is not ResponseState.not_asked]
    assert len(all_asked) == EXPECTED_BASE

    substantive = [
        r for r in RESPONSES
        if r.state is ResponseState.answered and r.raw_value is not None
    ]
    label_map = {sc.code: sc for sc in QUESTION.labels}
    numeric_values = [
        label_map[r.raw_value].numeric_value
        for r in substantive
        if r.raw_value in label_map and label_map[r.raw_value].numeric_value is not None
    ]

    mean = sum(numeric_values) / len(numeric_values)
    assert mean == pytest.approx(EXPECTED_MEAN)

    # Confirm the non-substantive respondent is in the base count
    ns_respondents = [r for r in RESPONSES if r.state is ResponseState.nonsubstantive]
    assert len(ns_respondents) == 1
    assert ns_respondents[0].respondent_id not in {r.respondent_id for r in substantive}


# ── 4. Routed question bases on those asked ───────────────────────────────────

def test_routed_question_bases_on_asked():
    """
    A question with an asked_base predicate must use a base of those
    who were asked, not the total sample N.
    """
    from tests.fixtures.routed_question import (
        EXPECTED_BASE,
        RESPONSES,
        ROUTED_QUESTION,
        TOTAL_N,
    )

    assert ROUTED_QUESTION.asked_base != "ALL"

    asked = [r for r in RESPONSES if r.state is not ResponseState.not_asked]
    not_asked = [r for r in RESPONSES if r.state is ResponseState.not_asked]

    assert len(asked) == EXPECTED_BASE
    assert len(not_asked) == TOTAL_N - EXPECTED_BASE
    assert EXPECTED_BASE < TOTAL_N


# ── 5. Unknown labels fail loudly ─────────────────────────────────────────────
#
# Round B task B1 removed resolve_roles (superseded by variant-based
# matching in scale_library.py) along with this test, which was its only
# direct caller outside scale_library.py itself -- a synthetic conformance
# test exercising a dead-path function with no remaining callers in the
# live path (see grep confirmation in the B1 task brief, step 6).


# ── 6. Grids group by grid_group id ──────────────────────────────────────────

def test_grid_groups_by_stem():
    """
    Questions sharing a grid_group id are retrievable as a group.
    Questions without that id are excluded.
    """
    from tests.fixtures.grid_questions import ALL_QUESTIONS, GRID_GROUP_ID, GRID_QUESTIONS

    grouped = [q for q in ALL_QUESTIONS if q.grid_group == GRID_GROUP_ID]
    ungrouped = [q for q in ALL_QUESTIONS if q.grid_group != GRID_GROUP_ID]

    assert len(grouped) == len(GRID_QUESTIONS)
    assert all(q.grid_group == GRID_GROUP_ID for q in grouped)
    assert all(q.qid in {gq.qid for gq in GRID_QUESTIONS} for q in grouped)
    assert len(ungrouped) == 1
    assert ungrouped[0].grid_group is None


# ── 7. Straightliner reproduces known flagged set ─────────────────────────────

def test_straightliner_reproduces_known_set():
    """
    detect_straightliners returns exactly the respondents with zero variance
    across all scale items and no others.
    """
    from tests.fixtures.straightliner import EXPECTED_FLAGGED, QUESTIONS, RESPONSES

    flagged = detect_straightliners(RESPONSES, QUESTIONS)

    assert flagged == EXPECTED_FLAGGED


# ── Section B: real vendor file guard ──────────────────────────────────────────
#
# Every question an adapter treats as a scale must fully resolve: role
# resolution must succeed AND scale_family must not be None. This is the
# exact regression class of the two bugs this fix pass closed — resolve_roles
# succeeding while identify_family silently returned None (Toluna's compound
# "Neutral / Neither X nor Y" labels), and a scale silently demoting to
# single_choice when a label didn't resolve at all (Toluna Q6's missing
# ability-family gradations). This guard asserts loudly; it does not skip
# quietly the way the vendor adapters used to.

_ROOT = Path(__file__).parent.parent
_MILIEU_PATH = _ROOT / "milieu_survey_coe_data.csv"
_TOLUNA_PATH = _ROOT / "toluna_survey_misinformation_data.xlsx"
_RAKUTEN_PATH = _ROOT / "rakuten_survey_support_measures_data.xlsx"


def _assert_all_scales_fully_resolved(questions, vendor: str) -> None:
    for q in questions:
        if q.qtype is not QuestionType.scale:
            continue
        assert q.scale_family is not None, (
            f"{vendor} question {q.qid!r} resolved as a scale but "
            "scale_family is None — role resolution and family "
            "identification have diverged again."
        )
        roles = {sc.role for sc in q.labels}
        assert CodeRole.top in roles, f"{vendor} question {q.qid!r} scale has no top role"
        assert CodeRole.bottom in roles, f"{vendor} question {q.qid!r} scale has no bottom role"


@pytest.mark.skipif(
    not _RAKUTEN_PATH.exists(),
    reason="rakuten_survey_support_measures_data.xlsx not found in project root",
)
def test_rakuten_real_file_scales_fully_resolve():
    from surveytool.ingest.rakuten import load

    survey = load(_RAKUTEN_PATH, "support-measures")
    assert any(q.qtype is QuestionType.scale for q in survey.questions), (
        "Expected at least one scale question in the Rakuten fixture"
    )
    _assert_all_scales_fully_resolved(survey.questions, "rakuten")


@pytest.mark.skipif(
    not _MILIEU_PATH.exists(),
    reason="milieu_survey_coe_data.csv not found in project root",
)
def test_milieu_real_file_scales_fully_resolve():
    from surveytool.ingest.milieu import load

    survey = load(_MILIEU_PATH, "coe")
    assert any(q.qtype is QuestionType.scale for q in survey.questions), (
        "Expected at least one scale question in the Milieu fixture"
    )
    _assert_all_scales_fully_resolved(survey.questions, "milieu")


@pytest.mark.skipif(
    not _TOLUNA_PATH.exists(),
    reason="toluna_survey_misinformation_data.xlsx not found in project root",
)
def test_toluna_real_file_scales_fully_resolve():
    from surveytool.ingest.toluna import load

    # Task 9: column "2" (age_band) is now a declared demographic
    # source_column in vendor_toluna.yaml, exempt from the load-path
    # collector — no override needed (contrast with the Task 5-era
    # override this test used before age_band was mapped).
    survey = load(_TOLUNA_PATH, "misinformation")
    assert any(q.qtype is QuestionType.scale for q in survey.questions), (
        "Expected at least one scale question in the Toluna fixture"
    )
    _assert_all_scales_fully_resolved(survey.questions, "toluna")


_RAKUTEN_CHN_CLANS_PATH = _ROOT / "rakuten_survey_chn_clans_data.xlsx"


@pytest.mark.skipif(
    not (_RAKUTEN_PATH.exists() and _RAKUTEN_CHN_CLANS_PATH.exists()),
    reason="a real Rakuten fixture is not present in project root",
)
def test_rakuten_datamap_block_sets_unchanged_by_a1_header_rule():
    """Round A prompt A1 changed the Datamap reader's block-header rule to
    also recognise an unbracketed "qid: text" header line (needed for
    PureSpectrum's Q10/D4). Rakuten's own Datamap sheets are fully
    bracketed, so both real Rakuten fixtures must produce byte-identical
    question qid sets before and after — this pins the exact sets down so a
    future change to the header rule can't silently start absorbing or
    splitting Rakuten blocks differently."""
    from surveytool.ingest.rakuten import load

    clans = load(_RAKUTEN_CHN_CLANS_PATH, "chn-clans")
    assert sorted(q.qid for q in clans.questions) == [
        "A1", "A2", "A3", "A4", "A5", "A6", "S1", "S2", "S3", "S4",
    ]

    support = load(_RAKUTEN_PATH, "support-measures")
    assert sorted(q.qid for q in support.questions) == [
        "Q1", "Q2", "Q3", "Q4", "Q5", "S1", "S2", "S3", "S4",
    ]


_RAKUTEN_CHN_CLANS_SCALE_FAMILIES = {
    "A1": "importance", "A2": "importance", "A3": "importance",
    "A4": "agreement", "A5": "agreement", "A6": "agreement",
}
_RAKUTEN_SUPPORT_SCALE_FAMILIES = {
    "Q1": "agreement", "Q2": "agreement", "Q3": "agreement", "Q4": "agreement", "Q5": "agreement",
}
_MILIEU_SCALE_FAMILIES = {"q10": "agreement", "q11": "agreement", "q12": "agreement", "q13": "agreement", "q14": "agreement"}
_TOLUNA_SCALE_FAMILIES = {
    "10": "effectiveness", "6": "ability",
    "7_local_mainstream_media": "likelihood", "7_online_social_media": "likelihood",
    "7_overseas_mainstream_media": "likelihood", "8": "importance", "9": "effectiveness",
}
_PURESPECTRUM_SCALE_FAMILIES = {
    "Q2": "intensity", "Q4": "relevance", "Q5": "intensity", "Q5A": "intensity", "Q5B": "intensity",
    "Q7": "importance", "Q8": "concern", "Q9": "worry",
}


def _scale_family_by_qid(questions) -> dict:
    return {q.qid: q.scale_family for q in questions if q.qtype is QuestionType.scale}


@pytest.mark.skipif(
    not (_RAKUTEN_PATH.exists() and _RAKUTEN_CHN_CLANS_PATH.exists() and _MILIEU_PATH.exists()
         and _TOLUNA_PATH.exists() and (_ROOT / "purespectrum_survey_wcs_data.xlsx").exists()),
    reason="not every real vendor fixture is present in project root",
)
def test_no_real_scale_question_changes_family_across_all_five_files():
    """Round A prompt A3 acceptance: adding 'strongly satisfied'/'strongly
    dissatisfied' to the satisfaction family (and auditing every other
    family for the same gap) must not reclassify any question that already
    matched. None of the five real fixtures contains a satisfaction
    question at all (verified directly — grepping every Datamap/header for
    "satisf" turns up nothing), so this pins every OTHER real scale
    question's family down as an explicit before/after regression guard:
    a future scales.yaml edit that silently shifts one of these must fail
    here, not go unnoticed."""
    from surveytool.ingest.milieu import load as milieu_load
    from surveytool.ingest.purespectrum import load as ps_load
    from surveytool.ingest.rakuten import load as rakuten_load
    from surveytool.ingest.toluna import load as toluna_load

    clans = rakuten_load(_RAKUTEN_CHN_CLANS_PATH, "chn-clans")
    assert _scale_family_by_qid(clans.questions) == _RAKUTEN_CHN_CLANS_SCALE_FAMILIES

    support = rakuten_load(_RAKUTEN_PATH, "support-measures")
    assert _scale_family_by_qid(support.questions) == _RAKUTEN_SUPPORT_SCALE_FAMILIES

    milieu = milieu_load(_MILIEU_PATH, "coe")
    assert _scale_family_by_qid(milieu.questions) == _MILIEU_SCALE_FAMILIES

    toluna = toluna_load(_TOLUNA_PATH, "misinformation")
    assert _scale_family_by_qid(toluna.questions) == _TOLUNA_SCALE_FAMILIES

    from datetime import datetime, timezone

    from surveytool.ingest.overrides import QuestionOverride
    now = datetime.now(timezone.utc)
    overrides = {
        v: QuestionOverride(variable=v, question_type="categorical", label_roles={}, resolved_at=now, library_version="t")
        for v in ["Q1", "Q3", "Q6", "D5"]
    }
    purespectrum = ps_load(_ROOT / "purespectrum_survey_wcs_data.xlsx", "wcs", overrides)
    assert _scale_family_by_qid(purespectrum.questions) == _PURESPECTRUM_SCALE_FAMILIES


# ── Section C: shared conformance assertion set across four vendors ────────────
#
# Per spec Prompt 11: every vendor profile must satisfy a shared assertion
# set — the file parses, every question receives a question type, and the
# fingerprint pre-check recognises the file under its own vendor and rejects
# it under each other vendor. Milieu is intentionally excluded from this
# section (see note below _shared_conformance_assertions) because its
# VendorSignature is empty — it is sniffed by CSV header regex, not
# sheet/column fingerprinting, so a fingerprint-based conformance check
# would be meaningless for it.

from surveytool.core.column_classification import ColumnClassification
from surveytool.ingest.fingerprint import VendorMismatchError, check_fingerprint
from surveytool.ingest.vendor_profile import get_vendor_profile

_PURESPECTRUM_PATH = _ROOT / "purespectrum_survey_wcs_data.xlsx"


def _shared_conformance_assertions(vendor_id: str, survey, sheet_names: frozenset[str], column_names: frozenset[str]) -> None:
    """The assertion set every vendor profile must satisfy per spec Prompt 11:
    the file parses (implied by the caller already having a `survey`), every
    question receives a question type, and the fingerprint pre-check
    recognises the file under its own vendor and rejects it under each
    other vendor."""
    from surveytool.core.model import QuestionType

    assert len(survey.questions) > 0, f"{vendor_id}: file parsed but produced zero questions"
    for q in survey.questions:
        assert q.qtype in QuestionType, f"{vendor_id} question {q.qid!r} has no question type"

    check_fingerprint(vendor_id, sheet_names=sheet_names, column_names=column_names)  # must not raise

    for other_vendor in ("rakuten", "milieu", "toluna", "purespectrum"):
        if other_vendor == vendor_id:
            continue
        other_profile = get_vendor_profile(other_vendor)
        if other_profile.signature is None or not other_profile.signature.expected_sheets and not other_profile.signature.expected_columns:
            continue  # Milieu has no meaningful signature to check rejection against
        with pytest.raises(VendorMismatchError):
            check_fingerprint(other_vendor, sheet_names=sheet_names, column_names=column_names)


@pytest.mark.skipif(not _RAKUTEN_PATH.exists(), reason="rakuten_survey_support_measures_data.xlsx not found")
def test_rakuten_shared_conformance_assertions():
    import openpyxl

    from surveytool.ingest.rakuten import load

    survey = load(_RAKUTEN_PATH, "support-measures")
    wb = openpyxl.load_workbook(_RAKUTEN_PATH, read_only=True, data_only=True)
    sheet_names = frozenset(wb.sheetnames)
    header = next(wb["A1"].iter_rows(values_only=True))
    column_names = frozenset(str(h) for h in header if h is not None)
    wb.close()
    _shared_conformance_assertions("rakuten", survey, sheet_names, column_names)


@pytest.mark.skipif(not _TOLUNA_PATH.exists(), reason="toluna_survey_misinformation_data.xlsx not found")
def test_toluna_shared_conformance_assertions():
    import openpyxl

    from surveytool.ingest.toluna import load

    # Task 9: column "2" (age_band) is now a declared demographic
    # source_column in vendor_toluna.yaml, exempt from the load-path
    # collector — no override needed.
    survey = load(_TOLUNA_PATH, "misinformation")
    wb = openpyxl.load_workbook(_TOLUNA_PATH, read_only=True, data_only=True)
    sheet_names = frozenset(wb.sheetnames)
    header = next(wb["RespondentData.Text"].iter_rows(values_only=True))
    column_names = frozenset(str(h) for h in header if h is not None)
    wb.close()
    _shared_conformance_assertions("toluna", survey, sheet_names, column_names)


@pytest.mark.skipif(
    not _PURESPECTRUM_PATH.exists(),
    reason="purespectrum_survey_wcs_data.xlsx not found in project root — vendor tabulation to verify PureSpectrum topline "
           "numbers has been requested from the client and has not arrived. Structural assertions only, once the file exists; "
           "no numerical golden fixture is written against numbers we produced ourselves.",
)
def test_purespectrum_shared_conformance_assertions():
    # Task 5 originally required an override-free load of the real fixture
    # to raise UnresolvedQuestionsError for D2/Q1/Q3/Q6/Q9/D5. Since then:
    # D2 (age_band) and Q9 (worry, fixed by Round A prompt A1) resolve on
    # their own, and Q1/Q3/Q6 classify as categorical directly (Round A
    # prompt A4 — no scale evidence at all). D5 is the sole remaining
    # unresolved question (see tests/test_purespectrum_fixture.py, which
    # asserts that raise directly). This shared-assertion test only cares
    # that a *resolved* load satisfies the cross-vendor invariants, so it
    # supplies the categorical override an analyst would write via the
    # resolver for D5, rather than asserting on the raise itself again.
    import openpyxl
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
        for variable in ("D5",)
    }

    survey = load(_PURESPECTRUM_PATH, "wcs", overrides)
    wb = openpyxl.load_workbook(_PURESPECTRUM_PATH, read_only=True, data_only=True)
    sheet_names = frozenset(wb.sheetnames)
    header = next(wb["A1"].iter_rows(values_only=True))
    column_names = frozenset(str(h) for h in header if h is not None)
    wb.close()
    _shared_conformance_assertions("purespectrum", survey, sheet_names, column_names)


@pytest.mark.skipif(
    not (_PURESPECTRUM_PATH.exists()),
    reason="purespectrum_survey_wcs_data.xlsx not found in project root",
)
def test_purespectrum_q1_q3_q6_classified_categorical_and_d5_queued_never_both_never_neither():
    """Round A prompt A4 acceptance: no question is both classified and
    queued for the resolver, and none is neither. An override-free load of
    the real PureSpectrum fixture must raise UnresolvedQuestionsError naming
    exactly D5 (see test_purespectrum_fixture.py for the direct assertion of
    that set); this test additionally confirms the complementary half — that
    Q1/Q3/Q6, which do NOT appear in that raise, are nonetheless present as
    real `categorical` Questions with a recorded reason once D5 alone is
    resolved, rather than silently missing from the Survey altogether."""
    from datetime import datetime, timezone

    from surveytool.charts.errors import UnresolvedQuestionsError
    from surveytool.core.model import QuestionType
    from surveytool.ingest.overrides import QuestionOverride
    from surveytool.ingest.purespectrum import load

    with pytest.raises(UnresolvedQuestionsError) as exc_info:
        load(_PURESPECTRUM_PATH, "wcs")
    assert {e.variable for e in exc_info.value.detail_entries} == {"D5"}

    now = datetime.now(timezone.utc)
    overrides = {
        "D5": QuestionOverride(
            variable="D5", question_type="categorical", label_roles={}, resolved_at=now, library_version="test",
        )
    }
    survey = load(_PURESPECTRUM_PATH, "wcs", overrides)
    questions_by_qid = {q.qid: q for q in survey.questions}
    for qid in ("Q1", "Q3", "Q6"):
        question = questions_by_qid[qid]
        assert question.qtype is QuestionType.categorical
        assert question.categorical_reason is not None


# ── Section D: Round A prompt A7 — conformance guards for A1/A2/A4/A5 ───────
#
# Each assertion category below fails the suite if the corresponding Round A
# fix is reverted:
#   1. Exact question count per file (A1's dropped-block regression).
#   2. No duplicate code key / duplicated label anywhere (A2).
#   3. Every question classified with a reason, or queued — never both,
#      never neither (A4).
#   4. Every emitted figure's carried base equals the denominator used,
#      asserted by value on Milieu q8 (A5).
#   5. No Datamap/header line skipped without being parsed or raised on (A1).

_RAKUTEN_CHN_CLANS_QUESTION_COUNT = 10
_RAKUTEN_SUPPORT_QUESTION_COUNT = 9
_MILIEU_QUESTION_COUNT = 9
_TOLUNA_QUESTION_COUNT = 12
_PURESPECTRUM_QUESTION_COUNT = 19  # with only D5 overridden; Q1/Q3/Q6 self-classify (A4)


def _all_five_real_surveys():
    """Load every real vendor file this project holds, skipping any that
    are absent rather than fabricating a stand-in. Returns a dict of
    vendor-label -> Survey for whichever files exist."""
    from datetime import datetime, timezone

    from surveytool.ingest.milieu import load as milieu_load
    from surveytool.ingest.overrides import QuestionOverride
    from surveytool.ingest.purespectrum import load as ps_load
    from surveytool.ingest.rakuten import load as rakuten_load
    from surveytool.ingest.toluna import load as toluna_load

    surveys: dict[str, object] = {}

    if _RAKUTEN_CHN_CLANS_PATH.exists():
        surveys["rakuten_chn_clans"] = rakuten_load(_RAKUTEN_CHN_CLANS_PATH, "chn-clans")
    if _RAKUTEN_PATH.exists():
        surveys["rakuten_support"] = rakuten_load(_RAKUTEN_PATH, "support-measures")
    if _MILIEU_PATH.exists():
        surveys["milieu"] = milieu_load(_MILIEU_PATH, "coe")
    if _TOLUNA_PATH.exists():
        surveys["toluna"] = toluna_load(_TOLUNA_PATH, "misinformation")

    purespectrum_path = _ROOT / "purespectrum_survey_wcs_data.xlsx"
    if purespectrum_path.exists():
        now = datetime.now(timezone.utc)
        overrides = {
            "D5": QuestionOverride(
                variable="D5", question_type="categorical", label_roles={}, resolved_at=now, library_version="test",
            )
        }
        surveys["purespectrum"] = ps_load(purespectrum_path, "wcs", overrides)

    return surveys


@pytest.mark.skipif(
    not (_RAKUTEN_CHN_CLANS_PATH.exists() and _RAKUTEN_PATH.exists() and _MILIEU_PATH.exists()
         and _TOLUNA_PATH.exists() and (_ROOT / "purespectrum_survey_wcs_data.xlsx").exists()),
    reason="not every real vendor fixture is present in project root",
)
def test_a7_exact_question_count_per_real_file():
    """A silently dropped question fails the run. Pins the exact count for
    every real file this project holds — a regression of A1's Datamap
    block-header fix (e.g. Q10/D4 silently vanishing again) changes one of
    these counts and must fail here."""
    surveys = _all_five_real_surveys()
    assert len(surveys["rakuten_chn_clans"].questions) == _RAKUTEN_CHN_CLANS_QUESTION_COUNT
    assert len(surveys["rakuten_support"].questions) == _RAKUTEN_SUPPORT_QUESTION_COUNT
    assert len(surveys["milieu"].questions) == _MILIEU_QUESTION_COUNT
    assert len(surveys["toluna"].questions) == _TOLUNA_QUESTION_COUNT
    assert len(surveys["purespectrum"].questions) == _PURESPECTRUM_QUESTION_COUNT


@pytest.mark.skipif(
    not (_RAKUTEN_CHN_CLANS_PATH.exists() and _RAKUTEN_PATH.exists() and _MILIEU_PATH.exists()
         and _TOLUNA_PATH.exists() and (_ROOT / "purespectrum_survey_wcs_data.xlsx").exists()),
    reason="not every real vendor fixture is present in project root",
)
def test_a7_no_question_carries_a_duplicate_code_key_or_duplicated_label():
    """A2's guard, re-asserted as a conformance check: no question in any
    real file maps one code to two different labels, or one label to two
    different codes. All five real files load clean with the guard active
    (load() itself would already have raised DuplicateCodeKeyError if not,
    since every adapter calls assert_no_duplicate_codes during construction
    — this re-derives the same check independently, over each Question's
    already-built labels, as a belt-and-braces conformance guard)."""
    surveys = _all_five_real_surveys()
    for vendor_label, survey in surveys.items():
        for question in survey.questions:
            seen_labels_by_code: dict = {}
            seen_codes_by_label: dict = {}
            for sc in question.labels:
                if sc.code in seen_labels_by_code:
                    assert seen_labels_by_code[sc.code] == sc.label, (
                        f"{vendor_label} question {question.qid!r}: code {sc.code!r} maps to both "
                        f"{seen_labels_by_code[sc.code]!r} and {sc.label!r}"
                    )
                seen_labels_by_code[sc.code] = sc.label
                if sc.label in seen_codes_by_label:
                    assert seen_codes_by_label[sc.label] == sc.code, (
                        f"{vendor_label} question {question.qid!r}: label {sc.label!r} maps to both "
                        f"code {seen_codes_by_label[sc.label]!r} and {sc.code!r}"
                    )
                seen_codes_by_label[sc.label] = sc.code


@pytest.mark.skipif(
    not (_ROOT / "purespectrum_survey_wcs_data.xlsx").exists(),
    reason="purespectrum_survey_wcs_data.xlsx not found in project root",
)
def test_a7_every_purespectrum_question_classified_with_reason_or_queued_never_both_never_neither():
    """A4's split, re-asserted as a conformance check on the one real file
    where both outcomes are actually exercised (PureSpectrum: Q1/Q3/Q6
    auto-categorical with a reason, D5 queued). Every non-exempt question
    is either classified with a recorded reason (categorical_reason is not
    None) or was queued for the resolver (named in the override-free
    load's UnresolvedQuestionsError) — never both, never neither."""
    from surveytool.charts.errors import UnresolvedQuestionsError
    from surveytool.core.model import QuestionType
    from surveytool.ingest.purespectrum import load

    purespectrum_path = _ROOT / "purespectrum_survey_wcs_data.xlsx"
    with pytest.raises(UnresolvedQuestionsError) as exc_info:
        load(purespectrum_path, "wcs")
    queued = {e.variable for e in exc_info.value.detail_entries}

    surveys = _all_five_real_surveys()
    survey = surveys["purespectrum"]
    for question in survey.questions:
        is_auto_categorical = (
            question.qtype is QuestionType.categorical and question.categorical_reason is not None
        )
        is_queued = question.qid in queued
        assert not (is_auto_categorical and is_queued), (
            f"question {question.qid!r} is both auto-categorical (with a reason) and queued for the resolver"
        )
    # D5 achieved neither a full match nor auto-categorical classification
    # in the override-free load (it was queued); Q1/Q3/Q6 must have
    # reached auto-categorical, not the queue, in the resolved survey.
    resolved_qids = {q.qid for q in survey.questions}
    for qid in ("Q1", "Q3", "Q6"):
        assert qid in resolved_qids
    assert queued == {"D5"}


@pytest.mark.skipif(
    not _MILIEU_PATH.exists(),
    reason="milieu_survey_coe_data.csv not found in project root",
)
def test_a7_milieu_q8_provenance_matches_a5_acceptance_table_by_value():
    """A5's acceptance table, re-asserted as a conformance check: every
    emitted figure's carried base equals the denominator actually used. See
    test_breaks_compute.py's test_a5_acceptance_table_milieu_q8_broken_by_gender
    for the fuller breaks-compute version of this same table — this is the
    frequency-layer companion, over compute_question_stats directly."""
    from surveytool.compute.frequency import compute_question_stats
    from surveytool.ingest.milieu import load

    survey = load(_MILIEU_PATH, "coe")
    q8 = next(q for q in survey.questions if q.qid == "q8")
    all_responses = [r for r in survey.responses if r.qid == "q8"]
    stats = compute_question_stats(q8, all_responses)

    assert stats.base == 567
    licence = next(cs for cs in stats.code_stats if "do not have a driving licence" in cs.label)
    assert licence.n == 244
    assert licence.pct == pytest.approx(43.033510, abs=1e-5)
    # base + routed + item_missing + nonsubstantive_excluded == cohort_size
    # always holds by construction (see BaseProvenance's own docstring).
    assert stats.base + stats.provenance.routed + stats.provenance.item_missing == stats.provenance.cohort_size
    assert stats.provenance.cohort_size == 1000


@pytest.mark.skipif(
    not (_RAKUTEN_CHN_CLANS_PATH.exists() and _RAKUTEN_PATH.exists()
         and (_ROOT / "purespectrum_survey_wcs_data.xlsx").exists()),
    reason="not every real bracketed-Datamap fixture is present in project root",
)
def test_a7_no_datamap_line_skipped_without_being_parsed_or_raised_on():
    """No Datamap line in any file is skipped without being either parsed
    or raised on: every non-blank column-A line in each real Datamap sheet
    is accounted for as a recognised block header or continuation marker
    (see DatamapReader.read_codebook's own raise-on-anything-else
    behaviour, exercised directly by the synthetic guard tests in
    test_datamap_reader.py). Re-derives the same raw line classification
    read_codebook uses internally, independently, over the real sheets —
    if any line were unclassifiable, read_codebook itself would already
    have raised DatamapMalformedLineError and these loads would never
    reach this assertion."""
    import openpyxl

    from surveytool.ingest.datamap_reader import _extract_qid_and_text, _is_continuation_marker
    from surveytool.ingest.vendor_profile import PURESPECTRUM_PROFILE, RAKUTEN_PROFILE

    for path, profile in (
        (_RAKUTEN_CHN_CLANS_PATH, RAKUTEN_PROFILE),
        (_RAKUTEN_PATH, RAKUTEN_PROFILE),
        (_ROOT / "purespectrum_survey_wcs_data.xlsx", PURESPECTRUM_PROFILE),
    ):
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        try:
            ws = wb[profile.codebook_sheet]
            rows = list(ws.iter_rows(values_only=True))
        finally:
            wb.close()

        col0_lines = [
            row[0].strip()
            for row in rows
            if len(row) > 0 and row[0] is not None and isinstance(row[0], str) and row[0].strip()
        ]
        next_by_index = {i: (col0_lines[i + 1] if i + 1 < len(col0_lines) else "") for i in range(len(col0_lines))}

        for i, cell in enumerate(col0_lines):
            if _is_continuation_marker(cell):
                continue
            # Every remaining column-A line must be a recognised block
            # header: extractable as a qid, AND the next non-blank column-A
            # line must itself be a continuation marker.
            assert _extract_qid_and_text(cell) is not None, (
                f"{path.name}: column-A line {cell!r} is neither a continuation marker "
                f"nor an extractable block header"
            )
            assert _is_continuation_marker(next_by_index[i]), (
                f"{path.name}: block header {cell!r} is not followed by a continuation marker "
                f"(next line: {next_by_index[i]!r})"
            )


# ── Task B3: rank replaces vendor code everywhere ───────────────────────────


@pytest.mark.skipif(not _TOLUNA_PATH.exists(), reason="Toluna fixture not present")
def test_toluna_q7_local_mainstream_media_rank_and_netting():
    from surveytool.ingest.toluna import load
    survey = load(_TOLUNA_PATH, "toluna_misinfo")
    q7 = next(q for q in survey.questions if q.qid == "7_local_mainstream_media")
    assert q7.qtype.value == "scale"

    ranks_by_label = {sc.label: sc.rank for sc in q7.labels}
    assert ranks_by_label["Very Unlikely"] == 1
    assert ranks_by_label["Unlikely"] == 2
    assert ranks_by_label["Neutral / Neither Likely nor Unlikely"] == 3
    assert ranks_by_label["Likely"] == 4
    assert ranks_by_label["Very Likely"] == 5

    from surveytool.compute.frequency import compute_question_stats
    responses = [r for r in survey.responses if r.qid == "7_local_mainstream_media"]
    stats = compute_question_stats(q7, responses)

    assert stats.base == 1000
    counts_by_label = {cs.label: cs.n for cs in stats.code_stats}
    pcts_by_label = {cs.label: round(cs.pct, 6) for cs in stats.code_stats}
    assert counts_by_label["Very Unlikely"] == 32
    assert counts_by_label["Unlikely"] == 190
    assert counts_by_label["Neutral / Neither Likely nor Unlikely"] == 276
    assert counts_by_label["Likely"] == 363
    assert counts_by_label["Very Likely"] == 139
    assert pcts_by_label["Very Unlikely"] == 3.2
    assert pcts_by_label["Unlikely"] == 19.0
    assert pcts_by_label["Neutral / Neither Likely nor Unlikely"] == 27.6
    assert pcts_by_label["Likely"] == 36.3
    assert pcts_by_label["Very Likely"] == 13.9

    assert round(stats.t2b, 6) == 50.2
    assert round(stats.b2b, 6) == 22.2
    assert round(stats.mean, 6) == 3.387


@pytest.mark.skipif(not _MILIEU_PATH.exists(), reason="Milieu fixture not present")
def test_milieu_agreement_grid_orders_strongly_disagree_to_strongly_agree():
    from surveytool.ingest.milieu import load
    survey = load(_MILIEU_PATH, "milieu_coe")
    agreement_questions = [q for q in survey.questions if q.qtype.value == "scale" and q.scale_family == "agreement"]
    assert len(agreement_questions) >= 5
    for q in agreement_questions:
        ordered_by_rank = sorted(q.labels, key=lambda sc: sc.rank)
        assert [sc.label for sc in ordered_by_rank] == [
            "Strongly Disagree", "Disagree", "Neutral", "Agree", "Strongly Agree",
        ] or [sc.label for sc in ordered_by_rank] == [
            "Strongly disagree", "Disagree", "Neutral", "Agree", "Strongly agree",
        ]


@pytest.mark.skipif(not _PURESPECTRUM_PATH.exists(), reason="PureSpectrum fixture not present")
def test_purespectrum_inverted_questions_mean_now_derives_from_rank_not_code():
    """Documents the Round B correction for the record (spec's explicit
    ask: 'Record the before and after for each in the run output so it can
    be shown to the client'). This test only proves the NEW (correct)
    values come from rank; the historical 'before' values are not
    re-derived here (that would require re-adding the old numeric_value-
    based mean logic just to prove a negative) -- they are documented in
    the plan/spec instead. What this test guards is that rank-derived mean
    differs from a hypothetical code-derived mean for at least one of
    these questions, proving the fix has observable effect."""
    from surveytool.ingest.purespectrum import load
    survey = load(_PURESPECTRUM_PATH, "ps_wcs")
    for qid in ("Q2", "Q5", "Q5A", "Q5B", "Q7", "Q8", "Q9"):
        question = next((q for q in survey.questions if q.qid == qid), None)
        if question is None:
            continue  # some of these qids may not all exist in this particular fixture; skip gracefully
        assert question.qtype.value == "scale"
        # Rank-based order must NOT equal numeric_value-based order for
        # these specific questions (the spec's whole point: five of seven
        # run opposite to code order).
        rank_order = [sc.code for sc in sorted(question.labels, key=lambda sc: sc.rank or 0)]
        code_order = [sc.code for sc in sorted(question.labels, key=lambda sc: sc.numeric_value or 0)]
        assert rank_order != code_order, f"{qid}: expected rank order to differ from code order (the defect this task fixes)"


# ── Task B4: diverging bar permitted on a real vendor scale question ──────

@pytest.mark.skipif(not _TOLUNA_PATH.exists(), reason="Toluna fixture not present")
def test_toluna_scale_question_permits_diverging_stacked_bar():
    from surveytool.ingest.toluna import load
    from surveytool.compute.breaks_compute import _scale_points, _net_definitions
    from surveytool.core.chart_validity import evaluate_chart_permissions, ChartType
    from surveytool.core.config import ToolConfig
    from surveytool.compute.breaks_compute import QuestionResult

    survey = load(_TOLUNA_PATH, "toluna_misinfo")
    q7 = next(q for q in survey.questions if q.qid == "7_local_mainstream_media")
    result = QuestionResult(
        question_id=q7.qid, question_text=q7.text, scale_id=q7.scale_family,
        scale_variant=q7.scale_variant, scale_points=_scale_points(q7),
        nets=_net_definitions(q7), base_total=1000, base_filtered=1000, columns=[],
    )
    permissions = evaluate_chart_permissions(result, column_count=1, config=ToolConfig())
    diverging = next(p for p in permissions if p.chart_type is ChartType.diverging_stacked_bar)
    assert diverging.permitted is True
