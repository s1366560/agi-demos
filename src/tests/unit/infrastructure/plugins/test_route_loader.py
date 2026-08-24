"""Unit tests for the inventory-driven builtin route loader."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from fastapi import APIRouter

from src.infrastructure.plugins import route_loader as route_loader_module
from src.infrastructure.plugins.route_inventory import INVENTORY_PATH
from src.infrastructure.plugins.route_loader import (
    BuiltinRouteRowOverride,
    RouteLoadError,
    install_builtin_routes,
    load_builtin_route_rows,
)
from src.infrastructure.plugins.v2.builtin_route_contracts import (
    BUILTIN_ROUTE_CONTRACT_CATALOG_PATH_V2,
)
from src.infrastructure.plugins.v2.builtin_system_http_routes import system_route_definitions_v2
from src.infrastructure.plugins.v2.builtin_tunnel_http_routes import tunnel_route_definitions_v2

_REPO_ROOT = Path(__file__).resolve().parents[5]


class _RecordingApp:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def include_router(self, router: object, **kwargs: Any) -> None:
        self.calls.append({"router": router, "kwargs": kwargs})


def _install_with_stub_helpers(app: _RecordingApp, **extra: Any) -> tuple[str, ...]:
    helper_calls: list[str] = []

    def make_helper(name: str):
        def helper(app: object, *args: object) -> None:
            helper_calls.append(name)

        return helper

    overrides = {
        "workspace-core-static": make_helper("workspace-core-static"),
        "workspace-core": make_helper("workspace-core"),
        "workspace-core-runtime": make_helper("workspace-core-runtime"),
        "task-session": make_helper("task-session"),
    }
    mounted = install_builtin_routes(
        app,
        workspace_core_settings=object(),
        inventory_path=_REPO_ROOT / INVENTORY_PATH,
        helper_overrides=overrides,
        **extra,
    )
    return mounted, helper_calls  # type: ignore[return-value]


@pytest.mark.unit
def test_loader_replays_baseline_order_and_prefixes() -> None:
    app = _RecordingApp()
    mounted, helper_calls = _install_with_stub_helpers(app)
    rows = load_builtin_route_rows(_REPO_ROOT / INVENTORY_PATH)
    expected_includes = [row for row in rows if row["kind"] == "include_router"]

    assert len(app.calls) == len(expected_includes)
    for call, row in zip(app.calls, expected_includes, strict=True):
        expected_kwargs = {"prefix": row["prefix"]} if row.get("prefix") else {}
        assert call["kwargs"] == expected_kwargs, row["row_id"]

    # Helpers fire at their baseline positions: static after auth, the
    # workspace group between tasks and cron.
    include_ids = [row["row_id"] for row in expected_includes]
    assert helper_calls[0] == "workspace-core-static"
    assert helper_calls[1:] == ["workspace-core", "workspace-core-runtime", "task-session"]
    assert include_ids[0] == "auth"
    assert "support" in mounted and "support-2" in mounted


@pytest.mark.unit
def test_loader_resolves_real_router_objects() -> None:
    app = _RecordingApp()
    _install_with_stub_helpers(app)

    assert all(isinstance(call["router"], APIRouter) for call in app.calls)


@pytest.mark.unit
def test_lifespan_owned_helper_is_not_mounted() -> None:
    app = _RecordingApp()
    mounted, _ = _install_with_stub_helpers(app)

    assert "http-route-capabilities" not in mounted


@pytest.mark.unit
def test_settings_helper_requires_settings() -> None:
    app = _RecordingApp()

    def noop_helper(app: object, *args: object) -> None:
        return None

    overrides = {
        "workspace-core-static": noop_helper,
        "workspace-core": noop_helper,
        "task-session": noop_helper,
    }
    with pytest.raises(RouteLoadError, match="workspace_core_settings"):
        install_builtin_routes(
            app,
            inventory_path=_REPO_ROOT / INVENTORY_PATH,
            helper_overrides=overrides,
        )


@pytest.mark.unit
def test_missing_inventory_fails_loud(tmp_path: Path) -> None:
    with pytest.raises(RouteLoadError, match="cannot read route inventory"):
        install_builtin_routes(_RecordingApp(), inventory_path=tmp_path / "absent.json")


@pytest.mark.unit
def test_malformed_inventory_fails_loud(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"unexpected": []}), encoding="utf-8")

    with pytest.raises(RouteLoadError, match="entries"):
        install_builtin_routes(_RecordingApp(), inventory_path=bad)


@pytest.mark.unit
class TestRouteRowPatches:
    """Per-row profile patching of the builtin route surface (I1 B6)."""

    def _install(self, app: _RecordingApp, **kwargs: Any) -> tuple[str, ...]:
        mounted, _ = _install_with_stub_helpers(app, **kwargs)
        return mounted

    def test_disabled_row_is_skipped(self) -> None:
        from src.infrastructure.plugins.route_loader import RouteRowPatch

        app = _RecordingApp()
        mounted = self._install(
            app, row_patches={"tenants": RouteRowPatch(row_id="tenants", enabled=False)}
        )
        assert "tenants" not in mounted
        assert "auth" in mounted

    def test_unknown_patch_target_rejected(self) -> None:
        from src.infrastructure.plugins.route_loader import RouteRowPatch

        app = _RecordingApp()
        with pytest.raises(RouteLoadError, match="unknown baseline rows"):
            self._install(
                app,
                row_patches={"no-such-row": RouteRowPatch(row_id="no-such-row", enabled=False)},
            )

    def test_prefix_replacement(self) -> None:
        from src.infrastructure.plugins.route_loader import RouteRowPatch

        app = _RecordingApp()
        self._install(
            app,
            row_patches={"auth": RouteRowPatch(row_id="auth", prefix="/api/v2")},
        )
        auth_calls = [c for c in app.calls if c["kwargs"].get("prefix") == "/api/v2"]
        assert len(auth_calls) == 1

    def test_module_replacement_resolves_substitute_router(self) -> None:
        from src.infrastructure.plugins.route_loader import RouteRowPatch

        app = _RecordingApp()
        mounted = self._install(
            app,
            row_patches={
                "tenants": RouteRowPatch(
                    row_id="tenants",
                    module="src.infrastructure.adapters.primary.web.routers.auth",
                    expression="auth.router",
                    prefix="/api/v1",
                )
            },
        )
        assert "tenants" in mounted

    def test_profile_patch_translation(self) -> None:
        from src.infrastructure.plugins.profile import ProfilePatch
        from src.infrastructure.plugins.route_loader import route_patches_from_profile

        patches = route_patches_from_profile(
            [
                ProfilePatch(target="route:tenants", enabled=False),
                ProfilePatch(target="route:auth", config={"prefix": "/api/v2"}),
                ProfilePatch(target="plugin-row-unrelated", enabled=False),
                ProfilePatch(target="route:legacy", remove=True),
            ]
        )
        assert set(patches) == {"tenants", "auth", "legacy"}
        assert patches["tenants"].enabled is False
        assert patches["legacy"].enabled is False
        assert patches["auth"].prefix == "/api/v2"

    def test_profile_patch_rejects_unknown_config_keys(self) -> None:
        from src.infrastructure.plugins.profile import ProfilePatch
        from src.infrastructure.plugins.route_loader import route_patches_from_profile

        with pytest.raises(RouteLoadError, match="unknown config keys"):
            route_patches_from_profile([ProfilePatch(target="route:auth", config={"bogus": 1})])


@pytest.mark.unit
class TestBuiltinRouteRowOverridesV2:
    """Explicit V2 row ownership replaces one complete inventory row in place."""

    @pytest.fixture(autouse=True)
    def _install_verified_definitions_on_recording_app(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        original = route_loader_module.install_route_definitions_v2
        self._installed_definitions: list[tuple[Any, ...]] = []

        def install(target: object, definitions: tuple[Any, ...]) -> None:
            self._installed_definitions.append(definitions)
            if isinstance(target, _RecordingApp):
                target.calls.append({"override": definitions[0].replaces_builtin_row_id})
                return
            original(target, definitions)

        monkeypatch.setattr(route_loader_module, "install_route_definitions_v2", install)

    @staticmethod
    def _override(
        row_id: str,
        definitions: tuple[Any, ...],
    ) -> BuiltinRouteRowOverride:
        owner_entry_id = definitions[0].owner_entry_id
        return BuiltinRouteRowOverride(
            row_id=row_id,
            owner_entry_id=owner_entry_id,
            definitions=definitions,
        )

    def test_complete_override_mounts_at_the_inventory_row_position(self) -> None:
        from src.infrastructure.adapters.primary.web.routers import (
            plugin_marketplace,
            tenant_webhooks,
        )

        app = _RecordingApp()
        definitions = system_route_definitions_v2()

        mounted, _ = _install_with_stub_helpers(
            app,
            row_overrides={
                "system": BuiltinRouteRowOverride(
                    row_id="system",
                    owner_entry_id="builtin-system-http-routes",
                    definitions=definitions,
                ),
            },
        )

        previous = next(
            index
            for index, call in enumerate(app.calls)
            if call.get("router") is tenant_webhooks.router
        )
        override = app.calls.index({"override": "system"})
        following = next(
            index
            for index, call in enumerate(app.calls)
            if call.get("router") is plugin_marketplace.router
        )
        assert previous < override < following
        assert "system" in mounted
        assert len(self._installed_definitions) == 2
        assert all(installed is definitions for installed in self._installed_definitions)

    def test_v2_override_never_resolves_the_static_inventory_target(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        original = route_loader_module._resolve_router

        def reject_system(entry: dict[str, Any]) -> object:
            if entry.get("row_id") == "system":
                raise AssertionError("V2-owned rows must not import the static router")
            return original(entry)

        monkeypatch.setattr(route_loader_module, "_resolve_router", reject_system)
        app = _RecordingApp()

        mounted, _ = _install_with_stub_helpers(
            app,
            row_overrides={
                "system": self._override(
                    "system",
                    system_route_definitions_v2(),
                ),
            },
        )

        assert "system" in mounted

    def test_stale_contract_catalog_fails_before_any_route_mount(
        self,
        tmp_path: Path,
    ) -> None:
        payload = json.loads(BUILTIN_ROUTE_CONTRACT_CATALOG_PATH_V2.read_text(encoding="utf-8"))
        payload["rows"][0]["contract_digest"] = "sha256:" + "0" * 64
        stale = tmp_path / "stale-route-catalog.json"
        stale.write_text(json.dumps(payload), encoding="utf-8")
        app = _RecordingApp()

        with pytest.raises(RouteLoadError, match="contract digest mismatch"):
            _install_with_stub_helpers(
                app,
                route_contract_catalog_path=stale,
                row_overrides={
                    "system": self._override(
                        "system",
                        system_route_definitions_v2(),
                    ),
                },
            )

        assert app.calls == []

    def test_mixed_http_websocket_override_uses_complete_structural_keys(self) -> None:
        app = _RecordingApp()

        mounted, _ = _install_with_stub_helpers(
            app,
            row_overrides={
                "tunnel": self._override(
                    "tunnel",
                    tunnel_route_definitions_v2(),
                ),
            },
        )

        assert {"override": "tunnel"} in app.calls
        assert "tunnel" in mounted

    def test_partial_multi_route_override_fails_closed(self) -> None:
        app = _RecordingApp()

        with pytest.raises(RouteLoadError, match="complete route key set"):
            _install_with_stub_helpers(
                app,
                row_overrides={
                    "system": BuiltinRouteRowOverride(
                        row_id="system",
                        owner_entry_id="builtin-system-http-routes",
                        definitions=system_route_definitions_v2()[:1],
                    )
                },
            )

        assert all(call.get("override") != "system" for call in app.calls)

    def test_unknown_override_target_is_rejected(self) -> None:
        definitions = tuple(
            replace(definition, replaces_builtin_row_id="missing")
            for definition in system_route_definitions_v2()
        )
        with pytest.raises(RouteLoadError, match="unknown baseline rows"):
            _install_with_stub_helpers(
                _RecordingApp(),
                row_overrides={
                    "missing": BuiltinRouteRowOverride(
                        row_id="missing",
                        owner_entry_id="builtin-system-http-routes",
                        definitions=definitions,
                    )
                },
            )

    def test_hybrid_helper_row_cannot_be_overridden_as_routes_only(self) -> None:
        definitions = tuple(
            replace(definition, replaces_builtin_row_id="create-pool")
            for definition in system_route_definitions_v2()
        )
        with pytest.raises(RouteLoadError, match="hybrid, not routes-only"):
            _install_with_stub_helpers(
                _RecordingApp(),
                row_overrides={
                    "create-pool": BuiltinRouteRowOverride(
                        row_id="create-pool",
                        owner_entry_id="builtin-system-http-routes",
                        definitions=definitions,
                    )
                },
            )

    def test_patch_and_v2_override_for_the_same_row_are_rejected(self) -> None:
        from src.infrastructure.plugins.route_loader import RouteRowPatch

        with pytest.raises(RouteLoadError, match="both a profile patch and a V2 override"):
            _install_with_stub_helpers(
                _RecordingApp(),
                row_patches={"system": RouteRowPatch(row_id="system", enabled=False)},
                row_overrides={
                    "system": BuiltinRouteRowOverride(
                        row_id="system",
                        owner_entry_id="builtin-system-http-routes",
                        definitions=system_route_definitions_v2(),
                    )
                },
            )
