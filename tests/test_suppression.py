"""
Tests for the suppression banding module.

Tests cover Band enum and classify_band function with default and custom
configuration values, including boundary conditions.
"""
from __future__ import annotations

import pytest

from surveytool.core.config import ToolConfig
from surveytool.core.suppression import Band, classify_band


class TestBandEnum:
    """Tests for the Band enum."""

    def test_band_values(self) -> None:
        """Band enum has exactly three members: ok, low_base, suppressed."""
        assert Band.ok.value == "ok"
        assert Band.low_base.value == "low_base"
        assert Band.suppressed.value == "suppressed"
        assert len(Band) == 3


class TestClassifyBandDefaults:
    """Tests for classify_band with default config values.

    Default config: cross_tab_suppress_threshold=10, suppression_low_base_multiplier=2.0
    So: hard_threshold=10, low_base_threshold=20
    """

    def test_boundary_suppressed(self) -> None:
        """base_cell < hard_threshold (9) -> suppressed."""
        config = ToolConfig()
        assert classify_band(9, config) == Band.suppressed

    def test_boundary_low_base_lower(self) -> None:
        """base_cell == hard_threshold (10) -> low_base (inclusive lower boundary)."""
        config = ToolConfig()
        assert classify_band(10, config) == Band.low_base

    def test_boundary_low_base_upper(self) -> None:
        """base_cell == low_base_threshold - 1 (19) -> low_base (inclusive upper boundary, exclusive)."""
        config = ToolConfig()
        assert classify_band(19, config) == Band.low_base

    def test_boundary_ok(self) -> None:
        """base_cell == low_base_threshold (20) -> ok (inclusive boundary)."""
        config = ToolConfig()
        assert classify_band(20, config) == Band.ok

    def test_well_into_suppressed(self) -> None:
        """Very small base_cell is suppressed."""
        config = ToolConfig()
        assert classify_band(1, config) == Band.suppressed
        assert classify_band(5, config) == Band.suppressed

    def test_well_into_low_base(self) -> None:
        """base_cell in middle of low_base range."""
        config = ToolConfig()
        assert classify_band(11, config) == Band.low_base
        assert classify_band(15, config) == Band.low_base

    def test_well_into_ok(self) -> None:
        """Large base_cell is ok."""
        config = ToolConfig()
        assert classify_band(50, config) == Band.ok
        assert classify_band(100, config) == Band.ok


class TestClassifyBandCustomConfig:
    """Tests for classify_band with non-default config values.

    Custom: threshold=5, multiplier=3.0
    So: hard_threshold=5, low_base_threshold=15
    """

    def test_custom_threshold_and_multiplier(self) -> None:
        """Prove low_base_threshold is genuinely computed from both config values."""
        config = ToolConfig(
            cross_tab_suppress_threshold=5,
            suppression_low_base_multiplier=3.0,
        )
        # hard_threshold=5, low_base_threshold=15
        assert classify_band(4, config) == Band.suppressed
        assert classify_band(5, config) == Band.low_base
        assert classify_band(14, config) == Band.low_base
        assert classify_band(15, config) == Band.ok


class TestToolConfigDefaults:
    """Tests confirming ToolConfig's new fields have correct defaults."""

    def test_suppression_low_base_multiplier_default(self) -> None:
        """suppression_low_base_multiplier defaults to 2.0."""
        config = ToolConfig()
        assert config.suppression_low_base_multiplier == 2.0

    def test_render_column_ceiling_default(self) -> None:
        """render_column_ceiling defaults to 24."""
        config = ToolConfig()
        assert config.render_column_ceiling == 24

    def test_breaks_confirmation_gate_depth_default(self) -> None:
        """breaks_confirmation_gate_depth defaults to 3."""
        config = ToolConfig()
        assert config.breaks_confirmation_gate_depth == 3

    def test_cross_tab_suppress_threshold_default(self) -> None:
        """cross_tab_suppress_threshold defaults to 10 (pre-existing field)."""
        config = ToolConfig()
        assert config.cross_tab_suppress_threshold == 10
