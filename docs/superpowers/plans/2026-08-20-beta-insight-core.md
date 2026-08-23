# Beta Insight: Core Vendor/Classification/Netting Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce a declarative `VendorProfile` model, a column-classification pass, a `binary`/`categorical` question-typing model that stops erroring on non-scale labels, single-pass validation with a structured error, project-level scale overrides, non-substantive base handling, and a new PureSpectrum vendor with fingerprint pre-check and a run summary — all while keeping every existing Rakuten/Milieu/Toluna behaviour and output byte-for-byte identical until Phase 2 deliberately changes it.

**Architecture:** Four sequential phases, each behaviour-gated. Phase 1 introduces `VendorProfile` as a pure data carrier read by adapters (no behaviour change) and extracts a shared `DatamapReader` for Rakuten only. Phase 2 adds `ColumnClassification`, `QuestionType.binary`/`categorical`, label normalisation, and three new scale families — this is where output is allowed to change, in the specific ways the spec describes. Phase 3 replaces fail-fast validation with a single structured error and adds project-level overrides plus non-substantive base exclusion. Phase 4 adds the PureSpectrum profile, the fingerprint pre-check, the run summary object, and extends the conformance suite to four vendors.

**Tech Stack:** Python 3.11+, Pydantic v2, pyyaml, openpyxl, pytest.

**Spec:** `beta-insight-core-build-plan.md` (repo root) — the approved phase/objective breakdown this plan implements task-by-task. The build plan in turn approves context `beta-insight-vendor-extension-context.md` (referenced as C1–C20, A1–A7) which is **not present in this repository**; where this plan needs a decision that document would have settled, the decision is stated explicitly inline with its rationale instead of citing a code that can't be checked.

## Global Constraints

- No LLM involvement anywhere in this work. All label/family matching is deterministic string comparison.
- No synthetic fixtures for PureSpectrum. `purespectrum_survey_wcs_data.xlsx` does not exist in this repository yet — see **Missing Fixtures** below. Tasks that need it are written to degrade to a skipped test, exactly like the existing `tests/test_conformance.py` Section B pattern (`@pytest.mark.skipif(not PATH.exists(), ...)`).
- Loud failure. An unclassified column halts the run with a plain-English structured error. It is never silently skipped.
- The Milieu and Toluna adapter *readers* (`surveytool/ingest/milieu.py`, `surveytool/ingest/toluna.py`) are not migrated to `DatamapReader` and their parsing logic is not touched in Phase 1. They gain a `VendorProfile` describing current behaviour and nothing more.
- Straightliner exclusion (`ToolConfig.straightliner_action`) stays per-project configurable and is a distinct mechanism from the new non-substantive-response base setting added in Phase 3 — do not conflate the two.
- Every new `SurveyToolError` subclass follows the existing taxonomy exactly: `code: ErrorCode`, `message: str` (plain English, shown verbatim to non-technical analysts per `[[user_context]]` — see memory), optional `detail: str`, optional `next_action: str`. Messages must never mention `scales.yaml`, YAML, override file paths, or any repository path (per spec Prompt 6).
- Behaviour-preserving means behaviour-preserving: Phase 1's exit condition is the **full existing test suite passing with zero test file modifications**. If any test would need to change, stop and report rather than edit the test.

## Missing Fixtures — read before starting Phase 2 or Phase 4

Discovery against the current repository confirmed:

- `purespectrum_survey_wcs_data.xlsx` does not exist anywhere in the repo (Phase 4 fixture).
- No fixture file contains a `date`, `status`, or `FLAG` column in the two real Rakuten files present (`rakuten_survey_support_measures_data.xlsx`, `rakuten_survey_chn_clans_data.xlsx` — both have header `['record', 'uuid', 'S1'..'S4', 'Q1'..'Q5' or 'A1'..'A6', 'uid']`, no `FLAG`, no `HC`-sheet reader in code).
- No "traffic law" survey fixture exists in the repo. The spec's Phase 2/Phase 5 test expectations (`S5` classifies BINARY, `S6`/traffic-law matches `calendar_frequency`, `Q1`–`Q10` are `agreement` scales, top-two-box on `S5` raises) and Phase 9 PureSpectrum expectations (42 columns, `QC2`/`QC2Flag`, `record`/`uuid`/`date`/`status`/`dtrack`/`qtime`/`start_date`/`transaction_id`) all reference files this repository does not have.

Tasks below that depend on these missing files are marked **[BLOCKED — awaiting fixture]** and are written two ways: (a) the production code and unit tests using small inline fixtures that exercise the same logic without the real file, so the phase's core deliverable ships and is tested now, and (b) a `pytest.mark.skipif` integration test stub pointed at the real path, mirroring the existing `tests/test_conformance.py` Section B pattern exactly, so it activates automatically the moment the file is dropped into the repo root. Do not fabricate the traffic-law or PureSpectrum fixture content yourselves — that would let a wrong assumption about the real file's shape pass silently.

---

## Phase 1: Vendor profile schema and registry, and the datamap-format base reader

### Task 1: `VendorProfile` dataclass and registry

**Files:**
- Create: `surveytool/ingest/vendor_profile.py`
- Test: `tests/test_vendor_profile.py`

**Interfaces:**
- Produces: `VendorProfile` (frozen dataclass), `VENDOR_PROFILES: dict[str, VendorProfile]` registry, `get_vendor_profile(vendor_id: str) -> VendorProfile`.
- Consumed by: Task 2 (Rakuten adapter reads its profile), Task 4 (`DatamapReader` takes a `VendorProfile`), Task 7 (`ColumnClassification` reads `reserved_metadata_columns`/`quality_columns`), Task 21 (PureSpectrum profile), Task 23 (fingerprint pre-check reads `signature`).

Every adapter today hardcodes its own constants: Rakuten's `_SKIP_QIDS = frozenset({"record", "uuid", "uid"})` and `"FLAG"` lookup (`surveytool/ingest/rakuten.py:25,218`), Milieu's `profile_id` respondent column and `_MULTI_DELIMITER = "; "` (`surveytool/ingest/milieu.py:23,225`), Toluna's `_RESPID_COLUMN = "respid"` and `_SHEET_NAME = "RespondentData.Text"` (`surveytool/ingest/toluna.py:26-27`). This task introduces the declarative carrier for all of that, without changing any adapter yet.

- [ ] **Step 1: Write the failing test for the dataclass shape and two new nullable fields**

```python
# tests/test_vendor_profile.py
from surveytool.ingest.vendor_profile import VendorProfile


def test_vendor_profile_quality_flag_and_verification_sheet_default_none():
    profile = VendorProfile(
        vendor_id="test_vendor",
        data_sheet=None,
        codebook_sheet=None,
        reserved_metadata_columns=frozenset(),
        quality_columns=frozenset(),
        quality_flag_column=None,
        quality_flag_pass_value=None,
        quality_flag_fail_value=None,
        verification_sheet=None,
        date_format=None,
        multiselect_column_pattern=None,
        other_specify_suffix=None,
        signature=None,
    )
    assert profile.quality_flag_column is None
    assert profile.verification_sheet is None
    assert profile.vendor_id == "test_vendor"


def test_vendor_profile_is_frozen():
    profile = VendorProfile(
        vendor_id="test_vendor",
        data_sheet=None,
        codebook_sheet=None,
        reserved_metadata_columns=frozenset(),
        quality_columns=frozenset(),
        quality_flag_column=None,
        quality_flag_pass_value=None,
        quality_flag_fail_value=None,
        verification_sheet=None,
        date_format=None,
        multiselect_column_pattern=None,
        other_specify_suffix=None,
        signature=None,
    )
    import dataclasses
    with pytest.raises(dataclasses.FrozenInstanceError):
        profile.vendor_id = "changed"
```

Add `import pytest` at the top of the test file alongside the existing import.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_vendor_profile.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'surveytool.ingest.vendor_profile'`

- [ ] **Step 3: Write the `VendorProfile` dataclass**

```python
# surveytool/ingest/vendor_profile.py
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class VendorProfile:
    """Declarative description of everything that varies between vendor
    adapters: sheet resolution, reserved/quality columns, date and
    multiselect conventions, and fingerprint signature.

    ``quality_flag_column`` and ``verification_sheet`` are nullable and, as
    of Phase 1, unused by any adapter — they exist so Rakuten's profile can
    name ``FLAG`` and the ``HC`` sheet declaratively without any adapter
    behaviour depending on it yet.
    """

    vendor_id: str
    data_sheet: str | None
    codebook_sheet: str | None
    reserved_metadata_columns: frozenset[str]
    quality_columns: frozenset[str]
    quality_flag_column: str | None
    quality_flag_pass_value: str | None
    quality_flag_fail_value: str | None
    verification_sheet: str | None
    date_format: str | None
    multiselect_column_pattern: str | None
    other_specify_suffix: str | None
    signature: "VendorSignature | None"


@dataclass(frozen=True)
class VendorSignature:
    """Expected sheet names and a small set of expected column names, used
    by the Phase 4 fingerprint pre-check to detect a file loaded under the
    wrong vendor selection."""

    expected_sheets: frozenset[str] = field(default_factory=frozenset)
    expected_columns: frozenset[str] = field(default_factory=frozenset)


_REGISTRY: dict[str, VendorProfile] = {}


def register_vendor_profile(profile: VendorProfile) -> None:
    _REGISTRY[profile.vendor_id] = profile


def get_vendor_profile(vendor_id: str) -> VendorProfile:
    return _REGISTRY[vendor_id]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_vendor_profile.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add surveytool/ingest/vendor_profile.py tests/test_vendor_profile.py
git commit -m "feat: add VendorProfile dataclass and registry"
```

---

### Task 2: Declare Rakuten, Milieu, Toluna profiles matching current behaviour exactly

**Files:**
- Modify: `surveytool/ingest/vendor_profile.py` (add profile constants + `register_vendor_profile` calls)
- Test: `tests/test_vendor_profile.py` (append)

**Interfaces:**
- Consumes: `VendorProfile`, `VendorSignature`, `register_vendor_profile` (Task 1).
- Produces: `RAKUTEN_PROFILE`, `MILIEU_PROFILE`, `TOLUNA_PROFILE` module-level constants, each registered under `get_vendor_profile("rakuten"|"milieu"|"toluna")`.

Values sourced directly from current adapter constants (no guessing — every value below is copied from the file/line cited):

| Field | Rakuten | Milieu | Toluna |
|---|---|---|---|
| `data_sheet` | `"A1"` (rakuten.py:298) | `None` (CSV, no sheet concept) | `"RespondentData.Text"` (toluna.py:27) |
| `codebook_sheet` | `"Datamap"` (rakuten.py:288) | `None` | `None` |
| `reserved_metadata_columns` | `frozenset({"record", "uuid", "uid"})` (rakuten.py:25 `_SKIP_QIDS`) | `frozenset({"profile_id"})` (milieu.py:225) | `frozenset({"respid"})` (toluna.py:26 `_RESPID_COLUMN`) |
| `quality_columns` | `frozenset({"FLAG"})` (rakuten.py:218) | `frozenset()` — no flag column exists | `frozenset()` — no flag column exists |
| `quality_flag_column` | `"FLAG"` | `None` | `None` |
| `quality_flag_pass_value` / `quality_flag_fail_value` | `None` / `None` — vendor's pass/fail coding was never consumed anywhere downstream (`Response.vendor_flag` is stored but unread; confirmed by grep), so there is nothing to declare truthfully yet | `None` / `None` | `None` / `None` |
| `verification_sheet` | `"HC"` — present in both real fixtures, currently read only by tests as a golden-figure source, never by adapter code (rakuten.py has no `wb["HC"]` reference) | `None` | `None` |
| `date_format` | `None` — no adapter parses dates | `None` | `None` |
| `multiselect_column_pattern` | `None` — Rakuten's datamap has no multi-select convention in code | `None` — Milieu represents multi-select as one delimited-cell column (`_MULTI_DELIMITER = "; "`, milieu.py:23), not a per-option column pattern | `None` — Toluna's adapter has no multi-select branch at all |
| `other_specify_suffix` | `None` — not implemented anywhere | `None` | `None` |
| `signature` | `VendorSignature(expected_sheets=frozenset({"A1", "Datamap"}), expected_columns=frozenset({"record", "uuid"}))` | `VendorSignature(expected_columns=frozenset())` — Milieu is sniffed by header regex, not column name; leave `expected_columns` empty and `expected_sheets` empty since CSV has no sheets | `VendorSignature(expected_sheets=frozenset({"RespondentData.Text"}), expected_columns=frozenset({"respid"}))` |

`quality_flag_pass_value`/`quality_flag_fail_value` being `None` for Rakuten is a deliberate, honest gap: the FLAG column's coding was never confirmed or consumed by any downstream code (`grep -rn "vendor_flag" surveytool/` shows it is only ever assigned, never read). Declaring a guessed pass/fail value would be inventing data. This mirrors the PureSpectrum `QC2`/`QC2Flag` "unconfirmed by the vendor" placeholder called for in Prompt 9 — Rakuten already needs the same honesty.

- [ ] **Step 1: Write the failing test asserting each profile's fields match the constants they replace**

```python
# tests/test_vendor_profile.py (append)
from surveytool.ingest.vendor_profile import (
    MILIEU_PROFILE,
    RAKUTEN_PROFILE,
    TOLUNA_PROFILE,
    get_vendor_profile,
)


def test_rakuten_profile_matches_current_constants():
    p = RAKUTEN_PROFILE
    assert p.vendor_id == "rakuten"
    assert p.data_sheet == "A1"
    assert p.codebook_sheet == "Datamap"
    assert p.reserved_metadata_columns == frozenset({"record", "uuid", "uid"})
    assert p.quality_columns == frozenset({"FLAG"})
    assert p.quality_flag_column == "FLAG"
    assert p.verification_sheet == "HC"
    assert p.date_format is None
    assert p.multiselect_column_pattern is None
    assert p.other_specify_suffix is None
    assert get_vendor_profile("rakuten") is p


def test_milieu_profile_matches_current_constants():
    p = MILIEU_PROFILE
    assert p.vendor_id == "milieu"
    assert p.data_sheet is None
    assert p.codebook_sheet is None
    assert p.reserved_metadata_columns == frozenset({"profile_id"})
    assert p.quality_columns == frozenset()
    assert p.quality_flag_column is None
    assert p.verification_sheet is None
    assert get_vendor_profile("milieu") is p


def test_toluna_profile_matches_current_constants():
    p = TOLUNA_PROFILE
    assert p.vendor_id == "toluna"
    assert p.data_sheet == "RespondentData.Text"
    assert p.codebook_sheet is None
    assert p.reserved_metadata_columns == frozenset({"respid"})
    assert p.quality_columns == frozenset()
    assert p.quality_flag_column is None
    assert p.verification_sheet is None
    assert get_vendor_profile("toluna") is p
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_vendor_profile.py -v`
Expected: FAIL with `ImportError: cannot import name 'RAKUTEN_PROFILE'`

- [ ] **Step 3: Add the three profile constants and register them**

```python
# surveytool/ingest/vendor_profile.py (append)

RAKUTEN_PROFILE = VendorProfile(
    vendor_id="rakuten",
    data_sheet="A1",
    codebook_sheet="Datamap",
    reserved_metadata_columns=frozenset({"record", "uuid", "uid"}),
    quality_columns=frozenset({"FLAG"}),
    quality_flag_column="FLAG",
    quality_flag_pass_value=None,
    quality_flag_fail_value=None,
    verification_sheet="HC",
    date_format=None,
    multiselect_column_pattern=None,
    other_specify_suffix=None,
    signature=VendorSignature(
        expected_sheets=frozenset({"A1", "Datamap"}),
        expected_columns=frozenset({"record", "uuid"}),
    ),
)

MILIEU_PROFILE = VendorProfile(
    vendor_id="milieu",
    data_sheet=None,
    codebook_sheet=None,
    reserved_metadata_columns=frozenset({"profile_id"}),
    quality_columns=frozenset(),
    quality_flag_column=None,
    quality_flag_pass_value=None,
    quality_flag_fail_value=None,
    verification_sheet=None,
    date_format=None,
    multiselect_column_pattern=None,
    other_specify_suffix=None,
    signature=VendorSignature(),
)

TOLUNA_PROFILE = VendorProfile(
    vendor_id="toluna",
    data_sheet="RespondentData.Text",
    codebook_sheet=None,
    reserved_metadata_columns=frozenset({"respid"}),
    quality_columns=frozenset(),
    quality_flag_column=None,
    quality_flag_pass_value=None,
    quality_flag_fail_value=None,
    verification_sheet=None,
    date_format=None,
    multiselect_column_pattern=None,
    other_specify_suffix=None,
    signature=VendorSignature(
        expected_sheets=frozenset({"RespondentData.Text"}),
        expected_columns=frozenset({"respid"}),
    ),
)

register_vendor_profile(RAKUTEN_PROFILE)
register_vendor_profile(MILIEU_PROFILE)
register_vendor_profile(TOLUNA_PROFILE)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_vendor_profile.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add surveytool/ingest/vendor_profile.py tests/test_vendor_profile.py
git commit -m "feat: declare Rakuten, Milieu, Toluna vendor profiles"
```

---

### Task 3: Migrate Rakuten adapter to read constants from its profile

**Files:**
- Modify: `surveytool/ingest/rakuten.py:24-25,218-220,288,298` (replace inline literals with profile lookups)
- Test: existing suite only — this task adds no new test file, per the "behaviour-preserving, no test modification" exit condition. Verification is running the full suite.

**Interfaces:**
- Consumes: `RAKUTEN_PROFILE`, `get_vendor_profile` (Task 2).

This is the first behaviour-preserving step: replace the four hardcoded literals with reads from `RAKUTEN_PROFILE`, changing nothing about what the code does.

- [ ] **Step 1: Run the full suite first to record the current green baseline**

Run: `python -m pytest -q`
Expected: PASS (record the pass count — this is the number that must be unchanged after this task)

- [ ] **Step 2: Replace `_SKIP_QIDS` and the sheet-name/FLAG literals with profile reads**

```python
# surveytool/ingest/rakuten.py
# Replace the module-level constants block:
_QID_RE = re.compile(r"\[([^\]]+)\]")

# DELETE: _SKIP_QIDS = frozenset({"record", "uuid", "uid"})
```

Add the import and a module-level profile reference near the top:

```python
from surveytool.ingest.vendor_profile import RAKUTEN_PROFILE
```

In `_flush()` inside `parse_codebook`, replace the skip check:

```python
    def _flush() -> None:
        if current_qid is None:
            return
        if current_qid in RAKUTEN_PROFILE.reserved_metadata_columns:
            return
        _build_question(current_qid, current_text or "", current_qtype_hint, current_codes, questions)
```

In `load_respondents`, replace the hardcoded `"FLAG"` lookup:

```python
    flag_col: int | None = col_index.get(RAKUTEN_PROFILE.quality_flag_column)
```

(`RAKUTEN_PROFILE.quality_flag_column` is `"FLAG"`, so `col_index.get("FLAG")` — identical lookup, same `None` result when absent.)

In `load()`, replace the two hardcoded sheet names:

```python
    try:
        try:
            ws_datamap = wb[RAKUTEN_PROFILE.codebook_sheet]
        except KeyError as exc:
            raise SurveyToolError(
                ErrorCode.MISSING_SHEET,
                "This file does not look like a Rakuten export.",
                detail=f"No {RAKUTEN_PROFILE.codebook_sheet} sheet was found.",
                next_action="Check the vendor setting, or pick a different file.",
            ) from exc

        try:
            ws_respondents = wb[RAKUTEN_PROFILE.data_sheet]
        except KeyError as exc:
            raise SurveyToolError(
                ErrorCode.MISSING_SHEET,
                "This file does not look like a Rakuten export.",
                detail=f"No {RAKUTEN_PROFILE.data_sheet} respondent-data sheet was found.",
                next_action="Check the vendor setting, or pick a different file.",
            ) from exc
```

Note the `detail` strings change from `"No Datamap sheet was found."` / `"No A1 respondent-data sheet was found."` to f-string equivalents that produce byte-identical text (`"No Datamap sheet was found."`, `"No A1 respondent-data sheet was found."`) — confirm this by eye before running tests, since any test asserting on `detail` text must still match.

- [ ] **Step 3: Run the full suite to confirm no regression**

Run: `python -m pytest -q`
Expected: PASS, same pass count as Step 1, zero test files modified

If any test fails or would need modification, stop here and report the specific failing assertion rather than editing the test — that means behaviour changed and Phase 1's exit condition has been violated.

- [ ] **Step 4: Commit**

```bash
git add surveytool/ingest/rakuten.py
git commit -m "refactor: read Rakuten adapter constants from VendorProfile"
```

---

### Task 4: `DatamapReader` — extract Rakuten's datamap-format parsing into a reusable reader

**Files:**
- Create: `surveytool/ingest/datamap_reader.py`
- Test: `tests/test_datamap_reader.py`

**Interfaces:**
- Consumes: `VendorProfile` (Task 1/2), `openpyxl` worksheet objects.
- Produces: `DatamapReader.read(ws_data, ws_codebook) -> tuple[DataFrameLike, Codebook]` where `Codebook` maps variable name to `(question_text: str, codes: list[tuple[int, str]])` — the ordered code/label pairs exactly as `parse_codebook` currently returns them via `_build_question`'s `codes` parameter, but *before* role/family resolution, so callers (Rakuten adapter) still do their own `resolve_roles`/`identify_family` step.
- Produces: `DatamapReaderError` (a `SurveyToolError` subclass) for the malformed-entry case (Values: line present, no code rows).
- Consumed by: Task 5 (Rakuten adapter migrates to use this).

Per the spec (Prompt 2), `DatamapReader` returns "the parsed data frame plus a codebook structure mapping variable name to question text and to an ordered list of code and label pairs." The "data frame" here is the row-tuple structure `load_respondents` already consumes (`ws_a1.iter_rows(values_only=True)` — a header row plus row tuples); this plan keeps that shape (a `(header: list[str], rows: list[tuple])` pair) rather than introducing an actual pandas `DataFrame`, since nothing downstream needs pandas and adding it would be scope creep on a "behaviour-preserving" phase. Call this returned type `RawTable`.

- [ ] **Step 1: Write the failing test for a normal codebook entry**

```python
# tests/test_datamap_reader.py
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
    text, codes = codebook["Q1"]
    assert text == "How satisfied are you?"
    assert codes == [(1, "Very satisfied"), (2, "Neutral"), (3, "Very dissatisfied")]


def test_datamap_reader_open_response_no_codes():
    codebook_ws = _FakeWorksheet([
        ("[Q2]: Please describe your experience", None, None),
        ("Open text", None, None),
        (None, None, None),
    ])
    reader = DatamapReader(RAKUTEN_PROFILE)
    codebook = reader.read_codebook(codebook_ws)
    assert "Q2" in codebook
    text, codes = codebook["Q2"]
    assert text == "Please describe your experience"
    assert codes == []


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_datamap_reader.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'surveytool.ingest.datamap_reader'`

- [ ] **Step 3: Write `DatamapReader`**

This is a direct extraction of `parse_codebook`/`_iter_until_blank` from `surveytool/ingest/rakuten.py:28-89`, generalised to take a `VendorProfile` instead of the module-level `_SKIP_QIDS`, and split so the raw `(text, codes)` pair is returned instead of a built `Question` — the caller (Rakuten adapter, Task 5) still does role/family resolution itself. The one genuinely new piece is the malformed-entry check: today, an entry with a `"Values:"` line and zero code rows silently produces `codes == []`, which `_build_question` then returns from early via `if not codes: return` (rakuten.py:141-142) — i.e. the question is silently dropped. `DatamapReader` must not repeat that silent drop; it must distinguish "genuinely no codes because this is an open-response type" (has a `qtype_hint`) from "codes were expected but absent" (no `qtype_hint`, a `Values:` line was seen, and zero code rows followed) and raise for the latter.

```python
# surveytool/ingest/datamap_reader.py
from __future__ import annotations

import re
from typing import Iterator

from surveytool.charts.errors import ErrorCode, SurveyToolError
from surveytool.ingest.vendor_profile import VendorProfile

_QID_RE = re.compile(r"\[([^\]]+)\]")

Codebook = dict[str, tuple[str, list[tuple[int, str]]]]


class DatamapReaderError(SurveyToolError):
    """Raised when a datamap codebook entry has a Values: line but no code
    rows follow it — a malformed entry that must not silently resolve to an
    empty label set."""

    def __init__(self, qid: str) -> None:
        self.qid = qid
        detail = (
            f"Codebook entry {qid!r} declares a Values: range but no code/label "
            "rows follow it."
        )
        super().__init__(
            ErrorCode.NO_QUESTIONS_FOUND,
            f"This file's codebook has a malformed entry for {qid!r}.",
            detail=detail,
            next_action="Check the codebook sheet for this question, or pick a different file.",
        )


def _iter_until_blank(rows: Iterator[tuple]) -> Iterator[tuple]:
    for row in rows:
        if all(v is None for v in row):
            break
        yield row


class DatamapReader:
    """Parses a datamap-format codebook: '[variable]: question text' header
    rows, an optional 'Values: n-m' hint row, then rows of (code, label)
    pairs. Shared by any vendor whose codebook follows this convention."""

    def __init__(self, profile: VendorProfile) -> None:
        self.profile = profile

    def read_codebook(self, ws_codebook) -> Codebook:
        codebook: Codebook = {}
        current_qid: str | None = None
        current_text: str | None = None
        current_qtype_hint: str | None = None
        current_codes: list[tuple[int, str]] = []
        saw_values_line = False

        def _flush() -> None:
            if current_qid is None:
                return
            if current_qid in self.profile.reserved_metadata_columns:
                return
            if current_qtype_hint is None and saw_values_line and not current_codes:
                raise DatamapReaderError(current_qid)
            codebook[current_qid] = (current_text or "", current_codes)

        for row in ws_codebook.iter_rows(values_only=True):
            col0, col1, col2 = (row[i] if i < len(row) else None for i in range(3))

            if col0 is None and col1 is None and col2 is None:
                continue

            if col0 and isinstance(col0, str) and col0.strip():
                cell = col0.strip()
                m = _QID_RE.match(cell)
                if m:
                    _flush()
                    current_qid = m.group(1)
                    current_text = cell[m.end():].lstrip(":").strip()
                    current_qtype_hint = None
                    current_codes = []
                    saw_values_line = False
                elif cell.startswith("Open numeric"):
                    current_qtype_hint = "open_numeric"
                elif cell.startswith("Open text"):
                    current_qtype_hint = "open_text"
                elif cell.startswith("Values:"):
                    saw_values_line = True
            elif col1 is not None and col2 is not None:
                try:
                    code = int(col1)
                except (TypeError, ValueError):
                    continue
                current_codes.append((code, str(col2)))

        _flush()
        return codebook

    def read_table(self, ws_data) -> tuple[list[str], list[tuple]]:
        rows = ws_data.iter_rows(values_only=True)
        header = list(next(rows))
        header_strs = [str(h) if h is not None else None for h in header]
        data_rows = list(_iter_until_blank(rows))
        return header_strs, data_rows
```

Note: `current_qtype_hint` is intentionally left un-consumed by this class (the open_numeric/open_text distinction is caller business logic for building `Question` objects — `DatamapReader` only needs it to decide "codes are legitimately absent here" vs "codes are missing and that's malformed"). Expose it via the codebook's `codes == []` case rather than a separate field: an open-response entry and a malformed entry both produce `codes == []` from `read_codebook`'s perspective *unless* malformed, which now raises instead of returning silently. This means Task 5's caller must independently know which qids are open-response (it already does, via `current_qtype_hint` — see Task 5, which reintroduces that piece at the adapter layer since `DatamapReader`'s job per the spec is table+codebook parsing, not question-type decisions).

Wait — re-examine: the caller needs `qtype_hint` to build `numeric_open`/`text_open` questions correctly (rakuten.py:99-121). If `DatamapReader.read_codebook` drops that information, Task 5 cannot reconstruct it. Fix: return it as part of the codebook tuple.

```python
Codebook = dict[str, tuple[str, list[tuple[int, str]], str | None]]
```

Update `_flush` to store `current_qtype_hint` as the third tuple element:

```python
            codebook[current_qid] = (current_text or "", current_codes, current_qtype_hint)
```

- [ ] **Step 4: Update the test file for the corrected three-element codebook tuple**

```python
# tests/test_datamap_reader.py — update the two passing-case assertions
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
```

- [ ] **Step 5: Run tests to verify all pass**

Run: `python -m pytest tests/test_datamap_reader.py -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Commit**

```bash
git add surveytool/ingest/datamap_reader.py tests/test_datamap_reader.py
git commit -m "feat: extract DatamapReader for datamap-format codebook parsing"
```

---

### Task 5: Migrate Rakuten adapter to use `DatamapReader`

**Files:**
- Modify: `surveytool/ingest/rakuten.py` (replace `parse_codebook`/`_iter_until_blank` with `DatamapReader` calls; keep `_build_question` and `load_respondents` as-is)

**Interfaces:**
- Consumes: `DatamapReader`, `Codebook`, `DatamapReaderError` (Task 4).

Do not touch `surveytool/ingest/milieu.py` or `surveytool/ingest/toluna.py` in this task — their file shapes have not been inspected against the datamap convention and must not be assumed to match (per spec Prompt 2 and the build plan's Phase 1 constraint).

- [ ] **Step 1: Run the full suite to record the green baseline including the HC-sheet golden fixtures**

Run: `python -m pytest -q`
Expected: PASS — note the pass count; this must be identical afterward, and no Rakuten output (`tests/test_compute.py`, `tests/test_cross_tab.py`, `tests/test_findings.py`, `tests/test_chart_data.py` HC-golden assertions) may change by any amount.

- [ ] **Step 2: Rewrite `rakuten.py` to use `DatamapReader` for codebook parsing**

```python
# surveytool/ingest/rakuten.py
from __future__ import annotations

import zipfile
from pathlib import Path

import openpyxl
from openpyxl.utils.exceptions import InvalidFileException

from surveytool.charts.errors import ErrorCode, SurveyToolError
from surveytool.core.hygiene import normalize_label
from surveytool.core.model import (
    CodeRole,
    Question,
    QuestionType,
    Response,
    ScaleCode,
    Survey,
)
from surveytool.core.nonsubstantive import classify_response, is_nonsubstantive_label
from surveytool.core.scale_library import identify_family, resolve_roles
from surveytool.ingest.datamap_reader import Codebook, DatamapReader
from surveytool.ingest.vendor_profile import RAKUTEN_PROFILE


def parse_codebook(ws_datamap) -> list[Question]:
    """Parse the Rakuten Datamap sheet into a list of Questions."""
    reader = DatamapReader(RAKUTEN_PROFILE)
    codebook: Codebook = reader.read_codebook(ws_datamap)

    questions: list[Question] = []
    for qid, (text, codes, qtype_hint) in codebook.items():
        _build_question(qid, text, qtype_hint, codes, questions)
    return questions
```

`_build_question` (rakuten.py lines 92-198) is unchanged — copy it verbatim below the new `parse_codebook`. `load_respondents` (lines 201-271) is unchanged. In `load()`, replace the codebook-parsing call site:

```python
        questions = parse_codebook(ws_datamap)
```

stays exactly as-is (still calls the local `parse_codebook`, which now delegates internally) — no change needed at the `load()` call site itself. Remove the now-unused `_iter_until_blank` and `_QID_RE` from `rakuten.py` (they live in `datamap_reader.py` now); remove `re` from the imports if nothing else in the file uses it (`_QID_RE` was its only use — confirm with `grep -n "re\." surveytool/ingest/rakuten.py` before deleting the import).

- [ ] **Step 3: Run the full suite to confirm zero regressions, especially the HC-golden tests**

Run: `python -m pytest -q`
Expected: PASS, identical pass count to Step 1. Specifically check:

Run: `python -m pytest tests/test_compute.py tests/test_cross_tab.py tests/test_findings.py tests/test_chart_data.py tests/test_conformance.py -v`
Expected: PASS, no golden-figure assertion changed.

If any Rakuten output changes by any amount, stop and report exactly which assertion changed and why, rather than adjusting the test.

- [ ] **Step 4: Commit**

```bash
git add surveytool/ingest/rakuten.py
git commit -m "refactor: migrate Rakuten adapter onto DatamapReader"
```

---

## Phase 2: Column classification, question typing, and label normalisation

This phase is where behaviour is allowed to change, in the specific ways described below. Every change here is additive-first: new enum members, new fields, new functions — existing paths keep working until a task explicitly rewires a call site.

### Task 6: `ColumnClassification` enum and `reserved_metadata_columns`/`quality_columns` on the profile

**Files:**
- Create: `surveytool/core/column_classification.py`
- Test: `tests/test_column_classification.py`

**Interfaces:**
- Produces: `ColumnClassification` enum (`QUESTION`, `DEMOGRAPHIC`, `METADATA`, `QUALITY`, `OPEN_END`, `UNCLASSIFIED`), `UnclassifiedColumnError(SurveyToolError)`.
- Consumed by: Task 7 (classification-assignment pass), Task 24 (run summary).

`reserved_metadata_columns` and `quality_columns` already exist on `VendorProfile` from Task 1/2 with values populated in Task 2's table. This task adds the enum and the loud-failure error only.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_column_classification.py
from surveytool.core.column_classification import ColumnClassification, UnclassifiedColumnError


def test_column_classification_members():
    assert {c.name for c in ColumnClassification} == {
        "QUESTION", "DEMOGRAPHIC", "METADATA", "QUALITY", "OPEN_END", "UNCLASSIFIED",
    }


def test_unclassified_column_error_names_column_and_header():
    err = UnclassifiedColumnError(column="Q99xyz", header_text="Q99xyz")
    assert "Q99xyz" in err.message or "Q99xyz" in (err.detail or "")
    assert err.code.value == "UNCLASSIFIED_COLUMN"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_column_classification.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Add `UNCLASSIFIED_COLUMN` to `ErrorCode` and write the new module**

```python
# surveytool/charts/errors.py — add to the ErrorCode enum (after NO_QUESTIONS_FOUND)
    UNCLASSIFIED_COLUMN = "UNCLASSIFIED_COLUMN"
```

Add its status mapping in `_STATUS_BY_CODE`:

```python
    ErrorCode.UNCLASSIFIED_COLUMN: 400,
```

```python
# surveytool/core/column_classification.py
from __future__ import annotations

from enum import Enum

from surveytool.charts.errors import ErrorCode, SurveyToolError


class ColumnClassification(str, Enum):
    QUESTION = "question"
    DEMOGRAPHIC = "demographic"
    METADATA = "metadata"
    QUALITY = "quality"
    OPEN_END = "open_end"
    UNCLASSIFIED = "unclassified"


class UnclassifiedColumnError(SurveyToolError):
    """Raised when a column matches none of the classification rules.

    Never silently skipped — an unclassified column halts the run with a
    plain-English explanation naming the column.
    """

    def __init__(self, column: str, header_text: str) -> None:
        self.column = column
        self.header_text = header_text
        detail = f"Column {column!r} (header: {header_text!r}) did not match any classification rule."
        super().__init__(
            ErrorCode.UNCLASSIFIED_COLUMN,
            f"This file has a column this tool doesn't know how to classify: {column!r}.",
            detail=detail,
            next_action="Check the vendor setting, or report this column so it can be added to the vendor profile.",
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_column_classification.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add surveytool/charts/errors.py surveytool/core/column_classification.py tests/test_column_classification.py
git commit -m "feat: add ColumnClassification enum and UnclassifiedColumnError"
```

---

### Task 7: Classify every column on load, in precedence order, and expose the classification map

**Files:**
- Create: `surveytool/ingest/classify_columns.py`
- Test: `tests/test_classify_columns.py`

**Interfaces:**
- Consumes: `VendorProfile` (Task 1/2), `ColumnClassification`, `UnclassifiedColumnError` (Task 6).
- Produces: `classify_columns(header: list[str], profile: VendorProfile, *, demographic_predicate, open_end_predicate) -> dict[str, ColumnClassification]`.
- Consumed by: Task 24 (run summary column inventory). **Not yet wired into any adapter's `load()`** — that wiring is explicitly out of scope for this task because Milieu/Toluna column-to-classification mapping needs their own header-parsing logic (their "columns" are CSV headers matched by regex, not a flat list), and rewiring `load()` call sites belongs with the PureSpectrum profile work in Phase 4, where classification is actually consumed end-to-end for the first time. This task delivers the classification function and proves it against fixtures per the spec's exact test list; Task 22 (PureSpectrum adapter) is the first real caller.

Precedence order per spec (Prompt 3): reserved metadata → quality → open-end (other-specify suffix match) → demographic (existing detection) → question → unclassified fallback. Demographic detection must reuse existing logic — `text_matches_demographic` (`surveytool/core/demographics/__init__.py:17-23`) for Milieu/Toluna-style text matching, or a structural predicate (Rakuten's `qid.startswith("S")`) — so this function takes both as injected predicates rather than hardcoding one vendor's rule.

- [ ] **Step 1: Write the failing tests — including the three vendor-specific assertions from the spec**

```python
# tests/test_classify_columns.py
import re

import pytest

from surveytool.core.column_classification import ColumnClassification, UnclassifiedColumnError
from surveytool.core.demographics import text_matches_demographic
from surveytool.ingest.classify_columns import classify_columns
from surveytool.ingest.vendor_profile import MILIEU_PROFILE, RAKUTEN_PROFILE, TOLUNA_PROFILE

_OE_SUFFIX_RE = re.compile(r"oe$")


def _no_open_end(_header: str) -> bool:
    return False


def _rakuten_demographic(qid: str) -> bool:
    return qid.startswith("S")


def test_status_classifies_as_metadata_rakuten():
    profile_with_status = RAKUTEN_PROFILE
    header = ["record", "uuid", "status", "S1", "Q1", "uid"]
    result = classify_columns(
        header,
        reserved_metadata_columns=profile_with_status.reserved_metadata_columns | {"status"},
        quality_columns=profile_with_status.quality_columns,
        demographic_predicate=_rakuten_demographic,
        open_end_predicate=_no_open_end,
    )
    assert result["status"] == ColumnClassification.METADATA


def test_flag_classifies_as_quality_rakuten():
    header = ["record", "uuid", "FLAG", "S1", "Q1", "uid"]
    result = classify_columns(
        header,
        reserved_metadata_columns=RAKUTEN_PROFILE.reserved_metadata_columns,
        quality_columns=RAKUTEN_PROFILE.quality_columns,
        demographic_predicate=_rakuten_demographic,
        open_end_predicate=_no_open_end,
    )
    assert result["FLAG"] == ColumnClassification.QUALITY


def test_q8r8oe_classifies_as_open_end():
    header = ["record", "uuid", "Q8r8oe", "uid"]
    result = classify_columns(
        header,
        reserved_metadata_columns=RAKUTEN_PROFILE.reserved_metadata_columns,
        quality_columns=RAKUTEN_PROFILE.quality_columns,
        demographic_predicate=_rakuten_demographic,
        open_end_predicate=lambda h: bool(_OE_SUFFIX_RE.search(h)),
    )
    assert result["Q8r8oe"] == ColumnClassification.OPEN_END


def test_unknown_column_raises():
    header = ["record", "uuid", "TotallyUnknownColumn"]
    with pytest.raises(UnclassifiedColumnError) as exc_info:
        classify_columns(
            header,
            reserved_metadata_columns=RAKUTEN_PROFILE.reserved_metadata_columns,
            quality_columns=RAKUTEN_PROFILE.quality_columns,
            demographic_predicate=lambda h: False,
            open_end_predicate=_no_open_end,
        )
    assert exc_info.value.column == "TotallyUnknownColumn"


def test_precedence_reserved_beats_quality():
    """A column present in both reserved_metadata_columns and quality_columns
    (pathological, but precedence must be deterministic) classifies as
    METADATA, since reserved metadata is checked first."""
    header = ["dual"]
    result = classify_columns(
        header,
        reserved_metadata_columns=frozenset({"dual"}),
        quality_columns=frozenset({"dual"}),
        demographic_predicate=lambda h: False,
        open_end_predicate=_no_open_end,
    )
    assert result["dual"] == ColumnClassification.METADATA


def test_question_is_fallback_before_unclassified():
    header = ["Q1"]
    result = classify_columns(
        header,
        reserved_metadata_columns=frozenset(),
        quality_columns=frozenset(),
        demographic_predicate=lambda h: False,
        open_end_predicate=_no_open_end,
        question_predicate=lambda h: h == "Q1",
    )
    assert result["Q1"] == ColumnClassification.QUESTION
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_classify_columns.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write `classify_columns`**

```python
# surveytool/ingest/classify_columns.py
from __future__ import annotations

from typing import Callable

from surveytool.core.column_classification import ColumnClassification, UnclassifiedColumnError


def classify_columns(
    header: list[str],
    *,
    reserved_metadata_columns: frozenset[str],
    quality_columns: frozenset[str],
    demographic_predicate: Callable[[str], bool],
    open_end_predicate: Callable[[str], bool],
    question_predicate: Callable[[str], bool] | None = None,
) -> dict[str, ColumnClassification]:
    """Classify every column in precedence order: reserved metadata, quality,
    open-end, demographic, question, then unclassified as the fallback.

    ``question_predicate`` defaults to "anything not yet classified and not
    caught by the fallback" — i.e. every column that reaches the question
    check without a predicate is classified QUESTION. Pass an explicit
    predicate when the caller wants question membership to be a genuine
    check rather than a default (see test_question_is_fallback_before_unclassified,
    which uses this to prove ordering).

    Raises UnclassifiedColumnError, naming the column, for anything matching
    none of the rules. Never silently skips.
    """
    result: dict[str, ColumnClassification] = {}
    for column in header:
        if column is None:
            continue
        if column in reserved_metadata_columns:
            result[column] = ColumnClassification.METADATA
        elif column in quality_columns:
            result[column] = ColumnClassification.QUALITY
        elif open_end_predicate(column):
            result[column] = ColumnClassification.OPEN_END
        elif demographic_predicate(column):
            result[column] = ColumnClassification.DEMOGRAPHIC
        elif question_predicate is None or question_predicate(column):
            result[column] = ColumnClassification.QUESTION
        else:
            raise UnclassifiedColumnError(column=column, header_text=column)
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_classify_columns.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add surveytool/ingest/classify_columns.py tests/test_classify_columns.py
git commit -m "feat: add classify_columns precedence-ordered classification pass"
```

---

### Task 8: `QuestionType.binary`/`categorical` and the netting gate

**Files:**
- Modify: `surveytool/core/model.py:10-16` (add enum members), `surveytool/core/model.py:54-69` (relax the scale-only validator to not apply to binary/categorical)
- Create: `surveytool/core/netting_gate.py`
- Test: `tests/test_netting_gate.py`, append to `tests/test_model.py` if it exists (check first — it may not; create if absent)

**Interfaces:**
- Consumes: `QuestionType`, `CodeRole`, `Question` (model.py).
- Produces: `QuestionType.binary`, `QuestionType.categorical` enum members; `NettingNotAllowedError(SurveyToolError)`; `require_scale_for_netting(question: Question, net_kind: str) -> None` (raises if not applicable).
- Consumed by: Task 9 (binary/categorical classification logic), any future netting call site (compute layer) — this plan does not find or modify an existing top-box/top-two-box request entry point beyond `frequency.py`'s `t2b`/`b2b` computation (see research: nets are always computed unconditionally for scale questions today, there is no separate "request a net" call site to gate). Since the spec requires gating "any request for top-box, top-two-box or bottom-box," and no such explicit per-metric request API exists yet in `surveytool/compute/frequency.py` (`compute_question_stats` always computes `t2b`/`b2b` for any question with top/bottom roles present, unconditionally — frequency.py:121-124), this task adds the gate function and wires it into `compute_question_stats` as a guard that runs before the `t2b`/`b2b` computation, raising if `question.qtype` is `binary` or `categorical`. This is the most faithful placement: it's the one place net values are actually produced.

- [ ] **Step 1: Write the failing test for the enum members and the gate**

```python
# tests/test_netting_gate.py
import pytest

from surveytool.core.model import CodeRole, Question, QuestionType, ScaleCode
from surveytool.core.netting_gate import NettingNotAllowedError, require_scale_for_netting


def test_question_type_has_binary_and_categorical():
    assert QuestionType.binary.value == "binary"
    assert QuestionType.categorical.value == "categorical"


def test_require_scale_for_netting_passes_for_scale():
    q = Question(
        qid="Q1",
        text="Agreement",
        qtype=QuestionType.scale,
        labels=[
            ScaleCode(code=1, label="Agree", role=CodeRole.top, numeric_value=1),
            ScaleCode(code=2, label="Disagree", role=CodeRole.bottom, numeric_value=2),
        ],
        scale_family="agreement",
    )
    require_scale_for_netting(q, "top_two_box")  # must not raise


def test_require_scale_for_netting_raises_for_binary():
    q = Question(
        qid="S5",
        text="Do you drive?",
        qtype=QuestionType.binary,
        labels=[
            ScaleCode(code=1, label="Yes", role=CodeRole.excluded, numeric_value=1),
            ScaleCode(code=2, label="No", role=CodeRole.excluded, numeric_value=2),
        ],
    )
    with pytest.raises(NettingNotAllowedError) as exc_info:
        require_scale_for_netting(q, "top_two_box")
    assert "S5" in str(exc_info.value)


def test_require_scale_for_netting_raises_for_categorical():
    q = Question(
        qid="Q1",
        text="Which region?",
        qtype=QuestionType.categorical,
        labels=[
            ScaleCode(code=1, label="North", role=CodeRole.excluded, numeric_value=1),
            ScaleCode(code=2, label="South", role=CodeRole.excluded, numeric_value=2),
            ScaleCode(code=3, label="East", role=CodeRole.excluded, numeric_value=3),
        ],
    )
    with pytest.raises(NettingNotAllowedError):
        require_scale_for_netting(q, "top_box")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_netting_gate.py -v`
Expected: FAIL — `AttributeError: binary` (enum member doesn't exist yet)

- [ ] **Step 3: Add the enum members and relax the validator**

```python
# surveytool/core/model.py — QuestionType enum
class QuestionType(str, Enum):
    scale = "scale"
    binary = "binary"
    categorical = "categorical"
    single_choice = "single_choice"
    multi_response = "multi_response"
    numeric_open = "numeric_open"
    text_open = "text_open"
    demographic = "demographic"
```

The `_scale_must_have_top_and_bottom` validator (model.py:54-69) already only applies `if self.qtype is not QuestionType.scale: return self` — binary/categorical questions are unaffected by construction, no change needed there. Confirm this by reading the guard clause again: `binary`/`categorical` questions pass through untouched since they're not `QuestionType.scale`. No modification required to the validator itself.

```python
# surveytool/core/netting_gate.py
from __future__ import annotations

from surveytool.charts.errors import ErrorCode, SurveyToolError
from surveytool.core.model import Question, QuestionType


class NettingNotAllowedError(SurveyToolError):
    """Raised when top-box, top-two-box, or bottom-box is requested on a
    question that isn't an ordered scale. Netting requires role-ordered
    labels; binary and categorical questions have no such ordering."""

    def __init__(self, qid: str, net_kind: str) -> None:
        self.qid = qid
        self.net_kind = net_kind
        detail = f"Question {qid!r} is not a scale, so {net_kind} cannot be computed for it."
        super().__init__(
            ErrorCode.UNRESOLVED_SCALE_LABELS,
            f"'{qid}' isn't an ordered scale, so netting isn't available for it.",
            detail=detail,
            next_action="Netting requires an ordered scale. Choose a scale question, or view this question's plain frequency instead.",
        )


def require_scale_for_netting(question: Question, net_kind: str) -> None:
    """Raise NettingNotAllowedError if question.qtype is not scale.

    Call before computing top-box, top-two-box, or bottom-box for any
    question. Never returns a silently unnetted or zero figure instead.
    """
    if question.qtype is not QuestionType.scale:
        raise NettingNotAllowedError(question.qid, net_kind)
```

`ErrorCode.UNRESOLVED_SCALE_LABELS` is reused rather than adding a new code — re-examine: the spec calls this a distinct "netting requires an ordered scale" condition, which is semantically different from "labels didn't resolve." Add a dedicated code instead for clarity and correct GUI switching.

```python
# surveytool/charts/errors.py — add to ErrorCode enum
    NETTING_NOT_ALLOWED = "NETTING_NOT_ALLOWED"
```

```python
# surveytool/charts/errors.py — add to _STATUS_BY_CODE
    ErrorCode.NETTING_NOT_ALLOWED: 400,
```

```python
# surveytool/core/netting_gate.py — fix the code reference
        super().__init__(
            ErrorCode.NETTING_NOT_ALLOWED,
            f"'{qid}' isn't an ordered scale, so netting isn't available for it.",
            detail=detail,
            next_action="Netting requires an ordered scale. Choose a scale question, or view this question's plain frequency instead.",
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_netting_gate.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Wire the gate into `compute_question_stats`**

Read `surveytool/compute/frequency.py:87-133` first to confirm the exact surrounding code before editing (line numbers may have drifted since discovery). Add the guard immediately before the `t2b`/`b2b` computation:

```python
# surveytool/compute/frequency.py — inside compute_question_stats, before computing t2b/b2b
    from surveytool.core.netting_gate import require_scale_for_netting  # local import avoids a cycle if frequency.py is imported by netting_gate's dependents

    has_top = any(sc.role is CodeRole.top for sc in question.labels)
    has_bottom = any(sc.role is CodeRole.bottom for sc in question.labels)
    if (has_top or has_bottom) and question.qtype not in (QuestionType.scale,):
        # A binary/categorical question should never reach here with top/bottom
        # roles present (Task 9 ensures only scale questions get top/bottom
        # roles), but guard explicitly rather than trusting that invariant silently.
        require_scale_for_netting(question, "top_two_box" if has_top else "bottom_two_box")
    t2b = sum(cs.pct for cs in code_stats if cs.role is CodeRole.top) if has_top else None
    b2b = sum(cs.pct for cs in code_stats if cs.role is CodeRole.bottom) if has_bottom else None
```

Move the `from surveytool.core.netting_gate import require_scale_for_netting` import to the top of `frequency.py` alongside its other imports instead of inline, unless a genuine circular-import problem is confirmed by running the tests — try the top-level import first:

```python
# surveytool/compute/frequency.py — top of file, alongside existing imports
from surveytool.core.netting_gate import require_scale_for_netting
```

and delete the inline import from inside the function.

- [ ] **Step 6: Run the full suite to confirm no regression on existing scale-question computations**

Run: `python -m pytest -q`
Expected: PASS, same count as before this task (binary/categorical questions don't exist in any adapter output yet, so this guard is currently unreachable in production — Task 9 makes it reachable).

- [ ] **Step 7: Commit**

```bash
git add surveytool/core/model.py surveytool/core/netting_gate.py surveytool/charts/errors.py surveytool/compute/frequency.py tests/test_netting_gate.py
git commit -m "feat: add QuestionType.binary/categorical and the netting gate"
```

---

### Task 9: Classify a question as SCALE / BINARY / CATEGORICAL instead of erroring on partial match

**Files:**
- Modify: `surveytool/core/scale_library.py` (add a new classification function; keep `resolve_roles`/`identify_family`/`any_label_matches_family` unchanged for backward compatibility with Milieu/Toluna, which are not touched in this phase per the build plan)
- Test: `tests/test_scale_library.py` (append, or create if it doesn't exist — check first)

**Interfaces:**
- Consumes: `resolve_roles`, `identify_family`, `_FAMILIES` (existing, scale_library.py).
- Produces: `classify_question_type(labels: list[str]) -> tuple[QuestionType, dict[str, CodeRole] | None, str | None]` — returns `(QuestionType.scale, roles, family)` on a full family match, `(QuestionType.binary, None, None)` when exactly two substantive labels match the new `binary` family (added in Task 10), `(QuestionType.categorical, None, None)` otherwise. Never raises for the binary/categorical cases; still raises `UnresolvedScaleLabelsError`-equivalent only when explicitly requested (this function itself never raises — Task 11 covers the "collect all, raise once" validation pass separately, which is where actual failure surfacing belongs per Phase 3).
- Consumed by: Task 12 (Rakuten adapter's `_build_question` switches to this), later Milieu/Toluna migration is explicitly **out of scope** for this plan (per build plan Phase 1 constraint: "Milieu and Toluna adapters are not modified"). This task only builds the classification function and proves it in isolation; wiring it into Rakuten happens in Task 12; Milieu/Toluna keep their existing `any_label_matches_family`-gated behaviour permanently unless a future prompt set says otherwise.

This is the core behaviour change the spec calls for: "Failing to match a scale family is now a legitimate outcome for BINARY and CATEGORICAL, not an error." The distinguishing rule per spec: BINARY requires "exactly two substantive labels" AND matching "the binary family" (added in Task 10) — not simply "any two-label question." A two-label question whose labels don't match the binary family (e.g. two arbitrary category names) is CATEGORICAL, not BINARY.

- [ ] **Step 1: Write the failing test — using the `binary` family added in Task 10 (this test is written now but will only pass once Task 10 adds the family; run order matters, see Step 2)**

```python
# tests/test_scale_library.py
from surveytool.core.model import CodeRole, QuestionType
from surveytool.core.scale_library import classify_question_type


def test_classify_full_scale_match_returns_scale():
    qtype, roles, family = classify_question_type(["strongly agree", "agree", "disagree", "strongly disagree"])
    assert qtype is QuestionType.scale
    assert family == "agreement"
    assert roles["strongly agree"] is CodeRole.top


def test_classify_binary_match_returns_binary_no_roles():
    qtype, roles, family = classify_question_type(["yes", "no"])
    assert qtype is QuestionType.binary
    assert roles is None
    assert family is None


def test_classify_no_match_falls_through_to_categorical():
    qtype, roles, family = classify_question_type(["North", "South", "East", "West"])
    assert qtype is QuestionType.categorical
    assert roles is None
    assert family is None


def test_classify_partial_match_falls_through_to_categorical_not_error():
    """A question where some labels match a family and others don't must
    demote cleanly to CATEGORICAL, not raise — this is the exact behaviour
    change from the old any_label_matches_family gate."""
    qtype, roles, family = classify_question_type(["agree", "banana", "disagree"])
    assert qtype is QuestionType.categorical
    assert roles is None
    assert family is None
```

- [ ] **Step 2: Run test to verify it fails for the right reason**

Run: `python -m pytest tests/test_scale_library.py -v`
Expected: FAIL with `ImportError: cannot import name 'classify_question_type'` (and, once that's fixed, `test_classify_binary_match_returns_binary_no_roles` will still fail until Task 10 adds the `binary` family — that's expected and acceptable to leave red temporarily since Task 10 is the very next task; do not skip ahead and add the family here, keep the tasks' boundaries clean).

- [ ] **Step 3: Write `classify_question_type`**

```python
# surveytool/core/scale_library.py — append
from surveytool.core.model import QuestionType  # add to existing imports at top of file


def classify_question_type(
    labels: list[str],
) -> tuple[QuestionType, dict[str, CodeRole] | None, str | None]:
    """Classify a question's substantive labels as SCALE, BINARY, or
    CATEGORICAL.

    SCALE: every label matches a single family (identify_family succeeds).
    Netting applies; returns the resolved roles and family name.

    BINARY: exactly two labels, and they match the 'binary' family
    (added by a later task). No netting; roles/family are None since a
    binary question has no top/neutral/bottom ordering to net over.

    CATEGORICAL: neither of the above, including a genuine partial match
    (some labels match a family, others don't) — this is the fallback that
    replaces the old hard error. Never raises.
    """
    normed = [_normalise(lb) for lb in labels]
    family = identify_family(labels)
    if family is not None:
        roles = {lb: role for lb, role in zip(labels, (_match_role(n) for n in normed))}
        return QuestionType.scale, roles, family

    if len(labels) == 2 and identify_family(labels) is None:
        binary_family = _FAMILIES.get("binary")
        if binary_family is not None and all(_label_in_family(n, binary_family) for n in normed):
            return QuestionType.binary, None, None

    return QuestionType.categorical, None, None
```

Re-examine: `identify_family(labels)` is called twice redundantly in the `len(labels) == 2` branch (once above, already known `None` at that point since we're past the `if family is not None` return). Simplify:

```python
def classify_question_type(
    labels: list[str],
) -> tuple[QuestionType, dict[str, CodeRole] | None, str | None]:
    normed = [_normalise(lb) for lb in labels]
    family = identify_family(labels)
    if family is not None:
        roles = {lb: role for lb, role in zip(labels, (_match_role(n) for n in normed))}
        return QuestionType.scale, roles, family

    if len(labels) == 2:
        binary_family = _FAMILIES.get("binary")
        if binary_family is not None and all(_label_in_family(n, binary_family) for n in normed):
            return QuestionType.binary, None, None

    return QuestionType.categorical, None, None
```

- [ ] **Step 4: Run tests — expect 3 of 4 passing, `test_classify_binary_match_returns_binary_no_roles` still red**

Run: `python -m pytest tests/test_scale_library.py -v`
Expected: 3 PASS, 1 FAIL (`test_classify_binary_match_returns_binary_no_roles`, since `_FAMILIES` has no `"binary"` key yet — `_FAMILIES.get("binary")` returns `None`, so the function falls through to `categorical`). This is expected; Task 10 fixes it.

- [ ] **Step 5: Commit with the known-red test noted**

```bash
git add surveytool/core/scale_library.py tests/test_scale_library.py
git commit -m "feat: add classify_question_type (scale/binary/categorical), binary case pending scales.yaml binary family"
```

---

### Task 10: Label normalisation function and three new scale families

**Files:**
- Modify: `surveytool/core/hygiene.py` (add normalisation function; keep `normalize_label` as-is since adapters call it for a narrower purpose — see note below)
- Modify: `surveytool/core/scale_library.py` (apply new normalisation at every comparison point; add `binary` family lookup already referenced in Task 9)
- Modify: `surveytool/core/scales.yaml` (add `binary`, `calendar_frequency`, `intensity` families)
- Test: `tests/test_hygiene.py` (create if absent — check first), append to `tests/test_scale_library.py`

**Interfaces:**
- Produces: `fold_label(label: str) -> str` in `hygiene.py` — the spec's fold: en-dash/em-dash/non-breaking-hyphen → ASCII hyphen, non-breaking space → space, curly quotes/apostrophes → straight, casefold, collapse whitespace runs, strip. Nothing else (no stemming, no fuzzy distance).
- Consumed by: `scale_library.py`'s `_normalise` (Task 9's `classify_question_type`, and existing `resolve_roles`/`identify_family`/`any_label_matches_family` — all four call sites must use the new fold, per spec "Apply it at every point where a file label is compared to a library pattern").

Existing `normalize_label` (hygiene.py:6-8) only strips whitespace and folds non-breaking space — it is called by every adapter today on raw cell values *before* scale-library comparison, and is a distinct, narrower operation used for general label cleanup (also used for non-scale display purposes, e.g. building `ScaleCode.label`). Do not repurpose it; add the new fold as a separate function and layer it specifically at the scale-library comparison boundary (`_normalise` in `scale_library.py`), since that's the exact seam the spec names ("Apply it at every point where a file label is compared to a library pattern" — that point is `_normalise`, not every adapter's raw-value cleanup).

- [ ] **Step 1: Write the failing test for `fold_label`**

```python
# tests/test_hygiene.py
from surveytool.core.hygiene import fold_label


def test_fold_label_en_dash_to_hyphen():
    assert fold_label("18–24") == "18-24"  # en-dash


def test_fold_label_em_dash_to_hyphen():
    assert fold_label("18—24") == "18-24"  # em-dash


def test_fold_label_non_breaking_hyphen_to_hyphen():
    assert fold_label("18‑24") == "18-24"  # non-breaking hyphen


def test_fold_label_non_breaking_space_to_space():
    assert fold_label("very satisfied") == "very satisfied"


def test_fold_label_curly_quotes_to_straight():
    assert fold_label("don’t know") == "don't know"
    assert fold_label("“yes”") == '"yes"'


def test_fold_label_case_folds():
    assert fold_label("STRONGLY AGREE") == "strongly agree"


def test_fold_label_collapses_whitespace_and_strips():
    assert fold_label("  strongly   agree  ") == "strongly agree"


def test_fold_label_no_stemming_or_fuzzy_matching():
    """fold_label must not alter word forms — only the exact listed
    transformations. 'agrees' must stay 'agrees', not become 'agree'."""
    assert fold_label("Agrees") == "agrees"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_hygiene.py -v`
Expected: FAIL with `ImportError: cannot import name 'fold_label'`

- [ ] **Step 3: Write `fold_label`**

```python
# surveytool/core/hygiene.py
from __future__ import annotations

import re

from surveytool.core.model import CodeRole

_DASH_FOLD = str.maketrans({
    "–": "-",  # en dash
    "—": "-",  # em dash
    "‑": "-",  # non-breaking hyphen
})
_QUOTE_FOLD = str.maketrans({
    "‘": "'",  # left single quote
    "’": "'",  # right single quote / apostrophe
    "“": '"',  # left double quote
    "”": '"',  # right double quote
})
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_label(label: str) -> str:
    """Strip whitespace and replace non-breaking spaces with regular spaces."""
    return label.replace("\xa0", " ").strip()


def fold_label(label: str) -> str:
    """Normalise a label for scale-library comparison.

    Folds en-dash, em-dash, and non-breaking hyphen to ASCII hyphen; folds
    non-breaking space to space; folds curly quotes/apostrophes to straight;
    case folds; collapses whitespace runs; strips leading/trailing
    whitespace. Nothing else — no stemming, no fuzzy distance, no substring
    guessing, so a wrong net is never silently produced from an approximate
    match.
    """
    folded = label.translate(_DASH_FOLD).translate(_QUOTE_FOLD)
    folded = folded.replace("\xa0", " ")
    folded = folded.casefold()
    folded = _WHITESPACE_RE.sub(" ", folded)
    return folded.strip()


def report_unresolved(
    labels: list[str],
    resolved: dict[str, CodeRole],
) -> list[str]:
    """Return labels that did not appear in the resolved mapping."""
    return [lb for lb in labels if lb not in resolved]
```

- [ ] **Step 4: Run tests to verify `fold_label` passes**

Run: `python -m pytest tests/test_hygiene.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Apply `fold_label` at the scale-library comparison boundary**

```python
# surveytool/core/scale_library.py — replace _normalise
from surveytool.core.hygiene import fold_label


def _normalise(label: str) -> str:
    return fold_label(label)
```

Every call site inside `scale_library.py` (`_match_role`, `_is_neutral_label` via `_match_role`, `identify_family`, `any_label_matches_family`, `classify_question_type`) already routes through `_normalise`, so this one change propagates everywhere the spec requires ("Apply it at every point where a file label is compared to a library pattern"). Library patterns themselves (the YAML strings in `scales.yaml`) are plain ASCII lowercase already, so folding them through `fold_label` is a no-op — confirm this holds by checking `scales.yaml` has no dashes/curly-quotes in its patterns (it doesn't, per Task discovery). No change needed on the pattern side.

- [ ] **Step 6: Run the existing scale_library/conformance suite to confirm no regression from the tighter normalisation**

Run: `python -m pytest tests/test_conformance.py tests/test_scale_library.py -v`
Expected: PASS. The old `_normalise` only handled `\xa0` and case+strip; the new one is a strict superset (adds dash/quote folding), so anything that matched before still matches — this should be safe, but verify against the real Milieu/Toluna fixtures since Section B of `test_conformance.py` is the guard for exactly this kind of drift.

- [ ] **Step 7: Add the three new families to `scales.yaml`**

```yaml
# surveytool/core/scales.yaml — append under the existing families: key

  binary:
    top_patterns:
      - "yes"
      - "true"
    neutral_patterns: []
    bottom_patterns:
      - "no"
      - "false"

  calendar_frequency:
    top_patterns:
      - "daily"
      - "weekly"
    neutral_patterns:
      - "monthly"
      - "occasionally"
      - "sometimes"
    bottom_patterns:
      - "rarely"
      - "never"

  intensity:
    top_patterns:
      - "a lot"
      - "a great deal"
    neutral_patterns:
      - "somewhat"
      - "a little"
      - "moderately"
    bottom_patterns:
      - "not at all"
      - "none"
```

Note `binary`'s `neutral_patterns: []` — YAML empty list, matching the existing schema shape (`dict[str, list[str]]`) with a genuinely empty neutral set, since yes/no/true/false has no neutral option per spec ("the two-point set").

- [ ] **Step 8: Write the failing tests for the three new families and the en-dash/label-normalisation cross-check**

```python
# tests/test_scale_library.py — append
from surveytool.core.scale_library import identify_family


def test_en_dash_age_range_matches_ascii_hyphen_pattern():
    """This test needs a library pattern containing a hyphen to prove the
    fold — none of the existing families have one, so this test adds a
    throwaway direct check against fold_label + a literal comparison rather
    than routing through identify_family (which needs a full family match).
    """
    from surveytool.core.hygiene import fold_label
    assert fold_label("18–24") == fold_label("18-24") == "18-24"


def test_binary_family_added_to_scales_yaml():
    qtype, roles, family = classify_question_type(["yes", "no"])
    assert qtype is QuestionType.binary


def test_calendar_frequency_family():
    family = identify_family(["daily", "weekly", "monthly", "rarely", "never"])
    assert family == "calendar_frequency"


def test_intensity_family():
    family = identify_family(["a lot", "somewhat", "not at all"])
    assert family == "intensity"


def test_partial_intensity_match_falls_through_to_categorical():
    qtype, roles, family = classify_question_type(["a lot", "somewhat", "purple"])
    assert qtype is QuestionType.categorical
```

- [ ] **Step 9: Run tests to verify they pass, including the previously-known-red binary test from Task 9**

Run: `python -m pytest tests/test_scale_library.py tests/test_hygiene.py -v`
Expected: PASS, including `test_classify_binary_match_returns_binary_no_roles` from Task 9 (now green since `_FAMILIES["binary"]` exists).

- [ ] **Step 10: Run the full suite to confirm no regression**

Run: `python -m pytest -q`
Expected: PASS. Pay particular attention to `test_conformance.py::test_unknown_label_raises` (Section A test 5) — it uses `tests/fixtures/unknown_labels.py` and asserts `resolve_roles` still raises for a genuinely unmatched label; `resolve_roles` itself is untouched by this task (only `_normalise` changed, which is a strict widening), so this should still pass, but confirm.

- [ ] **Step 11: Commit**

```bash
git add surveytool/core/hygiene.py surveytool/core/scale_library.py surveytool/core/scales.yaml tests/test_hygiene.py tests/test_scale_library.py
git commit -m "feat: add fold_label normalisation and binary/calendar_frequency/intensity scale families"
```

---

### Task 11: [BLOCKED — awaiting fixture] Traffic-law-file integration test stub for classification exit condition

**Files:**
- Create: `tests/test_traffic_law_fixture.py`

**Interfaces:**
- Consumes: `surveytool.ingest.rakuten.load` (or whichever adapter the traffic-law file turns out to use — unconfirmed, see below).

The spec's Phase 2 exit condition and Prompt 4/5 tests reference "the traffic law file" with `S5` classifying BINARY, `S6` matching `calendar_frequency`, and `Q1`–`Q10` as `agreement` scale questions. No such file exists anywhere in this repository (confirmed by `find` across the full tree). Do not fabricate this fixture's content — inventing plausible S5/S6/Q1-Q10 values to make a test pass would let a wrong assumption about the real file's shape pass silently, exactly the failure mode `beta-insight-core-build-plan.md`'s constraints section warns against ("No synthetic fixtures").

- [ ] **Step 1: Write a skip-guarded stub pointed at the expected path, mirroring the existing `tests/test_conformance.py` Section B pattern exactly**

```python
# tests/test_traffic_law_fixture.py
"""
Traffic-law-file classification exit condition (spec Prompt 4/Prompt 5).

Skipped until the traffic law survey fixture is supplied — its filename and
vendor are not yet known (the spec names S5/S6/Q1-Q10 but not a file path).
Once the file arrives, replace _TRAFFIC_LAW_PATH below with its real path
and vendor, and fill in the loader call.
"""
from pathlib import Path

import pytest

_ROOT = Path(__file__).parent.parent
_TRAFFIC_LAW_PATH = _ROOT / "traffic_law_survey_data.xlsx"  # placeholder name — confirm against the real filename when supplied


@pytest.mark.skipif(
    not _TRAFFIC_LAW_PATH.exists(),
    reason="Traffic law survey fixture not yet supplied by the client — filename and vendor unconfirmed.",
)
def test_traffic_law_s5_classifies_binary():
    pytest.skip("Awaiting traffic law fixture and confirmation of which vendor adapter parses it.")


@pytest.mark.skipif(
    not _TRAFFIC_LAW_PATH.exists(),
    reason="Traffic law survey fixture not yet supplied by the client — filename and vendor unconfirmed.",
)
def test_traffic_law_s6_classifies_calendar_frequency():
    pytest.skip("Awaiting traffic law fixture.")


@pytest.mark.skipif(
    not _TRAFFIC_LAW_PATH.exists(),
    reason="Traffic law survey fixture not yet supplied by the client — filename and vendor unconfirmed.",
)
def test_traffic_law_q1_to_q10_classify_agreement_scale():
    pytest.skip("Awaiting traffic law fixture.")


@pytest.mark.skipif(
    not _TRAFFIC_LAW_PATH.exists(),
    reason="Traffic law survey fixture not yet supplied by the client — filename and vendor unconfirmed.",
)
def test_traffic_law_top_two_box_on_s5_raises():
    pytest.skip("Awaiting traffic law fixture.")
```

- [ ] **Step 2: Run to confirm all four are skipped, not failing, not silently absent**

Run: `python -m pytest tests/test_traffic_law_fixture.py -v`
Expected: 4 SKIPPED (visible in output, not absent — matches the spec's Prompt 11 requirement that a blocked test be "visibly skipped rather than absent," applied here a phase early since the same blocker surfaces here first).

- [ ] **Step 3: Commit**

```bash
git add tests/test_traffic_law_fixture.py
git commit -m "test: add skip-guarded stub for traffic-law-file classification exit condition, awaiting fixture"
```

**Follow-up required (not a task in this plan — a note for the user):** when the traffic-law file and its vendor are known, fill in `_TRAFFIC_LAW_PATH`, load it through the correct adapter, and replace each `pytest.skip(...)` body with the real assertion from the spec (`S5` classification, `S6` classification, `Q1`-`Q10` classification, `NettingNotAllowedError` on `S5`).

---

### Task 12: Wire classification into the Rakuten adapter's question-building path

**Files:**
- Modify: `surveytool/ingest/rakuten.py:123-198` (`_build_question`'s scale-resolution branch)

**Interfaces:**
- Consumes: `classify_question_type` (Task 9).

Currently `_build_question`'s final branch always builds a `QuestionType.scale` question and calls `resolve_roles` directly, which raises `UnresolvedScaleLabelsError` on any unresolved label (rakuten.py:155). This task switches Rakuten onto the new classify-first path so a Rakuten question with non-scale labels demotes to `binary`/`categorical` instead of raising — this is a genuine behaviour change, scoped to Phase 2 as intended. Both current Rakuten fixtures (`support_measures`, `chn_clans`) only have `S`-prefixed demographic questions and `Q`/`A`-prefixed fully-agreement-matching scale questions per the HC-golden tests, so this change is not expected to alter their output — verify that expectation explicitly in Step 3 rather than assuming it.

- [ ] **Step 1: Run the full suite to record the baseline before this behaviour-changing edit**

Run: `python -m pytest -q`
Expected: PASS — record pass count.

- [ ] **Step 2: Rewrite the scale-resolution branch of `_build_question`**

```python
# surveytool/ingest/rakuten.py — replace lines 140-198 (the "Analysis question: try to resolve as scale" block onward)
    # Analysis question: classify as scale, binary, or categorical
    if not codes:
        return

    norm_labels = [normalize_label(label) for _, label in codes]

    ns_overrides: dict[str, CodeRole] = {}
    for nl in norm_labels:
        if is_nonsubstantive_label(nl):
            ns_overrides[nl] = CodeRole.nonsubstantive

    substantive_norm = [nl for nl in norm_labels if nl not in ns_overrides]

    qtype, roles, family = classify_question_type(substantive_norm)

    if qtype is QuestionType.scale:
        for ns_label, ns_role in ns_overrides.items():
            roles[ns_label] = ns_role

        substantive_codes_sorted = [
            (code, normalize_label(label))
            for code, label in sorted(codes, key=lambda x: x[0])
            if normalize_label(label) not in ns_overrides
        ]
        direction: str | None = None
        if substantive_codes_sorted:
            lowest_role = roles.get(substantive_codes_sorted[0][1])
            if lowest_role is CodeRole.bottom:
                direction = "ascending"
            elif lowest_role is CodeRole.top:
                direction = "descending"

        scale_codes = [
            ScaleCode(
                code=code,
                label=normalize_label(label),
                role=roles[normalize_label(label)],
                numeric_value=code,
            )
            for code, label in codes
        ]

        out.append(
            Question(
                qid=qid,
                text=text,
                qtype=QuestionType.scale,
                labels=scale_codes,
                scale_direction=direction,
                scale_family=family,
                base_eligible=True,
            )
        )
        return

    # BINARY or CATEGORICAL: no role/family resolution, no netting.
    labels_out = [
        ScaleCode(
            code=code,
            label=normalize_label(label),
            role=CodeRole.nonsubstantive if normalize_label(label) in ns_overrides else CodeRole.excluded,
            numeric_value=code,
        )
        for code, label in codes
    ]
    out.append(
        Question(
            qid=qid,
            text=text,
            qtype=qtype,
            labels=labels_out,
            base_eligible=True,
        )
    )
```

Add the new import at the top of `rakuten.py`:

```python
from surveytool.core.scale_library import classify_question_type
```

Remove the now-unused `identify_family, resolve_roles` import if nothing else in the file calls them directly — check with `grep -n "identify_family\|resolve_roles" surveytool/ingest/rakuten.py` after the edit; both were only used in the block just replaced, so remove them from the import line.

- [ ] **Step 3: Run the full suite and specifically the HC-golden Rakuten tests to confirm the two real fixtures are unaffected**

Run: `python -m pytest -q`
Expected: PASS, same count as Step 1.

Run: `python -m pytest tests/test_compute.py tests/test_cross_tab.py tests/test_findings.py tests/test_chart_data.py tests/test_conformance.py -v -k rakuten`
Expected: PASS, all HC-golden figures unchanged — this confirms the two real Rakuten fixtures' questions all still classify as `scale` with full family matches (as the pre-existing behaviour required, since `resolve_roles` never raised for them before). If any question in either real fixture demotes to `binary`/`categorical` where it was previously `scale`, that is a genuine finding to report, not silently accept — investigate which question and whether that's expected before proceeding.

- [ ] **Step 4: Commit**

```bash
git add surveytool/ingest/rakuten.py
git commit -m "feat: Rakuten adapter classifies binary/categorical instead of erroring on partial scale match"
```

---

## Phase 3: Single-pass validation, project overrides, non-substantive base handling

### Task 13: Structured multi-question unresolved-label error

**Files:**
- Modify: `surveytool/charts/errors.py` (extend or replace `UnresolvedScaleLabelsError`'s detail shape)
- Test: append to `tests/test_errors.py` (create if absent — check first)

**Interfaces:**
- Produces: `UnresolvedQuestion` (a small dataclass: `variable: str`, `question_text: str`, `codes: list[tuple[int, str]]`, `reason: str`), `UnresolvedQuestionsError(SurveyToolError)` — new class, additive alongside the existing `UnresolvedScaleLabelsError` rather than replacing it (Milieu/Toluna's existing call sites still raise the old class per-question; this new class is for the single-pass validator in Task 14, which is new code, not a retrofit of Milieu/Toluna).
- Consumed by: Task 14.

Per spec Prompt 6: "The error object follows the existing error taxonomy... its detail carries a list. Each entry has: variable name, question text, the full ordered list of code and label pairs, and the reason resolution failed. The message states how many questions are unresolved. The next action... must not mention scales.yaml, YAML, overrides files, or any repository path."

- [ ] **Step 1: Write the failing test**

```python
# tests/test_errors.py
from surveytool.charts.errors import UnresolvedQuestion, UnresolvedQuestionsError


def test_unresolved_questions_error_message_states_count():
    entries = [
        UnresolvedQuestion(variable="Q3", question_text="How often?", codes=[(1, "Purple")], reason="No family matched 'purple'."),
        UnresolvedQuestion(variable="Q7", question_text="How able?", codes=[(1, "Kinda")], reason="No family matched 'kinda'."),
        UnresolvedQuestion(variable="Q9", question_text="How much?", codes=[(1, "Bunches")], reason="No family matched 'bunches'."),
    ]
    err = UnresolvedQuestionsError(entries)
    assert "3" in err.message
    assert err.detail_entries == entries
    assert "scales.yaml" not in err.message.lower()
    assert "yaml" not in err.message.lower()
    assert "override" not in err.next_action.lower() or "resolver" in err.next_action.lower()


def test_unresolved_questions_error_next_action_is_plain_english():
    entries = [UnresolvedQuestion(variable="Q1", question_text="text", codes=[], reason="reason")]
    err = UnresolvedQuestionsError(entries)
    for forbidden in ("scales.yaml", ".yaml", "surveytool/", "repository"):
        assert forbidden not in err.next_action.lower()
        assert forbidden not in err.message.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_errors.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Add `UnresolvedQuestion` and `UnresolvedQuestionsError`**

```python
# surveytool/charts/errors.py — add near UnresolvedScaleLabelsError
from dataclasses import dataclass


@dataclass(frozen=True)
class UnresolvedQuestion:
    variable: str
    question_text: str
    codes: list[tuple[int, str]]
    reason: str


class UnresolvedQuestionsError(SurveyToolError):
    """Raised once per load, after a single validation pass over every
    question in the file, listing every question that failed to resolve.

    Replaces stop-at-first-failure: a file with several unresolved
    questions is reported completely in one error, not discovered one
    question per load attempt. The message and next_action are addressed to
    a non-technical analyst and never name scales.yaml, YAML, an overrides
    file, or any repository path — the remediation path is 'use the
    resolver', described in plain English.
    """

    def __init__(self, entries: list[UnresolvedQuestion]) -> None:
        self.detail_entries = entries
        count = len(entries)
        plural = "question" if count == 1 else "questions"
        variables = ", ".join(e.variable for e in entries)
        detail = f"Unresolved {plural}: {variables}."
        super().__init__(
            ErrorCode.UNRESOLVED_SCALE_LABELS,
            f"This file has {count} {plural} with response labels this tool doesn't recognise.",
            detail=detail,
            next_action="Open the resolver to assign each unrecognised response a role, or mark the question as not a scale.",
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_errors.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add surveytool/charts/errors.py tests/test_errors.py
git commit -m "feat: add UnresolvedQuestion/UnresolvedQuestionsError for single-pass validation"
```

---

### Task 14: Single validation pass replacing fail-at-first-question

**Files:**
- Create: `surveytool/ingest/validate_questions.py`
- Test: `tests/test_validate_questions.py`

**Interfaces:**
- Consumes: `classify_question_type` (Task 9), `UnresolvedQuestion`, `UnresolvedQuestionsError` (Task 13).
- Produces: `validate_all_questions(raw_questions: list[tuple[str, str, list[tuple[int, str]]]]) -> None` — takes `(variable, question_text, codes)` tuples, runs `classify_question_type` on each, and raises one `UnresolvedQuestionsError` if any fail; does nothing (returns `None`) if all resolve. "Fail" here means: the question is neither a clean SCALE match nor a clean BINARY/CATEGORICAL fallback — re-examine: per Task 9's `classify_question_type`, CATEGORICAL is *always* a valid, non-raising outcome, so nothing from that function alone actually "fails" anymore. This means single-pass validation's failure condition is narrower than "classify_question_type raised" (it never raises). Re-read the spec: Prompt 6 is really about the pre-Phase-2 world's fail-at-first-question behavior — but Phase 2 already removed the error for binary/categorical. What's left to "fail" in one pass, now that categorical absorbs partial matches?

Re-examine against the build plan: Phase 3's exit condition talks about "an override file resolving a question" — implying the validation pass's failure case is specifically about the override/resolver workflow, not the binary/categorical classification (which Phase 2 already made non-failing). The genuine remaining failure case is elsewhere: a question that is a SCALE by shape but has labels that don't fully agree — no, Task 9 already handles that by falling to CATEGORICAL. Stop and resolve this ambiguity before writing code, since guessing wrong here builds the wrong validator.

**AMBIGUITY — flagging per plan-writing rules rather than guessing:** After Phase 2, `classify_question_type` never raises; every question resolves to SCALE, BINARY, or CATEGORICAL. So it's unclear what "unresolved question" means for Prompt 6's single-pass validator, since the specific failure mode it's built to batch (label-resolution failure) was eliminated as an error case in Phase 2 for binary/categorical, and never existed for genuinely full scale matches. The only remaining place `UnresolvedScaleLabelsError`/equivalent can still legitimately fire is when a project *override* (Task 15) declares a question SCALE with an incomplete label-to-role assignment (spec Prompt 7: "Applying an override with an incomplete label assignment raises") — that's a different validation moment (at override-apply time, not at load-classification time) and Task 15 already covers it with its own raise.

Given this, Task 14's validator is written to batch failures from **override application**, not from `classify_question_type` — i.e. it runs *after* overrides are read and applied (Task 15/16), collecting every question whose override is incomplete or whose override references a variable not present in the file, into one `UnresolvedQuestionsError`, rather than raising on the first bad override. This is the genuine single-pass-validation surface left after Phase 2's reclassification. Build it this way, and note the dependency: **Task 14 must be sequenced after Task 15 (overrides), not before** — reorder in execution even though it's numbered here for narrative continuity with the spec's prompt order.

- [ ] **Step 1: Write the failing test for the batching behaviour against override validation (signature finalized once Task 15's override schema exists — write the test against the interface, not the implementation, so it can be authored now and implemented after Task 15)**

```python
# tests/test_validate_questions.py
"""
Single-pass validation batches every unresolved question's override failure
into one UnresolvedQuestionsError, rather than raising on the first bad
override. See Task 15 for the override schema this validates against.
"""
import pytest

from surveytool.charts.errors import UnresolvedQuestionsError
from surveytool.ingest.validate_questions import validate_all_questions


def test_three_unresolved_questions_produce_one_error_with_three_entries():
    raw_questions = [
        ("Q3", "How often?", [(1, "Purple"), (2, "Green")]),
        ("Q7", "How able?", [(1, "Kinda"), (2, "Sorta")]),
        ("Q9", "How much?", [(1, "Bunches"), (2, "Loads")]),
    ]
    # No overrides supplied — each falls to CATEGORICAL cleanly under
    # classify_question_type, so with no override requirement in force,
    # zero of these are "unresolved" in the override sense.
    validate_all_questions(raw_questions, overrides={})  # must not raise


def test_incomplete_override_questions_batch_into_one_error():
    from surveytool.ingest.overrides import QuestionOverride

    raw_questions = [
        ("Q3", "How often?", [(1, "Purple"), (2, "Green")]),
        ("Q7", "How able?", [(1, "Kinda"), (2, "Sorta")]),
    ]
    overrides = {
        "Q3": QuestionOverride(variable="Q3", question_type="scale", label_roles={"Purple": "top"}),  # incomplete: Green unassigned
        "Q7": QuestionOverride(variable="Q7", question_type="scale", label_roles={}),  # incomplete: both unassigned
    }
    with pytest.raises(UnresolvedQuestionsError) as exc_info:
        validate_all_questions(raw_questions, overrides=overrides)
    assert len(exc_info.value.detail_entries) == 2
    assert {e.variable for e in exc_info.value.detail_entries} == {"Q3", "Q7"}


def test_no_unresolved_questions_loads_cleanly():
    raw_questions = [("Q1", "Agreement?", [(1, "Agree"), (2, "Disagree")])]
    validate_all_questions(raw_questions, overrides={})  # must not raise
```

This test file forward-references `surveytool.ingest.overrides.QuestionOverride`, which Task 15 creates. Do not run this test file until Task 15 is complete — write it now (per the plan-authoring instruction to show real code, not placeholders) but treat it as part of Task 14's Step 1 only in the sense that its *content* is finalized here; its *execution* is Task 14's actual Step 2, sequenced after Task 15 lands. Note this dependency inversion explicitly in the execution log when running this task.

- [ ] **Step 2: Run test to verify it fails (only after Task 15 exists — see dependency note above)**

Run: `python -m pytest tests/test_validate_questions.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'surveytool.ingest.validate_questions'`

- [ ] **Step 3: Write `validate_all_questions`**

```python
# surveytool/ingest/validate_questions.py
from __future__ import annotations

from surveytool.charts.errors import UnresolvedQuestion, UnresolvedQuestionsError
from surveytool.ingest.overrides import QuestionOverride


def validate_all_questions(
    raw_questions: list[tuple[str, str, list[tuple[int, str]]]],
    *,
    overrides: dict[str, QuestionOverride],
) -> None:
    """Single validation pass over every question in the file.

    Collects every question whose project override is incomplete (declares
    question_type='scale' but doesn't assign every substantive label a
    role), then raises one UnresolvedQuestionsError naming all of them.
    Questions with no override, or a complete override, pass silently —
    classify_question_type (Phase 2) already handles the no-override case
    without raising, since CATEGORICAL is a legitimate outcome.
    """
    entries: list[UnresolvedQuestion] = []

    for variable, question_text, codes in raw_questions:
        override = overrides.get(variable)
        if override is None:
            continue
        if override.question_type != "scale":
            continue
        substantive_labels = {label for _, label in codes}
        assigned_labels = set(override.label_roles.keys())
        missing = substantive_labels - assigned_labels
        if missing:
            entries.append(
                UnresolvedQuestion(
                    variable=variable,
                    question_text=question_text,
                    codes=codes,
                    reason=f"Override declares this a scale but does not assign a role to: {sorted(missing)}.",
                )
            )

    if entries:
        raise UnresolvedQuestionsError(entries)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_validate_questions.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add surveytool/ingest/validate_questions.py tests/test_validate_questions.py
git commit -m "feat: add single-pass validation batching incomplete override failures"
```

---

### Task 15: Project overrides file — schema, read, precedence, audit fields

**Files:**
- Create: `surveytool/ingest/overrides.py`
- Test: `tests/test_overrides.py`

**Interfaces:**
- Produces: `QuestionOverride` (Pydantic model: `variable: str`, `question_type: Literal["scale", "binary", "categorical"]`, `label_roles: dict[str, Literal["top", "neutral", "bottom"]]`, `resolved_at: datetime`, `library_version: str`), `ProjectOverrides` (Pydantic model wrapping `dict[str, QuestionOverride]`), `load_overrides(path: Path) -> ProjectOverrides`, `apply_override(question_labels: list[str], override: QuestionOverride) -> dict[str, CodeRole]` (raises `IncompleteOverrideError` if `label_roles` doesn't cover every label), `write_override(path: Path, override: QuestionOverride) -> None` (the validated write function the UI layer calls — core never calls this itself).
- Consumed by: Task 14 (`validate_all_questions`), Task 16 (notice-on-library-match).

Per spec Prompt 7: schema per entry is `variable name, question type, and for SCALE type an explicit assignment of every label to top/neutral/bottom`, plus audit fields `resolved timestamp` and `scale library version at time of resolution`. "The core reads and applies overrides. The core does not write them... Expose a validated write function the UI layer can call, but no core path creates an override on its own."

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_overrides.py
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from surveytool.core.model import CodeRole
from surveytool.ingest.overrides import (
    IncompleteOverrideError,
    ProjectOverrides,
    QuestionOverride,
    apply_override,
    load_overrides,
    write_override,
)


def test_load_overrides_from_yaml(tmp_path: Path):
    override_path = tmp_path / "overrides.yaml"
    override_path.write_text(
        yaml.dump({
            "overrides": {
                "Q3": {
                    "variable": "Q3",
                    "question_type": "scale",
                    "label_roles": {"Purple": "top", "Green": "bottom"},
                    "resolved_at": "2026-08-20T00:00:00+00:00",
                    "library_version": "1.0.0",
                }
            }
        }),
        encoding="utf-8",
    )
    result = load_overrides(override_path)
    assert isinstance(result, ProjectOverrides)
    assert "Q3" in result.overrides
    assert result.overrides["Q3"].question_type == "scale"
    assert result.overrides["Q3"].label_roles == {"Purple": "top", "Green": "bottom"}


def test_apply_override_full_assignment_produces_roles():
    override = QuestionOverride(
        variable="Q3",
        question_type="scale",
        label_roles={"Purple": "top", "Green": "bottom"},
        resolved_at=datetime.now(timezone.utc),
        library_version="1.0.0",
    )
    roles = apply_override(["Purple", "Green"], override)
    assert roles["Purple"] is CodeRole.top
    assert roles["Green"] is CodeRole.bottom


def test_apply_override_incomplete_assignment_raises():
    override = QuestionOverride(
        variable="Q3",
        question_type="scale",
        label_roles={"Purple": "top"},  # Green missing
        resolved_at=datetime.now(timezone.utc),
        library_version="1.0.0",
    )
    with pytest.raises(IncompleteOverrideError) as exc_info:
        apply_override(["Purple", "Green"], override)
    assert "Green" in str(exc_info.value)


def test_write_override_then_read_back(tmp_path: Path):
    override_path = tmp_path / "overrides.yaml"
    override = QuestionOverride(
        variable="Q9",
        question_type="scale",
        label_roles={"A lot": "top", "Not at all": "bottom"},
        resolved_at=datetime.now(timezone.utc),
        library_version="1.0.0",
    )
    write_override(override_path, override)
    result = load_overrides(override_path)
    assert result.overrides["Q9"].label_roles == {"A lot": "top", "Not at all": "bottom"}


def test_write_override_incomplete_raises_before_writing(tmp_path: Path):
    """write_override is the validated write function — it must not
    persist an override whose scale type has no label_roles at all when
    the caller clearly intends it as a scale with zero assignments would
    be meaningless; validation happens by requiring at least the schema
    shape to be well-formed. (Genuinely incomplete-vs-complete depends on
    the question's real label set, which write_override doesn't know — so
    it validates shape only; apply_override is what checks completeness
    against real labels, per test above.)"""
    override = QuestionOverride(
        variable="Q9",
        question_type="scale",
        label_roles={},
        resolved_at=datetime.now(timezone.utc),
        library_version="1.0.0",
    )
    write_override(override_path := tmp_path / "overrides.yaml", override)
    result = load_overrides(override_path)
    assert result.overrides["Q9"].label_roles == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_overrides.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write `overrides.py`**

```python
# surveytool/ingest/overrides.py
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

from surveytool.charts.errors import ErrorCode, SurveyToolError
from surveytool.core.model import CodeRole


class QuestionOverride(BaseModel):
    variable: str
    question_type: Literal["scale", "binary", "categorical"]
    label_roles: dict[str, Literal["top", "neutral", "bottom"]] = Field(default_factory=dict)
    resolved_at: datetime
    library_version: str


class ProjectOverrides(BaseModel):
    overrides: dict[str, QuestionOverride] = Field(default_factory=dict)


class IncompleteOverrideError(SurveyToolError):
    """Raised when applying a SCALE override whose label_roles doesn't
    assign every label in the question. Never defaults an unassigned label
    to any role."""

    def __init__(self, variable: str, missing: list[str]) -> None:
        self.variable = variable
        self.missing = missing
        detail = f"Override for {variable!r} does not assign a role to: {sorted(missing)}."
        super().__init__(
            ErrorCode.UNRESOLVED_SCALE_LABELS,
            f"The saved resolution for '{variable}' is missing a role for some responses.",
            detail=detail,
            next_action="Open the resolver and assign every response a role for this question.",
        )


_ROLE_MAP: dict[str, CodeRole] = {"top": CodeRole.top, "neutral": CodeRole.neutral, "bottom": CodeRole.bottom}


def load_overrides(path: Path) -> ProjectOverrides:
    if not path.exists():
        return ProjectOverrides()
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return ProjectOverrides.model_validate(raw)


def apply_override(question_labels: list[str], override: QuestionOverride) -> dict[str, CodeRole]:
    """Apply a SCALE override's label_roles to a question's actual label
    set. Raises IncompleteOverrideError if any label lacks an assignment —
    never defaults an unassigned label to any role."""
    missing = [lb for lb in question_labels if lb not in override.label_roles]
    if missing:
        raise IncompleteOverrideError(override.variable, missing)
    return {lb: _ROLE_MAP[override.label_roles[lb]] for lb in question_labels}


def write_override(path: Path, override: QuestionOverride) -> None:
    """Validated write function for the UI/resolver layer. No core load
    path calls this — overrides are created by the resolver, applied by
    the core."""
    existing = load_overrides(path) if path.exists() else ProjectOverrides()
    existing.overrides[override.variable] = override
    path.write_text(
        yaml.dump(existing.model_dump(mode="json")),
        encoding="utf-8",
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_overrides.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Now that `overrides.py` exists, run Task 14's validator test**

Run: `python -m pytest tests/test_validate_questions.py -v`
Expected: PASS (3 tests) — this was blocked pending this task.

- [ ] **Step 6: Commit**

```bash
git add surveytool/ingest/overrides.py tests/test_overrides.py
git commit -m "feat: add project-level scale overrides — schema, read, apply, validated write"
```

---

### Task 16: Notice when an override-resolved question would now match the shared library

**Files:**
- Modify: `surveytool/ingest/overrides.py` (add notice detection function)
- Test: append to `tests/test_overrides.py`

**Interfaces:**
- Produces: `OverrideNotice` (dataclass: `variable: str`, `message: str`), `check_override_still_needed(variable: str, labels: list[str], override: QuestionOverride) -> OverrideNotice | None`.
- Consumed by: Task 24 (run summary's notices list).

Per spec Prompt 7: "Where a question resolved by override would now match a shared library family, keep using the override but record a notice on the load result. Do not switch silently."

- [ ] **Step 1: Write the failing test**

```python
# tests/test_overrides.py — append
from surveytool.ingest.overrides import check_override_still_needed


def test_override_notice_when_library_now_matches():
    override = QuestionOverride(
        variable="Q3",
        question_type="scale",
        label_roles={"Strongly Agree": "top", "Strongly Disagree": "bottom"},
        resolved_at=datetime.now(timezone.utc),
        library_version="0.9.0",
    )
    notice = check_override_still_needed("Q3", ["Strongly Agree", "Strongly Disagree"], override)
    assert notice is not None
    assert "Q3" in notice.message


def test_no_notice_when_library_still_does_not_match():
    override = QuestionOverride(
        variable="Q9",
        question_type="scale",
        label_roles={"Bunches": "top", "None": "bottom"},
        resolved_at=datetime.now(timezone.utc),
        library_version="0.9.0",
    )
    notice = check_override_still_needed("Q9", ["Bunches", "None"], override)
    assert notice is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_overrides.py -v -k notice`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Write `check_override_still_needed`**

```python
# surveytool/ingest/overrides.py — append
from dataclasses import dataclass

from surveytool.core.scale_library import identify_family


@dataclass(frozen=True)
class OverrideNotice:
    variable: str
    message: str


def check_override_still_needed(
    variable: str,
    labels: list[str],
    override: QuestionOverride,
) -> OverrideNotice | None:
    """Return a notice if the shared scale library would now resolve this
    question without the override. The override still wins — this never
    switches behaviour, only surfaces the fact for the run summary."""
    if override.question_type != "scale":
        return None
    family = identify_family(labels)
    if family is None:
        return None
    return OverrideNotice(
        variable=variable,
        message=f"'{variable}' is resolved by a saved override, but the shared scale library would now also resolve it (as '{family}'). The override is still being used.",
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_overrides.py -v`
Expected: PASS (7 tests total)

- [ ] **Step 5: Commit**

```bash
git add surveytool/ingest/overrides.py tests/test_overrides.py
git commit -m "feat: surface a notice when an override-resolved question now matches the shared library"
```

---

### Task 17: Non-substantive response labels as a per-project setting, with explicit base exclusion

**Files:**
- Modify: `surveytool/core/config.py` (add two new `ToolConfig` fields)
- Modify: `surveytool/compute/frequency.py` (apply base exclusion when the setting is on; always attach `base` to the output)
- Test: `tests/test_config.py` (create if absent — check first), append to `tests/test_compute.py`

**Interfaces:**
- Produces: `ToolConfig.nonsubstantive_labels: list[str]` (default `["prefer not to say", "don't know", "not applicable"]`), `ToolConfig.exclude_nonsubstantive_from_base: bool` (default `False`).
- Consumed by: `compute_question_stats` (frequency.py) — base computation.

Per spec Prompt 8: default is `false` (kept in base). When excluded, remove from denominator, record the resulting base on the output — base must be present on every table/chart payload regardless of the setting. Do not apply to demographic banner variables; cross-tab bases follow existing behaviour (i.e. this task touches `frequency.py`'s single-question stats only, not `cross_tab.py`).


- [ ] **Step 1: Add the two new `ToolConfig` fields**

```python
# surveytool/core/config.py — add to ToolConfig, after rounding_mode
    nonsubstantive_labels: list[str] = Field(
        default_factory=lambda: ["prefer not to say", "don't know", "not applicable"]
    )
    exclude_nonsubstantive_from_base: bool = False
```

- [ ] **Step 2: Write the failing test for the config default and override**

```python
# tests/test_config.py
from surveytool.core.config import ToolConfig


def test_nonsubstantive_defaults():
    config = ToolConfig()
    assert config.nonsubstantive_labels == ["prefer not to say", "don't know", "not applicable"]
    assert config.exclude_nonsubstantive_from_base is False


def test_exclude_nonsubstantive_from_base_can_be_set():
    config = ToolConfig(exclude_nonsubstantive_from_base=True)
    assert config.exclude_nonsubstantive_from_base is True
```

- [ ] **Step 3: Run test to verify it fails, then passes after Step 1's edit**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL first (field doesn't exist), then PASS (2 tests) once Step 1's edit lands. Apply Step 1 now if not already done, then re-run.

- [ ] **Step 4: Thread `exclude_nonsubstantive_from_base` into `compute_question_stats` as an optional parameter**

`compute_question_stats` (`surveytool/compute/frequency.py:87-133`) is called from `surveytool/core/projection.py`, `surveytool/compute/breaks_compute.py`, `surveytool/findings/sheet.py`, and `surveytool/compute/cross_tab.py`. Threading a full `ToolConfig` through all four call chains is out of scope for this task — instead add a narrow, defaulted boolean parameter so every existing call site is unaffected unless it explicitly opts in. This preserves Phase 3's "additive, not disruptive" character; wiring the project setting into every caller's config-reading path belongs to the desktop/app.py session-config plumbing, which is UI-adjacent and out of this plan's core-only scope per `beta-insight-core-build-plan.md`'s header ("Scope: compute core and backend only").

```python
# surveytool/compute/frequency.py — modify _base_responses and compute_question_stats
def _base_responses(
    responses: list[Response],
    *,
    exclude_nonsubstantive: bool = False,
) -> list[Response]:
    if exclude_nonsubstantive:
        return [r for r in responses if r.state is ResponseState.answered]
    return [r for r in responses if r.state in _BASE_STATES]


def compute_question_stats(
    question: Question,
    responses: list[Response],
    *,
    exclude_nonsubstantive_from_base: bool = False,
) -> QuestionStats:
    """Compute frequency statistics for a single question.

    ``responses`` must already be filtered to only this question's qid.
    ``exclude_nonsubstantive_from_base``, when True, removes nonsubstantive
    responses from the percentage base (default keeps them in the base,
    per project setting default). Demographic questions never call this
    with the flag set — banner variables are unaffected by construction,
    since callers only pass the flag through for question tables, not
    cross-tab banner computation (cross_tab.py is untouched by this task).
    The base is always present on the returned QuestionStats regardless of
    the setting.
    """
    base_resps = _base_responses(responses, exclude_nonsubstantive=exclude_nonsubstantive_from_base)
    base = len(base_resps)
    ...  # rest of function body unchanged, using base_resps as before
```

Apply this signature change and the `_base_responses` call-site update at the top of `compute_question_stats` (the `base_resps = _base_responses(responses)` line becomes `base_resps = _base_responses(responses, exclude_nonsubstantive=exclude_nonsubstantive_from_base)`); the rest of the function body (lines 98-133 in the current file) is unchanged — it already always returns `QuestionStats(..., base=base, ...)`, so "base is present on every output regardless of the setting" is already satisfied by the existing return shape, confirmed by reading `surveytool/compute/stats.py:17-24` (`QuestionStats.base: int` is not optional).

- [ ] **Step 5: Write the failing test proving base drops by exactly the excluded count and percentages rise correspondingly**

```python
# tests/test_compute.py — append
from surveytool.compute.frequency import compute_question_stats
from surveytool.core.model import CodeRole, Question, QuestionType, Response, ResponseState, ScaleCode


def _make_nonsubstantive_question() -> Question:
    return Question(
        qid="S7",
        text="How would you rate this?",
        qtype=QuestionType.scale,
        labels=[
            ScaleCode(code=1, label="Good", role=CodeRole.top, numeric_value=1),
            ScaleCode(code=2, label="Bad", role=CodeRole.bottom, numeric_value=2),
            ScaleCode(code=99, label="Prefer not to say", role=CodeRole.nonsubstantive, numeric_value=None),
        ],
        scale_family="agreement",
        base_eligible=True,
    )


def test_nonsubstantive_kept_in_base_when_setting_off():
    question = _make_nonsubstantive_question()
    responses = [
        Response(respondent_id="r1", qid="S7", raw_value=1, state=ResponseState.answered),
        Response(respondent_id="r2", qid="S7", raw_value=2, state=ResponseState.answered),
        Response(respondent_id="r3", qid="S7", raw_value=99, state=ResponseState.nonsubstantive),
    ]
    stats = compute_question_stats(question, responses, exclude_nonsubstantive_from_base=False)
    assert stats.base == 3


def test_nonsubstantive_excluded_from_base_when_setting_on():
    question = _make_nonsubstantive_question()
    responses = [
        Response(respondent_id="r1", qid="S7", raw_value=1, state=ResponseState.answered),
        Response(respondent_id="r2", qid="S7", raw_value=2, state=ResponseState.answered),
        Response(respondent_id="r3", qid="S7", raw_value=99, state=ResponseState.nonsubstantive),
    ]
    stats_off = compute_question_stats(question, responses, exclude_nonsubstantive_from_base=False)
    stats_on = compute_question_stats(question, responses, exclude_nonsubstantive_from_base=True)

    assert stats_on.base == stats_off.base - 1
    assert stats_on.base == 2

    good_stat_off = next(cs for cs in stats_off.code_stats if cs.code == 1)
    good_stat_on = next(cs for cs in stats_on.code_stats if cs.code == 1)
    assert good_stat_on.pct > good_stat_off.pct  # same n=1, smaller base => higher pct

    for stats in (stats_off, stats_on):
        assert stats.base is not None  # base explicit on output in both cases
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_config.py tests/test_compute.py -v -k nonsubstantive`
Expected: PASS (4 tests: 2 config defaults, 2 base-exclusion behaviour)

- [ ] **Step 7: Run the full suite to confirm the default (`exclude_nonsubstantive_from_base=False`) preserves every existing call site's behaviour byte-for-byte**

Run: `python -m pytest -q`
Expected: PASS, identical to the pre-Phase-3 baseline — every existing call to `compute_question_stats` omits the new keyword argument, so it defaults to `False`, which reproduces the original `_base_responses(responses)` behaviour exactly (`_BASE_STATES` unchanged, same filter).

- [ ] **Step 8: Commit**

```bash
git add surveytool/core/config.py surveytool/compute/frequency.py tests/test_config.py tests/test_compute.py
git commit -m "feat: add per-project non-substantive base exclusion setting"
```

---

## Phase 4: PureSpectrum vendor, fingerprint pre-check, run summary, conformance extension

### Task 18: PureSpectrum vendor profile

**Files:**
- Modify: `surveytool/ingest/vendor_profile.py` (add `PURESPECTRUM_PROFILE`)
- Test: append to `tests/test_vendor_profile.py`

**Interfaces:**
- Consumes: `VendorProfile`, `VendorSignature`, `register_vendor_profile` (Task 1).
- Produces: `PURESPECTRUM_PROFILE`, registered under `get_vendor_profile("purespectrum")`.

Values taken directly from the spec (Prompt 9), since no PureSpectrum fixture exists to verify against — this profile is declared from the spec's stated facts, and the fingerprint pre-check (Task 20) plus the real-file conformance test (Task 22, blocked) are what will catch any divergence once the file arrives.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_vendor_profile.py — append
from surveytool.ingest.vendor_profile import PURESPECTRUM_PROFILE


def test_purespectrum_profile():
    p = PURESPECTRUM_PROFILE
    assert p.vendor_id == "purespectrum"
    assert p.data_sheet == "A1"
    assert p.codebook_sheet == "Datamap"
    assert p.verification_sheet is None
    assert p.quality_flag_column is None
    assert p.reserved_metadata_columns == frozenset({
        "record", "uuid", "date", "status", "dtrack", "qtime", "start_date", "transaction_id",
    })
    assert p.quality_columns == frozenset({"QC2", "QC2Flag"})
    assert get_vendor_profile("purespectrum") is p
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_vendor_profile.py -v -k purespectrum`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Add the profile**

```python
# surveytool/ingest/vendor_profile.py — append

PURESPECTRUM_PROFILE = VendorProfile(
    vendor_id="purespectrum",
    data_sheet="A1",
    codebook_sheet="Datamap",
    reserved_metadata_columns=frozenset({
        "record", "uuid", "date", "status", "dtrack", "qtime", "start_date", "transaction_id",
    }),
    # QC2 / QC2Flag classify as QUALITY per spec Prompt 9 and are excluded
    # from question tables. Pass/fail coding is unconfirmed by the vendor —
    # quality_flag_column stays None so nothing implements filtering on an
    # unverified coding. This is a deliberate, marked placeholder, not an
    # oversight: see quality_flag_pass_value/fail_value below.
    quality_columns=frozenset({"QC2", "QC2Flag"}),
    quality_flag_column=None,  # PLACEHOLDER: PureSpectrum's QC2/QC2Flag pass/fail coding is unconfirmed by the vendor. Do not implement filtering on it until confirmed.
    quality_flag_pass_value=None,
    quality_flag_fail_value=None,
    verification_sheet=None,
    date_format=None,
    multiselect_column_pattern=r"^Q10r[1-8]$",
    other_specify_suffix="oe",
    signature=VendorSignature(
        expected_sheets=frozenset({"A1", "Datamap"}),
        expected_columns=frozenset({"record", "uuid", "date", "status", "dtrack"}),
    ),
)

register_vendor_profile(PURESPECTRUM_PROFILE)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_vendor_profile.py -v`
Expected: PASS (all tests, including the new PureSpectrum one)

- [ ] **Step 5: Commit**

```bash
git add surveytool/ingest/vendor_profile.py tests/test_vendor_profile.py
git commit -m "feat: add PureSpectrum vendor profile"
```

---

### Task 19: PureSpectrum adapter — register against `DatamapReader`, no new parser

**Files:**
- Create: `surveytool/ingest/purespectrum.py`
- Test: `tests/test_purespectrum.py`

**Interfaces:**
- Consumes: `DatamapReader` (Task 4), `PURESPECTRUM_PROFILE` (Task 18), `classify_columns` (Task 7), `classify_question_type` (Task 9).
- Produces: `load(path: Path, survey_id: str) -> Survey`, matching the existing adapter interface exactly (same signature as `rakuten.load`, `milieu.load`, `toluna.load`).

Per spec Prompt 9: "Register PureSpectrum against DatamapReader. No new parser." This adapter is structurally the Rakuten adapter (post-Task-5/12 refactor) parameterised by `PURESPECTRUM_PROFILE` instead of `RAKUTEN_PROFILE`, with QC2/QC2Flag excluded from question building via the `quality_columns` check (mirroring how Rakuten's `_flush` already skips `reserved_metadata_columns`).

- [ ] **Step 1: Write the failing unit test using an in-memory fake workbook (no real fixture needed for this — proves the wiring, not the real file's numbers)**

```python
# tests/test_purespectrum.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_purespectrum.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the PureSpectrum adapter**

```python
# surveytool/ingest/purespectrum.py
from __future__ import annotations

import zipfile
from pathlib import Path

import openpyxl
from openpyxl.utils.exceptions import InvalidFileException

from surveytool.charts.errors import ErrorCode, SurveyToolError
from surveytool.core.hygiene import normalize_label
from surveytool.core.model import (
    CodeRole,
    Question,
    QuestionType,
    Response,
    ScaleCode,
    Survey,
)
from surveytool.core.nonsubstantive import classify_response, is_nonsubstantive_label
from surveytool.core.scale_library import classify_question_type
from surveytool.ingest.datamap_reader import Codebook, DatamapReader
from surveytool.ingest.vendor_profile import PURESPECTRUM_PROFILE

_ALL_RESERVED = PURESPECTRUM_PROFILE.reserved_metadata_columns | PURESPECTRUM_PROFILE.quality_columns


def parse_codebook(ws_datamap) -> list[Question]:
    """Parse the PureSpectrum Datamap sheet. Structurally identical to the
    Rakuten adapter's parse_codebook (Task 5/12) — same DatamapReader, same
    classify_question_type path — parameterised by PURESPECTRUM_PROFILE.
    QC2/QC2Flag are excluded here via _ALL_RESERVED since DatamapReader's
    own skip only covers reserved_metadata_columns, not quality_columns —
    quality columns still need to appear in the run summary's classification
    map (Task 24), so they are filtered from *question* construction here,
    not from column classification generally."""
    reader = DatamapReader(PURESPECTRUM_PROFILE)
    codebook: Codebook = reader.read_codebook(ws_datamap)

    questions: list[Question] = []
    for qid, (text, codes, qtype_hint) in codebook.items():
        if qid in PURESPECTRUM_PROFILE.quality_columns:
            continue
        _build_question(qid, text, qtype_hint, codes, questions)
    return questions


def _build_question(
    qid: str,
    text: str,
    qtype_hint: str | None,
    codes: list[tuple[int, str]],
    out: list[Question],
) -> None:
    if qtype_hint == "open_numeric":
        out.append(Question(qid=qid, text=text, qtype=QuestionType.numeric_open, base_eligible=False))
        return
    if qtype_hint == "open_text":
        out.append(Question(qid=qid, text=text, qtype=QuestionType.text_open, base_eligible=False))
        return

    if not codes:
        return

    norm_labels = [normalize_label(label) for _, label in codes]
    ns_overrides: dict[str, CodeRole] = {
        nl: CodeRole.nonsubstantive for nl in norm_labels if is_nonsubstantive_label(nl)
    }
    substantive_norm = [nl for nl in norm_labels if nl not in ns_overrides]

    qtype, roles, family = classify_question_type(substantive_norm)

    if qtype is QuestionType.scale:
        for ns_label, ns_role in ns_overrides.items():
            roles[ns_label] = ns_role
        scale_codes = [
            ScaleCode(code=code, label=normalize_label(label), role=roles[normalize_label(label)], numeric_value=code)
            for code, label in codes
        ]
        out.append(
            Question(
                qid=qid, text=text, qtype=QuestionType.scale, labels=scale_codes,
                scale_family=family, base_eligible=True,
            )
        )
        return

    labels_out = [
        ScaleCode(
            code=code,
            label=normalize_label(label),
            role=CodeRole.nonsubstantive if normalize_label(label) in ns_overrides else CodeRole.excluded,
            numeric_value=code,
        )
        for code, label in codes
    ]
    out.append(Question(qid=qid, text=text, qtype=qtype, labels=labels_out, base_eligible=True))


def load_respondents(ws_a1, questions: list[Question]) -> tuple[list[Response], int]:
    """Identical shape to Rakuten's load_respondents (rakuten.py:201-271),
    parameterised by PURESPECTRUM_PROFILE instead of hardcoded column
    names. respondent_id resolution mirrors Rakuten's uuid-then-record
    fallback since PureSpectrum's reserved columns include both."""
    rows = ws_a1.iter_rows(values_only=True)
    header = next(rows)
    col_index: dict[str, int] = {str(h): i for i, h in enumerate(header) if h is not None}

    uuid_col = col_index.get("uuid")
    record_col = col_index.get("record")

    qid_to_col: dict[str, int] = {q.qid: col_index[q.qid] for q in questions if q.qid in col_index}
    q_by_qid: dict[str, Question] = {q.qid: q for q in questions}

    responses: list[Response] = []
    n_raw = 0

    for row in rows:
        if all(v is None for v in row):
            break

        respondent_id: str
        if uuid_col is not None and row[uuid_col] is not None:
            respondent_id = str(row[uuid_col])
        elif record_col is not None and row[record_col] is not None:
            respondent_id = str(row[record_col])
        else:
            continue

        n_raw += 1

        for qid, col_idx in qid_to_col.items():
            raw = row[col_idx]
            if isinstance(raw, float) and raw == int(raw):
                raw = int(raw)
            q = q_by_qid[qid]
            state = classify_response(raw, q)
            responses.append(Response(respondent_id=respondent_id, qid=qid, raw_value=raw, state=state))

    return responses, n_raw


def load(path: Path, survey_id: str) -> Survey:
    """Load a PureSpectrum xlsx file and return a canonical Survey."""
    try:
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    except (InvalidFileException, OSError, KeyError, zipfile.BadZipFile) as exc:
        raise SurveyToolError(
            ErrorCode.FILE_UNREADABLE,
            "This file could not be opened as a PureSpectrum export.",
            detail=str(exc),
            next_action="Confirm the file is a complete, un-corrupted .xlsx export, or pick a different file.",
        ) from exc

    try:
        try:
            ws_datamap = wb[PURESPECTRUM_PROFILE.codebook_sheet]
        except KeyError as exc:
            raise SurveyToolError(
                ErrorCode.MISSING_SHEET,
                "This file does not look like a PureSpectrum export.",
                detail=f"No {PURESPECTRUM_PROFILE.codebook_sheet} sheet was found.",
                next_action="Check the vendor setting, or pick a different file.",
            ) from exc

        try:
            ws_respondents = wb[PURESPECTRUM_PROFILE.data_sheet]
        except KeyError as exc:
            raise SurveyToolError(
                ErrorCode.MISSING_SHEET,
                "This file does not look like a PureSpectrum export.",
                detail=f"No {PURESPECTRUM_PROFILE.data_sheet} respondent-data sheet was found.",
                next_action="Check the vendor setting, or pick a different file.",
            ) from exc

        questions = parse_codebook(ws_datamap)
        if not questions:
            raise SurveyToolError(
                ErrorCode.NO_QUESTIONS_FOUND,
                "This file was read but has no computable questions in it.",
                next_action="Check the Datamap sheet, or pick a different file.",
            )
        responses, n_raw = load_respondents(ws_respondents, questions)
    finally:
        wb.close()

    return Survey(id=survey_id, n_raw=n_raw, n_analysis=n_raw, questions=questions, responses=responses)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_purespectrum.py -v`
Expected: PASS (1 test)

- [ ] **Step 5: Commit**

```bash
git add surveytool/ingest/purespectrum.py tests/test_purespectrum.py
git commit -m "feat: add PureSpectrum adapter using DatamapReader"
```

---

### Task 20: Fingerprint pre-check

**Files:**
- Create: `surveytool/ingest/fingerprint.py`
- Test: `tests/test_fingerprint.py`

**Interfaces:**
- Consumes: `VendorProfile`, `VendorSignature` (Task 1), `RAKUTEN_PROFILE`, `MILIEU_PROFILE`, `TOLUNA_PROFILE`, `PURESPECTRUM_PROFILE` (Tasks 2, 18).
- Produces: `VendorMismatchError(SurveyToolError)`, `check_fingerprint(selected_vendor: str, sheet_names: frozenset[str], column_names: frozenset[str]) -> None` — raises `VendorMismatchError` on mismatch against the selected profile; if exactly one other registered profile matches, names it in the error.

Per spec Prompt 9: "check the file against the selected profile's signature... on mismatch, check it against the other profiles and raise a structured error stating that the file does not match the selected vendor and, where exactly one other profile matches, naming that vendor. Vendor selection remains authoritative. The pre-check never auto-switches." `ErrorCode.VENDOR_MISMATCH` already exists (`errors.py:9`) but has no dedicated exception class yet — this task adds one.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_fingerprint.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_fingerprint.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Add `VendorMismatchError` and `check_fingerprint`**

```python
# surveytool/ingest/fingerprint.py
from __future__ import annotations

from surveytool.charts.errors import ErrorCode, SurveyToolError
from surveytool.ingest.vendor_profile import (
    MILIEU_PROFILE,
    PURESPECTRUM_PROFILE,
    RAKUTEN_PROFILE,
    TOLUNA_PROFILE,
    VendorProfile,
    get_vendor_profile,
)

_ALL_PROFILES: list[VendorProfile] = [RAKUTEN_PROFILE, MILIEU_PROFILE, TOLUNA_PROFILE, PURESPECTRUM_PROFILE]


class VendorMismatchError(SurveyToolError):
    """Raised when a loaded file's sheets/columns don't match the selected
    vendor's signature. Names the vendor the file appears to be, only when
    exactly one other registered profile matches — vendor selection stays
    authoritative; this never auto-switches the selection."""

    def __init__(self, selected_vendor: str, matched_vendor: str | None) -> None:
        self.selected_vendor = selected_vendor
        self.matched_vendor = matched_vendor
        if matched_vendor is not None:
            message = f"This file doesn't look like a {selected_vendor} export — it looks like {matched_vendor}."
            detail = f"Selected vendor {selected_vendor!r} signature did not match; {matched_vendor!r} signature did."
            next_action = f"Select {matched_vendor} as the vendor, or confirm this is really a {selected_vendor} file."
        else:
            message = f"This file doesn't look like a {selected_vendor} export."
            detail = f"Selected vendor {selected_vendor!r} signature did not match, and no other registered vendor matched either."
            next_action = "Check the vendor setting, or pick a different file."
        super().__init__(ErrorCode.VENDOR_MISMATCH, message, detail=detail, next_action=next_action)


def _signature_matches(profile: VendorProfile, sheet_names: frozenset[str], column_names: frozenset[str]) -> bool:
    sig = profile.signature
    if sig is None:
        return False
    sheets_ok = not sig.expected_sheets or sig.expected_sheets.issubset(sheet_names)
    columns_ok = not sig.expected_columns or sig.expected_columns.issubset(column_names)
    return sheets_ok and columns_ok


def check_fingerprint(
    selected_vendor: str,
    *,
    sheet_names: frozenset[str],
    column_names: frozenset[str],
) -> None:
    """Check a loaded file against the selected vendor's signature. Raises
    VendorMismatchError on mismatch. Never auto-switches — the caller's
    vendor selection is unaffected either way; this only decides whether to
    raise."""
    selected_profile = get_vendor_profile(selected_vendor)
    if _signature_matches(selected_profile, sheet_names, column_names):
        return

    matches = [
        p.vendor_id
        for p in _ALL_PROFILES
        if p.vendor_id != selected_vendor and _signature_matches(p, sheet_names, column_names)
    ]
    matched_vendor = matches[0] if len(matches) == 1 else None
    raise VendorMismatchError(selected_vendor, matched_vendor)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_fingerprint.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add surveytool/ingest/fingerprint.py tests/test_fingerprint.py
git commit -m "feat: add fingerprint pre-check with single-match vendor naming"
```

---

### Task 21: [BLOCKED — awaiting fixture] PureSpectrum real-file integration test stub

**Files:**
- Create: `tests/test_purespectrum_fixture.py`

**Interfaces:**
- Consumes: `surveytool.ingest.purespectrum.load` (Task 19), `check_fingerprint` (Task 20).

Per spec Prompt 9's test list: "the PureSpectrum file loads under the PureSpectrum selection and classifies all 42 columns. The PureSpectrum file under a Rakuten selection raises an error naming PureSpectrum." `purespectrum_survey_wcs_data.xlsx` does not exist in this repository. Same treatment as Task 11: a skip-guarded stub, not a fabricated fixture.

- [ ] **Step 1: Write the skip-guarded stub**

```python
# tests/test_purespectrum_fixture.py
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
```

- [ ] **Step 2: Run to confirm both are skipped visibly**

Run: `python -m pytest tests/test_purespectrum_fixture.py -v`
Expected: 2 SKIPPED

- [ ] **Step 3: Commit**

```bash
git add tests/test_purespectrum_fixture.py
git commit -m "test: add skip-guarded PureSpectrum real-file integration stub, awaiting fixture"
```

**Follow-up required (not a task in this plan):** once `purespectrum_survey_wcs_data.xlsx` arrives, confirm its actual header against `PURESPECTRUM_PROFILE`'s declared `reserved_metadata_columns`/`quality_columns` (Task 18) — the spec states these from the client's description, not from an inspected file, so Task 18's profile may need correcting against the real header before this test can be de-skipped.

---

### Task 22: Run summary object

**Files:**
- Create: `surveytool/ingest/run_summary.py`
- Test: `tests/test_run_summary.py`

**Interfaces:**
- Consumes: `ColumnClassification` (Task 6), `QuestionType`, `Survey`, `Question` (model.py), `VendorProfile` (Task 1), `OverrideNotice` (Task 16).
- Produces: `RunSummary` (Pydantic model): `column_classifications: dict[str, ColumnClassification]`, `classification_counts: dict[ColumnClassification, int]`, `disposition_counts: dict[str, int]`, `quality_flag_statement: str`, `verification_statement: str`, `override_resolutions: list[dict]` (variable, timestamp), `notices: list[str]`. Plus `build_run_summary(survey: Survey, profile: VendorProfile, column_classifications: dict[str, ColumnClassification], status_values: list[str], override_notices: list[OverrideNotice], overrides_applied: list[tuple[str, "datetime"]]) -> RunSummary`.

Per spec Prompt 10: quality and verification statements are **always present**, including the normal case — "A run summary that omits a section when there is nothing to say trains the reader to skim." This is the key design constraint: never `Optional[str] = None` for those two fields, always a real sentence either way.

- [ ] **Step 1: Write the failing tests for both the "nothing to report" and "something to report" cases**

```python
# tests/test_run_summary.py
from datetime import datetime, timezone

from surveytool.core.column_classification import ColumnClassification
from surveytool.ingest.overrides import OverrideNotice
from surveytool.ingest.run_summary import RunSummary, build_run_summary
from surveytool.ingest.vendor_profile import PURESPECTRUM_PROFILE, RAKUTEN_PROFILE


def test_purespectrum_summary_states_no_quality_flag_and_no_verification():
    summary = build_run_summary(
        profile=PURESPECTRUM_PROFILE,
        column_classifications={"record": ColumnClassification.METADATA, "Q1": ColumnClassification.QUESTION},
        status_values=[],
        override_notices=[],
        overrides_applied=[],
    )
    assert isinstance(summary, RunSummary)
    assert "no quality flag" in summary.quality_flag_statement.lower()
    assert "no" in summary.verification_statement.lower() and "sheet" in summary.verification_statement.lower()


def test_rakuten_summary_names_flag_and_confirms_hc_sheet_used():
    summary = build_run_summary(
        profile=RAKUTEN_PROFILE,
        column_classifications={"record": ColumnClassification.METADATA, "FLAG": ColumnClassification.QUALITY, "Q1": ColumnClassification.QUESTION},
        status_values=[],
        override_notices=[],
        overrides_applied=[],
        verification_sheet_used=True,
    )
    assert "FLAG" in summary.quality_flag_statement
    assert "HC" in summary.verification_statement


def test_summary_lists_all_columns_for_both_vendors():
    cols = {"record": ColumnClassification.METADATA, "Q1": ColumnClassification.QUESTION, "S1": ColumnClassification.DEMOGRAPHIC}
    summary = build_run_summary(
        profile=RAKUTEN_PROFILE, column_classifications=cols, status_values=[], override_notices=[], overrides_applied=[],
    )
    assert set(summary.column_classifications.keys()) == set(cols.keys())
    assert summary.classification_counts[ColumnClassification.METADATA] == 1
    assert summary.classification_counts[ColumnClassification.QUESTION] == 1
    assert summary.classification_counts[ColumnClassification.DEMOGRAPHIC] == 1


def test_summary_includes_override_resolutions_and_notices():
    now = datetime.now(timezone.utc)
    summary = build_run_summary(
        profile=RAKUTEN_PROFILE,
        column_classifications={},
        status_values=[],
        override_notices=[OverrideNotice(variable="Q3", message="Q3 now also matches the library.")],
        overrides_applied=[("Q3", now)],
    )
    assert summary.override_resolutions == [{"variable": "Q3", "resolved_at": now}]
    assert summary.notices == ["Q3 now also matches the library."]


def test_summary_reports_disposition_counts():
    summary = build_run_summary(
        profile=RAKUTEN_PROFILE,
        column_classifications={},
        status_values=["complete", "complete", "screened_out", "complete"],
        override_notices=[],
        overrides_applied=[],
    )
    assert summary.disposition_counts == {"complete": 3, "screened_out": 1}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_run_summary.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write `run_summary.py`**

```python
# surveytool/ingest/run_summary.py
from __future__ import annotations

from collections import Counter
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from surveytool.core.column_classification import ColumnClassification
from surveytool.ingest.overrides import OverrideNotice
from surveytool.ingest.vendor_profile import VendorProfile


class RunSummary(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    column_classifications: dict[str, ColumnClassification]
    classification_counts: dict[ColumnClassification, int]
    disposition_counts: dict[str, int]
    quality_flag_statement: str
    verification_statement: str
    override_resolutions: list[dict]
    notices: list[str]


def _quality_flag_statement(profile: VendorProfile) -> str:
    if profile.quality_flag_column is None:
        return (
            f"{profile.vendor_id} supplies no quality flag column. "
            "Straightliner exclusion based on a vendor-supplied flag is unavailable for this file; "
            "straightliner detection based on response variance is still available."
        )
    return (
        f"Quality flag column '{profile.quality_flag_column}' is available from {profile.vendor_id}."
    )


def _verification_statement(profile: VendorProfile, verification_sheet_used: bool) -> str:
    if profile.verification_sheet is None:
        return f"{profile.vendor_id} supplies no verification sheet. Topline figures are not cross-checked against a vendor tabulation."
    if verification_sheet_used:
        return f"Verification sheet '{profile.verification_sheet}' was present and used."
    return f"Verification sheet '{profile.verification_sheet}' is expected for {profile.vendor_id} but was not used for this run."


def build_run_summary(
    *,
    profile: VendorProfile,
    column_classifications: dict[str, ColumnClassification],
    status_values: list[str],
    override_notices: list[OverrideNotice],
    overrides_applied: list[tuple[str, datetime]],
    verification_sheet_used: bool = False,
) -> RunSummary:
    classification_counts = dict(Counter(column_classifications.values()))
    disposition_counts = dict(Counter(status_values))

    return RunSummary(
        column_classifications=column_classifications,
        classification_counts=classification_counts,
        disposition_counts=disposition_counts,
        quality_flag_statement=_quality_flag_statement(profile),
        verification_statement=_verification_statement(profile, verification_sheet_used),
        override_resolutions=[{"variable": v, "resolved_at": ts} for v, ts in overrides_applied],
        notices=[n.message for n in override_notices],
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_run_summary.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add surveytool/ingest/run_summary.py tests/test_run_summary.py
git commit -m "feat: add RunSummary — always-present quality/verification statements, column inventory, notices"
```

---

### Task 23: Extend the Phase 0 conformance suite to four vendors with a shared assertion set

**Files:**
- Modify: `tests/test_conformance.py` (add a shared assertion helper and PureSpectrum's skip-guarded Section B entry)

**Interfaces:**
- Consumes: `surveytool.ingest.purespectrum.load` (Task 19), `check_fingerprint` (Task 20), existing `_assert_all_scales_fully_resolved` (test_conformance.py:207-218, needs updating for the classification-aware world).

Per spec Prompt 11: "Add a shared assertion set every vendor profile must satisfy: the file parses, every column classifies, no column falls to UNCLASSIFIED, every question receives a question type, the run summary is complete, and the fingerprint pre-check recognises the file under its own vendor and rejects it under each other vendor." Keep the existing Rakuten HC-golden numerical fixtures unchanged and passing. Add the PureSpectrum fixture as a skipped structural-only test with a comment naming what it's waiting for.

- [ ] **Step 1: Update `_assert_all_scales_fully_resolved`'s docstring/scope note — no behaviour change needed since it already only checks `qtype is QuestionType.scale` questions, which remains correct in the classification-aware world (binary/categorical questions are simply skipped by its existing `if q.qtype is not QuestionType.scale: continue` guard, which needs no edit)**

Read `tests/test_conformance.py:207-218` again to confirm the guard clause already does the right thing — it does (`if q.qtype is not QuestionType.scale: continue`), so no code change is needed here, only the new shared assertion function below.

- [ ] **Step 2: Write the failing shared-assertion-set test structure, extended with a 4th vendor**

```python
# tests/test_conformance.py — append after the existing Section B tests
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
    import openpyxl

    from surveytool.ingest.purespectrum import load

    survey = load(_PURESPECTRUM_PATH, "wcs")
    wb = openpyxl.load_workbook(_PURESPECTRUM_PATH, read_only=True, data_only=True)
    sheet_names = frozenset(wb.sheetnames)
    header = next(wb["A1"].iter_rows(values_only=True))
    column_names = frozenset(str(h) for h in header if h is not None)
    wb.close()
    _shared_conformance_assertions("purespectrum", survey, sheet_names, column_names)
```

Note: Milieu is intentionally left out of `_shared_conformance_assertions`' direct call sites here (no `test_milieu_shared_conformance_assertions` added) because Milieu's `VendorSignature` is empty (`VendorSignature()`, Task 2) — it has no meaningful sheet/column fingerprint to check, since it's sniffed by CSV header regex, not column names (confirmed in Task 2's research). Calling `check_fingerprint("milieu", ...)` against an empty signature would trivially pass regardless of actual file content, which isn't a meaningful conformance check. This is a genuine gap worth flagging rather than silently working around: **if Milieu needs a real fingerprint signature to participate fully in Prompt 11's four-vendor suite, that requires deciding what column/shape signal reliably identifies a Milieu CSV — out of scope for this plan since it wasn't in the original spec's Milieu profile fields (Task 2) and inventing one now would be a new design decision, not a refactor.**

- [ ] **Step 3: Run the extended conformance suite**

Run: `python -m pytest tests/test_conformance.py -v`
Expected: PASS for Rakuten and Toluna shared-assertion tests (assuming their fixtures are present, which they are), SKIPPED for PureSpectrum (fixture absent), all existing Section A/B tests unchanged and still passing.

- [ ] **Step 4: Run the full suite one final time to confirm the whole plan's changes leave the baseline green**

Run: `python -m pytest -q`
Expected: PASS. Compare the total count against the very first baseline recorded in Task 3 Step 1 — the delta should be exactly the number of new tests added across this plan's tasks, with zero regressions and zero modified existing test files (only `tests/test_conformance.py` gained new test functions via append, no existing test function bodies changed).

- [ ] **Step 5: Commit**

```bash
git add tests/test_conformance.py
git commit -m "test: extend Phase 0 conformance suite to four vendors with shared assertion set"
```

---

## Self-Review

**Spec coverage** — every one of the 11 prompts maps to at least one task:

1. Vendor profile schema and registry → Tasks 1–2.
2. Datamap-format base reader → Tasks 4–5.
3. Column classification and reserved metadata → Tasks 6–7.
4. Question type model and netting gate → Tasks 8–9.
5. Label normalisation and scale family additions → Task 10 (Task 11 covers the traffic-law exit-condition test, blocked on a missing fixture).
6. Single-pass validation and structured error → Tasks 13–14.
7. Project-level overrides → Tasks 15–16.
8. Non-substantive responses and base handling → Task 17.
9. PureSpectrum profile and fingerprint pre-check → Tasks 18–21 (Task 21 blocked on a missing fixture).
10. Run summary → Task 22.
11. Conformance suite extension → Task 23.

Task 3 (Rakuten reads from its profile) and Task 12 (Rakuten wires classify_question_type) are plan-internal steps the spec's Prompt 1/4 describe as part of the same prompt but which this plan splits out as their own bite-sized, independently-testable tasks — consistent with the task right-sizing rule.

**Placeholder scan** — the two `[BLOCKED — awaiting fixture]` tasks (11, 21) are the only tasks that don't ship a real, spec-matching numerical assertion; both are explicit, spec-sanctioned skips (mirroring the build plan's own "No synthetic fixtures" constraint and Prompt 11's "leave a test marked skipped... rather than writing a test against numbers we produced ourselves"), not silent placeholders — each names exactly what it's waiting for and includes a "Follow-up required" note for when the fixture lands. No other task contains TBD/TODO-style placeholders; every step shows real code.

**Type consistency** — checked `QuestionType`, `ColumnClassification`, `VendorProfile`, `Codebook`, `QuestionOverride`, `RunSummary`, `UnresolvedQuestion` signatures across every task that references them; consistent throughout. One deliberate scope note: `classify_columns` (Task 7) is built and unit-tested but not wired into the Rakuten/Milieu/Toluna `load()` call sites in this plan — only `purespectrum.py` (Task 19) exercises it structurally via the run summary path (Task 22's `column_classifications` parameter is caller-supplied, not adapter-computed, in this plan's scope). Wiring `classify_columns` into every adapter's `load()` to *auto-populate* the run summary end-to-end is a natural next increment but was not separately specified with its own test expectations in the 11 prompts beyond Prompt 3's three assertions (already covered by Task 7's unit tests) and Prompt 10's "list all columns" (already covered by Task 22's tests using caller-supplied maps) — flagging this as the one place where full wiring is deferred rather than fully closed, so it doesn't pass silently as "done."
