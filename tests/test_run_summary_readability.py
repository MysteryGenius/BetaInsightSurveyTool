"""v4 feedback F5: the Run summary is readable -- guardrail findings as
short separate items, plain-English types, tables that wrap -- and the
top-bar buttons stay readable in every state.

API checks use the real Toluna file; CSS checks read index.html's own
design tokens and compute WCAG contrast from them.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).parent.parent
TOLUNA_PATH = ROOT / "toluna_survey_misinformation_data.xlsx"
INDEX_HTML = ROOT / "surveytool" / "desktop" / "static" / "index.html"
_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_IDENTIFIER = re.compile(r"\b[a-z0-9]+_[a-z0-9_]+\b")


@pytest.fixture
def toluna_summary():
    if not TOLUNA_PATH.exists():
        pytest.skip(f"{TOLUNA_PATH.name} not found in project root")
    from surveytool.desktop.app import app

    client = TestClient(app)
    with open(TOLUNA_PATH, "rb") as f:
        response = client.post(
            "/api/upload",
            data={"vendor": "toluna", "survey_id": "t"},
            files={"file": (TOLUNA_PATH.name, f, _XLSX_MIME)},
        )
    assert response.status_code == 200, response.text
    summary = client.get(f"/api/session/{response.json()['session_id']}/run-summary")
    assert summary.status_code == 200, summary.text
    return summary.json()


# --- 3. guardrail findings as separate short items --------------------------------


def test_guardrail_findings_are_separate_short_items(toluna_summary):
    items = toluna_summary["guardrail_items"]
    assert items[0].startswith("Toluna supplies no quality flag column.")
    assert items[1].startswith("Toluna supplies no verification sheet.")
    assert items[2] == "5 respondent(s) were flagged as straightliners and kept in the base."
    gaps = items[3:]
    # F6 groups gaps that share a reason into one finding.
    assert gaps == [
        "Age band: 'Below 18' was not collected. The age question in this file has no under-18 answer.",
        "Age band: '55-64' and '65+' were not collected. This file's oldest age answer is one "
        "combined \"55 years old and above\" group, shown as the 55 and above band, so 55-64 "
        "and 65+ can't be separated.",
    ]
    for item in items:
        assert len(item) <= 200, item
        assert not _IDENTIFIER.search(item), item
        assert ".xlsx" not in item and "toluna supplies" not in item


def test_question_types_are_plain_english(toluna_summary):
    labels = {c["question_type_label"] for c in toluna_summary["columns"] if c["question_type"]}
    assert labels == {"Rating scale", "Single choice"}


# --- 1/2. CSS: hover contrast and wrapping tables ----------------------------------


def _css() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")


def _tokens(css: str) -> dict[str, str]:
    return dict(re.findall(r"(--[\w-]+):\s*(#[0-9a-fA-F]{6})", css))


def _rule(css: str, selector: str) -> dict[str, str]:
    match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert match, f"no CSS rule for {selector}"
    return dict(
        (k.strip(), v.strip()) for k, v in (decl.split(":", 1) for decl in match.group(1).split(";") if ":" in decl)
    )


def _resolve(value: str, tokens: dict[str, str]) -> str:
    var = re.fullmatch(r"var\((--[\w-]+)\)", value)
    return tokens[var.group(1)] if var else value


def _contrast(fg: str, bg: str) -> float:
    def luminance(hex_colour: str) -> float:
        channels = [int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
        return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]

    hi, lo = sorted((luminance(fg), luminance(bg)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


@pytest.mark.parametrize("state", ["", ":hover", ":active"])
def test_secondary_button_text_is_readable_in_every_state(state):
    """Run summary, Project settings and Load a different file are all
    .btn.btn-secondary; their text must meet WCAG AA (4.5:1) on the fill
    each state actually paints, resolved from the design tokens."""
    css = _css()
    tokens = _tokens(css)
    base = _rule(css, ".btn-secondary")
    rule = {**base, **(_rule(css, f".btn-secondary{state}") if state else {})}
    # .btn:hover/.btn:active paint a dark fill; the secondary rule must override it.
    if state:
        assert "background" in _rule(css, f".btn-secondary{state}")
    fg = _resolve(rule["color"], tokens)
    bg = _resolve(rule["background"], tokens)
    assert _contrast(fg, bg) >= 4.5, (state, fg, bg)


def test_top_bar_buttons_are_secondary_buttons():
    css = _css()
    for button_id in ("run-summary-btn", "project-settings-btn", "summary-reset-btn"):
        assert re.search(rf'class="btn btn-secondary btn-small" id="{button_id}"', css), button_id


def test_run_summary_tables_wrap_instead_of_scrolling():
    css = _css()
    table = _rule(css, ".rs-table")
    assert table.get("table-layout") == "fixed"
    assert _rule(css, ".rs-table th, .rs-table td").get("overflow-wrap") == "anywhere"
    assert "nowrap" not in _rule(css, ".rs-table td.rs-col").get("white-space", "")
    assert '<colgroup><col class="rs-col-column"><col class="rs-col-text"><col class="rs-col-type"></colgroup>' in css


def test_top_bar_shows_the_vendor_name_not_its_key():
    if not TOLUNA_PATH.exists():
        pytest.skip(f"{TOLUNA_PATH.name} not found in project root")
    from surveytool.desktop.app import app

    client = TestClient(app)
    with open(TOLUNA_PATH, "rb") as f:
        response = client.post(
            "/api/upload",
            data={"vendor": "toluna", "survey_id": "t"},
            files={"file": (TOLUNA_PATH.name, f, _XLSX_MIME)},
        )
    assert response.json()["vendor_label"] == "Toluna"
    assert 'getElementById("summary-vendor").textContent = body.vendor_label' in _css()
