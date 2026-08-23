"""
Task 2 (state-audit remediation): override storage moved from the OS temp
directory to a persistent per-project location, with a one-time forward
migration from the old temp location.

Covers:
- an override written, "reboot" simulated (old temp dir cleared), still
  applies on the next load, purely from the new persistent path;
- the migration reads (copies) rather than moves — the old file survives;
- a migration produces exactly one notice, surfaced once;
- path-traversal-shaped survey_ids are still rejected against the new base
  directory, both via the allowlist regex and via the re-derived containment
  check independently.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from surveytool.charts.errors import ErrorCode, SurveyToolError
from surveytool.desktop import app as appmod
from surveytool.ingest.overrides import QuestionOverride, load_overrides, write_override


@pytest.fixture(autouse=True)
def _isolated_override_dirs(tmp_path: Path, monkeypatch):
    """Redirect both the new persistent dir and the legacy temp dir into
    tmp_path so this test can't touch a real user's home directory or a
    real system temp directory, and clear the module-level migration-notice
    cache before and after so tests don't leak state into each other."""
    monkeypatch.setattr(appmod, "_OVERRIDES_DIR", tmp_path / "new-overrides")
    monkeypatch.setattr(appmod, "_OLD_OVERRIDES_DIR", tmp_path / "old-overrides")
    appmod._MIGRATION_NOTICES.clear()
    yield
    appmod._MIGRATION_NOTICES.clear()


def _make_override(variable: str = "Q1") -> QuestionOverride:
    return QuestionOverride(
        variable=variable,
        question_type="binary",
        label_roles={},
        resolved_at=datetime.now(timezone.utc),
        library_version="1.0.0",
    )


def _write_legacy_override(survey_id: str, variable: str = "Q1") -> Path:
    old_path = appmod._OLD_OVERRIDES_DIR / f"{survey_id}.yaml"
    old_path.parent.mkdir(parents=True, exist_ok=True)
    write_override(old_path, _make_override(variable=variable))
    return old_path


def test_override_persists_across_simulated_reboot_with_temp_cleared():
    survey_id = "reboot-test"

    # Write directly to the legacy temp location, as if from a previous
    # process before this migration existed.
    old_path = _write_legacy_override(survey_id)
    assert old_path.exists()

    # First access after "restart": _project_overrides_path triggers the
    # migration and returns the new persistent path.
    new_path = appmod._project_overrides_path(survey_id)
    assert new_path == (appmod._OVERRIDES_DIR / f"{survey_id}.yaml").resolve()
    assert new_path.exists()
    loaded = load_overrides(new_path).overrides
    assert loaded["Q1"].question_type == "binary"

    # Simulate the temp directory being wiped by the OS on reboot — the
    # override must still apply purely from the new persistent path.
    import shutil
    shutil.rmtree(appmod._OLD_OVERRIDES_DIR, ignore_errors=True)
    assert not appmod._OLD_OVERRIDES_DIR.exists()

    reloaded_path = appmod._project_overrides_path(survey_id)
    reloaded = load_overrides(reloaded_path).overrides
    assert reloaded["Q1"].question_type == "binary"


def test_migration_copies_and_does_not_delete_old_file():
    survey_id = "migration-preserves-old"
    old_path = _write_legacy_override(survey_id)

    appmod._project_overrides_path(survey_id)

    assert old_path.exists(), "migration must be a copy, not a move"


def test_migration_records_a_notice_exactly_once():
    survey_id = "migration-notice-once"
    _write_legacy_override(survey_id)

    appmod._project_overrides_path(survey_id)
    notice = appmod._last_migration_notice(survey_id)
    assert notice is not None
    assert survey_id in notice

    # Popped once; a second read (e.g. a subsequent run summary build)
    # should not see it again, and a second path lookup should not
    # re-migrate or re-queue a notice since the new file now exists.
    assert appmod._last_migration_notice(survey_id) is None
    appmod._project_overrides_path(survey_id)
    assert appmod._last_migration_notice(survey_id) is None


def test_no_migration_when_only_new_file_exists():
    survey_id = "no-legacy-file"
    new_path = appmod._project_overrides_path(survey_id)
    write_override(new_path, _make_override())

    appmod._MIGRATION_NOTICES.clear()
    appmod._project_overrides_path(survey_id)
    assert appmod._last_migration_notice(survey_id) is None


def test_new_file_wins_when_both_old_and_new_already_exist():
    """If the new persistent file already exists, migration must not
    overwrite it with stale data from the old temp file."""
    survey_id = "both-exist"
    _write_legacy_override(survey_id, variable="OLD_Q")

    # First access migrates OLD_Q forward (old exists, new does not yet).
    new_path = appmod._project_overrides_path(survey_id)
    assert load_overrides(new_path).overrides.keys() == {"OLD_Q"}

    # Now the new file's content is replaced outright (simulating it having
    # diverged from the legacy file, e.g. a later resolver save that
    # doesn't exist in the old file at all).
    new_path.write_text("", encoding="utf-8")
    write_override(new_path, _make_override(variable="NEW_Q"))
    appmod._MIGRATION_NOTICES.clear()

    # A later access must not re-migrate and clobber NEW_Q with the stale
    # OLD_Q content still sitting in the legacy file.
    resolved = appmod._project_overrides_path(survey_id)
    loaded = load_overrides(resolved).overrides
    assert "NEW_Q" in loaded
    assert "OLD_Q" not in loaded
    assert appmod._last_migration_notice(survey_id) is None


@pytest.mark.parametrize(
    "bad_survey_id",
    ["../../../etc/passwd", "..", "a/b", "a\\b", "", "a" * 65, "with space"],
)
def test_path_traversal_survey_ids_rejected_against_new_base(bad_survey_id):
    with pytest.raises(SurveyToolError) as excinfo:
        appmod._project_overrides_path(bad_survey_id)
    assert excinfo.value.code == ErrorCode.CONFIG_INVALID


def test_resolve_under_containment_check_independently_rejects_traversal(tmp_path):
    """Exercises _resolve_under's containment re-derivation directly,
    independent of the regex in _validate_survey_id, against whichever
    base_dir is passed — confirming the check is re-derived against the new
    base directory rather than assuming the old one."""
    base = tmp_path / "some-base"
    with pytest.raises(SurveyToolError):
        appmod._resolve_under(base, "../escape")
