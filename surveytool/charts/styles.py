"""Chart style presets (chart style selector feature).

A ChartStyle varies exactly three things about a rendered chart: its
categorical palette, its background colour, and its font colour. Nothing
else -- chart type, layout, spacing, and typography (font family/weight)
are unaffected by style, per the feature's design spec.

`brand` is the default: it reuses palette.py's CATEGORICAL_PALETTE
verbatim and the background/font-colour values plotly_renderer.py has
always hardcoded, so choosing no style is byte-for-byte identical to
pre-this-feature behaviour (the same "additive, nothing changes unless
opted in" guarantee Round C1/C3 both maintained).

Each non-brand preset has its own independently validated 12-entry
palette (not a recolouring of CATEGORICAL_PALETTE). Validation is per-pair
pairwise distinguishability: every pairwise greyscale luminance difference
(formula: L = 0.299*R + 0.587*G + 0.114*B) is >= 15 (on 0-255 scale), and
every pairwise Euclidean RGB distance under protanopia/deuteranopia/
tritanopia simulation (Machado/Oliveira/Fluck 2009 matrices) is >= 20
(on 0-255 per-channel scale). The validation script and matrices are in
scratch_validate_palettes.py, which was used to generate these values
and should be deleted before ship (not part of the shipped codebase).
"""
from __future__ import annotations

from dataclasses import dataclass

from surveytool.charts.palette import CATEGORICAL_PALETTE


@dataclass(frozen=True)
class ChartStyle:
    name: str
    palette: tuple[str, ...]
    background: str
    font_color: str


_BRAND = ChartStyle(
    name="brand",
    palette=CATEGORICAL_PALETTE,
    background="#F4F1EA",
    font_color="#222222",
)

_HIGH_CONTRAST = ChartStyle(
    name="high_contrast",
    palette=(
        "#000000", "#FFFFFF", "#07191B", "#0D3914",
        "#185222", "#3F601F", "#726B0E", "#DA2DE5",
        "#22C36F", "#65CE31", "#19EEFF", "#96EF5C",
    ),
    background="#FFFFFF",
    font_color="#000000",
)

_COOL = ChartStyle(
    name="cool",
    palette=(
        "#041A1D", "#371B3F", "#2E3D53", "#612ADC",
        "#0E71F0", "#3084E5", "#5E9BA1", "#2FC9D8",
        "#6ECFC1", "#88D1FF", "#99E2FF", "#99FCFF",
    ),
    background="#F0F4F7",
    font_color="#1A2733",
)

_WARM = ChartStyle(
    name="warm",
    palette=(
        "#1B1309", "#3E2013", "#533420", "#833838",
        "#9D4756", "#86820F", "#B67A62", "#F18734",
        "#F9A81D", "#D2CD72", "#F2DA86", "#F8FE68",
    ),
    background="#FBF3EC",
    font_color="#332118",
)

STYLE_REGISTRY: dict[str, ChartStyle] = {s.name: s for s in (_BRAND, _HIGH_CONTRAST, _COOL, _WARM)}
DEFAULT_STYLE: ChartStyle = _BRAND


def get_style(name: str | None) -> ChartStyle:
    """Resolve a style name to its ChartStyle. None (no style chosen) and
    an unknown name (a style deleted from the registry after being saved,
    or corrupted input) both fall back to DEFAULT_STYLE silently -- a
    chart must never fail to render because of an unrecognised style
    name."""
    if name is None:
        return DEFAULT_STYLE
    return STYLE_REGISTRY.get(name, DEFAULT_STYLE)
