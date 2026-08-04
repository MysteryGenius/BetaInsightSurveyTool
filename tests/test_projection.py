"""projection.project() tests.

Section A: real Rakuten fixture (support-measures), break on age_band, no
           filter -- successful projection, correct cell_count/base_total/
           base_filtered, band tally, chart_render_permitted.
Section B: validation failure surfaces as Projection.errors, not a raise.
Section C: chart_render_permitted flips to False when cell_count exceeds a
           lowered render_column_ceiling.
Section D: structural proof project() never imports/calls into per-question
           compute (surveytool.compute.frequency).
Section E: suppressed_count/low_base_count tally correctly against real
           cells, forced into those bands via a lowered
           cross_tab_suppress_threshold / suppression_low_base_multiplier.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from surveytool.core.break_filter import BreakSpec, FilterSpec
from surveytool.core.config import ToolConfig
from surveytool.core.demographic_registry import load_registry
from surveytool.core.projection import DimensionSummary, Projection, project
from surveytool.core.respondent_frame import to_respondent_frame
from surveytool.core.suppression import Band

ROOT = Path(__file__).parent.parent
DEMOGRAPHICS_DIR = ROOT / "surveytool" / "core" / "demographics"
CANONICAL_PATH = DEMOGRAPHICS_DIR / "canonical.yaml"
VENDOR_PATHS = {
    "rakuten": DEMOGRAPHICS_DIR / "vendor_rakuten.yaml",
    "milieu": DEMOGRAPHICS_DIR / "vendor_milieu.yaml",
    "toluna": DEMOGRAPHICS_DIR / "vendor_toluna.yaml",
}
SUPPORT_MEASURES_PATH = ROOT / "rakuten_survey_support_measures_data.xlsx"


@pytest.fixture(scope="module")
def support_measures_survey():
    if not SUPPORT_MEASURES_PATH.exists():
        pytest.skip("HC file rakuten_survey_support_measures_data.xlsx not found in project root")
    from surveytool.ingest.rakuten import load

    return load(SUPPORT_MEASURES_PATH, "support-measures")


@pytest.fixture(scope="module")
def support_measures_frame(support_measures_survey):
    return to_respondent_frame(support_measures_survey)


@pytest.fixture(scope="module")
def support_measures_registry(support_measures_survey):
    return load_registry(
        CANONICAL_PATH,
        {"rakuten": VENDOR_PATHS["rakuten"]},
        surveys={"rakuten": support_measures_survey},
    )


# ── Section A: successful projection against real data ──────────────────────

def test_successful_projection_age_band_no_filter(
    support_measures_survey, support_measures_frame, support_measures_registry
):
    config = ToolConfig()
    result = project(
        BreakSpec(dimensions=["age_band"]),
        FilterSpec(),
        support_measures_survey,
        support_measures_frame,
        support_measures_registry,
        "rakuten",
        config,
    )

    assert isinstance(result, Projection)
    assert result.errors == []
    assert result.base_total == len(support_measures_frame)
    assert result.base_filtered == len(support_measures_frame)  # no filter applied

    # Known real cell sizes for age_band on this fixture (verified directly):
    # 18-24:50, 25-34:250, 35-44:250, 45-54:250, 55-64:137, 65+:63
    assert result.cell_count == 6
    assert len(result.cells) == 6
    assert sum(c.base_cell for c in result.cells) == result.base_filtered

    # Default thresholds (10 / 2.0 -> low_base_threshold=20): every real
    # age_band cell here (>=50) is well above that, so all cells are "ok".
    assert result.suppressed_count == 0
    assert result.low_base_count == 0
    assert all(c.band == Band.ok for c in result.cells)

    assert result.render_ceiling == config.render_column_ceiling
    assert result.chart_render_permitted is True  # 6 <= 24

    assert result.break_dimensions == [DimensionSummary(dimension="age_band", label="Age band")]

    # key/label_path shape sanity per build plan section 6.
    for cell in result.cells:
        assert cell.key == [["age_band", cell.key[0][1]]]
        assert len(cell.label_path) == 1


# ── Section B: validation failure surfaces as data, not a raise ─────────────

def test_validation_failure_populates_errors_not_raised(
    support_measures_survey, support_measures_frame, support_measures_registry
):
    config = ToolConfig()

    # Duplicate break dimension -- DUPLICATE_BREAK_DIMENSION, per build plan
    # section 4 check 2. Must not raise.
    result = project(
        BreakSpec(dimensions=["age_band", "age_band"]),
        FilterSpec(),
        support_measures_survey,
        support_measures_frame,
        support_measures_registry,
        "rakuten",
        config,
    )

    assert isinstance(result, Projection)
    assert len(result.errors) == 1
    assert result.errors[0].code == "DUPLICATE_BREAK_DIMENSION"
    assert result.errors[0].message
    assert result.errors[0].detail is not None
    assert result.errors[0].next_action is not None

    # Every other field at a sensible empty/zero default.
    assert result.cell_count == 0
    assert result.cells == []
    assert result.suppressed_count == 0
    assert result.low_base_count == 0
    assert result.break_dimensions == []
    assert result.chart_render_permitted is False
    assert result.base_filtered == 0

    # base_total is still populated -- it doesn't depend on validation.
    assert result.base_total == len(support_measures_frame)


# ── Section C: chart_render_permitted flips False above a lowered ceiling ───

def test_chart_render_permitted_false_above_lowered_ceiling(
    support_measures_survey, support_measures_frame, support_measures_registry
):
    # age_band resolves to 6 real cells on this fixture; force the ceiling
    # below that instead of needing huge real data.
    config = ToolConfig(render_column_ceiling=3)
    result = project(
        BreakSpec(dimensions=["age_band"]),
        FilterSpec(),
        support_measures_survey,
        support_measures_frame,
        support_measures_registry,
        "rakuten",
        config,
    )

    assert result.errors == []
    assert result.cell_count == 6
    assert result.render_ceiling == 3
    assert result.chart_render_permitted is False


def test_chart_render_permitted_true_at_default_ceiling(
    support_measures_survey, support_measures_frame, support_measures_registry
):
    config = ToolConfig()  # default render_column_ceiling=24
    result = project(
        BreakSpec(dimensions=["age_band"]),
        FilterSpec(),
        support_measures_survey,
        support_measures_frame,
        support_measures_registry,
        "rakuten",
        config,
    )
    assert result.cell_count == 6
    assert result.chart_render_permitted is True


# ── Section D: structural proof of no per-question compute ──────────────────

def test_projection_module_does_not_import_frequency_compute():
    """project() must never touch surveytool.compute.frequency (or any
    per-question compute path) -- that's what keeps projection cheap enough
    to run on every UI pill change. Prove it structurally: the module source
    names no such import."""
    import ast

    import surveytool.core.projection as projection_module

    source = Path(projection_module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)

    assert not any("compute.frequency" in name for name in imported_modules)

    # No call site anywhere in the module actually invokes
    # compute_question_stats (a bare textual check would also flag this
    # docstring's own explanatory prose, so walk the AST for Call nodes).
    called_names = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "compute_question_stats" not in called_names

    # Also confirm the module object itself never pulled it in transitively
    # via a wildcard/indirect import.
    assert not hasattr(projection_module, "compute_question_stats")


def test_projection_does_not_import_frequency_module_at_runtime(
    support_measures_survey, support_measures_frame, support_measures_registry
):
    """Belt-and-braces: after calling project(), surveytool.compute.frequency
    must not have been imported as a side effect (it may already be imported
    by an unrelated test in the same process, so this only checks that
    project() itself doesn't trigger the import fresh)."""
    import sys

    was_already_imported = "surveytool.compute.frequency" in sys.modules

    config = ToolConfig()
    project(
        BreakSpec(dimensions=["age_band"]),
        FilterSpec(),
        support_measures_survey,
        support_measures_frame,
        support_measures_registry,
        "rakuten",
        config,
    )

    if not was_already_imported:
        assert "surveytool.compute.frequency" not in sys.modules


# ── Section E: suppressed_count / low_base_count tally correctly ────────────

def test_suppressed_and_low_base_counts_match_real_cell_bands(
    support_measures_survey, support_measures_frame, support_measures_registry
):
    """Real age_band cells: 18-24:50, 25-34:250, 35-44:250, 45-54:250,
    55-64:137, 65+:63. Choose thresholds that split these into all three
    bands: hard_threshold=60 (suppress <60 -> only 18-24:50 suppressed),
    multiplier=2.5 -> low_base_threshold=150 (low_base in [60,150) ->
    65+:63 and 55-64:137; ok >=150 -> 25-34, 35-44, 45-54)."""
    config = ToolConfig(cross_tab_suppress_threshold=60, suppression_low_base_multiplier=2.5)

    result = project(
        BreakSpec(dimensions=["age_band"]),
        FilterSpec(),
        support_measures_survey,
        support_measures_frame,
        support_measures_registry,
        "rakuten",
        config,
    )

    assert result.errors == []
    assert result.cell_count == 6

    expected_bands = {}
    for cell in result.cells:
        n = cell.base_cell
        if n < 60:
            expected_bands[cell.label_path[0]] = Band.suppressed
        elif n < 150:
            expected_bands[cell.label_path[0]] = Band.low_base
        else:
            expected_bands[cell.label_path[0]] = Band.ok

    for cell in result.cells:
        assert cell.band == expected_bands[cell.label_path[0]]

    assert result.suppressed_count == sum(1 for b in expected_bands.values() if b == Band.suppressed)
    assert result.low_base_count == sum(1 for b in expected_bands.values() if b == Band.low_base)
    assert result.suppressed_count == 1  # only 18-24 (50) is < 60
    assert result.low_base_count == 2  # 55-64 (137) and 65+ (63) are in [60, 150)
