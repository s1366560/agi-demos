"""Tool media stays reachable through V2 dispatch without starting any runtime service."""

import asyncio
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest


@contextmanager
def _no_external_io(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """Install transport guards and sentinel configuration before product imports."""
    import socket
    from urllib.parse import urlsplit

    attempts: list[str] = []
    clear_settings = None

    def denied(kind: str) -> Mock:
        def fail(*args: object, **kwargs: object) -> None:
            attempts.append(kind)
            raise AssertionError(f"forbidden external operation: {kind}")

        return Mock(side_effect=fail)

    try:
        monkeypatch.setattr(socket.socket, "connect", denied("socket.connect"))
        monkeypatch.setattr(socket.socket, "connect_ex", denied("socket.connect_ex"))
        monkeypatch.setattr(socket, "create_connection", denied("socket.create_connection"))
        for key, value in {
            "REDIS_HOST": "127.0.0.1",
            "REDIS_PORT": "1",
            "REDIS_PASSWORD": "",
            "WORKSPACE_CORE_BASE_URL": "http://127.0.0.1:1",
            "WORKSPACE_CORE_SERVICE_TOKEN": "route-test-only",
            "WORKSPACE_CORE_PROVIDER_WEBHOOK_TOKEN": "route-webhook-test-only",
            "WORKSPACE_CORE_PROVIDER_EVENT_TOKEN": "route-event-test-only",
            "WORKSPACE_CORE_AGENT_REGISTRY_TOKEN": "route-registry-test-only",
        }.items():
            monkeypatch.setenv(key, value)

        import asyncpg
        import redis
        import redis.asyncio as async_redis
        from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

        monkeypatch.setattr(asyncpg, "connect", AsyncMock(side_effect=denied("asyncpg.connect")))
        monkeypatch.setattr(AsyncEngine, "connect", denied("sqlalchemy.connect"))
        monkeypatch.setattr(async_sessionmaker, "__call__", denied("sqlalchemy.session"))
        monkeypatch.setattr(redis.Redis, "execute_command", denied("redis.command"))
        monkeypatch.setattr(
            async_redis.Redis,
            "execute_command",
            AsyncMock(side_effect=denied("redis.async_command")),
        )

        from src.configuration.config import Settings, get_settings

        isolated_env = tmp_path / ".env"
        isolated_env.write_text(
            "DATABASE_URL=postgresql://route_test:unused@127.0.0.1:1/route_test\n"
            "REDIS_HOST=127.0.0.1\nREDIS_PORT=1\nREDIS_PASSWORD=\n",
            encoding="utf-8",
        )
        monkeypatch.setitem(Settings.model_config, "env_file", isolated_env)
        clear_settings = get_settings.cache_clear
        clear_settings()
        settings = get_settings()
        database = urlsplit(settings.postgres_url)
        redis_address = urlsplit(settings.redis_url)
        if (database.hostname, database.port, database.path) != (
            "127.0.0.1",
            1,
            "/route_test",
        ):
            raise AssertionError("database isolation configuration was not applied")
        if (redis_address.hostname, redis_address.port, redis_address.path) != (
            "127.0.0.1",
            1,
            "/0",
        ):
            raise AssertionError("redis isolation configuration was not applied")
        if redis_address.password is not None or get_settings() is not settings:
            raise AssertionError("isolated settings cache or redis credentials are invalid")

        from src.infrastructure.plugins.v2 import llm_health_runtime
        from src.infrastructure.scheduler import scheduler_service

        for module, names in (
            (scheduler_service, ("start_scheduler", "sync_all_jobs", "stop_scheduler")),
            (
                llm_health_runtime,
                (
                    "start_health_checker",
                    "sync_llm_health_checker_providers_v2",
                    "stop_health_checker",
                ),
            ),
        ):
            for name in names:
                monkeypatch.setattr(module, name, AsyncMock(side_effect=denied(name)))
        yield
    finally:
        if clear_settings is not None:
            clear_settings()
        if attempts:
            raise AssertionError(f"external-operation attempts were blocked: {attempts}")


_CHILD_DRIVER = """\
import json, runpy, sys
sys.path[:] = json.loads(sys.argv[1])
namespace = runpy.run_path(sys.argv[2])
namespace['_run_route_child'](*sys.argv[3:])
"""


def _parent_state() -> tuple[object, ...]:
    """Observe existing parent globals without importing or constructing settings."""
    modules = {
        name: module
        for name, module in sys.modules.copy().items()
        if name.startswith("src.") and isinstance(module, ModuleType)
    }
    retained = {
        (name, attribute): id(vars(module)[attribute])
        for name, module in modules.items()
        for attribute in ("settings", "engine", "async_session_factory")
        if attribute in vars(module)
    }
    configuration = []
    for module_name, settings_type, getter_name in (
        ("src.configuration.config", "Settings", "get_settings"),
        (
            "src.configuration.workspace_core",
            "WorkspaceCoreSettings",
            "get_workspace_core_settings",
        ),
    ):
        module = modules.get(module_name)
        if module is not None:
            getter = vars(module).get(getter_name)
            cache_info = getattr(getter, "cache_info", None)
            model_config = getattr(vars(module).get(settings_type), "model_config", {})
            configuration.append(
                (
                    module_name,
                    hashlib.sha256(repr(dict(model_config)).encode()).hexdigest(),
                    cache_info() if cache_info is not None else id(getter),
                )
            )
    environment_digest = hashlib.sha256(
        json.dumps(dict(os.environ), sort_keys=True).encode()
    ).hexdigest()
    module_ids = {name: id(module) for name, module in modules.items()}
    return module_ids, retained, configuration, environment_digest, tuple(sys.path)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("route_kind", "authenticated", "artifact_id", "expected"),
    [
        ("media", False, "cloud-media", 401),
        ("media", True, "missing-media", 404),
        ("media", True, "cloud-media", 200),
        ("step", False, "unused", 401),
    ],
)
def test_native_routes_use_published_generation(
    route_kind: str, authenticated: bool, artifact_id: str, expected: int
) -> None:
    # Import-time settings and engine objects cannot be undone with cache_clear().
    # Keep the transport guard and every product import inside an OS child process.
    before = _parent_state()
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            _CHILD_DRIVER,
            json.dumps(sys.path),
            str(Path(__file__).resolve()),
            route_kind,
            str(authenticated),
            artifact_id,
            str(expected),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert _parent_state() == before, "native route test changed parent process state"
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.rstrip().endswith("CUA_NATIVE_ROUTE_CHILD_OK")


def _run_route_child(route_kind: str, authenticated: str, artifact_id: str, expected: str) -> None:
    with (
        tempfile.TemporaryDirectory(prefix="memstack-native-route-child-") as temporary,
        pytest.MonkeyPatch.context() as patch,
        _no_external_io(patch, Path(temporary)),
    ):
        asyncio.run(
            _exercise_native_route(route_kind, authenticated == "True", artifact_id, int(expected))
        )
    print("CUA_NATIVE_ROUTE_CHILD_OK")


async def _exercise_native_route(
    route_kind: str, authenticated: bool, artifact_id: str, expected: int
) -> None:
    import httpx
    from fastapi import FastAPI

    from src.domain.model.artifact.artifact import ArtifactStatus
    from src.domain.model.plugins.generated_v2 import ProfileSnapshotV2
    from src.infrastructure.adapters.primary.web.routers.agent import (
        computer_use_media as api,
    )
    from src.infrastructure.adapters.primary.web.startup.generation_http_v2 import (
        mount_generation_http_dispatcher_v2,
    )
    from src.infrastructure.plugins.v2.boundary import pin_generation_v2
    from src.infrastructure.plugins.v2.builtin_agent_http_routes import (
        agent_route_definitions_v2,
    )
    from src.infrastructure.plugins.v2.http_routes import (
        RouteTableRegistryV2,
        RouteTableV2,
        install_route_definitions_v2,
    )
    from src.infrastructure.plugins.v2.runtime import GenerationManagerV2, LoaderV2

    generation = await LoaderV2(target_catalog={}).stage(
        ProfileSnapshotV2(
            schema_version=2,
            profile_id="tool-media-test",
            generation=1,
            manifests=(),
            entries=(),
            digest="0" * 64,
        )
    )
    assert generation.fibers == ()
    host = GenerationManagerV2()
    await host.publish(generation)
    private_app = FastAPI()
    definitions = agent_route_definitions_v2()
    install_route_definitions_v2(private_app, definitions)
    artifact = SimpleNamespace(
        tenant_id="tenant",
        project_id="project",
        conversation_id="conversation",
        status=ArtifactStatus.READY,
        metadata={"upload_source": "native_computer_use"},
        mime_type="image/png",
        size_bytes=3,
    )
    services = SimpleNamespace(
        artifacts=SimpleNamespace(
            get_artifact=AsyncMock(return_value=artifact if artifact_id == "cloud-media" else None)
        ),
        content=SimpleNamespace(
            get_bytes=AsyncMock(return_value=SimpleNamespace(mime_type="image/png", content=b"png"))
        ),
        commit=AsyncMock(),
    )
    if authenticated:
        private_app.dependency_overrides[api.get_current_user] = lambda: SimpleNamespace(id="user")
    private_app.dependency_overrides[api.get_db] = lambda: SimpleNamespace(
        scalar=AsyncMock(return_value="conversation")
    )
    private_app.dependency_overrides[api.artifact_http_application_authority_dependency_v2] = (
        lambda: SimpleNamespace(services=services)
    )
    try:
        registry = RouteTableRegistryV2()
        await registry.publish(
            generation.descriptor,
            RouteTableV2.from_fastapi_graph(private_app, definitions=definitions),
        )
        app = FastAPI()
        app.state.platform_plugin_route_registry_v2 = registry
        mount_generation_http_dispatcher_v2(app)
        async with (
            pin_generation_v2(host),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client,
        ):
            if route_kind == "step":
                response = await client.post(
                    "/api/v1/agent/device/requests/request/steps/step/authorize",
                    json={},
                )
            else:
                response = await client.get(
                    f"/api/v1/agent/conversations/conversation/tool-media/{artifact_id}",
                    params={"tenant_id": "tenant", "project_id": "project"},
                )
        assert response.status_code == expected, response.text
        if expected == 200:
            assert response.content == b"png"
            assert response.headers["content-type"] == "image/png"
            assert response.headers["content-length"] == "3"
            assert response.headers["cache-control"] == "private, no-store"
            assert response.headers["x-content-type-options"] == "nosniff"
            services.commit.assert_awaited_once()
        else:
            services.content.get_bytes.assert_not_awaited()
    finally:
        await host.close()
