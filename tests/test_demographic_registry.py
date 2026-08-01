"""Demographic registry loader tests.

Section A: synthetic minimal canonical+vendor YAML (temp files), exercising
           each of the three failure modes plus a successful load.
Section B: loads the REAL registry files (surveytool/core/demographics/*.yaml)
           against the REAL vendor Survey objects (via the existing ingest
           adapters) for all three vendors. Forcing function proving the
           value_maps are complete for real data. Skipped automatically when
           vendor files are absent from the project root.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from surveytool.charts.errors import (
    CanonicalCategoryUnreachableError,
    DimensionNotInCanonicalError,
    UnmappedSourceValueError,
)
from surveytool.core.demographic_registry import ResolvedRegistry, load_registry
from surveytool.core.model import Response, ResponseState, Survey

ROOT = Path(__file__).parent.parent
DEMOGRAPHICS_DIR = ROOT / "surveytool" / "core" / "demographics"
CANONICAL_PATH = DEMOGRAPHICS_DIR / "canonical.yaml"
VENDOR_PATHS = {
    "rakuten": DEMOGRAPHICS_DIR / "vendor_rakuten.yaml",
    "milieu": DEMOGRAPHICS_DIR / "vendor_milieu.yaml",
    "toluna": DEMOGRAPHICS_DIR / "vendor_toluna.yaml",
}

SUPPORT_MEASURES_PATH = ROOT / "rakuten_survey_support_measures_data.xlsx"
CHN_CLANS_PATH = ROOT / "rakuten_survey_chn_clans_data.xlsx"
MILIEU_PATH = ROOT / "milieu_survey_coe_data.csv"
TOLUNA_PATH = ROOT / "toluna_survey_misinformation_data.xlsx"


# ── Section A: synthetic fixtures ────────────────────────────────────────────

_CANONICAL_MINIMAL = {
    "dimensions": {
        "gender": {
            "label": "Gender",
            "multi_select": False,
            "categories": [
                {"value": "male", "label": "Male", "order": 1},
                {"value": "female", "label": "Female", "order": 2},
                {"value": "not_stated", "label": "Not stated", "order": 99, "non_response": True},
            ],
        },
    }
}

_VENDOR_OK = {
    "vendor": "acme",
    "dimensions": {
        "gender": {
            "source_column": "G1",
            "value_map": {"1": "male", "2": "female", "9": "not_stated"},
        },
    },
}


def _write_yaml(path: Path, data: dict) -> Path:
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f)
    return path


@pytest.fixture
def canonical_path(tmp_path) -> Path:
    return _write_yaml(tmp_path / "canonical.yaml", _CANONICAL_MINIMAL)


def test_successful_load_returns_resolved_registry(tmp_path, canonical_path):
    vendor_path = _write_yaml(tmp_path / "vendor_acme.yaml", _VENDOR_OK)

    registry = load_registry(canonical_path, {"acme": vendor_path})

    assert isinstance(registry, ResolvedRegistry)
    assert "gender" in registry.canonical.dimensions
    assert registry.vendors["acme"].dimensions["gender"].source_column == "G1"


def test_non_response_category_treated_as_ordinary(tmp_path, canonical_path):
    """not_stated participates in reachability like any other category — no
    special-casing. If the vendor mapping omits it, reachability fails just
    like it would for any other missing category."""
    vendor_missing_non_response = {
        "vendor": "acme",
        "dimensions": {
            "gender": {
                "source_column": "G1",
                "value_map": {"1": "male", "2": "female"},
            },
        },
    }
    vendor_path = _write_yaml(tmp_path / "vendor_acme.yaml", vendor_missing_non_response)

    with pytest.raises(CanonicalCategoryUnreachableError) as exc_info:
        load_registry(canonical_path, {"acme": vendor_path})

    assert exc_info.value.category == "not_stated"


def test_dimension_not_in_canonical_raises(tmp_path, canonical_path):
    vendor_extra_dimension = {
        "vendor": "acme",
        "dimensions": {
            "gender": {
                "source_column": "G1",
                "value_map": {"1": "male", "2": "female", "9": "not_stated"},
            },
            "region": {
                "source_column": "R1",
                "value_map": {"1": "north"},
            },
        },
    }
    vendor_path = _write_yaml(tmp_path / "vendor_acme.yaml", vendor_extra_dimension)

    with pytest.raises(DimensionNotInCanonicalError) as exc_info:
        load_registry(canonical_path, {"acme": vendor_path})

    assert exc_info.value.vendor == "acme"
    assert exc_info.value.dimension == "region"


def test_canonical_category_unreachable_raises(tmp_path, canonical_path):
    vendor_incomplete = {
        "vendor": "acme",
        "dimensions": {
            "gender": {
                "source_column": "G1",
                # missing "not_stated" target entirely
                "value_map": {"1": "male", "2": "female"},
            },
        },
    }
    vendor_path = _write_yaml(tmp_path / "vendor_acme.yaml", vendor_incomplete)

    with pytest.raises(CanonicalCategoryUnreachableError) as exc_info:
        load_registry(canonical_path, {"acme": vendor_path})

    assert exc_info.value.vendor == "acme"
    assert exc_info.value.dimension == "gender"
    assert exc_info.value.category == "not_stated"


def test_reachability_checked_before_unmapped_source_value(tmp_path, canonical_path):
    """Rule 1 (cheap, YAML-only) runs before rule 2 (needs data) — an
    unreachable-category failure is raised even though survey data is
    supplied and would also trigger an unmapped-value failure."""
    vendor_incomplete = {
        "vendor": "acme",
        "dimensions": {
            "gender": {
                "source_column": "G1",
                "value_map": {"1": "male", "2": "female"},
            },
        },
    }
    vendor_path = _write_yaml(tmp_path / "vendor_acme.yaml", vendor_incomplete)

    survey = Survey(
        id="s1",
        n_raw=1,
        n_analysis=1,
        responses=[
            Response(respondent_id="r1", qid="G1", raw_value="7", state=ResponseState.answered),
        ],
    )

    with pytest.raises(CanonicalCategoryUnreachableError):
        load_registry(canonical_path, {"acme": vendor_path}, surveys={"acme": survey})


def test_unmapped_source_value_raises_when_present_in_real_data(tmp_path, canonical_path):
    vendor_path = _write_yaml(tmp_path / "vendor_acme.yaml", _VENDOR_OK)

    survey = Survey(
        id="s1",
        n_raw=1,
        n_analysis=1,
        responses=[
            Response(respondent_id="r1", qid="G1", raw_value="1", state=ResponseState.answered),
            Response(respondent_id="r2", qid="G1", raw_value="7", state=ResponseState.answered),
        ],
    )

    with pytest.raises(UnmappedSourceValueError) as exc_info:
        load_registry(canonical_path, {"acme": vendor_path}, surveys={"acme": survey})

    assert exc_info.value.vendor == "acme"
    assert exc_info.value.dimension == "gender"
    assert exc_info.value.raw_value == "7"


def test_unmapped_source_value_not_checked_without_survey_data(tmp_path, canonical_path):
    """Without a surveys entry for a vendor, rule 2 is skipped for that
    vendor — reachability (rule 1) alone is enough to succeed."""
    vendor_path = _write_yaml(tmp_path / "vendor_acme.yaml", _VENDOR_OK)

    registry = load_registry(canonical_path, {"acme": vendor_path}, surveys=None)
    assert isinstance(registry, ResolvedRegistry)


def test_multi_select_source_values_split_on_delimiter(tmp_path):
    canonical_multi = {
        "dimensions": {
            "reasons": {
                "label": "Reasons",
                "multi_select": True,
                "categories": [
                    {"value": "cost", "label": "Cost", "order": 1},
                    {"value": "time", "label": "Time", "order": 2},
                ],
            },
        }
    }
    canonical_path = _write_yaml(tmp_path / "canonical.yaml", canonical_multi)
    vendor = {
        "vendor": "acme",
        "dimensions": {
            "reasons": {
                "source_column": "R1",
                "multi_select": True,
                "value_map": {"1": "cost", "2": "time"},
            },
        },
    }
    vendor_path = _write_yaml(tmp_path / "vendor_acme.yaml", vendor)

    survey = Survey(
        id="s1",
        n_raw=1,
        n_analysis=1,
        responses=[
            Response(respondent_id="r1", qid="R1", raw_value="1; 2", state=ResponseState.answered),
        ],
    )

    registry = load_registry(canonical_path, {"acme": vendor_path}, surveys={"acme": survey})
    assert isinstance(registry, ResolvedRegistry)


def test_multi_select_unmapped_value_in_delimited_list_raises(tmp_path):
    canonical_multi = {
        "dimensions": {
            "reasons": {
                "label": "Reasons",
                "multi_select": True,
                "categories": [
                    {"value": "cost", "label": "Cost", "order": 1},
                ],
            },
        }
    }
    canonical_path = _write_yaml(tmp_path / "canonical.yaml", canonical_multi)
    vendor = {
        "vendor": "acme",
        "dimensions": {
            "reasons": {
                "source_column": "R1",
                "multi_select": True,
                "value_map": {"1": "cost"},
            },
        },
    }
    vendor_path = _write_yaml(tmp_path / "vendor_acme.yaml", vendor)

    survey = Survey(
        id="s1",
        n_raw=1,
        n_analysis=1,
        responses=[
            Response(respondent_id="r1", qid="R1", raw_value="1; 9", state=ResponseState.answered),
        ],
    )

    with pytest.raises(UnmappedSourceValueError) as exc_info:
        load_registry(canonical_path, {"acme": vendor_path}, surveys={"acme": survey})

    assert exc_info.value.raw_value == "9"


# ── Section B: real registry files against real vendor Survey objects ───────

@pytest.fixture(scope="module")
def rakuten_surveys():
    from surveytool.ingest.rakuten import load
    return {
        "support_measures": load(SUPPORT_MEASURES_PATH, "support-measures"),
        "chn_clans": load(CHN_CLANS_PATH, "chn-clans"),
    }


@pytest.mark.skipif(
    not SUPPORT_MEASURES_PATH.exists(),
    reason="HC file rakuten_survey_support_measures_data.xlsx not found in project root",
)
def test_real_rakuten_registry_loads_with_support_measures_file(rakuten_surveys):
    registry = load_registry(
        CANONICAL_PATH,
        {"rakuten": VENDOR_PATHS["rakuten"]},
        surveys={"rakuten": rakuten_surveys["support_measures"]},
    )
    assert isinstance(registry, ResolvedRegistry)
    assert set(registry.vendors["rakuten"].dimensions) == {
        "gender", "age_band", "ethnicity", "residential_status",
    }


@pytest.mark.skipif(
    not CHN_CLANS_PATH.exists(),
    reason="HC file rakuten_survey_chn_clans_data.xlsx not found in project root",
)
def test_real_rakuten_registry_loads_with_chn_clans_file(rakuten_surveys):
    registry = load_registry(
        CANONICAL_PATH,
        {"rakuten": VENDOR_PATHS["rakuten"]},
        surveys={"rakuten": rakuten_surveys["chn_clans"]},
    )
    assert isinstance(registry, ResolvedRegistry)


@pytest.mark.skipif(
    not MILIEU_PATH.exists(),
    reason="HC file milieu_survey_coe_data.csv not found in project root",
)
def test_real_milieu_registry_loads_with_no_unmapped_values():
    from surveytool.ingest.milieu import load
    survey = load(MILIEU_PATH, "coe")

    registry = load_registry(
        CANONICAL_PATH,
        {"milieu": VENDOR_PATHS["milieu"]},
        surveys={"milieu": survey},
    )
    assert isinstance(registry, ResolvedRegistry)
    assert set(registry.vendors["milieu"].dimensions) == {
        "gender", "ethnicity", "car_ownership", "car_ownership_reasons",
    }


@pytest.mark.skipif(
    not TOLUNA_PATH.exists(),
    reason="HC file toluna_survey_misinformation_data.xlsx not found in project root",
)
def test_real_toluna_registry_loads_with_no_unmapped_values():
    from surveytool.ingest.toluna import load
    survey = load(TOLUNA_PATH, "misinformation")

    registry = load_registry(
        CANONICAL_PATH,
        {"toluna": VENDOR_PATHS["toluna"]},
        surveys={"toluna": survey},
    )
    assert isinstance(registry, ResolvedRegistry)
    # age_band deliberately absent: Toluna's 5 age bands don't cover the
    # canonical under_18/55_64/65_plus categories (see vendor_toluna.yaml).
    assert set(registry.vendors["toluna"].dimensions) == {
        "gender", "ethnicity", "income", "education",
    }
    assert "age_band" not in registry.vendors["toluna"].dimensions


@pytest.mark.skipif(
    not (SUPPORT_MEASURES_PATH.exists() and MILIEU_PATH.exists() and TOLUNA_PATH.exists()),
    reason="one or more HC vendor files not found in project root",
)
def test_real_full_registry_loads_all_three_vendors_together(rakuten_surveys):
    from surveytool.ingest.milieu import load as load_milieu
    from surveytool.ingest.toluna import load as load_toluna

    surveys = {
        "rakuten": rakuten_surveys["support_measures"],
        "milieu": load_milieu(MILIEU_PATH, "coe"),
        "toluna": load_toluna(TOLUNA_PATH, "misinformation"),
    }

    registry = load_registry(CANONICAL_PATH, VENDOR_PATHS, surveys=surveys)

    assert isinstance(registry, ResolvedRegistry)
    assert set(registry.vendors) == {"rakuten", "milieu", "toluna"}
    # gender and ethnicity are declared by all three vendors
    for vendor in ("rakuten", "milieu", "toluna"):
        assert "gender" in registry.vendors[vendor].dimensions
        assert "ethnicity" in registry.vendors[vendor].dimensions
