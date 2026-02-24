"""Unit tests for plugin discovery helpers."""

from types import SimpleNamespace
from typing import ClassVar

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
def test_discover_plugins_loads_entrypoint_manifest_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Entry point plugin manifest metadata should be normalized into discovered plugin fields."""

    class _Plugin:
        name = "demo-plugin"
        plugin_manifest: ClassVar[dict] = {
            "id": "demo-plugin",
            "kind": "channel",
            "version": "9.9.9",
            "channels": ["feishu"],
            "providers": ["demo-provider"],
            "skills": ["demo-skill"],
        }

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
    plugin = discovered[0]
    assert plugin.package == "demo-package"
    assert plugin.version == "9.9.9"
    assert plugin.kind == "channel"
    assert plugin.manifest_id == "demo-plugin"
    assert plugin.channels == ("feishu",)
    assert plugin.providers == ("demo-provider",)
    assert plugin.skills == ("demo-skill",)
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
def test_discover_plugins_loads_local_manifest_metadata(tmp_path) -> None:
    """Discovery should include optional local plugin manifest metadata."""
    plugin_dir = tmp_path / ".memstack" / "plugins" / "demo"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin.py").write_text(
        "\n".join(
            [
                "class DemoPlugin:",
                "    name = 'demo-plugin'",
                "",
                "    def setup(self, _api):",
                "        return None",
            ]
        ),
        encoding="utf-8",
    )
    (plugin_dir / "memstack.plugin.json").write_text(
        (
            "{"
            '"id":"demo-plugin",'
            '"kind":"channel",'
            '"version":"0.2.0",'
            '"channels":["feishu"],'
            '"providers":["demo-provider"],'
            '"skills":["demo-skill"]'
            "}"
        ),
        encoding="utf-8",
    )

    discovered, diagnostics = discover_plugins(
        state_store=PluginStateStore(base_path=tmp_path),
        include_builtins=False,
        include_entrypoints=False,
    )

    assert len(discovered) == 1
    plugin = discovered[0]
    assert plugin.kind == "channel"
    assert plugin.version == "0.2.0"
    assert plugin.manifest_id == "demo-plugin"
    assert plugin.manifest_path is not None
    assert plugin.channels == ("feishu",)
    assert plugin.providers == ("demo-provider",)
    assert plugin.skills == ("demo-skill",)
    assert diagnostics == []


@pytest.mark.unit
def test_discover_plugins_warns_manifest_id_mismatch(tmp_path) -> None:
    """Manifest id mismatch should not block plugin discovery."""
    plugin_dir = tmp_path / ".memstack" / "plugins" / "demo"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin.py").write_text(
        "\n".join(
            [
                "class DemoPlugin:",
                "    name = 'demo-plugin'",
                "",
                "    def setup(self, _api):",
                "        return None",
            ]
        ),
        encoding="utf-8",
    )
    (plugin_dir / "memstack.plugin.json").write_text('{"id":"other-plugin"}', encoding="utf-8")

    discovered, diagnostics = discover_plugins(
        state_store=PluginStateStore(base_path=tmp_path),
        include_builtins=False,
        include_entrypoints=False,
    )

    assert [plugin.name for plugin in discovered] == ["demo-plugin"]
    assert any(diagnostic.code == "plugin_manifest_id_mismatch" for diagnostic in diagnostics)


@pytest.mark.unit
def test_discover_plugins_strict_mode_skips_manifest_id_mismatch(tmp_path) -> None:
    """Strict manifest mode should skip plugin when manifest id mismatches runtime name."""
    plugin_dir = tmp_path / ".memstack" / "plugins" / "demo"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin.py").write_text(
        "\n".join(
            [
                "class DemoPlugin:",
                "    name = 'demo-plugin'",
                "",
                "    def setup(self, _api):",
                "        return None",
            ]
        ),
        encoding="utf-8",
    )
    (plugin_dir / "memstack.plugin.json").write_text('{"id":"other-plugin"}', encoding="utf-8")

    discovered, diagnostics = discover_plugins(
        state_store=PluginStateStore(base_path=tmp_path),
        include_builtins=False,
        include_entrypoints=False,
        strict_local_manifest=True,
    )

    assert discovered == []
    assert any(diagnostic.code == "plugin_manifest_id_mismatch" for diagnostic in diagnostics)
    assert any(diagnostic.code == "plugin_manifest_strict_skip" for diagnostic in diagnostics)


@pytest.mark.unit
def test_discover_plugins_reports_invalid_manifest(tmp_path) -> None:
    """Invalid manifest should emit diagnostics but keep plugin discoverable."""
    plugin_dir = tmp_path / ".memstack" / "plugins" / "demo"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin.py").write_text(
        "\n".join(
            [
                "class DemoPlugin:",
                "    name = 'demo-plugin'",
                "",
                "    def setup(self, _api):",
                "        return None",
            ]
        ),
        encoding="utf-8",
    )
    (plugin_dir / "memstack.plugin.json").write_text("{invalid", encoding="utf-8")

    discovered, diagnostics = discover_plugins(
        state_store=PluginStateStore(base_path=tmp_path),
        include_builtins=False,
        include_entrypoints=False,
    )

    assert [plugin.name for plugin in discovered] == ["demo-plugin"]
    assert any(diagnostic.code == "plugin_manifest_invalid" for diagnostic in diagnostics)


@pytest.mark.unit
def test_discover_plugins_strict_mode_skips_invalid_manifest(tmp_path) -> None:
    """Strict manifest mode should skip plugin when manifest is invalid."""
    plugin_dir = tmp_path / ".memstack" / "plugins" / "demo"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin.py").write_text(
        "\n".join(
            [
                "class DemoPlugin:",
                "    name = 'demo-plugin'",
                "",
                "    def setup(self, _api):",
                "        return None",
            ]
        ),
        encoding="utf-8",
    )
    (plugin_dir / "memstack.plugin.json").write_text("{invalid", encoding="utf-8")

    discovered, diagnostics = discover_plugins(
        state_store=PluginStateStore(base_path=tmp_path),
        include_builtins=False,
        include_entrypoints=False,
        strict_local_manifest=True,
    )

    assert discovered == []
    assert any(diagnostic.code == "plugin_manifest_invalid" for diagnostic in diagnostics)
    assert any(diagnostic.code == "plugin_manifest_strict_skip" for diagnostic in diagnostics)


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
