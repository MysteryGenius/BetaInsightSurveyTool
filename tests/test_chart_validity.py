"""evaluate_chart_permissions() tests (build plan section 9).

Section A: synthetic QuestionResult shapes -- one test per chart-type rule,
           plus the ceiling-override clobbering an individually-permitted
           type, plus the SCALE_POLARITY_UNDECLARED case.
Section B: real Toluna registry entries for ability/effectiveness/importance/
           likelihood -- pins the build plan's Toluna reporting deliverable.
"""
from __future__ import annotations

import pytest

from surveytool.core.chart_validity import (
    ChartPermission,
    ChartType,
    evaluate_chart_permissions,
)
from surveytool.compute.breaks_compute import NetDefinition, QuestionResult, ScalePoint
from surveytool.core.config import ToolConfig


def _scale_points(n: int) -> list[ScalePoint]:
    return [
        ScalePoint(code=i, label=f"Point {i}", order=i, polarity=None)
        for i in range(n)
    ]


def _question_result(
    scale_id: str | None = "agreement",
    n_scale_points: int = 5,
    nets: list[NetDefinition] | None = None,
    n_columns: int = 3,
) -> QuestionResult:
    return QuestionResult(
        question_id="Q1",
        question_text="Synthetic question",
        scale_id=scale_id,
        scale_points=_scale_points(n_scale_points),
        nets=nets if nets is not None else [],
        base_total=100,
        base_filtered=100,
        columns=[],  # column_count is passed explicitly, not derived here
    )


def _permission_by_type(
    permissions: list[ChartPermission], chart_type: ChartType
) -> ChartPermission:
    return next(p for p in permissions if p.chart_type is chart_type)


# ── stacked_bar_100 ──────────────────────────────────────────────────────

def test_stacked_bar_100_requires_two_or_more_scale_points():
    config = ToolConfig()
    result_one_point = _question_result(n_scale_points=1)
    perms = evaluate_chart_permissions(result_one_point, column_count=3, config=config)
    perm = _permission_by_type(perms, ChartType.stacked_bar_100)
    assert perm.permitted is False

    result_two_points = _question_result(n_scale_points=2)
    perms = evaluate_chart_permissions(result_two_points, column_count=3, config=config)
    perm = _permission_by_type(perms, ChartType.stacked_bar_100)
    assert perm.permitted is True
    assert perm.reason is None


# ── diverging_stacked_bar ────────────────────────────────────────────────

def test_diverging_stacked_bar_declared_vs_undeclared_scale_family():
    config = ToolConfig()

    declared = _question_result(scale_id="agreement")
    perms = evaluate_chart_permissions(declared, column_count=3, config=config)
    perm = _permission_by_type(perms, ChartType.diverging_stacked_bar)
    assert perm.permitted is True
    assert perm.reason is None

    undeclared = _question_result(scale_id="not_a_real_family")
    perms = evaluate_chart_permissions(undeclared, column_count=3, config=config)
    perm = _permission_by_type(perms, ChartType.diverging_stacked_bar)
    assert perm.permitted is False
    assert perm.reason == "SCALE_POLARITY_UNDECLARED"


def test_diverging_stacked_bar_none_scale_id_is_undeclared():
    config = ToolConfig()
    result = _question_result(scale_id=None)
    perms = evaluate_chart_permissions(result, column_count=3, config=config)
    perm = _permission_by_type(perms, ChartType.diverging_stacked_bar)
    assert perm.permitted is False
    assert perm.reason == "SCALE_POLARITY_UNDECLARED"


# ── grouped_bar ──────────────────────────────────────────────────────────

def test_grouped_bar_within_and_above_scale_point_limit():
    config = ToolConfig()

    within = _question_result(n_scale_points=7)
    perms = evaluate_chart_permissions(within, column_count=3, config=config)
    assert _permission_by_type(perms, ChartType.grouped_bar).permitted is True

    above = _question_result(n_scale_points=8)
    perms = evaluate_chart_permissions(above, column_count=3, config=config)
    assert _permission_by_type(perms, ChartType.grouped_bar).permitted is False


def test_grouped_bar_within_and_above_ceiling():
    config = ToolConfig(render_column_ceiling=24)
    result = _question_result(n_scale_points=5)

    within = evaluate_chart_permissions(result, column_count=24, config=config)
    assert _permission_by_type(within, ChartType.grouped_bar).permitted is True

    above = evaluate_chart_permissions(result, column_count=25, config=config)
    assert _permission_by_type(above, ChartType.grouped_bar).permitted is False


# ── net_bar ──────────────────────────────────────────────────────────────

def test_net_bar_with_and_without_nets_defined():
    config = ToolConfig()

    with_net = _question_result(
        nets=[NetDefinition(net_id="t2b", label="Top 2 Box", member_codes=[4, 5])]
    )
    perms = evaluate_chart_permissions(with_net, column_count=3, config=config)
    assert _permission_by_type(perms, ChartType.net_bar).permitted is True

    without_net = _question_result(nets=[])
    perms = evaluate_chart_permissions(without_net, column_count=3, config=config)
    assert _permission_by_type(perms, ChartType.net_bar).permitted is False


# ── table ────────────────────────────────────────────────────────────────

def test_table_always_permitted():
    config = ToolConfig()
    result = _question_result(n_scale_points=1, scale_id=None, nets=[])
    perms = evaluate_chart_permissions(result, column_count=3, config=config)
    perm = _permission_by_type(perms, ChartType.table)
    assert perm.permitted is True
    assert perm.reason is None


# ── ceiling override clobbers individually-permitted rules ─────────────────

def test_ceiling_override_clobbers_individually_permitted_types():
    """stacked_bar_100 would independently be permitted (3 scale points, >=2
    rule satisfied), but column_count exceeds the ceiling, so the override
    must clobber it to refused with the exact ceiling reason. table stays
    permitted in the same scenario."""
    config = ToolConfig(render_column_ceiling=24)
    result = _question_result(n_scale_points=3, scale_id="agreement", nets=[
        NetDefinition(net_id="t2b", label="Top 2 Box", member_codes=[4, 5])
    ])

    perms = evaluate_chart_permissions(result, column_count=25, config=config)

    for chart_type in (
        ChartType.stacked_bar_100,
        ChartType.diverging_stacked_bar,
        ChartType.grouped_bar,
        ChartType.net_bar,
    ):
        perm = _permission_by_type(perms, chart_type)
        assert perm.permitted is False, f"{chart_type} should be clobbered"
        assert perm.reason == "COLUMN_COUNT_EXCEEDS_RENDER_LIMIT"

    table_perm = _permission_by_type(perms, ChartType.table)
    assert table_perm.permitted is True
    assert table_perm.reason is None


# ── Section B: real Toluna registry entries ─────────────────────────────────

@pytest.mark.parametrize(
    "scale_family,expected_declared",
    [
        ("ability", True),
        ("effectiveness", True),
        ("importance", True),
        ("likelihood", True),
    ],
)
def test_toluna_scale_families_declared_polarity(scale_family, expected_declared):
    """Pins the build plan's reporting deliverable: which of the four Toluna
    named scales (ability, effectiveness, importance, likelihood) have
    declared polarity in scale_polarity.yaml. All four are declared -- see
    scale_polarity.yaml and task-7-report.md for the reasoning."""
    config = ToolConfig()
    result = _question_result(scale_id=scale_family)
    perms = evaluate_chart_permissions(result, column_count=3, config=config)
    perm = _permission_by_type(perms, ChartType.diverging_stacked_bar)
    assert perm.permitted is expected_declared
    if not expected_declared:
        assert perm.reason == "SCALE_POLARITY_UNDECLARED"
    else:
        assert perm.reason is None
