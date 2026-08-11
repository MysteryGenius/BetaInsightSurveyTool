# SurveyTool

SurveyTool ingests multi-vendor survey exports (Rakuten, Milieu, Toluna), computes cross-tabs, frequencies, and nested demographic "breaks and filters" with suppression banding, generates Plotly charts, and produces exportable findings sheets. It's available as both a command-line tool and a desktop GUI (a FastAPI backend served inside a native window via `pywebview`).

## Requirements

- Python >= 3.11

## Installation (development)

```bash
# CLI + test suite
pip install -e ".[dev]"

# Desktop GUI (adds FastAPI/uvicorn)
pip install -e ".[desktop]"
```

## Running it

### CLI

Installed as the `surveytool` command (see [pyproject.toml](pyproject.toml)):

```bash
surveytool ingest --vendor rakuten --file survey.xlsx --survey-id my-survey
surveytool reconcile --figures figures.yaml ...
```

Supported vendors: `rakuten`, `milieu`, `toluna`. See [surveytool/cli.py](surveytool/cli.py) for full subcommand options.

### Desktop GUI

```bash
python -m surveytool.desktop.main
```

This starts a local FastAPI/uvicorn server on port 47812 and opens it in a native `pywebview` window (Edge WebView2 on Windows).

## Running tests

```bash
pytest -v
```

## Building a Windows release

A PyInstaller + Inno Setup packaging pipeline already exists in [packaging/](packaging/) and is automated in CI.

### Automated (recommended)

The [.github/workflows/windows-package.yml](.github/workflows/windows-package.yml) GitHub Actions workflow builds the Windows installer automatically:

- Triggers on every push to `main`, or manually via the **Actions** tab → **Windows Package** → **Run workflow**.
- Runs on `windows-latest`, installs `.[packaging]`, builds the app with PyInstaller, bundles the WebView2 bootstrapper, and compiles the installer with Inno Setup.
- Uploads the result as a build artifact named `SurveyTool-Setup-x64-unsigned` (or `SurveyTool-Setup-x64` if a `WINDOWS_CERTIFICATE` secret is configured — code signing is currently a no-op stub, not yet wired up).

Download the artifact from the completed workflow run in the Actions tab.

### Manual (on a Windows machine)

1. Install packaging dependencies:
   ```powershell
   pip install -e ".[packaging]"
   ```
2. Build the app bundle with PyInstaller:
   ```powershell
   cd packaging
   pyinstaller surveytool.spec
   ```
   This produces `dist/SurveyTool/SurveyTool.exe`.
3. Download the WebView2 Runtime bootstrapper into `packaging/`:
   ```powershell
   Invoke-WebRequest -Uri "https://go.microsoft.com/fwlink/p/?LinkId=2124703" -OutFile "MicrosoftEdgeWebview2Setup.exe"
   ```
4. Install [Inno Setup 6](https://jrsoftware.org/isinfo.php), then compile the installer:
   ```cmd
   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" /DMyAppVersion=<version> /DMyOutputBaseName=SurveyTool-Setup-x64 installer.iss
   ```
   Use the version from `[project].version` in [pyproject.toml](pyproject.toml) — bump it there before cutting a release.
5. The installer is written to `packaging/Output/SurveyTool-Setup-x64.exe`. It's a per-user installer (no admin rights required), installs to `%localappdata%\SurveyTool`, and silently installs the WebView2 Runtime if it isn't already present.

## Project layout

- `surveytool/` — main package
  - `core/` — shared domain logic
  - `ingest/` — per-vendor loaders (`rakuten.py`, `milieu.py`, `toluna.py`)
  - `compute/` — cross-tab / breaks-and-filters computation
  - `charts/` — Plotly chart generation and export
  - `findings/` — findings sheet export and reconciliation
  - `desktop/` — FastAPI app + pywebview desktop shell
  - `cli.py` — CLI entry point
- `tests/` — test suite (pytest)
- `packaging/` — PyInstaller spec and Inno Setup installer script for Windows releases
