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
