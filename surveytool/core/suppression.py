"""
Suppression banding for the breaks-and-filters compute core.

This module provides a two-band suppression classification system for the new
N-dimensional breaks system, separate from the legacy three-band CellStatus
in cross_tab.py.
"""
from __future__ import annotations

from enum import Enum

from surveytool.core.config import ToolConfig


class Band(str, Enum):
    """Two-band suppression classification for breaks-and-filters cells."""

    ok = "ok"
    low_base = "low_base"
    suppressed = "suppressed"


def classify_band(base_cell: int, config: ToolConfig) -> Band:
    """
    Classify a cell's base count into a suppression band.

    Args:
        base_cell: The count of respondents in the cell.
        config: The tool configuration containing threshold values.

    Returns:
        Band.suppressed if base_cell < cross_tab_suppress_threshold
        Band.low_base if base_cell is in [cross_tab_suppress_threshold, low_base_threshold)
        Band.ok if base_cell >= low_base_threshold

    The low_base_threshold is derived as:
        cross_tab_suppress_threshold * suppression_low_base_multiplier
    """
    hard_threshold = config.cross_tab_suppress_threshold
    multiplier = config.suppression_low_base_multiplier
    low_base_threshold = hard_threshold * multiplier

    if base_cell < hard_threshold:
        return Band.suppressed
    elif base_cell < low_base_threshold:
        return Band.low_base
    else:
        return Band.ok
