# surveytool/ingest/overrides.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, ValidationError

from surveytool.charts.errors import ErrorCode, SurveyToolError
from surveytool.core.model import CodeRole, QuestionType
from surveytool.core.scale_library import identify_family


class QuestionOverride(BaseModel):
    variable: str
    question_type: Literal["scale", "binary", "categorical", "excluded"]
    label_roles: dict[str, Literal["top", "neutral", "bottom"]] = Field(default_factory=dict)
    label_ranks: dict[str, int] | None = None
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


class InvalidRankAssignmentError(SurveyToolError):
    """Raised when a SCALE override's label_ranks are present but don't form
    a valid rank assignment: not exactly {1, 2, ..., N} for the N
    substantive (non-nonsubstantive) labels being ranked. A duplicate rank
    (e.g. two labels both ranked 3) or a gap (e.g. 1, 2, 4 with nothing at
    3) silently degrades mean computation and chart ordering downstream, so
    this is checked and rejected at write time rather than allowed to reach
    a Question and break in some far-away consumer."""

    def __init__(self, variable: str, ranks: dict[str, int]) -> None:
        self.variable = variable
        self.ranks = ranks
        detail = f"Override for {variable!r} has invalid ranks: {ranks!r}. Ranks must be exactly 1..{len(ranks)}, each used once."
        super().__init__(
            ErrorCode.UNRESOLVED_SCALE_LABELS,
            f"The saved resolution for '{variable}' has an invalid rank assignment.",
            detail=detail,
            next_action="Open the resolver and assign each response a unique rank, numbered consecutively starting at 1 with no gaps or repeats.",
        )


_ROLE_MAP: dict[str, CodeRole] = {"top": CodeRole.top, "neutral": CodeRole.neutral, "bottom": CodeRole.bottom}


class CorruptedOverridesFileError(SurveyToolError):
    """Round A prompt A11: raised when a project's saved overrides file
    exists but cannot be read as valid YAML, or doesn't match the
    ProjectOverrides schema. Before this, a corrupted file raised a raw
    yaml.YAMLError or pydantic.ValidationError that named no file and
    surfaced as an opaque INTERNAL failure — the analyst had no way to
    know their saved resolutions were the problem, and the tool never
    silently proceeded as though no override existed (that would have
    demoted every previously-resolved question back through the resolver
    with no explanation)."""

    def __init__(self, path: Path, reason: str) -> None:
        self.path = path
        detail = f"The overrides file at {path} could not be read: {reason}"
        super().__init__(
            ErrorCode.CONFIG_INVALID,
            "This project's saved question resolutions could not be read.",
            detail=detail,
            next_action=(
                "The overrides file may be corrupted. Check it at the path above, "
                "restore it from a backup, or delete it to start resolving questions again."
            ),
        )


def load_overrides(path: Path) -> ProjectOverrides:
    if not path.exists():
        return ProjectOverrides()
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise CorruptedOverridesFileError(path, str(exc)) from exc
    try:
        return ProjectOverrides.model_validate(raw)
    except ValidationError as exc:
        raise CorruptedOverridesFileError(path, str(exc)) from exc


def apply_override(question_labels: list[str], override: QuestionOverride) -> dict[str, tuple[CodeRole, int]]:
    """Apply a SCALE override's label_roles (and label_ranks, if present) to
    a question's actual label set. Raises IncompleteOverrideError if any
    label lacks a role assignment -- never defaults an unassigned label to
    any role.

    Rank resolution: if the override carries label_ranks, use them
    directly (validated to cover the same labels as label_roles, AND to be
    a valid rank assignment -- exactly {1, ..., N} for the N labels being
    ranked, each used exactly once; raises InvalidRankAssignmentError
    otherwise, since a duplicate or gapped rank silently skews any mean
    computed over this scale and breaks chart ordering). If the
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
        ranks_for_question = {lb: override.label_ranks[lb] for lb in question_labels}
        expected = set(range(1, len(question_labels) + 1))
        if set(ranks_for_question.values()) != expected:
            raise InvalidRankAssignmentError(override.variable, ranks_for_question)
        return {lb: (roles[lb], ranks_for_question[lb]) for lb in question_labels}

    _ROLE_ORDER = {CodeRole.bottom: 0, CodeRole.neutral: 1, CodeRole.top: 2, CodeRole.nonsubstantive: 3}
    ordered = sorted(question_labels, key=lambda lb: (_ROLE_ORDER[roles[lb]], question_labels.index(lb)))
    rank_by_label = {lb: i + 1 for i, lb in enumerate(ordered) if roles[lb] is not CodeRole.nonsubstantive}
    return {lb: (roles[lb], rank_by_label.get(lb)) for lb in question_labels}


_QTYPE_MAP = {"scale": QuestionType.scale, "binary": QuestionType.binary, "categorical": QuestionType.categorical}


def resolve_with_override(
    substantive_labels: list[str],
    overrides: dict[str, "QuestionOverride"],
    qid: str,
) -> tuple[QuestionType, dict[str, tuple[CodeRole, int]] | None, str | None, str | None] | None:
    """Adapter-facing entry point: if `qid` has a project override, resolve
    this question's classification and roles from the override instead of
    the shared scale library, and return the same (qtype, roles, family,
    variant) shape classify_question_type returns so it drops into each
    adapter's existing branch structure unchanged. Returns None when
    there's no override for this qid, so the caller falls through to its
    normal classify_question_type/resolve_roles call.

    An "excluded" override maps to QuestionType.excluded with roles=None —
    adapters use this to build a placeholder Question that stays out of
    reporting (base_eligible=False) instead of calling classify at all.

    `variant` is always None for an override-resolved scale question: an
    override assigns roles/ranks directly per label, with no named library
    variant behind it (Task B4). This is intentional and means
    diverging-bar centering (which needs variant identity) is correctly
    not permitted for an override-resolved scale question.
    """
    override = overrides.get(qid)
    if override is None:
        return None
    if override.question_type == "excluded":
        return QuestionType.excluded, None, None, None
    if override.question_type == "scale":
        roles = apply_override(substantive_labels, override)
        family = identify_family(substantive_labels, qid=qid)
        return QuestionType.scale, roles, family, None
    return _QTYPE_MAP[override.question_type], None, None, None


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
    family = identify_family(labels, qid=variable)
    if family is None:
        return None
    return OverrideNotice(
        variable=variable,
        message=f"'{variable}' is resolved by a saved override, but the shared scale library would now also resolve it (as '{family}'). The override is still being used.",
    )
