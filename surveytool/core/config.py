from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field


class ToolConfig(BaseModel):
    straightliner_action: Literal["keep", "exclude"] = "keep"
    base_policy: Literal["total_answering", "total_asked"] = "total_answering"
    rounding_decimals: int = 1
    rounding_mode: Literal["half_up"] = "half_up"
    default_banner: list[str] = Field(default_factory=lambda: ["age", "ethnicity"])
    per_project: dict[str, dict[str, Any]] = Field(default_factory=dict)


def load_config(path: Path) -> ToolConfig:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return ToolConfig.model_validate(raw)


def project_config(base: ToolConfig, project_id: str) -> ToolConfig:
    overrides = base.per_project.get(project_id, {})
    if not overrides:
        return base
    merged = base.model_dump(exclude={"per_project"})
    merged.update(overrides)
    merged["per_project"] = base.per_project
    return ToolConfig.model_validate(merged)
