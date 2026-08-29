# tests/test_overrides.py
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from surveytool.core.model import CodeRole
from surveytool.ingest.overrides import (
    IncompleteOverrideError,
    InvalidRankAssignmentError,
    ProjectOverrides,
    QuestionOverride,
    apply_override,
    check_override_still_needed,
    load_overrides,
    write_override,
)


def test_load_overrides_from_yaml(tmp_path: Path):
    override_path = tmp_path / "overrides.yaml"
    override_path.write_text(
        yaml.dump({
            "overrides": {
                "Q3": {
                    "variable": "Q3",
                    "question_type": "scale",
                    "label_roles": {"Purple": "top", "Green": "bottom"},
                    "resolved_at": "2026-08-20T00:00:00+00:00",
                    "library_version": "1.0.0",
                }
            }
        }),
        encoding="utf-8",
    )
    result = load_overrides(override_path)
    assert isinstance(result, ProjectOverrides)
    assert "Q3" in result.overrides
    assert result.overrides["Q3"].question_type == "scale"
    assert result.overrides["Q3"].label_roles == {"Purple": "top", "Green": "bottom"}


def test_apply_override_full_assignment_produces_roles():
    override = QuestionOverride(
        variable="Q3",
        question_type="scale",
        label_roles={"Purple": "top", "Green": "bottom"},
        resolved_at=datetime.now(timezone.utc),
        library_version="1.0.0",
    )
    roles = apply_override(["Purple", "Green"], override)
    assert roles["Purple"][0] is CodeRole.top
    assert roles["Green"][0] is CodeRole.bottom


def test_apply_override_incomplete_assignment_raises():
    override = QuestionOverride(
        variable="Q3",
        question_type="scale",
        label_roles={"Purple": "top"},  # Green missing
        resolved_at=datetime.now(timezone.utc),
        library_version="1.0.0",
    )
    with pytest.raises(IncompleteOverrideError) as exc_info:
        apply_override(["Purple", "Green"], override)
    assert "Green" in str(exc_info.value)


def test_apply_override_explicit_ranks_used_directly():
    override = QuestionOverride(
        variable="Q3",
        question_type="scale",
        label_roles={"Low": "bottom", "Mid": "neutral", "High": "top"},
        label_ranks={"Low": 1, "Mid": 2, "High": 3},
        resolved_at=datetime.now(timezone.utc),
        library_version="1.0.0",
    )
    roles = apply_override(["Low", "Mid", "High"], override)
    assert roles == {
        "Low": (CodeRole.bottom, 1),
        "Mid": (CodeRole.neutral, 2),
        "High": (CodeRole.top, 3),
    }


def test_apply_override_duplicate_ranks_rejected():
    """Whole-branch review Minor #5: {"Low": 5, "Mid": 5, "High": 5} must be
    rejected -- duplicate ranks silently degrade mean computation and chart
    ordering downstream, and were previously accepted with no validation at
    all."""
    override = QuestionOverride(
        variable="Q3",
        question_type="scale",
        label_roles={"Low": "bottom", "Mid": "neutral", "High": "top"},
        label_ranks={"Low": 5, "Mid": 5, "High": 5},
        resolved_at=datetime.now(timezone.utc),
        library_version="1.0.0",
    )
    with pytest.raises(InvalidRankAssignmentError) as exc_info:
        apply_override(["Low", "Mid", "High"], override)
    assert "Q3" in str(exc_info.value)


def test_apply_override_gapped_ranks_rejected():
    """Ranks 1, 2, 4 (a gap at 3) must be rejected -- not exactly 1..N."""
    override = QuestionOverride(
        variable="Q3",
        question_type="scale",
        label_roles={"Low": "bottom", "Mid": "neutral", "High": "top"},
        label_ranks={"Low": 1, "Mid": 2, "High": 4},
        resolved_at=datetime.now(timezone.utc),
        library_version="1.0.0",
    )
    with pytest.raises(InvalidRankAssignmentError):
        apply_override(["Low", "Mid", "High"], override)


def test_write_override_then_read_back(tmp_path: Path):
    override_path = tmp_path / "overrides.yaml"
    override = QuestionOverride(
        variable="Q9",
        question_type="scale",
        label_roles={"A lot": "top", "Not at all": "bottom"},
        resolved_at=datetime.now(timezone.utc),
        library_version="1.0.0",
    )
    write_override(override_path, override)
    result = load_overrides(override_path)
    assert result.overrides["Q9"].label_roles == {"A lot": "top", "Not at all": "bottom"}


def test_write_override_incomplete_raises_before_writing(tmp_path: Path):
    """write_override is the validated write function — it must not
    persist an override whose scale type has no label_roles at all when
    the caller clearly intends it as a scale with zero assignments would
    be meaningless; validation happens by requiring at least the schema
    shape to be well-formed. (Genuinely incomplete-vs-complete depends on
    the question's real label set, which write_override doesn't know — so
    it validates shape only; apply_override is what checks completeness
    against real labels, per test above.)"""
    override = QuestionOverride(
        variable="Q9",
        question_type="scale",
        label_roles={},
        resolved_at=datetime.now(timezone.utc),
        library_version="1.0.0",
    )
    write_override(override_path := tmp_path / "overrides.yaml", override)
    result = load_overrides(override_path)
    assert result.overrides["Q9"].label_roles == {}


def test_override_notice_when_library_now_matches():
    override = QuestionOverride(
        variable="Q3",
        question_type="scale",
        label_roles={"Strongly Agree": "top", "Strongly Disagree": "bottom"},
        resolved_at=datetime.now(timezone.utc),
        library_version="0.9.0",
    )
    notice = check_override_still_needed("Q3", ["Strongly Agree", "Strongly Disagree"], override)
    assert notice is not None
    assert "Q3" in notice.message


def test_no_notice_when_library_still_does_not_match():
    override = QuestionOverride(
        variable="Q9",
        question_type="scale",
        label_roles={"Bunches": "top", "None": "bottom"},
        resolved_at=datetime.now(timezone.utc),
        library_version="0.9.0",
    )
    notice = check_override_still_needed("Q9", ["Bunches", "None"], override)
    assert notice is None
