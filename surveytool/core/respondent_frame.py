from __future__ import annotations

import pandas as pd

from surveytool.core.model import Survey


def to_respondent_frame(survey: Survey) -> pd.DataFrame:
    """Pivot Survey.responses into one row per respondent_id, one column per qid.

    Pure reshape of raw_value — no netting, scoring, or label resolution.
    """
    rows = [
        {"respondent_id": r.respondent_id, "qid": r.qid, "raw_value": r.raw_value}
        for r in survey.responses
    ]
    long = pd.DataFrame(rows, columns=["respondent_id", "qid", "raw_value"])
    return long.pivot(index="respondent_id", columns="qid", values="raw_value")
