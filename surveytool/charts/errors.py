from __future__ import annotations


class MissingFindingsRow(KeyError):
    """Raised when a required row is absent from the findings sheet.

    Never substitute a zero or default — the chart must fail loudly so the
    caller knows the findings sheet is incomplete for this question/breakdown.
    """

    def __init__(self, qid: str, breakdown_variable: str, breakdown_level: str, metric: str) -> None:
        self.qid = qid
        self.breakdown_variable = breakdown_variable
        self.breakdown_level = breakdown_level
        self.metric = metric
        super().__init__(
            f"Missing findings row: qid={qid!r} breakdown_variable={breakdown_variable!r} "
            f"breakdown_level={breakdown_level!r} metric={metric!r}"
        )
