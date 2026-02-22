"""Unit tests for plugin discovery helpers."""

from types import SimpleNamespace

import pytest

from src.infrastructure.agent.plugins.discovery import discover_plugins
from src.infrastructure.agent.plugins.state_store import PluginStateStore


@pytest.mark.unit
def test_discover_plugins_has_no_builtin_plugins() -> None:
    """Core discovery should not auto-load built-in channel plugins."""
    discovered, diagnostics = discover_plugins(include_entrypoints=False)

    assert discovered == []
    assert all(diagnostic.code != "plugin_discovery_failed" for diagnostic in diagnostics)


@pytest.mark.unit
def test_discover_plugins_respects_disabled_state(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Disabled plugins should be skipped from entrypoint discovery."""

    class _Plugin:
        name = "feishu-channel-plugin"

        def setup(self, _api):
            return None

    class _EntryPoint:
        name = "feishu"
        dist = SimpleNamespace(name="memstack-plugin-feishu", version="0.1.0")

        @staticmethod
        def load():
            return _Plugin

    store = PluginStateStore(base_path=tmp_path)
    store.set_plugin_enabled("feishu-channel-plugin", False)
    monkeypatch.setattr(
        "src.infrastructure.agent.plugins.discovery._iter_entry_points",
        lambda _group: [_EntryPoint()],
    )

    discovered, diagnostics = discover_plugins(
        state_store=store,
        include_builtins=False,
        include_entrypoints=True,
    )

    assert discovered == []
    assert any(diagnostic.code == "plugin_disabled" for diagnostic in diagnostics)


@pytest.mark.unit
def test_discover_plugins_loads_entrypoint_plugin(monkeypatch: pytest.MonkeyPatch) -> None:
    """Entry point plugin should be discovered and normalized."""

    class _Plugin:
        name = "demo-plugin"

        def setup(self, _api):
            return None

    class _EntryPoint:
        name = "demo-plugin"
        dist = SimpleNamespace(name="demo-package", version="1.2.3")

        @staticmethod
        def load():
            return _Plugin

    monkeypatch.setattr(
        "src.infrastructure.agent.plugins.discovery._iter_entry_points",
        lambda _group: [_EntryPoint()],
    )

    discovered, diagnostics = discover_plugins(
        include_builtins=False,
        include_entrypoints=True,
    )

    assert [plugin.name for plugin in discovered] == ["demo-plugin"]
    assert discovered[0].package == "demo-package"
    assert discovered[0].version == "1.2.3"
    assert diagnostics == []


@pytest.mark.unit
def test_discover_plugins_loads_local_plugin_from_memstack_dir(tmp_path) -> None:
    """Discovery should load local plugin from .memstack/plugins/<name>/plugin.py."""
    plugin_file = tmp_path / ".memstack" / "plugins" / "feishu" / "plugin.py"
    plugin_file.parent.mkdir(parents=True, exist_ok=True)
    plugin_file.write_text(
        "\n".join(
            [
                "class FeishuPlugin:",
                "    name = 'feishu-channel-plugin'",
                "",
                "    def setup(self, _api):",
                "        return None",
            ]
        ),
        encoding="utf-8",
    )
    store = PluginStateStore(base_path=tmp_path)

    discovered, diagnostics = discover_plugins(
        state_store=store,
        include_builtins=False,
        include_entrypoints=False,
    )

    assert [plugin.name for plugin in discovered] == ["feishu-channel-plugin"]
    assert discovered[0].source == "local"
    assert diagnostics == []


@pytest.mark.unit
def test_discover_plugins_respects_disabled_local_plugin_state(tmp_path) -> None:
    """Disabled local plugin should be skipped just like entrypoint plugins."""
    plugin_file = tmp_path / ".memstack" / "plugins" / "demo" / "plugin.py"
    plugin_file.parent.mkdir(parents=True, exist_ok=True)
    plugin_file.write_text(
        "\n".join(
            [
                "class DemoPlugin:",
                "    name = 'demo-local-plugin'",
                "",
                "    def setup(self, _api):",
                "        return None",
            ]
        ),
        encoding="utf-8",
    )
    store = PluginStateStore(base_path=tmp_path)
    store.set_plugin_enabled("demo-local-plugin", False)

    discovered, diagnostics = discover_plugins(
        state_store=store,
        include_builtins=False,
        include_entrypoints=False,
    )

    assert discovered == []
    assert any(diagnostic.code == "plugin_disabled" for diagnostic in diagnostics)


@pytest.mark.unit
def test_discover_plugins_prefers_local_plugin_over_entrypoint_on_conflict(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Local plugin should take precedence when local and entrypoint names conflict."""
    plugin_file = tmp_path / ".memstack" / "plugins" / "feishu" / "plugin.py"
    plugin_file.parent.mkdir(parents=True, exist_ok=True)
    plugin_file.write_text(
        "\n".join(
            [
                "class LocalPlugin:",
                "    name = 'feishu-channel-plugin'",
                "",
                "    def setup(self, _api):",
                "        return None",
            ]
        ),
        encoding="utf-8",
    )

    class _EntryPlugin:
        name = "feishu-channel-plugin"

        def setup(self, _api):
            return None

    class _EntryPoint:
        name = "feishu"
        dist = SimpleNamespace(name="memstack-plugin-feishu", version="0.1.0")

        @staticmethod
        def load():
            return _EntryPlugin

    monkeypatch.setattr(
        "src.infrastructure.agent.plugins.discovery._iter_entry_points",
        lambda _group: [_EntryPoint()],
    )

    discovered, diagnostics = discover_plugins(
        state_store=PluginStateStore(base_path=tmp_path),
        include_builtins=False,
        include_entrypoints=True,
        include_local_paths=True,
    )

    assert len(discovered) == 1
    assert discovered[0].name == "feishu-channel-plugin"
    assert discovered[0].source == "local"
    assert any(diagnostic.code == "plugin_name_conflict" for diagnostic in diagnostics)
