from __future__ import annotations

from dataclasses import dataclass

from surveytool.findings.sheet import FindingsRow


@dataclass(frozen=True)
class Mismatch:
    qid: str
    breakdown_variable: str
    breakdown_level: str
    metric: str
    written_value: float
    computed_value: float | None
    delta: float | None   # written − computed; None when computed_value is None
    note: str


def reconcile(
    findings: list[FindingsRow],
    written: dict[str, float],
    tolerance: float = 0.05,
) -> list[Mismatch]:
    """Compare written figures against the findings sheet.

    Keys in ``written`` must use the form ``"{qid}|{breakdown_variable}|{breakdown_level}|{metric}"``.
    Returns a list of Mismatch objects for every entry that disagrees with the sheet
    (or is absent from it). Empty list means perfect agreement.
    """
    index: dict[str, FindingsRow] = {}
    for row in findings:
        key = f"{row.qid}|{row.breakdown_variable}|{row.breakdown_level}|{row.metric}"
        index[key] = row

    mismatches: list[Mismatch] = []
    for key, written_value in written.items():
        parts = key.split("|", 3)
        if len(parts) == 4:
            qid, bvar, blevel, metric = parts
        else:
            qid, bvar, blevel, metric = key, "", "", ""

        row = index.get(key)
        if row is None:
            mismatches.append(Mismatch(
                qid=qid,
                breakdown_variable=bvar,
                breakdown_level=blevel,
                metric=metric,
                written_value=written_value,
                computed_value=None,
                delta=None,
                note="key not found in findings sheet",
            ))
            continue

        computed = row.value
        if computed is None or abs(written_value - computed) > tolerance:
            delta = (written_value - computed) if computed is not None else None
            note = (
                f"written {written_value} vs computed {computed} "
                f"(delta {delta:+.3f})" if delta is not None
                else f"written {written_value} but computed value is None"
            )
            mismatches.append(Mismatch(
                qid=qid,
                breakdown_variable=bvar,
                breakdown_level=blevel,
                metric=metric,
                written_value=written_value,
                computed_value=computed,
                delta=delta,
                note=note,
            ))

    return mismatches
