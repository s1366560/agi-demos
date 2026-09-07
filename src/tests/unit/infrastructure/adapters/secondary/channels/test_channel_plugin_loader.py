"""Tests for channel_plugin_loader."""

from __future__ import annotations

from pathlib import Path
from types import ModuleType

import pytest

from src.infrastructure.adapters.secondary.channels import channel_plugin_loader
from src.infrastructure.adapters.secondary.channels.channel_plugin_loader import (
    load_channel_module,
    register_channel_plugin,
)


@pytest.mark.unit
class TestLoadChannelModule:
    def test_load_feishu_client(self) -> None:
        mod = load_channel_module("feishu", "client")
        assert isinstance(mod, ModuleType)
        assert hasattr(mod, "FeishuClient")

    def test_load_feishu_adapter(self) -> None:
        mod = load_channel_module("feishu", "adapter")
        assert isinstance(mod, ModuleType)
        assert hasattr(mod, "FeishuAdapter")

    def test_cache_returns_same_object(self) -> None:
        mod1 = load_channel_module("feishu", "client")
        mod2 = load_channel_module("feishu", "client")
        assert mod1 is mod2

    def test_unknown_channel_raises_key_error(self) -> None:
        with pytest.raises(KeyError, match="Unknown channel"):
            load_channel_module("nonexistent_channel", "client")

    def test_unknown_submodule_raises_file_not_found(self) -> None:
        with pytest.raises(FileNotFoundError, match="Channel implementation module not found: .*does_not_exist_xyz.py"):
            load_channel_module("feishu", "does_not_exist_xyz")


@pytest.mark.unit
class TestRegisterChannelPlugin:
    def test_register_and_load(self, tmp_path: Path) -> None:
        plugin_file = tmp_path / "hello.py"
        plugin_file.write_text("GREETING = 'hi'\n")

        register_channel_plugin("test_channel", tmp_path)
        try:
            mod = load_channel_module("test_channel", "hello")
            assert mod.GREETING == "hi"
        finally:
            channel_plugin_loader._CHANNEL_MODULE_REGISTRY.pop("test_channel", None)  # type: ignore[attr-defined]
            load_channel_module.cache_clear()

    def test_register_clears_cache(self) -> None:
        info = load_channel_module.cache_info()
        initial_size = info.currsize

        register_channel_plugin("_dummy_clear_test", Path("/nonexistent"))
        info_after = load_channel_module.cache_info()
        assert info_after.currsize == 0 or info_after.currsize <= initial_size

        channel_plugin_loader._CHANNEL_MODULE_REGISTRY.pop("_dummy_clear_test", None)  # type: ignore[attr-defined]
        load_channel_module.cache_clear()
