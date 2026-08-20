"""Protocol v2 plugin runtime startup and shutdown."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from starlette.types import Scope

from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

logger = logging.getLogger(__name__)
_ROOT = Path(__file__).resolve().parents[6]
DEFAULT_PROFILE_V2_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
DEFAULT_MANIFEST_V2_PATHS = (_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",)


async def initialize_plugin_runtime_v2(app: FastAPI) -> PlatformPluginRuntimeHostV2:
    """Compose and publish the required initial v2 generation."""
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=DEFAULT_PROFILE_V2_PATH,
        manifest_paths=DEFAULT_MANIFEST_V2_PATHS,
        generation=1,
        version=1,
    )
    if not publication.accepted:
        await host.close()
        raise RuntimeError(
            "plugin runtime v2 bootstrap failed: "
            f"{publication.receipt.error_code}: {publication.receipt.error_message}"
        )
    app.state.platform_plugin_runtime_v2 = host
    logger.info(
        "Published plugin runtime v2 generation=%d digest=%s",
        publication.snapshot.generation,
        publication.snapshot.digest,
    )
    return host


async def shutdown_plugin_runtime_v2(app: FastAPI) -> None:
    """Retire the current v2 generation and wait for Fiber disposal."""
    host = getattr(app.state, "platform_plugin_runtime_v2", None)
    if not isinstance(host, PlatformPluginRuntimeHostV2):
        return
    await host.close()
    app.state.platform_plugin_runtime_v2 = None


def plugin_runtime_host_v2_from_scope(scope: Scope) -> PlatformPluginRuntimeHostV2:
    """Resolve the initialized host for the request generation middleware."""
    app = scope.get("app")
    host = getattr(getattr(app, "state", None), "platform_plugin_runtime_v2", None)
    if not isinstance(host, PlatformPluginRuntimeHostV2):
        raise RuntimeError("plugin runtime v2 is not initialized")
    return host
