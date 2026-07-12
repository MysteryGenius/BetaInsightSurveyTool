from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from surveytool.findings.sheet import FindingsRow

ChartType = Literal["dist", "xbreak", "means"]

_UNSAFE = re.compile(r"[^\w\-]")


def _safe(s: str) -> str:
    return _UNSAFE.sub("_", s)[:40].strip("_")


@dataclass
class ChartSpec:
    chart_type: ChartType
    survey_id: str
    qid: str
    question_text: str
    breakdown_variable: str
    metric: str
    rows: list[FindingsRow]

    @property
    def filename(self) -> str:
        return (
            f"{_safe(self.survey_id)}"
            f"__{_safe(self.qid)}"
            f"__{self.chart_type}"
            f"__{_safe(self.breakdown_variable)}.png"
        )
