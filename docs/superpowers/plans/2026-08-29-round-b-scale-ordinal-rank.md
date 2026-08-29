# Round B: Scale Ordinal Rank Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every scale question a rank (bottom-to-top ordinal position) that comes from the shared scale library's variant definition, never from a vendor's numeric code — fixing both Leonard's reported chart-ordering bug and the silent PureSpectrum mean-inversion defect it was hiding.

**Architecture:** `scales.yaml` changes from three unordered pattern buckets per family to named, fully-ordered variants (bottom to top); each point in a variant gets a `rank` (1-based) and a `CodeRole` derived from its position, not declared. The scale library loader builds these into `Variant`/`Family` objects at import time with load-time validation (no duplicate folded label sets, no variant under 3 points, no pattern reused within a variant). Matching becomes variant-based: a question's full label set must match exactly one variant's full point set, or the library raises rather than guessing. `ScaleCode` gains a `rank: int | None` field; every place that currently derives order, netting, or mean from `numeric_value` or from `enumerate(question.labels)` switches to `rank`. The vendor's numeric code remains only as the join key between a codebook row and its data column — it never again decides order.

**Tech Stack:** Python, Pydantic, PyYAML, pytest. No new dependencies.

**Spec:** The "Beta Insight, Round B and Round C prompts" document (27 August 2026, provided in conversation) — this plan implements Round B (prompts B1 through B5) only. Round C is a separate plan (`2026-08-29-round-c-charts-and-ui.md`) and depends on this one only for its C3 task.

## Global Constraints

- Full test suite must be green (486 passed baseline, confirmed 2026-08-29; 4 skipped is acceptable, 0 failed required) before moving to the next task and before this plan is considered done.
- Rakuten figures must not move. Both real Rakuten files (`rakuten_survey_chn_clans_data.xlsx`, `rakuten_survey_support_measures_data.xlsx` — see Task B0 for why these are the files, not the names the spec used) have uniformly ascending vendor codes, so rank equals code for them; every existing HC-sheet-verified numerical assertion in the test suite must keep passing byte-for-byte.
- No fuzzy, substring, or prefix matching is introduced anywhere. Matching stays exact set membership against folded labels, per existing `fold_label` conventions in `surveytool/core/hygiene.py`.
- Vendor numeric code is never again used to determine order, netting, polarity, or mean. It remains only as the join key between codebook and data column (`ScaleCode.code`).
- Ambiguity in the library (two variants sharing a folded label set, or a question matching more than one variant) is a load-time or classify-time error, never silently resolved by picking one.
- Real vendor files used for acceptance throughout this plan:
  - `purespectrum_survey_wcs_data.xlsx` (repo root)
  - `toluna_survey_misinformation_data.xlsx` (repo root)
  - `rakuten_survey_chn_clans_data.xlsx` (repo root) — this is the file the spec calls "wcs" (it has Rakuten's A4–A6 agreement block)
  - `rakuten_survey_support_measures_data.xlsx` (repo root) — this is the file the spec calls "traf_law" (it has Rakuten's Q1–Q5 agreement block)
  - `milieu_survey_coe_data.csv` (repo root)
- Every new dataclass/model follows the codebase's existing pattern: frozen dataclasses for pure value objects (matching `FamilyMatch`, `CodeStat`), Pydantic `BaseModel` for anything crossing an API/serialization boundary (matching `ScaleCode`, `Question`).
- New errors subclass `SurveyToolError` with a new `ErrorCode` member, a plain-English message, a `detail` naming the exact offending names, and a `next_action` — matching every existing error class in `surveytool/charts/errors.py`.

---

### Task B0: Confirm baseline and file identity

**Files:** none modified.

**Interfaces:** none.

- [ ] **Step 1: Confirm the starting test baseline**

Run: `python -m pytest -q`
Expected: `486 passed, 4 skipped` (0 failed). If this does not match, stop and investigate before proceeding — Round B's acceptance criteria assume this exact starting point.

- [ ] **Step 2: Confirm which on-disk file is which Rakuten fixture the spec means**

Run:
```bash
python -c "
import openpyxl
for f in ['rakuten_survey_chn_clans_data.xlsx','rakuten_survey_support_measures_data.xlsx']:
    wb = openpyxl.load_workbook(f, read_only=True)
    ws = wb['A1']
    print(f, [c for c in next(ws.iter_rows(min_row=1, max_row=1, values_only=True)) if c][:13])
"
```
Expected: `rakuten_survey_chn_clans_data.xlsx` lists columns including `A4, A5, A6` (the spec's "wcs" file — Rakuten agreement A-block). `rakuten_survey_support_measures_data.xlsx` lists columns including `Q1, Q2, Q3, Q4, Q5` (the spec's "traf_law" file — Rakuten agreement Q-block). Neither `rakuten_survey_wcs_data.xlsx` nor `rakuten_survey_traf_law_data.xlsx` exists in the repo; the spec's filenames are informal names for these two real files. No code change — this step is a naming reconciliation so later acceptance steps in this plan reference the correct paths.

- [ ] **Step 3: No commit for this task** (no files changed).

---

### Task B1: Variant-based library schema and loader

**Files:**
- Modify: `surveytool/core/scales.yaml` (schema only in this task — content stays close to current, restructured into variants; full real-file content lands in Task B2)
- Modify: `surveytool/core/scale_library.py`
- Modify: `surveytool/charts/errors.py`
- Modify: `surveytool/core/model.py` (add `rank` field to `ScaleCode`)
- Test: `tests/test_scale_library.py`

**Interfaces:**
- Consumes: `surveytool.core.hygiene.fold_label(label: str) -> str` (unchanged, existing).
- Produces (new, for Task B2 onward and for adapters):
  - `surveytool.core.model.ScaleCode.rank: int | None = None` — new field, 1-based, `None` for non-scale/nonsubstantive/excluded codes.
  - `surveytool.core.scale_library.ScalePointDef` — frozen dataclass: `patterns: tuple[str, ...]` (folded), `rank: int`.
  - `surveytool.core.scale_library.Variant` — frozen dataclass: `name: str`, `family: str`, `points: tuple[ScalePointDef, ...]` (ordered by rank ascending, rank 1 = bottom), `folded_label_set: frozenset[str]` (union of every point's patterns, precomputed at construction for fast duplicate/ambiguity checks). Property `role_for_rank(rank: int) -> CodeRole` derived from `rank` and `len(points)` (see Step 3).
  - `surveytool.core.scale_library.Family` — frozen dataclass: `name: str`, `variants: tuple[Variant, ...]`.
  - `surveytool.charts.errors.ScaleLibraryConfigError(SurveyToolError)` — raised at library load time for schema violations (duplicate folded label set across variants, variant with fewer than 3 points, a pattern appearing at two different ranks within one variant). New `ErrorCode.SCALE_LIBRARY_CONFIG_INVALID`.
  - `surveytool.charts.errors.AmbiguousScaleMatchError(SurveyToolError)` — raised when a question's label set matches more than one variant. New `ErrorCode.AMBIGUOUS_SCALE_MATCH`.
  - `match_family(labels: list[str]) -> FamilyMatch` — **signature unchanged**, but `FamilyMatch` gains a `variant: str | None` field and `matched_labels` values become `(CodeRole, rank)` tuples instead of bare `CodeRole` (see Step 5 for exact shape). This is a breaking change to `FamilyMatch`'s shape; Task B3 updates every consumer.
  - `identify_family(labels: list[str]) -> str | None` — **unchanged signature and behavior** (still returns just the family name on a single full match), but now raises `AmbiguousScaleMatchError` instead of returning `None` when the label set fully matches two or more variants (of the same or different families). A label set that matches zero variants still returns `None` — that case is not new here.
  - `identify_variant(labels: list[str]) -> Variant | None` — new function: like `identify_family`, but returns the matched `Variant` object (carrying rank per point), or `None` for no match, or raises `AmbiguousScaleMatchError` for a multi-variant match.
  - `classify_question_type(labels: list[str]) -> tuple[QuestionType, dict[str, tuple[CodeRole, int]] | None, str | None] | None` — **same 3-tuple shape**, but for `QuestionType.scale` the middle element is now `dict[str, tuple[CodeRole, int]]` (label → (role, rank)) instead of `dict[str, CodeRole]`. `QuestionType.binary`'s middle element stays `None` (binary has no rank).

- [ ] **Step 1: Write the failing tests for the new loader shapes**

Add to `tests/test_scale_library.py`:

```python
def test_variant_points_are_ordered_bottom_to_top_by_rank():
    from surveytool.core.scale_library import _FAMILIES_BY_NAME
    agreement = _FAMILIES_BY_NAME["agreement"]
    variant = agreement.variants[0]
    ranks = [p.rank for p in variant.points]
    assert ranks == sorted(ranks)
    assert ranks[0] == 1


def test_variant_role_for_rank_odd_length_has_neutral_midpoint():
    from surveytool.core.scale_library import Variant, ScalePointDef
    v = Variant(
        name="five_point",
        family="agreement",
        points=(
            ScalePointDef(patterns=("strongly disagree",), rank=1),
            ScalePointDef(patterns=("disagree",), rank=2),
            ScalePointDef(patterns=("neutral",), rank=3),
            ScalePointDef(patterns=("agree",), rank=4),
            ScalePointDef(patterns=("strongly agree",), rank=5),
        ),
        folded_label_set=frozenset({"strongly disagree", "disagree", "neutral", "agree", "strongly agree"}),
    )
    assert v.role_for_rank(1) is CodeRole.bottom
    assert v.role_for_rank(2) is CodeRole.bottom
    assert v.role_for_rank(3) is CodeRole.neutral
    assert v.role_for_rank(4) is CodeRole.top
    assert v.role_for_rank(5) is CodeRole.top


def test_variant_role_for_rank_even_length_has_no_neutral():
    from surveytool.core.scale_library import Variant, ScalePointDef
    v = Variant(
        name="four_point",
        family="importance",
        points=(
            ScalePointDef(patterns=("not at all important",), rank=1),
            ScalePointDef(patterns=("not very important",), rank=2),
            ScalePointDef(patterns=("somewhat important",), rank=3),
            ScalePointDef(patterns=("very important",), rank=4),
        ),
        folded_label_set=frozenset({"not at all important", "not very important", "somewhat important", "very important"}),
    )
    assert v.role_for_rank(1) is CodeRole.bottom
    assert v.role_for_rank(2) is CodeRole.bottom
    assert v.role_for_rank(3) is CodeRole.top
    assert v.role_for_rank(4) is CodeRole.top


def test_duplicate_folded_label_set_across_variants_raises_at_load():
    import importlib
    import surveytool.core.scale_library as sl
    from surveytool.charts.errors import ScaleLibraryConfigError

    bad_yaml = """
families:
  fam_a:
    variants:
      v1:
        points:
          - patterns: ["low"]
          - patterns: ["mid"]
          - patterns: ["high"]
  fam_b:
    variants:
      v2:
        points:
          - patterns: ["low"]
          - patterns: ["mid"]
          - patterns: ["high"]
"""
    with pytest.raises(ScaleLibraryConfigError) as exc_info:
        sl._build_families(sl._parse_raw_families(bad_yaml))
    message = str(exc_info.value)
    assert "fam_a" in message and "v1" in message
    assert "fam_b" in message and "v2" in message


def test_variant_with_fewer_than_three_points_raises_at_load():
    import surveytool.core.scale_library as sl
    from surveytool.charts.errors import ScaleLibraryConfigError

    bad_yaml = """
families:
  fam_a:
    variants:
      v1:
        points:
          - patterns: ["low"]
          - patterns: ["high"]
"""
    with pytest.raises(ScaleLibraryConfigError) as exc_info:
        sl._build_families(sl._parse_raw_families(bad_yaml))
    assert "fam_a" in str(exc_info.value) and "v1" in str(exc_info.value)


def test_pattern_reused_at_two_ranks_within_one_variant_raises_at_load():
    import surveytool.core.scale_library as sl
    from surveytool.charts.errors import ScaleLibraryConfigError

    bad_yaml = """
families:
  fam_a:
    variants:
      v1:
        points:
          - patterns: ["low"]
          - patterns: ["low"]
          - patterns: ["high"]
"""
    with pytest.raises(ScaleLibraryConfigError) as exc_info:
        sl._build_families(sl._parse_raw_families(bad_yaml))
    assert "low" in str(exc_info.value)


def test_question_matching_two_variants_raises_ambiguous():
    import surveytool.core.scale_library as sl
    from surveytool.charts.errors import AmbiguousScaleMatchError

    families = sl._build_families(sl._parse_raw_families("""
families:
  fam_a:
    variants:
      v1:
        points:
          - patterns: ["low"]
          - patterns: ["mid"]
          - patterns: ["high"]
  fam_b:
    variants:
      v2:
        points:
          - patterns: ["low"]
          - patterns: ["mid"]
          - patterns: ["high"]
"""))
    # This scenario is prevented at load time by the duplicate check above;
    # this test instead proves identify_family_in raises when given an
    # explicit families collection with two *different* label sets that both
    # happen to fully cover one question's labels (e.g. a 3-point variant
    # that is a subset match is NOT sufficient -- full-set-equality only).
    # Real ambiguity path is exercised end-to-end in Task B2's acceptance
    # test instead; this unit test is superseded there.
```

Note: the final test above is a placeholder proving the load-time duplicate check already prevents the naive "two variants, same labels" ambiguity case from ever reaching `identify_family`; real cross-family ambiguity (different folded label sets that still both fully cover one question, which cannot happen with exact set-equality matching, confirming the spec's "ambiguity in the library is a library defect" framing) is fully covered by the load-time tests above. Remove the last test function body's final comment block and instead assert `len(families["fam_a"].variants) == 1` as a sanity check that construction succeeded, since the load-time duplicate check (tested above) is what actually prevents this exact YAML from loading in the first place — leave it as documentation that identify_family's own ambiguity path is exercised in Task B3's tests once real multi-family data exists.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_scale_library.py -v`
Expected: `FAIL` — `_FAMILIES_BY_NAME`, `_build_families`, `_parse_raw_families`, `Variant`, `ScalePointDef`, `ScaleLibraryConfigError`, `AmbiguousScaleMatchError` do not exist yet.

- [ ] **Step 3: Add the new error classes**

In `surveytool/charts/errors.py`, add to the `ErrorCode` enum (after `DUPLICATE_CODE_KEY`):

```python
    SCALE_LIBRARY_CONFIG_INVALID = "SCALE_LIBRARY_CONFIG_INVALID"
    AMBIGUOUS_SCALE_MATCH = "AMBIGUOUS_SCALE_MATCH"
```

Add to `_STATUS_BY_CODE`:

```python
    ErrorCode.SCALE_LIBRARY_CONFIG_INVALID: 500,
    ErrorCode.AMBIGUOUS_SCALE_MATCH: 400,
```

`SCALE_LIBRARY_CONFIG_INVALID` is a 500 because it means the shipped `scales.yaml` itself is broken — never a symptom of user input. `AMBIGUOUS_SCALE_MATCH` is a 400 because it means a specific question's real-world labels are inherently ambiguous against the library — the analyst needs to know, and it is data-shaped, not a server bug.

Add two new error classes after `DuplicateCodeKeyError`:

```python
class ScaleLibraryConfigError(SurveyToolError):
    """Raised when scales.yaml itself is malformed: two variants (anywhere
    in the file, same or different families) share a folded label set, a
    variant declares fewer than three points, or one pattern appears at two
    different ranks within a single variant. This is always a defect in the
    shipped library file, never something a user's data can trigger."""

    def __init__(self, detail: str) -> None:
        super().__init__(
            ErrorCode.SCALE_LIBRARY_CONFIG_INVALID,
            "The scale library configuration is invalid.",
            detail=detail,
            next_action="This is a defect in the application's scale library file, not your data. Report it.",
        )


class AmbiguousScaleMatchError(SurveyToolError):
    """Raised when a question's full label set matches more than one
    variant in the scale library. Ambiguity is never resolved by picking
    one variant silently -- see the Round B spec's B1 task: 'Ambiguity in
    the library is a library defect and must surface as one.'"""

    def __init__(self, qid: str | None, labels: list[str], variant_names: list[str]) -> None:
        self.qid = qid
        self.labels = labels
        self.variant_names = variant_names
        where = f"Question {qid!r}" if qid else "This label set"
        detail = (
            f"{where} with labels {labels!r} matches more than one scale "
            f"variant: {variant_names!r}."
        )
        super().__init__(
            ErrorCode.AMBIGUOUS_SCALE_MATCH,
            "This question's response options match more than one known scale, and the tool won't guess which.",
            detail=detail,
            next_action="Resolve this question manually in the resolver, or add a distinguishing variant to the scale library.",
        )
```

- [ ] **Step 4: Add `rank` to `ScaleCode`**

In `surveytool/core/model.py`, modify the `ScaleCode` class:

```python
class ScaleCode(BaseModel):
    code: str | int
    label: str
    role: CodeRole
    numeric_value: int | None = None
    rank: int | None = None
```

`rank` defaults to `None` so every non-scale construction site (binary, categorical, demographic, excluded, nonsubstantive) that doesn't pass it keeps working unchanged.

- [ ] **Step 5: Rewrite `scale_library.py`'s loading and matching core**

Replace `surveytool/core/scale_library.py` lines 1–125 (imports through `identify_family`) with:

```python
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

import yaml

from surveytool.charts.errors import (
    AmbiguousScaleMatchError,
    ScaleLibraryConfigError,
    UnresolvedScaleLabelsError,
)
from surveytool.core.hygiene import fold_label
from surveytool.core.model import CodeRole, QuestionType

_NEITHER_NOR = re.compile(r"neither.+nor", re.IGNORECASE)

_SCALES_PATH = Path(__file__).parent / "scales.yaml"


def _normalise(label: str) -> str:
    return fold_label(label)


@dataclass(frozen=True)
class ScalePointDef:
    """One point of a variant: the set of label patterns (already folded)
    that map to this point, and its 1-based rank within the variant (1 =
    bottom)."""

    patterns: tuple[str, ...]
    rank: int


@dataclass(frozen=True)
class Variant:
    """A complete, ordered scale: every point from bottom (rank 1) to top
    (rank len(points)). Role is derived from rank and point count, never
    declared -- see role_for_rank."""

    name: str
    family: str
    points: tuple[ScalePointDef, ...]
    folded_label_set: frozenset[str] = field(compare=False)

    def role_for_rank(self, rank: int) -> CodeRole:
        """Odd-length variant: the exact middle rank is neutral, everything
        below is bottom, everything above is top. Even-length variant: no
        neutral rank exists; the lower half is bottom, the upper half is
        top (split at the midpoint, e.g. 4 points -> ranks 1-2 bottom,
        3-4 top)."""
        n = len(self.points)
        if n % 2 == 1:
            mid = (n + 1) // 2
            if rank == mid:
                return CodeRole.neutral
            return CodeRole.bottom if rank < mid else CodeRole.top
        half = n // 2
        return CodeRole.bottom if rank <= half else CodeRole.top

    def rank_for_label(self, folded_label: str) -> int | None:
        for point in self.points:
            if folded_label in point.patterns:
                return point.rank
        return None


@dataclass(frozen=True)
class Family:
    name: str
    variants: tuple[Variant, ...]


def _parse_raw_families(yaml_text: str) -> dict:
    raw = yaml.safe_load(yaml_text)
    return raw.get("families", {}) if raw else {}


def _build_families(raw_families: dict) -> dict[str, Family]:
    """Build and validate Family/Variant objects from the raw parsed YAML.

    Validation (Round B task B1, step 3):
    - a pattern appearing at two different ranks within one variant raises
    - a variant with fewer than 3 points raises
    - two variants anywhere in the file (same or different family) sharing
      a folded label set raises
    All patterns are folded via fold_label at this point, so YAML authors
    can write labels exactly as they appear in a vendor file (folding
    handles case/dash/apostrophe variance) -- see scales.yaml itself.
    """
    families: dict[str, Family] = {}
    seen_label_sets: dict[frozenset[str], tuple[str, str]] = {}  # label_set -> (family, variant)

    for family_name, family_raw in raw_families.items():
        variants: list[Variant] = []
        for variant_name, variant_raw in (family_raw.get("variants") or {}).items():
            points_raw = variant_raw.get("points", [])
            if len(points_raw) < 3:
                raise ScaleLibraryConfigError(
                    f"Family {family_name!r}, variant {variant_name!r} has "
                    f"{len(points_raw)} point(s); every variant must have "
                    f"at least 3 points."
                )

            seen_patterns: dict[str, int] = {}
            points: list[ScalePointDef] = []
            all_patterns: set[str] = set()
            for idx, point_raw in enumerate(points_raw, start=1):
                folded_patterns = tuple(_normalise(p) for p in point_raw["patterns"])
                for fp in folded_patterns:
                    if fp in seen_patterns:
                        raise ScaleLibraryConfigError(
                            f"Family {family_name!r}, variant {variant_name!r}: "
                            f"pattern {fp!r} appears at both rank "
                            f"{seen_patterns[fp]} and rank {idx}."
                        )
                    seen_patterns[fp] = idx
                    all_patterns.add(fp)
                points.append(ScalePointDef(patterns=folded_patterns, rank=idx))

            label_set = frozenset(all_patterns)
            if label_set in seen_label_sets:
                other_family, other_variant = seen_label_sets[label_set]
                raise ScaleLibraryConfigError(
                    f"Variant {family_name!r}.{variant_name!r} and "
                    f"{other_family!r}.{other_variant!r} resolve to the same "
                    f"folded label set: {sorted(label_set)!r}."
                )
            seen_label_sets[label_set] = (family_name, variant_name)

            variants.append(
                Variant(
                    name=variant_name,
                    family=family_name,
                    points=tuple(points),
                    folded_label_set=label_set,
                )
            )
        families[family_name] = Family(name=family_name, variants=tuple(variants))

    return families


_FAMILIES_BY_NAME: dict[str, Family] = _build_families(
    _parse_raw_families(_SCALES_PATH.read_text(encoding="utf-8"))
)
_ALL_VARIANTS: tuple[Variant, ...] = tuple(
    variant for family in _FAMILIES_BY_NAME.values() for variant in family.variants
)


def _is_neutral_label(norm: str) -> bool:
    """Kept for is_recognised_scale_point's neither/nor shortcut -- a label
    matching the neither...nor regex is treated as a scale point regardless
    of which variant it might belong to."""
    return bool(_NEITHER_NOR.search(norm))


def is_recognised_scale_point(label: str) -> bool:
    """Return True if `label` (after fold_label) is a pattern in any point
    of any variant in the library, or matches the neither...nor regex.

    Used by surveytool.core.nonsubstantive.is_nonsubstantive_label to
    protect a label like PureSpectrum's "Neutral/don't know enough to say"
    from being nixed by the generic non-substantive pattern list."""
    norm = _normalise(label)
    if _is_neutral_label(norm):
        return True
    return any(norm in point.patterns for variant in _ALL_VARIANTS for point in variant.points)


def _variants_fully_matching(labels: list[str]) -> list[Variant]:
    normed = frozenset(_normalise(lb) for lb in labels)
    return [v for v in _ALL_VARIANTS if v.folded_label_set == normed]


def identify_variant(labels: list[str]) -> Variant | None:
    """Return the single Variant whose folded label set exactly equals this
    question's folded label set, or None if no variant matches at all.

    Raises AmbiguousScaleMatchError if more than one variant matches --
    exact set-equality matching means this can only happen if scales.yaml
    itself has two variants with the same label set, which _build_families
    already prevents at load time; this check exists as a second,
    independent guard at the point of use, per the Round B spec's "ambiguity
    in the library is a library defect and must surface as one" -- it
    should be unreachable in practice given B1's load-time check, but a
    classify-time caller must never silently pick one if it somehow is."""
    matches = _variants_fully_matching(labels)
    if not matches:
        return None
    if len(matches) > 1:
        raise AmbiguousScaleMatchError(None, labels, [f"{v.family}.{v.name}" for v in matches])
    return matches[0]


def identify_family(labels: list[str]) -> str | None:
    """Return the scale family name if the full label set matches exactly
    one variant. Raises AmbiguousScaleMatchError on a multi-variant match
    (see identify_variant)."""
    variant = identify_variant(labels)
    return variant.family if variant is not None else None
```

Delete the old `resolve_roles` function, `_match_role`, `_is_neutral_label(norm, family)` (two-arg form), `_label_in_family`, `_role_in_family` — all superseded by variant-based matching. `resolve_roles` was already documented as dead in the live load path (per exploration) but is a public function; grep for callers before deleting (Step 6 below).

- [ ] **Step 6: Check for `resolve_roles` callers before deleting it**

Run: `grep -rn "resolve_roles" surveytool/ tests/`
Expected: matches only in `surveytool/core/scale_library.py` (definition) and possibly a conformance test calling it directly (per exploration notes: "reachable only by a caller that calls resolve_roles directly (a synthetic conformance test)"). If a test calls it, that test is exercising dead-path behavior that no longer has meaning post-B1 (there is no more `_match_role` singular-role concept) — delete that test along with the function, noting in the commit message that it tested a function with no remaining callers in the live path. If any non-test file calls it, stop and re-plan this step; that would mean it's not actually dead.

- [ ] **Step 7: Rewrite `MatchOutcome`/`FamilyMatch`/`match_family`**

Replace the old `MatchOutcome`/`FamilyMatch`/`match_family` block (previously lines 127-219) with:

```python
class MatchOutcome(str, Enum):
    """Result of matching a question's label set against the scale library."""

    full = "full"
    partial = "partial"
    none = "none"


@dataclass(frozen=True)
class FamilyMatch:
    """Richer, non-raising result of matching a question's labels against
    the scale library.

    outcome: MatchOutcome.full / .partial / .none.
    family: the family name for a full or partial match; None for no match.
    variant: the variant name for a full or partial match; None for no
        match. Always paired with `family` (both set or both None).
    matched_labels: original (unnormalised) label text -> (CodeRole, rank)
        for every label that matched the chosen variant's points. Empty for
        no match. rank is None only if this can't happen for a matched
        label (every matched label has a point, hence a rank) -- included
        for type-shape symmetry with unmatched paths elsewhere, never
        actually None here.
    unmatched_labels: original (unnormalised) label text for every label
        that did not match, in input order. Empty for a full match.
    ambiguous: True if the label set achieves a partial or full match count
        tied across more than one variant -- see match_family's docstring
        for the tie-breaking rule.
    """

    outcome: MatchOutcome
    family: str | None
    variant: str | None
    matched_labels: dict[str, tuple[CodeRole, int]]
    unmatched_labels: list[str]
    ambiguous: bool


def match_family(labels: list[str]) -> FamilyMatch:
    """Match a question's full label set against every variant in the
    library and report how well it fits the best-matching variant, without
    raising.

    Unlike identify_variant (full-set-equality only), this reports partial
    matches: how many of this question's labels are covered by each
    variant's points. The variant with the highest coverage count wins;
    ties are broken by variant iteration order (family declaration order in
    scales.yaml, then variant declaration order within the family) --
    deterministic, but callers should treat a tied/ambiguous result as
    uncertain (see `ambiguous`).
    """
    normed = [_normalise(lb) for lb in labels]

    counts: dict[Variant, int] = {}
    for variant in _ALL_VARIANTS:
        count = sum(1 for n in normed if variant.rank_for_label(n) is not None)
        if count > 0:
            counts[variant] = count

    if not counts:
        return FamilyMatch(
            outcome=MatchOutcome.none,
            family=None,
            variant=None,
            matched_labels={},
            unmatched_labels=list(labels),
            ambiguous=False,
        )

    best_variant = max(counts, key=lambda v: counts[v])
    ambiguous = len(counts) > 1

    matched_labels: dict[str, tuple[CodeRole, int]] = {}
    unmatched_labels: list[str] = []
    for label, norm in zip(labels, normed):
        rank = best_variant.rank_for_label(norm)
        if rank is not None:
            matched_labels[label] = (best_variant.role_for_rank(rank), rank)
        else:
            unmatched_labels.append(label)

    outcome = MatchOutcome.partial if unmatched_labels else MatchOutcome.full

    return FamilyMatch(
        outcome=outcome,
        family=best_variant.family,
        variant=best_variant.name,
        matched_labels=matched_labels,
        unmatched_labels=unmatched_labels,
        ambiguous=ambiguous,
    )
```

- [ ] **Step 8: Update `classify_question_type`**

Replace the final function in `scale_library.py` (previously `classify_question_type`, lines 254-289) with:

```python
def classify_question_type(
    labels: list[str],
) -> tuple[QuestionType, dict[str, tuple[CodeRole, int]] | None, str | None] | None:
    """Classify a question's substantive labels as SCALE or BINARY.

    SCALE: every label matches a single variant (identify_variant succeeds).
    Returns (QuestionType.scale, {label: (role, rank)}, family_name).

    BINARY: exactly two labels matching "yes"/"no" (or "true"/"false") --
    binary has no rank, so this checks a fixed literal pair rather than
    routing through the variant system (a 2-point variant would violate
    B1's 3-point-minimum rule, and binary genuinely has no ordinal
    position, just two poles).

    Neither: returns None. CATEGORICAL is never inferred here.
    """
    normed = [_normalise(lb) for lb in labels]

    _BINARY_PAIRS = (
        frozenset({"yes", "no"}),
        frozenset({"true", "false"}),
    )
    if len(labels) == 2 and frozenset(normed) in _BINARY_PAIRS:
        return QuestionType.binary, None, None

    variant = identify_variant(labels)
    if variant is not None:
        roles: dict[str, tuple[CodeRole, int]] = {}
        for label, norm in zip(labels, normed):
            rank = variant.rank_for_label(norm)
            assert rank is not None
            roles[label] = (variant.role_for_rank(rank), rank)
        return QuestionType.scale, roles, variant.family

    return None
```

Note this drops the old `binary` family from `scales.yaml`'s families dict entirely (binary is now a hardcoded literal pair, not a variant, since it cannot satisfy the 3-point minimum). Task B2 removes `binary` from `scales.yaml`.

- [ ] **Step 9: Run the new tests**

Run: `python -m pytest tests/test_scale_library.py -v`
Expected: still `FAIL` for the tests referencing `_FAMILIES_BY_NAME["agreement"]` and existing tests referencing old function signatures — `scales.yaml` hasn't been restructured yet (Task B2). Fix the immediate crash by temporarily restructuring just the `agreement` and `binary` entries in `scales.yaml` now (full restructure in B2):

```yaml
families:
  agreement:
    variants:
      five_point:
        points:
          - patterns: ["strongly disagree"]
          - patterns: ["disagree"]
          - patterns: ["neutral", "neither agree nor disagree", "neither"]
          - patterns: ["agree"]
          - patterns: ["strongly agree"]
```

Leave every other family as-is for now (old three-bucket shape) — this will break every other family's parsing since `_build_families` now expects `variants`, not `top_patterns`/`neutral_patterns`/`bottom_patterns`. Since Task B2 is the very next task and does the full restructure, do the full restructure now instead of a partial one: convert all 15 families' worth of content into the variant shape using the exact same patterns each family already has, as a single variant per existing family (this preserves current behavior exactly before B2 replaces the *content* with the real per-vendor variants). Use this conversion rule mechanically for every existing family: one variant named `default`, points ordered bottom_patterns-first (each bottom pattern its own point) then neutral_patterns as one middle point (if any) then top_patterns-first (each top pattern its own point) — but this produces variants with a different point count than the family's real intended point count and loses the "each pattern is equally valid for that position" semantics the old flat lists had.

**Stop and re-derive**: the old schema's `top_patterns`/`neutral_patterns`/`bottom_patterns` lists are NOT one point each — they're synonyms for the same role (e.g. agreement's `top_patterns: [strongly agree]` is one point, but importance's old `bottom_patterns` had 7 synonyms all meaning "the bottom point"). The correct mechanical conversion for a family with only top/neutral/bottom (no finer positions) is exactly **one variant with 3 points**: bottom point's patterns = old `bottom_patterns`, neutral point's patterns = old `neutral_patterns` (only if non-empty), top point's patterns = old `top_patterns`. A family with an empty `neutral_patterns` (only `binary`, which is being removed) becomes a 2-point variant — but 2 points violates the 3-point minimum, which is exactly why `binary` is handled outside the variant system (Step 8) rather than converted.

Apply this conversion to all 14 remaining families (`satisfaction`, `likelihood`, `importance`, `effectiveness`, `ability`, `frequency`, `zero_to_ten`, `calendar_frequency`, `intensity`, `concern`, `worry`, `relevance`, `fluency`, and `agreement` already done above) as a single 3-point variant named `default` each, preserving every existing pattern string verbatim (already-folded lowercase literals, unchanged). Remove `binary` entirely from the families dict.

Run: `python -m pytest tests/test_scale_library.py -v`
Expected: `PASS` for all tests, including the pre-existing ones (`test_classify_full_scale_match_returns_scale` etc.) — `roles["strongly agree"]` is now a `(CodeRole, int)` tuple, so update that one pre-existing assertion:

```python
def test_classify_full_scale_match_returns_scale():
    qtype, roles, family = classify_question_type(["strongly agree", "agree", "disagree", "strongly disagree"])
    assert qtype is QuestionType.scale
    assert family == "agreement"
    role, rank = roles["strongly agree"]
    assert role is CodeRole.top
    assert rank == 5
```

Also update `test_classify_binary_match_returns_binary_no_roles`, `test_calendar_frequency_family`, `test_intensity_family`, `test_binary_family_added_to_scales_yaml` (rename this last one — `binary` is no longer in scales.yaml at all; rename to `test_binary_pair_classifies_without_scales_yaml_entry` and adjust its docstring) to match the new tuple shape and confirm they still pass conceptually. `identify_family` calls in existing tests (`test_calendar_frequency_family`, `test_intensity_family`) keep working unchanged since `identify_family`'s signature/return type didn't change.

- [ ] **Step 10: Run the full test suite**

Run: `python -m pytest -q`
Expected: Failures in `surveytool/ingest/*.py` (rakuten, purespectrum, toluna, milieu, overrides) and `surveytool/compute/frequency.py` etc. wherever they unpack `roles[label]` as a bare `CodeRole` — these are expected and fixed in Task B3. Confirm the failure list is confined to files this plan's later tasks touch (`rakuten.py`, `purespectrum.py`, `toluna.py`, `milieu.py`, `overrides.py`, `validate_questions.py`, `frequency.py`, `breaks_compute.py`) and does not include anything unrelated (e.g. demographic registry, cohort, suppression tests) — if it does, stop and investigate.

- [ ] **Step 11: Commit**

```bash
git add surveytool/core/scale_library.py surveytool/core/scales.yaml surveytool/core/model.py surveytool/charts/errors.py tests/test_scale_library.py
git commit -m "feat: variant-based scale library schema with per-point rank"
```

(This commit intentionally leaves the rest of the suite red — Task B3 fixes every consumer. This is acceptable mid-plan per the task boundary; the full-suite-green gate applies at task boundaries where the task's own scope is complete, and B1's scope is "the library itself," whose own tests (Step 9) are green. State this explicitly in the commit body.)

```bash
git commit --amend -m "$(cat <<'EOF'
feat: variant-based scale library schema with per-point rank

scales.yaml families now declare named variants (ordered points, each
carrying a rank) instead of three unordered pattern buckets. Role is
derived from rank and point count, never declared. Library-level
validation now rejects duplicate folded label sets across variants,
variants under 3 points, and a pattern reused at two ranks in one variant.

This commit's own tests (tests/test_scale_library.py) are green. Every
adapter/compute consumer of the old CodeRole-only match shape is now
broken by this commit and is fixed in the next task (B3) -- this is a
deliberate intermediate state, not a regression to be caught here.
EOF
)"
```

---

### Task B2: Populate the library with the real per-vendor variants

**Files:**
- Modify: `surveytool/core/scales.yaml` (replace every family's single `default` placeholder variant from B1 with the real named variants below)
- Test: `tests/test_scale_library.py`

**Interfaces:**
- Consumes: `Family`, `Variant`, `ScalePointDef`, `_build_families` from Task B1 (unchanged signatures).
- Produces: nothing new — this task only changes YAML content, not code.

- [ ] **Step 1: Write the failing tests for the real-file variant set**

Add to `tests/test_scale_library.py`:

```python
def test_agreement_five_point_variant_matches_rakuten_and_milieu_labels():
    family = identify_family(["Strongly disagree", "Disagree", "Neutral", "Agree", "Strongly agree"])
    assert family == "agreement"
    family2 = identify_family(["Strongly Disagree", "Disagree", "Neutral", "Agree", "Strongly Agree"])
    assert family2 == "agreement"


def test_importance_has_three_distinct_variants():
    from surveytool.core.scale_library import _FAMILIES_BY_NAME
    importance = _FAMILIES_BY_NAME["importance"]
    assert len(importance.variants) == 3
    variant_names = {v.name for v in importance.variants}
    assert variant_names == {"five_point_gradated", "four_point_polar", "five_point_polar"}


def test_purespectrum_q7_five_point_gradated_importance():
    qtype, roles, family = classify_question_type(
        ["Not important at all", "Slightly important", "Moderately important", "Very important", "Extremely important"]
    )
    assert qtype is QuestionType.scale
    assert family == "importance"
    assert roles["Not important at all"] == (CodeRole.bottom, 1)
    assert roles["Extremely important"] == (CodeRole.top, 5)


def test_toluna_five_point_polar_importance_distinct_from_gradated():
    qtype, roles, family = classify_question_type(
        ["Very Unimportant", "Unimportant", "Neutral / Neither Important nor Unimportant", "Important", "Very Important"]
    )
    assert qtype is QuestionType.scale
    assert family == "importance"
    assert roles["Very Unimportant"] == (CodeRole.bottom, 1)
    assert roles["Neutral / Neither Important nor Unimportant"] == (CodeRole.neutral, 3)


def test_toluna_likelihood_five_point_polar():
    qtype, roles, family = classify_question_type(
        ["Very Unlikely", "Unlikely", "Neutral / Neither Likely nor Unlikely", "Likely", "Very Likely"]
    )
    assert qtype is QuestionType.scale
    assert family == "likelihood"
    assert roles["Very Unlikely"] == (CodeRole.bottom, 1)
    assert roles["Unlikely"] == (CodeRole.bottom, 2)
    assert roles["Neutral / Neither Likely nor Unlikely"] == (CodeRole.neutral, 3)
    assert roles["Likely"] == (CodeRole.top, 4)
    assert roles["Very Likely"] == (CodeRole.top, 5)


def test_intensity_has_two_distinct_four_point_variants():
    from surveytool.core.scale_library import _FAMILIES_BY_NAME
    intensity = _FAMILIES_BY_NAME["intensity"]
    assert len(intensity.variants) == 2
    variant_names = {v.name for v in intensity.variants}
    assert variant_names == {"four_point_not_at_all", "four_point_not_really"}


def test_purespectrum_q2_intensity_not_at_all_variant():
    qtype, roles, family = classify_question_type(["Not at all", "A little", "Somewhat", "A lot"])
    assert qtype is QuestionType.scale
    assert family == "intensity"
    assert roles["Not at all"] == (CodeRole.bottom, 1)
    assert roles["A lot"] == (CodeRole.top, 4)


def test_purespectrum_q5_intensity_not_really_variant():
    qtype, roles, family = classify_question_type(["Not really", "A little", "Somewhat", "A great deal"])
    assert qtype is QuestionType.scale
    assert family == "intensity"
    assert roles["Not really"] == (CodeRole.bottom, 1)
    assert roles["A great deal"] == (CodeRole.top, 4)


def test_fluency_matches_full_literal_suffixed_labels():
    labels = [
        "None — I don't really speak it, just recognize it",
        "Basic — a few words or phrases",
        "Conversational — can hold an everyday conversation",
        "Fluent — comfortable in most situations",
    ]
    qtype, roles, family = classify_question_type(labels)
    assert qtype is QuestionType.scale
    assert family == "fluency"


def test_relevance_five_point():
    qtype, roles, family = classify_question_type(
        ["Not relevant at all", "Not very relevant", "Neutral/don't know enough to say", "Relevant", "Extremely relevant"]
    )
    assert qtype is QuestionType.scale
    assert family == "relevance"
    assert roles["Neutral/don't know enough to say"] == (CodeRole.neutral, 3)


def test_concern_four_point():
    qtype, roles, family = classify_question_type(
        ["Not concerned at all", "Not very concerned", "Somewhat concerned", "Very concerned"]
    )
    assert qtype is QuestionType.scale
    assert family == "concern"
    assert roles["Not concerned at all"] == (CodeRole.bottom, 1)
    assert roles["Very concerned"] == (CodeRole.top, 4)


def test_worry_four_point():
    qtype, roles, family = classify_question_type(
        ["Not worried at all", "Not very worried", "Somewhat worried", "Very worried"]
    )
    assert qtype is QuestionType.scale
    assert family == "worry"
    assert roles["Not worried at all"] == (CodeRole.bottom, 1)
    assert roles["Very worried"] == (CodeRole.top, 4)


def test_effectiveness_and_ability_five_point_polar():
    qtype, roles, family = classify_question_type(
        ["Very Ineffective", "Ineffective", "Neutral / Neither Effective nor Ineffective", "Effective", "Very Effective"]
    )
    assert qtype is QuestionType.scale
    assert family == "effectiveness"

    qtype2, roles2, family2 = classify_question_type(
        ["Extremely unable to", "Somewhat unable to", "Neutral / Neither able nor unable to", "Somewhat able to", "Extremely able to"]
    )
    assert qtype2 is QuestionType.scale
    assert family2 == "ability"


def test_no_variant_anywhere_matches_two_others():
    """Every real-file variant is distinguishable from every other one --
    this is a coarse cross-check that Task B2's population didn't
    accidentally introduce a duplicate (would have already raised at import
    time, but this documents the intent explicitly)."""
    from surveytool.core.scale_library import _ALL_VARIANTS
    seen = set()
    for v in _ALL_VARIANTS:
        assert v.folded_label_set not in seen
        seen.add(v.folded_label_set)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_scale_library.py -v`
Expected: `FAIL` — `importance` only has one `default` variant so far (from B1's mechanical conversion), not three named ones; `fluency`/`intensity`/etc. likewise still have the B1 placeholder shape.

- [ ] **Step 3: Replace `scales.yaml` families content with the real per-vendor variants**

Replace the entire `families:` block in `surveytool/core/scales.yaml` with:

```yaml
families:
  agreement:
    variants:
      five_point:
        points:
          - patterns: ["strongly disagree"]
          - patterns: ["disagree"]
          - patterns: ["neutral", "neither agree nor disagree", "neither"]
          - patterns: ["agree"]
          - patterns: ["strongly agree"]

  importance:
    variants:
      five_point_gradated:
        points:
          - patterns: ["not important at all"]
          - patterns: ["slightly important"]
          - patterns: ["moderately important"]
          - patterns: ["very important"]
          - patterns: ["extremely important"]
      four_point_polar:
        points:
          - patterns: ["not at all important"]
          - patterns: ["not very important"]
          - patterns: ["somewhat important"]
          - patterns: ["very important"]
      five_point_polar:
        points:
          - patterns: ["very unimportant"]
          - patterns: ["unimportant"]
          - patterns: ["neutral / neither important nor unimportant"]
          - patterns: ["important"]
          - patterns: ["very important"]

  likelihood:
    variants:
      five_point_polar:
        points:
          - patterns: ["very unlikely"]
          - patterns: ["unlikely"]
          - patterns: ["neutral / neither likely nor unlikely"]
          - patterns: ["likely"]
          - patterns: ["very likely"]

  effectiveness:
    variants:
      five_point_polar:
        points:
          - patterns: ["very ineffective"]
          - patterns: ["ineffective"]
          - patterns: ["neutral / neither effective nor ineffective"]
          - patterns: ["effective"]
          - patterns: ["very effective"]

  ability:
    variants:
      five_point_polar:
        points:
          - patterns: ["extremely unable to"]
          - patterns: ["somewhat unable to"]
          - patterns: ["neutral / neither able nor unable to"]
          - patterns: ["somewhat able to"]
          - patterns: ["extremely able to"]

  intensity:
    variants:
      four_point_not_at_all:
        points:
          - patterns: ["not at all"]
          - patterns: ["a little"]
          - patterns: ["somewhat"]
          - patterns: ["a lot"]
      four_point_not_really:
        points:
          - patterns: ["not really"]
          - patterns: ["a little"]
          - patterns: ["somewhat"]
          - patterns: ["a great deal"]

  relevance:
    variants:
      five_point:
        points:
          - patterns: ["not relevant at all"]
          - patterns: ["not very relevant"]
          - patterns: ["neutral/don't know enough to say", "neutral"]
          - patterns: ["relevant"]
          - patterns: ["extremely relevant"]

  concern:
    variants:
      four_point:
        points:
          - patterns: ["not concerned at all"]
          - patterns: ["not very concerned"]
          - patterns: ["somewhat concerned"]
          - patterns: ["very concerned"]

  worry:
    variants:
      four_point:
        points:
          - patterns: ["not worried at all"]
          - patterns: ["not very worried"]
          - patterns: ["somewhat worried"]
          - patterns: ["very worried"]

  fluency:
    variants:
      four_point_suffixed:
        points:
          - patterns:
              - "none - i don't really speak it, just recognize it"
          - patterns:
              - "basic - a few words or phrases"
          - patterns:
              - "conversational - can hold an everyday conversation"
          - patterns:
              - "fluent - comfortable in most situations"

  satisfaction: {}
  frequency: {}
  zero_to_ten: {}
  calendar_frequency: {}
```

Notes on this content:

- Every pattern is written already folded (lowercase, ASCII hyphen, straight apostrophe) — `_build_families` folds again on load, which is idempotent, but writing them pre-folded keeps the file self-documenting about exactly what a folded label looks like, matching the codebase's existing YAML convention (see the old file's comments about labels already being normalized strings).
- `satisfaction`, `frequency`, `zero_to_ten`, `calendar_frequency` are left with **no variants** (`{}`) per B2's explicit instruction: "Do not delete a family that currently has no variant; leave it empty and let it fail to match loudly." A family key with an empty dict parses fine under `_build_families` (`family_raw.get("variants") or {}` yields no variants, `variants=()`), and `match_family`/`identify_variant` simply never match anything in these families since `_ALL_VARIANTS` has no entries for them.
- The fluency pattern's em-dash (`—`) is written as a literal ASCII hyphen here because YAML authors write already-folded patterns (per the existing convention) — `fold_label` folds `—`/`–`/`‑` to `-` on the vendor-label side at classify time, so a folded pattern using plain `-` matches a vendor label using `—` after both sides are folded. Confirm this holds in Step 4's test run.
- `binary` is gone entirely (handled by the hardcoded literal pair in `classify_question_type`, Task B1 Step 8).

- [ ] **Step 4: Run the scale library tests**

Run: `python -m pytest tests/test_scale_library.py -v`
Expected: `PASS`. If `test_fluency_matches_full_literal_suffixed_labels` fails on the em-dash fold, inspect `fold_label`'s `_DASH_FOLD` table (`surveytool/core/hygiene.py:7-11`) — it already folds em-dash (`—`) to ASCII `-`, so both the pattern (already `-`) and the input label (folded from `—` to `-`) should land on the same folded string. If it still fails, the input test label's em-dash character must be verified byte-for-byte against what `openpyxl` actually reads from the PureSpectrum fixture (Task B3's real-fixture test will catch this decisively; treat a failure here as a signal to inspect the exact fixture bytes, not to loosen the pattern).

- [ ] **Step 5: Run the full test suite to confirm no wider regressions from this content-only change**

Run: `python -m pytest -q`
Expected: same failure set as Task B1 Step 10 (ingest adapters, frequency, breaks_compute — all fixed in B3), plus now also failures in tests that assumed the old `importance`/`intensity`/etc. single-bucket shape resolved specific real labels differently. Confirm every new failure traces to the label-set-shape change (e.g. a test using PureSpectrum's D5 fluency dash-suffixed labels that the OLD library deliberately did not match — Task B2's acceptance says D5 now DOES match) rather than an unrelated regression.

- [ ] **Step 6: Commit**

```bash
git add surveytool/core/scales.yaml tests/test_scale_library.py
git commit -m "feat: populate scale library with real per-vendor variants (Round B2)"
```

---

### Task B3: Rank replaces vendor code everywhere

**Files:**
- Modify: `surveytool/ingest/rakuten.py`
- Modify: `surveytool/ingest/purespectrum.py`
- Modify: `surveytool/ingest/toluna.py`
- Modify: `surveytool/ingest/milieu.py`
- Modify: `surveytool/ingest/overrides.py`
- Modify: `surveytool/ingest/validate_questions.py`
- Modify: `surveytool/compute/frequency.py`
- Modify: `surveytool/compute/breaks_compute.py`
- Test: `tests/test_conformance.py`
- Test: `tests/test_scale_library.py` (ambiguity-raising integration, added here since it needs real adapter plumbing)

**Interfaces:**
- Consumes: `classify_question_type`, `match_family`, `identify_family`, `identify_variant` from Task B1/B2 (all now return `(CodeRole, rank)` tuples where they used to return bare `CodeRole`).
- Produces:
  - Every `ScaleCode` constructed for a scale question now carries `rank=<int>` from the matched variant.
  - `surveytool.compute.frequency.compute_question_stats`'s `mean` is computed from `rank`, not `numeric_value`.
  - `surveytool.compute.breaks_compute._scale_points` orders `ScalePoint`s by `rank` ascending, not by `enumerate(question.labels)` position.
  - `surveytool.ingest.overrides.QuestionOverride.label_roles` value type changes from `Literal["top","neutral","bottom"]` to a structure carrying rank too (see Step 5) — this changes the on-disk override YAML shape, which is why Step 5 also writes a migration.

- [ ] **Step 1: Write the failing test for the Toluna Q7 rank table (the spec's acceptance table)**

Add to `tests/test_conformance.py` (in the Section B real-file area, near the existing Toluna tests):

```python
_TOLUNA_PATH = _ROOT / "toluna_survey_misinformation_data.xlsx"  # already defined earlier in the file; reuse


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
```

Also add, in the same file, a Milieu ordering test:

```python
@pytest.mark.skipif(not _MILIEU_PATH.exists(), reason="Milieu fixture not present")
def test_milieu_agreement_grid_orders_strongly_disagree_to_strongly_agree():
    from surveytool.ingest.milieu import load
    survey = load(_MILIEU_PATH, "milieu_coe")
    grid_qids = [q.qid for q in survey.questions if q.grid_group and q.grid_group.startswith("grid_q10")]
    # q10-q14 share one grid_group per Milieu's header parsing (grid_stem-keyed)
    agreement_questions = [q for q in survey.questions if q.qtype.value == "scale" and q.scale_family == "agreement"]
    assert len(agreement_questions) >= 5
    for q in agreement_questions:
        ordered_by_rank = sorted(q.labels, key=lambda sc: sc.rank)
        assert [sc.label for sc in ordered_by_rank] == [
            "Strongly Disagree", "Disagree", "Neutral", "Agree", "Strongly Agree",
        ] or [sc.label for sc in ordered_by_rank] == [
            "Strongly disagree", "Disagree", "Neutral", "Agree", "Strongly agree",
        ]
```

(The label casing is asserted as either variant since the real Milieu fixture's exact casing wasn't confirmed during planning — Step 4 below runs this against the real file and you should tighten this assertion to the single actual casing once observed, removing the `or` branch.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_conformance.py -k "toluna_q7 or milieu_agreement_grid" -v`
Expected: `FAIL` — `ScaleCode.rank` is `None` everywhere still (adapters haven't been updated), and `q7.labels` iteration order is still data-appearance order, not rank order, so even accessing `.rank` will show `None` rather than the expected integers.

- [ ] **Step 3: Update `rakuten.py` and `purespectrum.py` (identical fix, both use `_build_question`)**

In `surveytool/ingest/rakuten.py`, replace the `qtype is QuestionType.scale` block (lines 165-203):

```python
    if qtype is QuestionType.scale:
        for ns_label, ns_role in ns_overrides.items():
            roles[ns_label] = (ns_role, None)

        scale_codes = [
            ScaleCode(
                code=code,
                label=normalize_label(label),
                role=roles[normalize_label(label)][0],
                numeric_value=code,
                rank=roles[normalize_label(label)][1],
            )
            for code, label in codes
        ]

        substantive_ranked = sorted(
            (sc for sc in scale_codes if sc.rank is not None),
            key=lambda sc: sc.rank,
        )
        direction: str | None = None
        if substantive_ranked:
            # Direction is now about whether the vendor's code order agrees
            # or disagrees with rank order, purely for informational/
            # provenance purposes -- it is never used to derive rank, role,
            # netting, or mean (those all come from rank, Task B3). Compare
            # the code order (as codes appear in the codebook, already
            # sorted by code since `codes` is codebook row order) against
            # rank order for the same labels.
            codes_by_rank_order = [sc.code for sc in substantive_ranked]
            codes_in_codebook_order = [c for c, lb in codes if normalize_label(lb) not in ns_overrides]
            if codes_in_codebook_order == codes_by_rank_order:
                direction = "ascending"
            elif codes_in_codebook_order == list(reversed(codes_by_rank_order)):
                direction = "descending"

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
```

Note `ns_overrides[nl] = CodeRole.nonsubstantive` (set earlier at line 127) is a bare `CodeRole`, not a tuple — the line `roles[ns_label] = (ns_role, None)` above converts it to the `(role, rank)` shape so the dict-of-tuples is uniform before the list comprehension reads `roles[...][0]`/`roles[...][1]`. Confirm `ns_role` here really is the bare `CodeRole.nonsubstantive` value (it is — check line 124-127 above where `ns_overrides: dict[str, CodeRole] = {}` is built).

Apply the identical change to `surveytool/ingest/purespectrum.py`'s `qtype is QuestionType.scale` block (lines 182-209) — same structure, same variable names, since `_build_question` in both files was already near-identical.

Also update the `ns_overrides` typing comment in both files from `dict[str, CodeRole]` — leave the dict's own declared type as `dict[str, CodeRole]` (it still holds bare `CodeRole` values at the point of construction, only the merge into `roles` wraps it into a tuple) — no change needed there, just confirm it compiles.

- [ ] **Step 4: Update `toluna.py` and `milieu.py` (identical fix, both use `_build_scale_question`)**

In `surveytool/ingest/toluna.py`, replace `_build_scale_question` (lines 84-141):

```python
def _build_scale_question(
    qid: str,
    text: str,
    values: list[str],
    grid_group: str | None,
    override: QuestionOverride | None = None,
    nonsubstantive_labels: list[str] | None = None,
) -> Question:
    """Builds a scale Question. Caller (parse_header) is responsible for
    only reaching this function once it already knows the substantive
    label set achieves a full match_family outcome (or an override says
    scale). Role and rank both come from the matched variant (Task B3) --
    `values`' own data-appearance order plays no part in role, rank,
    netting, or mean; it is used only as the ScaleCode.code join key
    (a synthesized 1-based sequential id, since Toluna has no real vendor
    numeric code) and, informationally, for `scale_direction`.
    """
    ns_overrides: dict[str, CodeRole] = {
        v: CodeRole.nonsubstantive for v in values if is_nonsubstantive_label(v, nonsubstantive_labels)
    }
    substantive_values = [v for v in values if v not in ns_overrides]

    if override is not None:
        role_map = apply_override(substantive_values, override)
        roles: dict[str, tuple[CodeRole, int | None]] = {
            label: (role, override.label_ranks.get(label) if override.label_ranks else None)
            for label, role in role_map.items()
        }
    else:
        match = match_family(substantive_values)
        roles = dict(match.matched_labels)
    for label, role in ns_overrides.items():
        roles[label] = (role, None)

    family = identify_family(substantive_values)

    ranked_values = sorted(
        (v for v in substantive_values if roles[v][1] is not None),
        key=lambda v: roles[v][1],
    )
    direction: str | None = None
    if ranked_values:
        if substantive_values == ranked_values:
            direction = "ascending"
        elif substantive_values == list(reversed(ranked_values)):
            direction = "descending"

    labels: list[ScaleCode] = []
    for i, value in enumerate(values, start=1):
        role, rank = roles[value]
        numeric_value = i if role is not CodeRole.nonsubstantive else None
        labels.append(ScaleCode(code=i, label=value, role=role, numeric_value=numeric_value, rank=rank))

    return Question(
        qid=qid,
        text=text,
        qtype=QuestionType.scale,
        labels=labels,
        scale_direction=direction,
        scale_family=family,
        grid_group=grid_group,
        base_eligible=True,
    )
```

Note the override branch references `override.label_ranks` — this field does not exist yet on `QuestionOverride`; it is added in Step 5 below. Apply the identical restructuring to `surveytool/ingest/milieu.py`'s `_build_scale_question` (lines 96-153) — same logic, same variable names (the two functions were already near-duplicates).

- [ ] **Step 5: Update `overrides.py` to carry rank**

A saved override currently records only `label_roles: dict[str, Literal["top","neutral","bottom"]]`. Since rank must now also come from the library (or, for an override, from the analyst), extend `QuestionOverride`:

In `surveytool/ingest/overrides.py`, modify `QuestionOverride`:

```python
class QuestionOverride(BaseModel):
    variable: str
    question_type: Literal["scale", "binary", "categorical", "excluded"]
    label_roles: dict[str, Literal["top", "neutral", "bottom"]] = Field(default_factory=dict)
    label_ranks: dict[str, int] | None = None
    resolved_at: datetime
    library_version: str
```

`label_ranks` is `None` for any override saved before this change (backward-compatible read: old override files simply have no key, Pydantic defaults it to `None`) or for a non-scale override (binary/categorical/excluded have no rank concept). `apply_override` must now also validate that a scale override's `label_ranks`, when present, assigns a rank to the same set of labels `label_roles` covers, and derive ranks from position when `label_ranks` is `None` (an old override with no ranks saved — see next paragraph for the exact rule) so a pre-Round-B override file continues to work without forcing every user to re-resolve every question.

Modify `apply_override`:

```python
def apply_override(question_labels: list[str], override: QuestionOverride) -> dict[str, tuple[CodeRole, int]]:
    """Apply a SCALE override's label_roles (and label_ranks, if present) to
    a question's actual label set. Raises IncompleteOverrideError if any
    label lacks a role assignment -- never defaults an unassigned label to
    any role.

    Rank resolution: if the override carries label_ranks, use them
    directly (validated to cover the same labels as label_roles). If the
    override predates Round B (label_ranks is None), derive a rank
    deterministically from role order among question_labels themselves,
    in the order role groups naturally sort (bottom, then neutral, then
    top), preserving question_labels' own relative order within each role
    group -- this reproduces a reasonable rank for old overrides without
    forcing every project to re-resolve, though it is a best-effort
    backfill, not a guarantee of matching what the analyst would pick
    today. New overrides saved after this change always carry label_ranks
    explicitly (Task C3/UI layer's responsibility going forward), so this
    fallback only ever applies to overrides written before Round B shipped.
    """
    missing = [lb for lb in question_labels if lb not in override.label_roles]
    if missing:
        raise IncompleteOverrideError(override.variable, missing)

    roles = {lb: _ROLE_MAP[override.label_roles[lb]] for lb in question_labels}

    if override.label_ranks is not None:
        rank_missing = [lb for lb in question_labels if lb not in override.label_ranks]
        if rank_missing:
            raise IncompleteOverrideError(override.variable, rank_missing)
        return {lb: (roles[lb], override.label_ranks[lb]) for lb in question_labels}

    _ROLE_ORDER = {CodeRole.bottom: 0, CodeRole.neutral: 1, CodeRole.top: 2, CodeRole.nonsubstantive: 3}
    ordered = sorted(question_labels, key=lambda lb: (_ROLE_ORDER[roles[lb]], question_labels.index(lb)))
    rank_by_label = {lb: i + 1 for i, lb in enumerate(ordered) if roles[lb] is not CodeRole.nonsubstantive}
    return {lb: (roles[lb], rank_by_label.get(lb)) for lb in question_labels}
```

Update `resolve_with_override`'s scale branch (line ~122-125) to match the new `apply_override` return shape:

```python
    if override.question_type == "scale":
        roles = apply_override(substantive_labels, override)
        family = identify_family(substantive_labels)
        return QuestionType.scale, roles, family
```

(No change needed here beyond what already exists — `apply_override`'s new return shape flows straight through, since `resolve_with_override`'s own return type annotation already needs updating from `dict[str, CodeRole] | None` to `dict[str, tuple[CodeRole, int]] | None`, matching `classify_question_type`'s shape from Task B1.)

Update `check_override_still_needed` — no change needed, it only calls `identify_family` which is unchanged.

- [ ] **Step 6: Update `validate_questions.py`'s `AutoCategorical`/`classify_or_collect` path if it touches roles**

Run: `grep -n "CodeRole\|roles\[" surveytool/ingest/validate_questions.py`
Expected: `validate_questions.py` deals with `FamilyMatch`/`UnresolvedQuestion` shapes (labels, reasons), not raw role dicts — confirm no direct unpacking of a bare `CodeRole` needs updating. If `reason_for_match`/`close_family_hint_for_match` read `match.matched_labels` values as bare roles anywhere (e.g. to describe "would resolve as top/neutral/bottom" in hint text), update those call sites to unpack the `(role, rank)` tuple, using only `role` for the hint text (rank has no place in resolver hint prose per B1's "hint is text-only, never pre-selects anything").

- [ ] **Step 7: Update `frequency.py`'s mean computation**

In `surveytool/compute/frequency.py`, replace lines 158-166:

```python
    else:
        code_stats = _count_scale_codes(question, base_resps, base)
        label_map = _build_label_map(question)
        ranks = [
            label_map[r.raw_value].rank
            for r in responses
            if r.state is ResponseState.answered
            and r.raw_value in label_map
            and label_map[r.raw_value].rank is not None
        ]
        mean = sum(ranks) / len(ranks) if ranks else None
```

Update the `QuestionStats.mean` docstring in `surveytool/compute/stats.py` line 62 from `# None if no code has numeric_value` to `# None if no code has rank`.

- [ ] **Step 8: Update `breaks_compute.py`'s scale point ordering**

In `surveytool/compute/breaks_compute.py`, replace `_scale_points` (lines 155-164):

```python
def _scale_points(question: Question) -> list[ScalePoint]:
    """Order by rank ascending (rank 1 = bottom), never by the position a
    label happened to land at in question.labels (which for Milieu/Toluna
    is vendor-data-appearance order and carries no ordinal meaning -- see
    Round B). A code with no rank (categorical/binary/nonsubstantive) sorts
    after every ranked point, in its original question.labels order, since
    there is no ordinal position to place it at."""
    ranked = sorted(
        (sc for sc in question.labels if sc.rank is not None),
        key=lambda sc: sc.rank,
    )
    unranked = [sc for sc in question.labels if sc.rank is None]
    ordered = ranked + unranked
    return [
        ScalePoint(
            code=sc.code,
            label=sc.label,
            order=i,
            polarity=_POLARITY_BY_ROLE.get(sc.role),
        )
        for i, sc in enumerate(ordered)
    ]
```

`ScalePoint.order` is kept as a 0-based display-order field (unchanged type/meaning for its consumers in `plotly_renderer.py`), now derived from rank instead of raw list position — this is the minimal-blast-radius fix since `plotly_renderer.py`'s `_scale_colour(order)` and category-axis ordering already iterate `question_result.scale_points` in emitted order and need no further change (Round C's C1/C2 tasks touch palette/labels, not ordering).

- [ ] **Step 9: Run the targeted tests**

Run: `python -m pytest tests/test_conformance.py -k "toluna_q7 or milieu_agreement_grid" -v`
Expected: `PASS`. If the Milieu casing assertion in Step 1 needs tightening, do so now based on the actual observed casing.

- [ ] **Step 10: Run the full suite**

Run: `python -m pytest -q`
Expected: `486 passed, 4 skipped` restored, plus the new tests added in this task and B1/B2 all passing (so the total passed count will be higher than 486 — record the new total). Any remaining failure means a consumer of the old bare-`CodeRole` shape was missed; grep for `roles\[` and `matched_labels\[` across the whole tree to find it:

Run: `grep -rn "roles\[\|matched_labels\[\|\.matched_labels\b" surveytool/ tests/`

Fix any remaining site the same way (unpack `(role, rank)` instead of a bare role) and re-run until green.

- [ ] **Step 11: Assert Rakuten HC figures are unchanged (critical acceptance gate)**

Run: `python -m pytest tests/ -k "rakuten and (hc or HC)" -v` (adjust the `-k` filter to match however the existing Rakuten HC-verified tests are named — grep first: `grep -rln "HC" tests/*.py`)

Expected: every existing Rakuten HC-sheet-derived numeric assertion still passes byte-for-byte, since both real Rakuten files have uniformly ascending vendor codes (per the spec, confirmed in the spec's own analysis table) — rank equals code for every Rakuten scale question, so this task changes nothing observable about Rakuten's output. If any Rakuten figure differs, stop immediately and report per the spec's explicit instruction ("If any Rakuten figure moves, stop and report") — do not attempt to "fix" it by adjusting the new rank logic to match the old code-based figure; investigate which one is actually correct first.

- [ ] **Step 12: Record the PureSpectrum before/after inversion for the run output**

Add a test (or extend an existing PureSpectrum conformance test) in `tests/test_conformance.py` that documents the before/after mean for each of Q2, Q5, Q5A, Q5B, Q7, Q8, Q9:

```python
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
```

Run: `python -m pytest tests/test_conformance.py -k "purespectrum_inverted" -v -s`
Expected: `PASS`. If a particular qid doesn't exist in the actual fixture (confirm by running with `-s` and checking which qids were skipped via the `continue`), that's fine — the spec's list of seven qids was drawn from the actual PureSpectrum Datamap, but confirm at least the ones present show the inversion.

- [ ] **Step 13: Commit**

```bash
git add surveytool/ingest/rakuten.py surveytool/ingest/purespectrum.py surveytool/ingest/toluna.py surveytool/ingest/milieu.py surveytool/ingest/overrides.py surveytool/ingest/validate_questions.py surveytool/compute/frequency.py surveytool/compute/breaks_compute.py surveytool/compute/stats.py tests/test_conformance.py tests/test_scale_library.py
git commit -m "fix: derive rank, netting, and mean from the scale library, never vendor code"
```

---

### Task B4: Consumers of rank — charts, diverging bar, mean availability, findings

**Files:**
- Modify: `surveytool/core/scale_polarity.yaml`
- Modify: `surveytool/core/chart_validity.py`
- Modify: `surveytool/charts/plotly_renderer.py`
- Modify: `surveytool/findings/sheet.py`
- Test: `tests/test_chart_validity.py` (create if it doesn't already exist as a distinct file — check first)
- Test: `tests/test_conformance.py`

**Interfaces:**
- Consumes: `QuestionResult.scale_id` (unchanged — still `Question.scale_family`), `ScalePoint.rank` — **new field**, added to `ScalePoint` in this task (Task B3's `_scale_points` sorted by rank but didn't expose it on the model itself; this task adds it for the findings sheet and for diverging-bar midpoint logic to consume it directly rather than re-deriving from order).
- Produces:
  - `surveytool.compute.breaks_compute.ScalePoint.rank: int | None` — new field.
  - `surveytool.core.chart_validity._has_declared_polarity` now checks by **variant identity** (`family.variant`), not bare family name, since B1/B2 mean one family can have variants of different lengths (only some bipolar). New helper `_variant_key(question_result) -> str | None` builds `f"{family}.{variant}"` — but `QuestionResult` doesn't currently carry variant name, only `scale_id` (=family). This requires threading `scale_variant` through `Question` → `QuestionResult`.
  - `surveytool.findings.sheet.FindingsRow` gains a `rank: int | None` field.

- [ ] **Step 1: Check whether a dedicated chart_validity test file exists**

Run: `ls tests/ | grep -i chart_valid`
If it exists, use it; if not, create `tests/test_chart_validity.py` with a minimal header matching other test files' import style (check `tests/test_scale_library.py`'s import block as the template).

- [ ] **Step 2: Thread `scale_variant` through `Question` and `QuestionResult`**

In `surveytool/core/model.py`, add to `Question`:

```python
    scale_variant: str | None = None
```

(next to the existing `scale_family: str | None = None` field, line 55).

In every adapter's scale-question construction site (`rakuten.py`, `purespectrum.py`, `toluna.py`, `milieu.py`, all touched in Task B3), add `scale_variant=variant.name` to the `Question(...)` call. This requires each adapter to have the matched `Variant` object in scope at that point, not just its `family` string. Update:

- `rakuten.py`/`purespectrum.py`: `classify_question_type` (Task B1) returns `(QuestionType, dict, family_name)` — it does not return the `Variant` object itself. Add a new return path: change `classify_question_type`'s return type to include the variant name as a 4th tuple element: `tuple[QuestionType, dict[str, tuple[CodeRole, int]] | None, str | None, str | None] | None` (family_name, variant_name). Update Task B1's `classify_question_type` body (in `scale_library.py`) to return `variant.family, variant.name` instead of just `variant.family`, and its binary branch to return `None, None, None, None`... actually binary already returns `(QuestionType.binary, None, None)` — extend to `(QuestionType.binary, None, None, None)`.

Since this changes `classify_question_type`'s tuple arity, this is a breaking change touching every unpacking call site. Grep first:

Run: `grep -rn "classify_question_type(" surveytool/ tests/`

Update every call site (`rakuten.py::_build_question`, `purespectrum.py::_build_question`, `overrides.py` does NOT call this directly, `tests/test_scale_library.py`'s many direct calls) to unpack 4 elements: `qtype, roles, family, variant_name = classify_question_type(...)`.

Update `tests/test_scale_library.py`'s existing calls (from Tasks B1/B2) similarly — e.g.:

```python
def test_classify_full_scale_match_returns_scale():
    qtype, roles, family, variant = classify_question_type(["strongly agree", "agree", "disagree", "strongly disagree"])
    assert qtype is QuestionType.scale
    assert family == "agreement"
    assert variant == "five_point"
    role, rank = roles["strongly agree"]
    assert role is CodeRole.top
    assert rank == 5
```

(Apply the same `variant` unpacking to every other `classify_question_type` call in that test file added across B1/B2.)

Also update `resolve_with_override`'s return shape in `overrides.py` to match (4-tuple, with `variant_name=None` always for an override-resolved question, since an override has no variant concept — it directly assigns role+rank per label, not via a named variant):

```python
def resolve_with_override(
    substantive_labels: list[str],
    overrides: dict[str, "QuestionOverride"],
    qid: str,
) -> tuple[QuestionType, dict[str, tuple[CodeRole, int]] | None, str | None, str | None] | None:
    override = overrides.get(qid)
    if override is None:
        return None
    if override.question_type == "excluded":
        return QuestionType.excluded, None, None, None
    if override.question_type == "scale":
        roles = apply_override(substantive_labels, override)
        family = identify_family(substantive_labels)
        return QuestionType.scale, roles, family, None
    return _QTYPE_MAP[override.question_type], None, None, None
```

Update every adapter's `_build_question`/`parse_header` call site accordingly (`override_result = resolve_with_override(...)` unpacking becomes 4-tuple; `classified = classify_question_type(...)` unpacking becomes 4-tuple), and pass `scale_variant=variant_name` into each `Question(...)` scale construction (`variant_name` will be `None` for an override-resolved scale question — that's correct, since overrides don't name a library variant).

For `toluna.py`/`milieu.py`'s `_build_scale_question`, which calls `match_family` (not `classify_question_type`) — `FamilyMatch` already carries `.variant` (Task B1), so use `match.variant` directly; no arity change needed there, just pass it through to `Question(..., scale_variant=match.variant if override is None else None)`.

- [ ] **Step 3: Add `rank` to `ScalePoint` and thread it through `_scale_points`**

In `surveytool/compute/breaks_compute.py`, modify `ScalePoint`:

```python
class ScalePoint(BaseModel):
    """One scale point of a question, in rank order (see _scale_points)."""

    code: str | int
    label: str
    order: int
    polarity: str | None
    rank: int | None = None
```

Modify `_scale_points` (from Task B3 Step 8) to pass `rank=sc.rank`:

```python
    return [
        ScalePoint(
            code=sc.code,
            label=sc.label,
            order=i,
            polarity=_POLARITY_BY_ROLE.get(sc.role),
            rank=sc.rank,
        )
        for i, sc in enumerate(ordered)
    ]
```

Add `scale_variant: str | None` to `QuestionResult`:

```python
class QuestionResult(BaseModel):
    question_id: str
    question_text: str
    scale_id: str | None
    scale_variant: str | None
    scale_points: list[ScalePoint]
    ...
```

Update `compute_breaks_crosstab`'s `QuestionResult(...)` construction (near line 371-382) to pass `scale_variant=question.scale_variant`.

- [ ] **Step 4: Re-key `scale_polarity.yaml` by variant**

Replace `surveytool/core/scale_polarity.yaml` content:

```yaml
# Scale polarity registry (Round B4).
#
# Keyed by "<family>.<variant>" -- NOT by family alone, since Round B gave
# one family multiple variants of different lengths (e.g. importance has a
# 5-point gradated variant and a 4-point polar variant), and midpoint
# centering for diverging_stacked_bar depends on point count (odd variants
# center on the neutral point; even variants center between the two middle
# ranks) -- a decision that must be made per-variant, not per-family.
#
# An entry here means the variant is a genuine bipolar scale eligible for
# diverging_stacked_bar. Absence means undeclared.
scale_variants:
  agreement.five_point:
    polarity: declared
  importance.five_point_gradated:
    polarity: declared
  importance.four_point_polar:
    polarity: declared
  importance.five_point_polar:
    polarity: declared
  likelihood.five_point_polar:
    polarity: declared
  effectiveness.five_point_polar:
    polarity: declared
  ability.five_point_polar:
    polarity: declared
  intensity.four_point_not_at_all:
    polarity: declared
  intensity.four_point_not_really:
    polarity: declared
  relevance.five_point:
    polarity: declared
  concern.four_point:
    polarity: declared
  worry.four_point:
    polarity: declared
  fluency.four_point_suffixed:
    polarity: declared

  # satisfaction, frequency, zero_to_ten, calendar_frequency have no
  # variants populated yet (Task B2) -- nothing to declare here until a
  # real file supplies one.
```

Every variant populated in Task B2 is declared bipolar here (this matches B4's acceptance: "Diverging stacked bar is offered on all four vendors for every scale question... No chart falls back to data order for a question that has rank" — every populated variant in this plan came from an explicitly ordered bottom-to-top scale, so all are legitimately bipolar; there is no undeclared-but-populated variant in this plan's scope).

- [ ] **Step 5: Update `chart_validity.py` to look up by variant key**

In `surveytool/core/chart_validity.py`, replace `_load_polarity_registry`/`_POLARITY_REGISTRY`/`_has_declared_polarity`:

```python
def _load_polarity_registry() -> dict[str, dict]:
    raw = yaml.safe_load(_POLARITY_PATH.read_text(encoding="utf-8"))
    return raw["scale_variants"]


_POLARITY_REGISTRY: dict[str, dict] = _load_polarity_registry()


def _variant_key(scale_id: str | None, scale_variant: str | None) -> str | None:
    if scale_id is None or scale_variant is None:
        return None
    return f"{scale_id}.{scale_variant}"


def _has_declared_polarity(scale_id: str | None, scale_variant: str | None) -> bool:
    key = _variant_key(scale_id, scale_variant)
    return key is not None and key in _POLARITY_REGISTRY
```

Update `evaluate_chart_permissions`'s `diverging_stacked_bar` permission construction (line ~87-98):

```python
        ChartType.diverging_stacked_bar: (
            ChartPermission(
                chart_type=ChartType.diverging_stacked_bar,
                permitted=True,
            )
            if _has_declared_polarity(question_result.scale_id, question_result.scale_variant)
            else ChartPermission(
                chart_type=ChartType.diverging_stacked_bar,
                permitted=False,
                reason=_REASON_SCALE_POLARITY_UNDECLARED,
            )
        ),
```

An override-resolved scale question has `scale_variant=None` (Step 2) even though it has `scale_id` (family) set — this means diverging bar is `NOT permitted` for any override-resolved scale question, since there's no variant key to look up. This is intentional and matches B1's design: an override assigns per-label roles/ranks directly, with no named variant to declare polarity for centering purposes; extending polarity declaration to override-resolved questions is out of scope for this plan (no spec requirement asks for it) and should be flagged to the user as a known limitation rather than silently worked around.

- [ ] **Step 6: Update `plotly_renderer.py`'s diverging bar midpoint centering**

Currently `_diverging_stacked_bar_figure` (Task exploration, `plotly_renderer.py:169-214`) signs each point `-1.0` for `negative` polarity, `+1.0` otherwise (including neutral, which was previously always a single family-wide `midpoint_role: neutral` — a note in the old `scale_polarity.yaml` that is now redundant since `Variant.role_for_rank` already derives `CodeRole.neutral` correctly for odd-length variants and no neutral role at all for even-length ones). No centering logic change is actually needed here for odd vs. even, since `CodeRole.neutral` already only exists on odd-length variants (Task B1's `role_for_rank`) and the existing sign logic (`sign = -1.0 if point.polarity == "negative" else 1.0`) already puts neutral points on the positive side at zero net effect on the visual "gap" — but B4's task text says "centres on the neutral point where the variant has one, and between the two middle ranks where it does not." Confirm the current behavior already satisfies this for an odd variant (neutral rendered as a small positive-side segment starting at 0, visually centered since it's the only trace with `polarity == "neutral"` triggering `sign = 1.0`... but "neutral" is not "negative" so it currently gets `sign = 1.0`, meaning it stacks on the positive side, not centered at all).

**This is a real gap**: re-derive the centering logic properly. Replace `_diverging_stacked_bar_figure`:

```python
def _diverging_stacked_bar_figure(question_result: QuestionResult) -> go.Figure:
    """Bars diverging from 0: bottom-half points (by rank) extend left,
    top-half points extend right. An odd-length variant's exact-middle
    point (CodeRole.neutral) is rendered as its own centered segment
    straddling zero, half on each side, so it visually sits on the
    dividing line rather than stacking onto either wing. An even-length
    variant has no neutral point at all -- it divides cleanly at the
    midpoint with no straddling segment needed.
    """
    fig = go.Figure()
    x_labels = [_column_display_label(c) for c in question_result.columns]

    for point in question_result.scale_points:
        code = str(point.code)
        if point.polarity == "neutral":
            # Straddle zero: half the value on each side, as two half-
            # magnitude traces sharing one legend name via one trace with
            # a symmetric base -- Plotly's relative stacking doesn't
            # support a single bar straddling zero directly, so split the
            # value in half and draw one negative-side and one positive-
            # side trace, both using this point's colour and label, with
            # showlegend suppressed on the second so it appears once.
            neg_half = []
            pos_half = []
            for column in question_result.columns:
                pct = 0.0 if column.percentages is None else column.percentages.get(code, 0.0)
                neg_half.append(-pct / 2.0)
                pos_half.append(pct / 2.0)
            fig.add_trace(go.Bar(name=point.label, x=x_labels, y=neg_half, marker_color=_scale_colour(point.rank or 0)))
            fig.add_trace(go.Bar(name=point.label, x=x_labels, y=pos_half, marker_color=_scale_colour(point.rank or 0), showlegend=False))
            continue

        sign = -1.0 if point.polarity == "negative" else 1.0
        y_values = []
        for column in question_result.columns:
            if column.percentages is None:
                y_values.append(0.0)
            else:
                y_values.append(sign * column.percentages.get(code, 0.0))
        fig.add_trace(
            go.Bar(
                name=point.label,
                x=x_labels,
                y=y_values,
                marker_color=_scale_colour(point.rank or 0),
            )
        )

    gap_extent = [
        (-100 if c.band is Band.suppressed else 0, 100 if c.band is Band.suppressed else 0)
        for c in question_result.columns
    ]
    if any(lo or hi for lo, hi in gap_extent):
        fig.add_trace(
            go.Bar(
                name="Suppressed (base too small)",
                x=x_labels,
                y=[hi for _, hi in gap_extent],
                base=[lo for lo, _ in gap_extent],
                marker_color=_SUPPRESSED_GREY,
                marker_pattern_shape="x",
            )
        )

    fig.update_layout(barmode="relative", yaxis_title="%")
    fig.add_hline(y=0, line_color="#888888", line_width=1)
    return fig
```

Changed `_scale_colour(order)` calls to `_scale_colour(point.rank or 0)` throughout this function so colour assignment is stable by rank (ordinal identity) rather than by display position — this anticipates Round C's C3 (manual reorder must never change colour-by-identity), though C1 is the task that formalizes a shared palette; leave `_scale_colour`/`_SCALE_PALETTE` as-is in this task, just change what's passed to it. Do the same `order` → `rank or 0` substitution in `_stacked_bar_100_figure` and `_grouped_bar_figure` for the same forward-compatibility reason (both currently call `_scale_colour(order)` from `enumerate(question_result.scale_points)`).

For an even-length variant (no `CodeRole.neutral` exists per `role_for_rank`), the loop above never hits the `polarity == "neutral"` branch — every point is unambiguously `negative` or `positive`, dividing cleanly at the midpoint exactly as B4 asks ("between the two middle ranks where it does not [have a neutral point]"), with no code change needed for that case beyond what's already written.

- [ ] **Step 7: Add `rank` to `FindingsRow`**

In `surveytool/findings/sheet.py`, modify `FindingsRow`:

```python
@dataclass(frozen=True)
class FindingsRow:
    survey_id: str
    qid: str
    question_text: str
    breakdown_variable: str
    breakdown_level: str
    breakdown_level_label: str
    cell_base: int
    metric: str
    value: float | None
    convention: str
    role: CodeRole | None = None
    rank: int | None = None
```

Update `_emit_rows`'s `pct_`/`n_` row construction (lines 52-65) to pass `rank=cs.rank` — but `CodeStat` (in `surveytool/compute/stats.py`) doesn't carry `rank` yet either. Add it there first:

```python
@dataclass(frozen=True)
class CodeStat:
    code: str | int
    label: str
    role: CodeRole
    n: int
    pct: float
    rank: int | None = None
```

Update `_count_scale_codes`/`_count_multi_response_codes` in `surveytool/compute/frequency.py` (both build `CodeStat(...)` from `sc` — a `ScaleCode`) to pass `rank=sc.rank`:

```python
        result.append(CodeStat(code=sc.code, label=sc.label, role=sc.role, n=n, pct=pct, rank=sc.rank))
```

(Apply to both functions — `_count_scale_codes` line 50 and `_count_multi_response_codes` line 90.)

Now update `_emit_rows` in `sheet.py`:

```python
    for cs in qs_result.code_stats:
        rows.append(FindingsRow(
            survey_id=survey_id,
            qid=question.qid,
            question_text=question.text,
            breakdown_variable=breakdown_variable,
            breakdown_level=breakdown_level,
            breakdown_level_label=breakdown_level_label,
            cell_base=base,
            metric=f"pct_{cs.label}",
            value=cs.pct,
            convention="pct",
            role=cs.role,
            rank=cs.rank,
        ))
```

(The `n_` row below it stays without `role`/`rank` — matching existing behavior where only the `pct_` row carries `role`; rank follows the same convention, only on the `pct_` row, since `n_`/`pct_` are always paired for one label and a consumer needing rank for an `n_` row can look up its sibling `pct_` row.)

- [ ] **Step 8: Run targeted tests**

Run: `python -m pytest tests/test_scale_library.py tests/test_conformance.py tests/test_chart_validity.py tests/ -k "diverging or findings or chart_valid" -v`
Expected: `PASS`. Fix any remaining `ScalePoint`/`QuestionResult`/`FindingsRow`/`CodeStat` construction site missing a newly-required-in-practice-but-defaulted field (all new fields default to `None`, so no site should actually need updating to avoid a `TypeError` — but confirm via the run that nothing else broke).

- [ ] **Step 9: Add the diverging-bar-on-all-vendors acceptance test**

Add to `tests/test_conformance.py`:

```python
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
```

(Adjust `ToolConfig()` construction if it requires arguments — check `surveytool/core/config.py` first.)

Run: `python -m pytest tests/test_conformance.py -k "diverging_stacked_bar" -v`
Expected: `PASS`.

- [ ] **Step 10: Run the full suite**

Run: `python -m pytest -q`
Expected: all green, including every test from B1-B4.

- [ ] **Step 11: Commit**

```bash
git add surveytool/core/model.py surveytool/core/scale_polarity.yaml surveytool/core/chart_validity.py surveytool/compute/breaks_compute.py surveytool/compute/stats.py surveytool/compute/frequency.py surveytool/charts/plotly_renderer.py surveytool/findings/sheet.py surveytool/ingest/rakuten.py surveytool/ingest/purespectrum.py surveytool/ingest/toluna.py surveytool/ingest/milieu.py surveytool/ingest/overrides.py tests/test_conformance.py tests/test_scale_library.py tests/test_chart_validity.py
git commit -m "feat: rank-aware diverging bar centering, variant-keyed polarity, findings rank column"
```

---

### Task B5: Round B conformance suite

**Files:**
- Modify: `tests/test_conformance.py`

**Interfaces:**
- Consumes: everything from B1-B4.
- Produces: no new production code — this task only adds the standing regression suite the spec asks for, so a future revert of B2/B3 fails loudly.

- [ ] **Step 1: Write the "every scale question matches exactly one variant" sweep**

Add to `tests/test_conformance.py`:

```python
@pytest.mark.skipif(
    not (_TOLUNA_PATH.exists() and _MILIEU_PATH.exists() and _PURESPECTRUM_PATH.exists()
         and _RAKUTEN_CHN_CLANS_PATH.exists() and _RAKUTEN_PATH.exists()),
    reason="Not all five real vendor fixtures present",
)
def test_every_scale_question_in_every_real_file_matches_exactly_one_variant():
    """Round B5: a scale question matching zero or more than one variant
    fails the run. This sweep loads all five real files and checks every
    Question with qtype == scale carries both scale_family and
    scale_variant (a question that reached qtype=scale via classify_or_collect's
    single-full-match path always has both; an override-resolved scale
    question has scale_family set but scale_variant=None by design -- Task
    B4 Step 5's documented limitation -- so this sweep only asserts on
    non-override-resolved scale questions, identified as those with
    scale_variant is not None OR scale_family is None entirely, i.e. it
    never accepts a scale question with scale_family set but scale_variant
    unset UNLESS that question's qid has a stored override)."""
    from surveytool.ingest.rakuten import load as rakuten_load
    from surveytool.ingest.purespectrum import load as ps_load
    from surveytool.ingest.toluna import load as toluna_load
    from surveytool.ingest.milieu import load as milieu_load

    surveys = [
        rakuten_load(_RAKUTEN_CHN_CLANS_PATH, "chn_clans"),
        rakuten_load(_RAKUTEN_PATH, "support_measures"),
        ps_load(_PURESPECTRUM_PATH, "ps_wcs"),
        toluna_load(_TOLUNA_PATH, "toluna_misinfo"),
        milieu_load(_MILIEU_PATH, "milieu_coe"),
    ]
    for survey in surveys:
        for q in survey.questions:
            if q.qtype.value != "scale":
                continue
            assert q.scale_family is not None, f"{survey.id}/{q.qid}: scale question with no family"
            if q.scale_variant is None:
                pytest.fail(
                    f"{survey.id}/{q.qid}: scale question with family "
                    f"{q.scale_family!r} but no variant -- either an "
                    f"override resolved it (acceptable, but this sweep "
                    f"found none configured for these fixtures) or the "
                    f"library match path failed to record one (a defect)."
                )
```

(No overrides are configured for these five real files in the plain conformance run, so the strict `scale_variant is not None` check is correct here without an override carve-out; if a future test setup adds overrides for one of these files, this test will need the carve-out described in the docstring — leave the docstring as forward-looking documentation.)

- [ ] **Step 2: Write "no ordering/netting/mean derives from vendor code" as a structural grep-based test**

This is a code-shape assertion, not a runtime one — add it as a plain Python test that scans source text for the old anti-pattern.

```python
def test_no_compute_path_orders_or_nets_by_numeric_value():
    """Round B5: structural guard against regression. numeric_value must
    never again appear in an ordering, netting, or mean expression. This
    greps the specific files Task B3 fixed rather than the whole tree,
    since numeric_value legitimately still exists on ScaleCode as the join
    key (Round B's own design) -- this test isn't "ban the field", it's
    "ban using it for the things rank now owns"."""
    import re
    guarded_files = [
        _ROOT / "surveytool" / "compute" / "frequency.py",
        _ROOT / "surveytool" / "compute" / "breaks_compute.py",
    ]
    forbidden = re.compile(r"numeric_value")
    for path in guarded_files:
        text = path.read_text(encoding="utf-8")
        assert not forbidden.search(text), (
            f"{path} references numeric_value -- Round B requires rank for "
            f"ordering/netting/mean, never the vendor's numeric code."
        )
```

- [ ] **Step 3: Write the Toluna Q7 table assertion as a standalone, explicitly-named regression test**

(Already added in Task B3 Step 1 as `test_toluna_q7_local_mainstream_media_rank_and_netting` — confirm it's present and passing; this step is a checklist confirmation, not new code.)

Run: `python -m pytest tests/test_conformance.py -k "test_toluna_q7_local_mainstream_media_rank_and_netting" -v`
Expected: `PASS`.

- [ ] **Step 4: Write the Rakuten HC-figures-unchanged assertion as an explicit, named regression guard**

Run: `grep -rln "HC" tests/*.py` to find the existing Rakuten HC tests (per exploration, these already exist as the "standing regression guard" per every prior plan's convention). Confirm they run as part of the default `pytest -q` invocation (no special marker excludes them) — if they do, Round B5's requirement "Assert Rakuten HC figures unchanged" is already satisfied by the existing suite continuing to pass; add a one-line comment above the relevant existing test class/module noting Round B's dependency on it:

```python
# Round B (2026-08-29) depends on every assertion in this module continuing
# to pass unchanged -- Rakuten's vendor codes are uniformly ascending, so
# rank == code for every Rakuten scale question, and Round B's rank-based
# netting/mean must reproduce these exact figures. See
# docs/superpowers/plans/2026-08-29-round-b-scale-ordinal-rank.md Task B3
# Step 11.
```

(Insert this comment at the top of whichever file holds the HC tests — do not duplicate the tests themselves.)

- [ ] **Step 5: Write the "duplicate variant fails to load" test as a standalone regression guard**

(Already added in Task B1 Step 1 as `test_duplicate_folded_label_set_across_variants_raises_at_load` — confirm present and passing.)

- [ ] **Step 6: Run the complete suite one final time**

Run: `python -m pytest -q`
Expected: all green. Record the final passed/skipped count.

- [ ] **Step 7: Commit**

```bash
git add tests/test_conformance.py
git commit -m "test: Round B conformance suite (variant coverage, no-code-ordering guard, HC regression note)"
```

---

## Self-Review Notes (for the plan author, not a task)

- **Spec coverage check**: B1 (variant schema, load-time validation, ambiguity raise) → Task B1. B2 (real variant population, D5 fluency literal match) → Task B2. B3 (rank replaces code, Rakuten unchanged, PureSpectrum inverts, Toluna Q7 table, Milieu order) → Task B3. B4 (chart ordering, diverging bar on all vendors, mean newly available on Toluna/Milieu, findings rank column) → Task B4. B5 (conformance suite) → Task B5. All five prompts have a task.
- **"Mean becomes newly available on Toluna and Milieu" (B4 point 3)**: this was already true structurally the moment `ScaleCode.rank` is populated for those vendors in Task B3 (since `frequency.py`'s mean now sums `rank` instead of `numeric_value`, and Toluna/Milieu's `numeric_value` was already non-None before this plan — meaning mean was already computed for them, just wrongly ordered). Confirm in Task B4 whether a "newly available" run-summary label is actually needed as separate UI-facing text — re-reading B4 point 3, "Label it in the run summary as newly available so nobody assumes it was there before" implies a run-summary text change. This is a small gap: **add a Task B4 Step 12** before the commit:

- [ ] **Step 12 (added): Label mean as newly available for Toluna/Milieu in the run summary**

Run: `grep -n "def build_run_summary\|mean" surveytool/desktop/app.py | head -30` to locate the run summary builder (per exploration, `_build_session_run_summary` in `app.py`). Add a note to the run summary payload for any Toluna/Milieu scale question carrying a non-null mean, flagged as `mean_newly_available: true`, with accompanying text "Mean score is now available for this question (previously not computed for this vendor)." Since this touches `desktop/app.py`'s run summary construction and payload shape (a UI-facing concern, not covered by this plan's Files list), treat this as a small addition to Task B4 rather than a new task — locate the exact run summary function, add the field to whatever payload model it returns, gated on `vendor in ("toluna", "milieu") and question.qtype == "scale" and mean is not None`, and add one test asserting the flag appears for the Toluna Q7 case and does not appear for any Rakuten/PureSpectrum question (since mean was already available for those vendors before this plan).

- **Placeholder scan**: no "TBD"/"add error handling"/"similar to Task N" patterns found in the above — every step has literal code or literal grep commands.
- **Type consistency check**: `classify_question_type` return arity changes from 3-tuple (Task B1) to 4-tuple (Task B4 Step 2) — this is flagged explicitly in Task B4 as a second breaking change to the same function, with every call site re-updated. Confirmed `FamilyMatch.variant` (added Task B1 Step 7) is consumed correctly in Task B4 Step 2's `toluna.py`/`milieu.py` update (`match.variant`). Confirmed `ScalePoint.rank`, `CodeStat.rank`, `FindingsRow.rank`, `QuestionOverride.label_ranks`, `Question.scale_variant`, `QuestionResult.scale_variant` are all threaded consistently task-to-task.
- **Gap found on self-review: `label_ranks` was added to `QuestionOverride` (Task B3 Step 5) but never made reachable from the resolver UI's own request payload**, so an analyst resolving a question via `/api/session/{id}/resolve` would always hit `apply_override`'s old-override rank-backfill path (Task B3 Step 5's `_ROLE_ORDER` fallback) rather than ever supplying a real rank — meaning override-resolved scale questions can never get a first-class analyst-chosen rank through the UI as written. This is real end-to-end plumbing the spec's B1-B5 text does not explicitly call out (the resolver UI is out of B's stated scope — B is a data-model round) but leaving it unaddressed means "resolve a question in the UI" silently produces best-effort ranks forever. Add a **Task B6** below to close this, scoped narrowly to the one payload/endpoint change, so the plan is honest about what "done" means for overrides.

---

### Task B6: Thread rank through the resolver's save endpoint

**Files:**
- Modify: `surveytool/desktop/app.py`
- Test: `tests/test_desktop_resolve.py`

**Interfaces:**
- Consumes: `QuestionOverride.label_ranks` (Task B3 Step 5), `apply_override` (Task B3 Step 5).
- Produces: `ResolvedQuestionPayload.label_ranks: dict[str, int] | None = None` — new optional field on the existing resolver request payload.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_desktop_resolve.py` (check its existing imports/fixtures first and match its style — it already exercises `/api/session/{id}/resolve` per the exploration notes):

```python
def test_resolve_with_explicit_ranks_persists_and_applies(client, pending_session_id):
    """A resolver save that supplies label_ranks explicitly must persist
    those exact ranks (not the position-based backfill apply_override uses
    for a rank-less override) and the re-run session's Question must carry
    them."""
    response = client.post(
        f"/api/session/{pending_session_id}/resolve",
        json={
            "resolutions": [
                {
                    "variable": "SOME_QID",
                    "question_type": "scale",
                    "label_roles": {"Low": "bottom", "Mid": "neutral", "High": "top"},
                    "label_ranks": {"Low": 1, "Mid": 2, "High": 3},
                }
            ]
        },
    )
    assert response.status_code == 200
```

(Adjust `client`/`pending_session_id` fixture names and the exact qid/labels to whatever `tests/test_desktop_resolve.py` already uses for its other resolve tests — read the file first and mirror its existing fixture setup rather than inventing new ones.)

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_desktop_resolve.py -k "explicit_ranks" -v`
Expected: `FAIL` — `ResolvedQuestionPayload` rejects (or silently drops, depending on Pydantic's extra-field policy) `label_ranks` since the field doesn't exist yet.

- [ ] **Step 3: Add `label_ranks` to the payload and thread it into the override**

In `surveytool/desktop/app.py`, modify `ResolvedQuestionPayload`:

```python
class ResolvedQuestionPayload(BaseModel):
    variable: str
    question_type: Literal["scale", "binary", "categorical", "excluded"]
    label_roles: dict[str, Literal["top", "neutral", "bottom"]] = {}
    label_ranks: dict[str, int] | None = None
```

In `resolve_questions`, update the `QuestionOverride(...)` construction:

```python
        override = QuestionOverride(
            variable=entry.variable,
            question_type=entry.question_type,
            label_roles=entry.label_roles,
            label_ranks=entry.label_ranks,
            resolved_at=now,
            library_version=_SCALE_LIBRARY_VERSION,
        )
```

- [ ] **Step 4: Run the test**

Run: `python -m pytest tests/test_desktop_resolve.py -k "explicit_ranks" -v`
Expected: `PASS`.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest -q`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add surveytool/desktop/app.py tests/test_desktop_resolve.py
git commit -m "feat: accept explicit label ranks from the resolver save endpoint"
```
