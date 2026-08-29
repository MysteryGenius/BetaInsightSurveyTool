from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

import yaml

from surveytool.charts.errors import AmbiguousScaleMatchError, ScaleLibraryConfigError
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


def identify_variant(labels: list[str], qid: str | None = None) -> Variant | None:
    """Return the single Variant whose folded label set exactly equals this
    question's folded label set, or None if no variant matches at all.

    Raises AmbiguousScaleMatchError if more than one variant matches --
    exact set-equality matching means this can only happen if scales.yaml
    itself has two variants with the same label set, which _build_families
    already prevents at load time; this check exists as a second,
    independent guard at the point of use, per the Round B spec's "ambiguity
    in the library is a library defect and must surface as one" -- it
    should be unreachable in practice given B1's load-time check, but a
    classify-time caller must never silently pick one if it somehow is.

    `qid`, when the caller has one in scope (a real adapter classifying a
    real question), is threaded into the raised error so an end user sees
    which question triggered it -- see AmbiguousScaleMatchError's docstring.
    A synthetic/unit-test caller with no real question in scope passes None
    (the default), same as before this parameter existed."""
    matches = _variants_fully_matching(labels)
    if not matches:
        return None
    if len(matches) > 1:
        raise AmbiguousScaleMatchError(qid, labels, [f"{v.family}.{v.name}" for v in matches])
    return matches[0]


def identify_family(labels: list[str], qid: str | None = None) -> str | None:
    """Return the scale family name if the full label set matches exactly
    one variant. Raises AmbiguousScaleMatchError on a multi-variant match
    (see identify_variant). `qid` is forwarded to identify_variant so a real
    ambiguous-match error names the question."""
    variant = identify_variant(labels, qid=qid)
    return variant.family if variant is not None else None


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
    missing_point_patterns: the chosen variant's own pattern text for every
        point no label matched (one representative pattern per missing
        point, in rank order). Empty for a full match. A full match
        requires both unmatched_labels AND missing_point_patterns to be
        empty -- a question can match every one of its own labels to some
        point (unmatched_labels empty) while still leaving some of the
        variant's points uncovered (missing_point_patterns non-empty),
        which is a partial match, not full (see match_family).
    ambiguous: True if the label set achieves a partial or full match count
        tied across more than one variant -- see match_family's docstring
        for the tie-breaking rule.
    """

    outcome: MatchOutcome
    family: str | None
    variant: str | None
    matched_labels: dict[str, tuple[CodeRole, int]]
    unmatched_labels: list[str]
    missing_point_patterns: list[str]
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
            missing_point_patterns=[],
            ambiguous=False,
        )

    best_variant = max(counts, key=lambda v: counts[v])
    ambiguous = len(counts) > 1

    matched_labels: dict[str, tuple[CodeRole, int]] = {}
    unmatched_labels: list[str] = []
    matched_ranks: set[int] = set()
    for label, norm in zip(labels, normed):
        rank = best_variant.rank_for_label(norm)
        if rank is not None:
            matched_labels[label] = (best_variant.role_for_rank(rank), rank)
            matched_ranks.add(rank)
        else:
            unmatched_labels.append(label)

    # "full" must mean full coverage in BOTH directions: every label in the
    # question maps to a point in the variant (unmatched_labels empty) AND
    # every point in the variant is covered by some label (no gaps). A
    # strict subset of a variant's points (e.g. a 3-label question matching
    # 3 of a 5-point variant's points) previously reported "full" here
    # purely because unmatched_labels was empty, even though 2 of the
    # variant's points were never used by any label -- inconsistent with
    # identify_family's full set-equality semantics and misleading to every
    # consumer that reads outcome=full as "this variant's points are fully
    # accounted for" (diverging-bar charting, resolver hint text, rank
    # contiguity).
    missing_point_patterns = [
        point.patterns[0] for point in best_variant.points if point.rank not in matched_ranks
    ]
    # "full" must mean full coverage in BOTH directions: every label in the
    # question maps to a point in the variant (unmatched_labels empty) AND
    # every point in the variant is covered by some label (no gaps, i.e.
    # missing_point_patterns empty). A strict subset of a variant's points
    # (e.g. a 3-label question matching 3 of a 5-point variant's points)
    # previously reported "full" here purely because unmatched_labels was
    # empty, even though 2 of the variant's points were never used by any
    # label -- inconsistent with identify_family's full set-equality
    # semantics and misleading to every consumer that reads outcome=full as
    # "this variant's points are fully accounted for" (diverging-bar
    # charting, resolver hint text, rank contiguity).
    outcome = (
        MatchOutcome.full
        if not unmatched_labels and not missing_point_patterns
        else MatchOutcome.partial
    )

    return FamilyMatch(
        outcome=outcome,
        family=best_variant.family,
        variant=best_variant.name,
        matched_labels=matched_labels,
        unmatched_labels=unmatched_labels,
        missing_point_patterns=missing_point_patterns,
        ambiguous=ambiguous,
    )


def has_polarity_pair(labels: list[str]) -> bool:
    """Round A prompt A4: return True if the label set contains a
    `not`-prefixed or `un`-prefixed counterpart of another label in the same
    set (e.g. "Able" / "Unable", "Effective" / "Not effective") — a
    deterministic, inspectable signal that a label set is graded on a
    single dimension even when no individual label matches a known family's
    exact vocabulary.
    """
    normed = {_normalise(lb) for lb in labels}
    for norm in normed:
        for prefix in ("not ", "un"):
            if norm.startswith(prefix) and norm[len(prefix):] in normed:
                return True
    return False


def is_ordinal_resolver_candidate(labels: list[str]) -> bool:
    """Round A prompt A4: decide whether a question that failed to achieve
    a full scale match still belongs in the resolver queue (genuinely looks
    ordinal) versus being classified as categorical outright (no evidence of
    an underlying scale at all).

    Committed position (see the prompt): a resolver candidate is a question
    where at least one label matches a pattern in any family
    (is_recognised_scale_point), or the label set shows a polarity pair
    (has_polarity_pair). Everything else is categorical. Deliberately no
    fuzzy or prefix matching beyond has_polarity_pair's exact-word check --
    that would risk over-matching genuinely categorical lists.
    """
    return any(is_recognised_scale_point(lb) for lb in labels) or has_polarity_pair(labels)


def classify_question_type(
    labels: list[str],
    qid: str | None = None,
) -> tuple[QuestionType, dict[str, tuple[CodeRole, int]] | None, str | None, str | None] | None:
    """Classify a question's substantive labels as SCALE or BINARY.

    SCALE: every label matches a single variant (identify_variant succeeds).
    Returns (QuestionType.scale, {label: (role, rank)}, family_name, variant_name).

    BINARY: exactly two labels matching "yes"/"no" (or "true"/"false") --
    binary has no rank, so this checks a fixed literal pair rather than
    routing through the variant system (a 2-point variant would violate
    B1's 3-point-minimum rule, and binary genuinely has no ordinal
    position, just two poles).

    Neither: returns None. CATEGORICAL is never inferred here.

    `qid`, when the caller (a real adapter) has one in scope, is forwarded
    to identify_variant so a real ambiguous-match error names the question
    that triggered it.
    """
    normed = [_normalise(lb) for lb in labels]

    _BINARY_PAIRS = (
        frozenset({"yes", "no"}),
        frozenset({"true", "false"}),
    )
    if len(labels) == 2 and frozenset(normed) in _BINARY_PAIRS:
        return QuestionType.binary, None, None, None

    variant = identify_variant(labels, qid=qid)
    if variant is not None:
        roles: dict[str, tuple[CodeRole, int]] = {}
        for label, norm in zip(labels, normed):
            rank = variant.rank_for_label(norm)
            assert rank is not None
            roles[label] = (variant.role_for_rank(rank), rank)
        return QuestionType.scale, roles, variant.family, variant.name

    return None
