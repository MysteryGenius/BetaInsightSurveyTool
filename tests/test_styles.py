import re
from pathlib import Path

from surveytool.charts.styles import ChartStyle, DEFAULT_STYLE, STYLE_REGISTRY, get_style
from surveytool.charts.palette import CATEGORICAL_PALETTE

_CHART_LEGEND_JS = Path(__file__).parent.parent / "surveytool" / "desktop" / "static" / "chart_legend.js"


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


def _parse_client_chart_styles(js_text: str) -> dict[str, dict]:
    """Extracts chart_legend.js's CLIENT_CHART_STYLES object into a plain dict of
    {style_name: {"palette": [...], "background": "...", "fontColor": "..."}}.

    This is a minimal structural extraction (regex over the known,
    hand-authored literal shape), not a real JS parser -- it only needs to
    be precise enough to catch STYLE_REGISTRY/CLIENT_CHART_STYLES drifting
    apart, the exact failure mode a prior task-level review already caught
    once (brand's palette was null in the JS instead of matching
    CATEGORICAL_PALETTE).
    """
    match = re.search(
        r"const CLIENT_CHART_STYLES = \{(.*?)\n\};", js_text, re.DOTALL
    )
    assert match is not None, "CLIENT_CHART_STYLES object not found in chart_legend.js"
    body = match.group(1)

    styles: dict[str, dict] = {}
    # One block per style entry: `name: { palette: [...], background: "...", fontColor: "..." },`
    for entry_match in re.finditer(
        r"(\w+):\s*\{\s*palette:\s*\[(.*?)\],\s*background:\s*\"(#[0-9A-Fa-f]{6})\",\s*fontColor:\s*\"(#[0-9A-Fa-f]{6})\",?\s*\}",
        body,
        re.DOTALL,
    ):
        name, palette_raw, background, font_color = entry_match.groups()
        palette = tuple(re.findall(r"\"(#[0-9A-Fa-f]{6})\"", palette_raw))
        styles[name] = {
            "palette": palette,
            "background": background,
            "fontColor": font_color,
        }
    return styles


def test_client_chart_styles_js_matches_python_style_registry_exactly():
    """Guards against surveytool/desktop/static/chart_legend.js's
    CLIENT_CHART_STYLES (a hand-duplicated client-side mirror of
    STYLE_REGISTRY, needed so the on-screen chart can apply a chosen style
    without a server round trip) drifting away from
    surveytool/charts/styles.py's STYLE_REGISTRY. A prior task-level review
    already caught one instance of this drift (brand's palette was null in
    the JS when it should have matched CATEGORICAL_PALETTE) -- this test
    fails loudly if a future edit updates one registry without the other.

    CLIENT_CHART_STYLES originally lived in breaks.js; it moved to the
    shared chart_legend.js (loaded by both charts.js and breaks.js) so both
    tabs' style pickers can reuse the same client-side mirror.
    """
    js_text = _CHART_LEGEND_JS.read_text(encoding="utf-8")
    client_styles = _parse_client_chart_styles(js_text)

    assert set(client_styles) == set(STYLE_REGISTRY), (
        "CLIENT_CHART_STYLES (chart_legend.js) and STYLE_REGISTRY (styles.py) "
        "must declare the exact same style names."
    )

    for name, python_style in STYLE_REGISTRY.items():
        js_style = client_styles[name]
        assert tuple(js_style["palette"]) == tuple(python_style.palette), (
            f"{name}: chart_legend.js CLIENT_CHART_STYLES palette does not match "
            f"styles.py STYLE_REGISTRY palette.\n"
            f"  JS:     {js_style['palette']}\n"
            f"  Python: {python_style.palette}"
        )
        assert js_style["background"].upper() == python_style.background.upper(), (
            f"{name}: chart_legend.js background {js_style['background']!r} != "
            f"styles.py background {python_style.background!r}"
        )
        assert js_style["fontColor"].upper() == python_style.font_color.upper(), (
            f"{name}: chart_legend.js fontColor {js_style['fontColor']!r} != "
            f"styles.py font_color {python_style.font_color!r}"
        )
