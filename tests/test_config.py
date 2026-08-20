from __future__ import annotations

from surveytool.core.config import ToolConfig


def test_nonsubstantive_defaults():
    config = ToolConfig()
    assert config.nonsubstantive_labels == ["prefer not to say", "don't know", "not applicable"]
    assert config.exclude_nonsubstantive_from_base is False


def test_exclude_nonsubstantive_from_base_can_be_set():
    config = ToolConfig(exclude_nonsubstantive_from_base=True)
    assert config.exclude_nonsubstantive_from_base is True
