# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

SurveyTool ingests survey exports from four vendors (Rakuten, Milieu, Toluna, PureSpectrum) and normalises them into one canonical model. From that model it computes findings, cross-tabs and nested demographic "breaks and filters" with suppression, then renders Plotly charts. It ships as a CLI and as a Windows desktop app: a FastAPI backend shown in a `pywebview` window. End users are non-technical analysts.

## Commands

```bash
# Dev install. The tests need the desktop extra too: tests/conftest.py imports
# surveytool.desktop.app (FastAPI) for every test.
pip install -e ".[dev,desktop]"        # a .venv/ already exists at the repo root

pytest -q                              # full suite (~3 min), what CI runs on 3.11 and 3.12
pytest tests/test_breaks_invariants.py -q
pytest tests/test_purespectrum.py::test_purespectrum_ascending_scale_computes_scale_direction
pytest --ignore=tests/test_charts.py -q   # skip the chart-rendering tests

# CLI. FILE is positional. The CLI accepts only rakuten|milieu|toluna;
# PureSpectrum is desktop-only.
surveytool ingest   rakuten_survey_support_measures_data.xlsx --survey-id sm --vendor rakuten
surveytool findings FILE --survey-id ID --vendor V [--out f.csv] [--reconcile figures.yaml]
surveytool charts   FILE --survey-id ID --vendor V --out-dir out/

# Desktop backend on its own (no native window; open it in a browser)
python -m uvicorn surveytool.desktop.app:app --host 127.0.0.1 --port 8731
# Full desktop shell (pywebview, port 47812)
python -m surveytool.desktop.main

node --check surveytool/desktop/static/breaks.js   # the only JS "lint"; there is no JS build
```

There is no linter or formatter configured. Windows packaging (PyInstaller and Inno Setup in `packaging/`) runs in `.github/workflows/windows-package.yml` on every push to `main`; the README has the manual steps.

## Test data

The real vendor files at the repo root (`*_survey_*_data.xlsx` / `.csv`) are test fixtures. Tests open them by path and `pytest.skip` if one is missing, so don't move or rename them. Tests in `tests/fixtures/` are synthetic Python fixtures. `conftest.py` has an autouse fixture that redirects the app's persistent `~/.surveytool/*` stores into `tmp_path`. Any new persistent store in `desktop/app.py` must be added there too.

## Architecture

### Pipeline

`ingest/<vendor>.py: load()` → `core.model.Survey` (`Question` + `Response`) → `findings.sheet.build_findings_sheet` → charts. The desktop's `_run_pipeline` in `desktop/app.py` is the canonical orchestration. It loads project settings, runs the fingerprint check, applies overrides, loads the demographic registry, excludes straightliners, then builds findings and a respondent frame.

- **Vendor differences are declarative.** `ingest/vendor_profile.py` defines a `VendorProfile` per vendor (sheets, reserved and quality columns, multiselect pattern, fingerprint signature). `ingest/fingerprint.py` uses it to reject a file uploaded under the wrong vendor. `ingest/datamap_reader.py` parses Datamap-style codebooks.
- **Scale recognition is library-driven, never inferred from code numbers.** `core/scales.yaml` (families → variants → ordered points with label patterns) and `core/scale_library.py` assign `CodeRole` (top, neutral, bottom, nonsubstantive) from label text. A `scale` `Question` fails validation without both a top and a bottom role. Diverging-chart polarity is looked up per `<family>.<variant>` in `core/scale_polarity.yaml`.
- **Unmatched questions are collected, never guessed.** An adapter raises a single `UnresolvedQuestionsError` listing every question it couldn't classify. The desktop then keeps a `PendingSession`, the UI's resolver panel posts answers to `/api/session/{id}/resolve`, and `ingest/overrides.py` persists them to `~/.surveytool/overrides/` before the pipeline re-runs.

### Two chart and compute paths

They share one figure layer but are otherwise separate:

1. **Charts tab (legacy):** findings → `charts/chart_data.py` (`dist`, `xbreak`, `means`) → `plotly_renderer.build_legacy_figure`. The single-break cross-tab is in `compute/cross_tab.py`.
2. **Cross-tab tab (breaks and filters):**
   - `core/demographic_registry.py` maps vendor columns onto canonical dimensions (`core/demographics/canonical.yaml` + `vendor_<v>.yaml`).
   - `core/projection.py` gives a cheap shape and count check, re-run on every pill change. It must never call per-question compute.
   - `compute/breaks_compute.py` handles N-dimensional breaks. Each cell is a slice passed to the unmodified `compute.frequency.compute_question_stats`.
   - `core/suppression.py` handles banding.
   - `core/chart_validity.py` decides which of the five chart types are permitted. The server decides this, never the frontend.
   - `core/breaks_payload.py` joins the results, and `plotly_renderer.build_figure` draws them.

Both paths render through `charts/plotly_renderer.py`, so the on-screen figure and the PNG export (kaleido `rasterize`) come from the same code. `static/charts.js` draws the server's figure JSON and does no chart logic of its own. Per-question chart style (`charts/styles.py`), response colours and display order persist per survey under `~/.surveytool/{chart_style,display_order}/`.

### Invariants the tests enforce

- **INV-1 (`tests/test_breaks_invariants.py`):** a depth-1 break must reproduce `compute_cross_tab` exactly. Don't reimplement netting or percentaging in breaks code; slice and call the shared function.
- **Conformance (`test_conformance.py`, `test_breaks_conformance.py`):** these guard against silent degradation, such as a scale quietly becoming `single_choice` or `scale_family` becoming `None`.

### Errors

Every user-facing failure is a `SurveyToolError` (defined in `charts/errors.py`, despite the location). It carries a stable `ErrorCode`, a plain-English `message`, and optional `detail` and `next_action` fields. Every code needs an HTTP status in `_STATUS_BY_CODE`. The frontend switches only on `code`, never on message text. Keep messages in plain language and include a remediation step.

### Desktop app

`desktop/app.py` holds all routes and keeps sessions in memory (`_SESSIONS`, `_PENDING_SESSIONS`). Uploads are staged in the OS temp dir. The frontend is plain JS with no bundler: `static/index.html` (a large inline script), `breaks.js` (Cross-tab), `charts.js`, `chart_legend.js` (shared drag-reorder and colour legend), and a vendored `static/vendor/plotly.min.js` so the app makes no network calls at runtime.

## Docs and conventions

- `beta-insight-core-build-plan.md` and `beta-insight-ui-prompts.md` are the current round's plans. Many docstrings cite "build plan section N" from an earlier breaks-core plan that isn't in the repo.
- Feature designs and plans live in `docs/superpowers/specs/` and `docs/superpowers/plans/` (named `YYYY-MM-DD-<topic>.md`).
- Commits use `feat:`, `fix:`, `test:`, `chore:` or `style:` prefixes, often tagged with review-item IDs such as `(C2, I1)`.
