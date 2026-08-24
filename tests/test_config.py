from __future__ import annotations

from surveytool.core.config import ToolConfig
from surveytool.core.nonsubstantive import DEFAULT_NONSUBSTANTIVE_LABELS


def test_nonsubstantive_defaults():
    config = ToolConfig()
    # ToolConfig's default must be exactly the same default patterns that
    # is_nonsubstantive_label(label, labels=None) falls back to -- not a
    # second hardcoded literal that could silently diverge (see Task 7
    # remediation: this was a Critical finding).
    assert config.nonsubstantive_labels == list(DEFAULT_NONSUBSTANTIVE_LABELS)
    assert config.exclude_nonsubstantive_from_base is False


def test_exclude_nonsubstantive_from_base_can_be_set():
    config = ToolConfig(exclude_nonsubstantive_from_base=True)
    assert config.exclude_nonsubstantive_from_base is True
