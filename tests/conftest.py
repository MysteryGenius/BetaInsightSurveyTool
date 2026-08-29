"""Shared test fixtures.

Autouse isolation for surveytool.desktop.app's persistent override storage
(`_OVERRIDES_DIR`, `Path.home()/.surveytool/overrides`) and its legacy
temp-dir counterpart (`_OLD_OVERRIDES_DIR`). Any test that exercises the
FastAPI app's upload/resolve/settings/breaks endpoints can trigger a write
under `_project_overrides_path`, which since Task 2 resolves under the
user's real home directory rather than the OS temp dir. Without this
fixture, running the suite on a developer or CI machine accumulates real,
permanent files under `~/.surveytool/overrides/` with no cleanup (see
final-review Finding 1) — before Task 2 these went to the OS temp dir and
were swept automatically; the persistent move needs a matching test seam.

This fixture is intentionally broad (autouse, session-independent,
function-scoped) so it applies uniformly to every test module, including
ones added later, without each one having to remember to opt in.
`tests/test_override_storage_migration.py` already had its own
equivalent fixture for its own dedicated tests; this one generalizes that
same pattern to the rest of the suite.

Round C3 adds `_DISPLAY_ORDER_DIR` (`Path.home()/.surveytool/display_order`)
to this same redirect for the same reason -- it is a brand-new persistent
per-survey_id store, written by the new display-order endpoints.
"""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolated_override_storage(tmp_path: Path, monkeypatch):
    """Redirect the desktop app's override storage directories into
    tmp_path for the duration of each test, so nothing in the suite ever
    reads or writes the real ~/.surveytool/overrides/ or
    ~/.surveytool/display_order/."""
    from surveytool.desktop import app as appmod

    monkeypatch.setattr(appmod, "_OVERRIDES_DIR", tmp_path / "overrides")
    monkeypatch.setattr(appmod, "_OLD_OVERRIDES_DIR", tmp_path / "old-overrides")
    monkeypatch.setattr(appmod, "_DISPLAY_ORDER_DIR", tmp_path / "display_order")
    appmod._MIGRATION_NOTICES.clear()
    yield
    appmod._MIGRATION_NOTICES.clear()
