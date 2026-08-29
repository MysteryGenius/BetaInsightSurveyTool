"""Single source of truth for display precision (Round C4).

DISPLAY_PRECISION governs every rounded presentation of a percentage figure
-- chart tooltip, chart axis label, chart data label, and the on-screen
panel figure the user reads alongside the chart. All of these must always
agree; the fix for the '8.230453' tooltip bug the spec reports is that no
component rounds independently -- every one of them calls format_percentage
from here.

The findings sheet's underlying FindingsRow.value is NEVER rounded --
full precision stays available there regardless of what DISPLAY_PRECISION
is set to, per the spec: 'Full precision remains available in the
findings sheet.'
"""
from __future__ import annotations

DISPLAY_PRECISION: int = 1


def format_percentage(value: float, precision: int = DISPLAY_PRECISION) -> str:
    return f"{value:.{precision}f}%"
