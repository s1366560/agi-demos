"""Unit tests for the inventory-driven builtin route loader."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi import APIRouter

from src.infrastructure.plugins.route_inventory import INVENTORY_PATH
from src.infrastructure.plugins.route_loader import (
    RouteLoadError,
    install_builtin_routes,
    load_builtin_route_rows,
)

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
