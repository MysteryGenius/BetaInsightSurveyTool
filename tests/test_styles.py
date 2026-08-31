from surveytool.charts.styles import ChartStyle, DEFAULT_STYLE, STYLE_REGISTRY, get_style
from surveytool.charts.palette import CATEGORICAL_PALETTE


def test_registry_has_exactly_four_presets():
    assert set(STYLE_REGISTRY) == {"brand", "high_contrast", "cool", "warm"}


def test_brand_is_the_default_style():
    assert DEFAULT_STYLE.name == "brand"
    assert DEFAULT_STYLE is STYLE_REGISTRY["brand"]


def test_brand_reuses_categorical_palette_verbatim():
    assert STYLE_REGISTRY["brand"].palette == CATEGORICAL_PALETTE


def test_brand_matches_current_hardcoded_colours():
    """Byte-for-byte match to the values plotly_renderer._apply_header
    hardcodes today (#F4F1EA / #222222) -- the additive guarantee that
    choosing no style is identical to today's behaviour."""
    assert STYLE_REGISTRY["brand"].background == "#F4F1EA"
    assert STYLE_REGISTRY["brand"].font_color == "#222222"


def test_every_preset_has_twelve_distinct_palette_entries():
    for style in STYLE_REGISTRY.values():
        assert len(style.palette) == 12, style.name
        assert len(set(style.palette)) == 12, style.name


def test_non_brand_presets_have_their_own_distinct_palette():
    """Each non-brand preset's palette must be its own set, not a
    recolouring/reuse of CATEGORICAL_PALETTE or of each other."""
    palettes = [STYLE_REGISTRY[name].palette for name in ("high_contrast", "cool", "warm")]
    all_palettes = [CATEGORICAL_PALETTE, *palettes]
    for i in range(len(all_palettes)):
        for j in range(i + 1, len(all_palettes)):
            assert all_palettes[i] != all_palettes[j]


def test_get_style_returns_named_style():
    assert get_style("cool") is STYLE_REGISTRY["cool"]


def test_get_style_none_falls_back_to_brand():
    assert get_style(None) is DEFAULT_STYLE


def test_get_style_unknown_name_falls_back_to_brand_silently():
    assert get_style("nonexistent_style_name") is DEFAULT_STYLE


def test_chart_style_is_frozen():
    style = STYLE_REGISTRY["brand"]
    try:
        style.name = "changed"
        assert False, "ChartStyle must be frozen"
    except AttributeError:
        pass
