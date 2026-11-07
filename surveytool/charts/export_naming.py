"""Cross-tab export filenames and collision handling (v4 feedback F1).

A Cross-tab PNG's name carries what it shows -- question, chart type,
break-by and filter -- so exporting under a different break never lands on
an earlier file. When a name is still taken, the file gets a numbered
suffix. The only file ever overwritten is one the manifest says came from an
identical earlier export.
"""
from __future__ import annotations

import re
from pathlib import Path

_SLUG_UNSAFE = re.compile(r"[^a-z0-9]+")


def _slug(text: str) -> str:
    return _SLUG_UNSAFE.sub("-", text.lower()).strip("-")


def crosstab_export_stem(
    question_id: str,
    chart_type: str,
    swapped: bool,
    break_dims: list[str],
    filter_spec: dict[str, list[str]] | None,
) -> str:
    """`{qid}_{chart_type}_by-{dims}[_filter-{dim}-{vals}][_swapped]`, no extension.

    Example: `5_grouped_bar_by-gender`. Nested break dimensions are joined
    with `-and-`; each filter dimension gets its own segment (sorted, so the
    same filter always gives the same name), with several values joined
    by `+`.
    """
    parts = [question_id, chart_type, "by-" + "-and-".join(_slug(d) for d in break_dims)]
    for dim in sorted(filter_spec or {}):
        values = sorted((filter_spec or {})[dim])
        if not values:
            continue
        parts.append(f"filter-{_slug(dim)}-" + "+".join(_slug(v) for v in values))
    if swapped:
        parts.append("swapped")
    return "_".join(parts)


def crosstab_export_identity(
    survey_id: str,
    question_id: str,
    chart_type: str,
    swapped: bool,
    break_dims: list[str],
    filter_spec: dict[str, list[str]] | None,
) -> dict:
    """What makes two exports the same chart. Stored in the manifest, so a
    later export can tell an identical re-export (safe to overwrite) from a
    different chart that happens to want the same filename."""
    return {
        "survey_id": survey_id,
        "question_id": question_id,
        "chart_type": chart_type,
        "swap_axes": swapped,
        "break_by": list(break_dims),
        "filter": {dim: sorted(vals) for dim, vals in sorted((filter_spec or {}).items()) if vals},
    }


def _candidates(stem: str):
    yield f"{stem}.png"
    n = 2
    while True:
        yield f"{stem}_{n}.png"
        n += 1


def resolve_export_filename(
    out_dir: Path,
    stem: str,
    identity: dict,
    manifest_by_filename: dict[str, dict],
    taken_this_export: set[str],
) -> tuple[str, bool]:
    """Pick the filename for one export. Returns (filename, replaced).

    - A file from an earlier export whose manifest identity equals `identity`
      is overwritten (replaced=True), including a previously suffixed one.
    - Anything else already there -- a different chart, a file the manifest
      doesn't know about, or a name already used in this same export --
      pushes the new file to the next free `_2`, `_3`... name.
    Never overwrites a file it can't prove is the same chart.
    """
    # Prefer re-using the exact file an identical earlier export wrote.
    for filename, entry in manifest_by_filename.items():
        if filename in taken_this_export or not (out_dir / filename).exists():
            continue
        if entry.get("identity") == identity and (
            filename == f"{stem}.png" or re.fullmatch(re.escape(stem) + r"_\d+\.png", filename)
        ):
            return filename, True

    for filename in _candidates(stem):
        if filename in taken_this_export:
            continue
        if (out_dir / filename).exists():
            continue
        return filename, False
    raise AssertionError("unreachable")  # _candidates is infinite
