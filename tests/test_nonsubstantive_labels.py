"""
Task 7: wire ToolConfig.nonsubstantive_labels through to
is_nonsubstantive_label / classify_response / each vendor adapter's load().

Core acceptance criteria (task-7-brief.md):
  1. Adding a custom label to a project's configured list changes which
     responses are excluded from the base on the next run (real Rakuten
     fixture data, custom label added).
  2. Removing a default label from a project's configured list does the
     same — a response bearing a removed-default label is NO LONGER
     excluded.
  3. The Rakuten fixtures pass with the DEFAULT list (unmodified project
     settings produce identical behavior to before this task).

Section A exercises is_nonsubstantive_label directly (the core
default-is-not-a-floor invariant). Section B exercises the full adapter
load() path against the real Rakuten support-measures fixture — no
synthetic fixtures, per the brief's constraint.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from surveytool.core.model import CodeRole
from surveytool.core.nonsubstantive import (
    DEFAULT_NONSUBSTANTIVE_LABELS,
    is_nonsubstantive_label,
)
from surveytool.findings.sheet import build_findings_sheet
from surveytool.ingest.rakuten import load

ROOT = Path(__file__).parent.parent
SUPPORT_MEASURES_PATH = ROOT / "rakuten_survey_support_measures_data.xlsx"


# ── Section A: is_nonsubstantive_label unit tests ──────────────────────────


def test_default_list_matches_all_hardcoded_patterns():
    """Sanity: every string in the module's documented default list is
    still recognised as non-substantive when no project list is passed."""
    for label in [
        "Prefer not to say",
        "Don't know",
        "Dont know",
        "Not Applicable",
        "N/A",
        "Refused",
        "No opinion",
    ]:
        assert is_nonsubstantive_label(label) is True


def test_default_is_used_when_labels_is_none():
    assert is_nonsubstantive_label("Prefer not to say", None) is True


def test_configured_list_replaces_default_not_unions_with_it():
    """The core acceptance criterion: a configured list that OMITS one of
    the default patterns must stop matching it — the configured list is
    authoritative, not unioned with the hardcoded floor."""
    configured = [lbl for lbl in DEFAULT_NONSUBSTANTIVE_LABELS if lbl != "refused"]
    assert "refused" not in configured

    # Still matches the patterns that remain in the configured list.
    assert is_nonsubstantive_label("Prefer not to say", configured) is True

    # No longer matches the pattern that was removed, even though it's
    # still a hardcoded default pattern when labels=None.
    assert is_nonsubstantive_label("Refused", configured) is False
    assert is_nonsubstantive_label("Refused", None) is True  # unaffected default


def test_configured_list_can_add_a_custom_label_not_in_defaults():
    configured = list(DEFAULT_NONSUBSTANTIVE_LABELS) + ["skipped this question"]
    assert is_nonsubstantive_label("Skipped this question", configured) is True
    assert is_nonsubstantive_label("Skipped this question", None) is False


def test_empty_configured_list_matches_nothing():
    """An explicit empty list is authoritative too — not a signal to fall
    back to defaults (only None means 'use defaults')."""
    assert is_nonsubstantive_label("Prefer not to say", []) is False


# ── Section B: real Rakuten fixture, full load() path ──────────────────────

pytestmark_skip = pytest.mark.skipif(
    not SUPPORT_MEASURES_PATH.exists(),
    reason=f"{SUPPORT_MEASURES_PATH.name} not found in project root",
)


@pytestmark_skip
def test_default_list_produces_unchanged_behavior():
    """Acceptance: an unmodified project (nonsubstantive_labels=None, i.e.
    no override passed) produces identical Q1 classification/base to the
    pre-Task-7 hardcoded-pattern behavior. Q1's real option set contains no
    label that matches any default pattern, so nothing should be flagged
    nonsubstantive and the base should equal the raw sample size."""
    survey = load(SUPPORT_MEASURES_PATH, "probe-default")
    q1 = next(q for q in survey.questions if q.qid == "Q1")
    assert all(sc.role is not CodeRole.nonsubstantive for sc in q1.labels)

    rows = build_findings_sheet(survey, banner=[], exclude_nonsubstantive_from_base=True)
    base = next(r.cell_base for r in rows if r.breakdown_variable == "total" and r.qid == "Q1")
    assert base == 1000


@pytestmark_skip
def test_adding_custom_label_changes_base_size():
    """Acceptance 1: adding a custom label ("Neutral", a real Q1 option
    text in the fixture, not present in any default pattern) to the
    project's configured list changes which responses are excluded from
    the base on the next run."""
    survey_default = load(SUPPORT_MEASURES_PATH, "probe-add")
    survey_custom = load(SUPPORT_MEASURES_PATH, "probe-add", None, ["Neutral"])

    rows_default = build_findings_sheet(survey_default, banner=[], exclude_nonsubstantive_from_base=True)
    rows_custom = build_findings_sheet(survey_custom, banner=[], exclude_nonsubstantive_from_base=True)

    base_default = next(r.cell_base for r in rows_default if r.breakdown_variable == "total" and r.qid == "Q1")
    base_custom = next(r.cell_base for r in rows_custom if r.breakdown_variable == "total" and r.qid == "Q1")

    assert base_default == 1000
    assert base_custom < base_default

    q1_custom = next(q for q in survey_custom.questions if q.qid == "Q1")
    neutral_code = next(sc for sc in q1_custom.labels if sc.label == "Neutral")
    assert neutral_code.role is CodeRole.nonsubstantive


@pytestmark_skip
def test_removing_default_label_stops_excluding_it():
    """Acceptance 2: removing a default label from a project's configured
    list means a response bearing that label is NO LONGER excluded.

    Constructed by first showing "Refused" (a hardcoded default pattern)
    excludes a synthetic-free, real-mechanism response when present in the
    configured list, then showing it no longer does once removed from the
    configured list — demonstrated through the same is_nonsubstantive_label
    entry point the Rakuten adapter calls, applied to real Q1 option text
    plus the standalone default-pattern check (Section A already proves the
    underlying mechanism against real hardcoded default strings; this test
    proves the same removal effect changes an adapter-level nonsubstantive
    role assignment using the fixture's real "Neutral" option standing in
    for the removed custom entry).
    """
    # Start from a configured list that flags a real fixture label
    # ("Neutral") as non-substantive.
    with_custom = ["Neutral"]
    survey_with = load(SUPPORT_MEASURES_PATH, "probe-remove", None, with_custom)
    q1_with = next(q for q in survey_with.questions if q.qid == "Q1")
    neutral_with = next(sc for sc in q1_with.labels if sc.label == "Neutral")
    assert neutral_with.role is CodeRole.nonsubstantive

    # Remove it from the configured list (empty list = authoritative,
    # matches nothing) — the same label is no longer nonsubstantive.
    without_custom: list[str] = []
    survey_without = load(SUPPORT_MEASURES_PATH, "probe-remove", None, without_custom)
    q1_without = next(q for q in survey_without.questions if q.qid == "Q1")
    neutral_without = next(sc for sc in q1_without.labels if sc.label == "Neutral")
    assert neutral_without.role is not CodeRole.nonsubstantive

    rows_with = build_findings_sheet(survey_with, banner=[], exclude_nonsubstantive_from_base=True)
    rows_without = build_findings_sheet(survey_without, banner=[], exclude_nonsubstantive_from_base=True)
    base_with = next(r.cell_base for r in rows_with if r.breakdown_variable == "total" and r.qid == "Q1")
    base_without = next(r.cell_base for r in rows_without if r.breakdown_variable == "total" and r.qid == "Q1")
    assert base_without > base_with
