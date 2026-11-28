"""A signed Environments command authorizes a real private ttyd through the Rust server."""

import asyncio
import json
import os
import secrets
import socket
import subprocess
import tempfile
import time
from contextlib import ExitStack
from pathlib import Path

import httpx
import pytest
from alembic.config import Config
from fastapi import FastAPI
from sqlalchemy import URL
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from websockets.asyncio.client import connect

import docker
from alembic import command
from plugins.business.environments.backend.interaction_channel import project_terminal
from plugins.business.environments.backend.package_sandbox_operations import SANDBOX_OPERATIONS
from src.configuration.config import get_settings
from src.host.identity.initial_owner import create_initial_owner
from src.host.transport.project_package_routes import project_package_router
from src.infrastructure.adapters.primary.web.dependencies import create_api_key
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentPlanRunModel,
    AgentPlanVersionModel,
    Conversation,
)
from src.tests.integration.test_environments_package import environment_release  # noqa: F401

ROOT = Path(__file__).resolve().parents[3]
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUST_SANDBOX_TERMINAL_TESTS") != "1",
        reason="requires Rust server and Docker Sandbox image",
    ),
]


def _service(stack, engine, image, port, **options):
    container = engine.containers.run(
        image, detach=True, ports={f"{port}/tcp": ("127.0.0.1", None)}, **options
    )
    stack.callback(container.remove, force=True, v=True)
    container.reload()
    return container, int(container.attrs["NetworkSettings"]["Ports"][f"{port}/tcp"][0]["HostPort"])


@pytest.fixture
def rust_authority():
    binary = ROOT / "agi-stack/target/debug/agistack-server"
    with ExitStack() as stack:
        engine = docker.from_env()
        stack.callback(engine.close)
        password = secrets.token_hex(24)
        pg, port = _service(
            stack,
            engine,
            "pgvector/pgvector:pg16",
            5432,
            environment={"POSTGRES_PASSWORD": password, "POSTGRES_DB": "terminal"},
        )
        _, redis_port = _service(stack, engine, "redis:7-alpine", 6379)
        for _ in range(100):
            if (
                pg.exec_run(
                    ["pg_isready", "-h", "127.0.0.1", "-U", "postgres", "-d", "terminal"]
                ).exit_code
                == 0
            ):
                break
            time.sleep(0.15)
        else:
            pytest.fail("Isolated PostgreSQL did not start")
        db = URL.create(
            "postgresql+asyncpg",
            username="postgres",
            password=password,
            host="127.0.0.1",
            port=port,
            database="terminal",
        )
        migration = Config(str(ROOT / "alembic.ini"))
        migration.attributes.update(database_url=db, configure_logger=False)
        command.upgrade(migration, "head")
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            address = f"127.0.0.1:{sock.getsockname()[1]}"
        directory = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        settings = directory / "database.env"
        settings.write_text("DATABASE_URL=" + db.render_as_string(hide_password=False) + "\n")
        settings.chmod(0o600)
        env = {
            k: os.environ[k]
            for k in ("PATH", "HOME", "TMPDIR", "DOCKER_HOST", "DOCKER_CONFIG")
            if k in os.environ
        }
        env.update(
            AGISTACK_ADDR=address,
            AGISTACK_DEV_DATABASE_ENV=str(settings),
            AGISTACK_CONTAINER_RUNTIME="docker",
            AGISTACK_SANDBOX_IMAGE=os.getenv(
                "AGISTACK_TERMINAL_TEST_IMAGE", "sandbox-mcp-server:latest"
            ),
            AGISTACK_SANDBOX_AUTH_SECRET=secrets.token_hex(32),
            REDIS_URL=f"redis://127.0.0.1:{redis_port}",
            # This scenario does not call Workspace Core. Keep the required client isolated.
            WORKSPACE_CORE_BASE_URL="http://127.0.0.1:1",
            WORKSPACE_CORE_SERVICE_TOKEN=secrets.token_hex(32),
        )
        server = subprocess.Popen(
            [binary], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        stack.callback(server.wait, timeout=15)
        stack.callback(server.terminate)
        base = f"http://{address}"
        for _ in range(100):
            if server.poll() is not None:
                pytest.fail("Isolated Rust server exited during startup")
            try:
                httpx.get(base + "/health", timeout=1, trust_env=False)
                break
            except httpx.ConnectError:
                time.sleep(0.1)
        else:
            pytest.fail("Isolated Rust server did not start")
        yield db, base


async def _running_plan(session, scope, user, sandbox_id):
    """Persist the approved-run fixture consumed by the same SQL authority as production."""
    session.add(Conversation(id="conversation", **scope, user_id=user, title="Terminal fixture"))
    await session.flush()
    session.add(
        AgentPlanVersionModel(
            id="plan", conversation_id="conversation", version=1, status="approved", tasks_json=[]
        )
    )
    await session.flush()
    session.add(
        AgentPlanRunModel(
            id="run",
            conversation_id="conversation",
            project_id=scope["project_id"],
            plan_version_id="plan",
            idempotency_key="isolated",
            message_id="message",
            request_message="Terminal fixture",
            status="running",
            revision=1,
            permission_profile="full_access",
            authorization_snapshot={
                "conversation_id": "conversation",
                "project_id": scope["project_id"],
                "plan_version_id": "plan",
                "permission_profile": "full_access",
                "environment": {"kind": "local", "id": sandbox_id, "workspace_path": "/workspace"},
            },
        )
    )
    await session.commit()


async def _shell_round_trip(origin, path, key, grant):
    uri = (
        origin.replace("http:", "ws:") + path + "/terminal/sessions/" + grant["session_id"] + "/ws"
    )
    async with connect(
        uri, subprotocols=["memstack.auth", key, "memstack.terminal-v2", grant["resume_token"]]
    ) as socket:
        # The assembled sentinel cannot be satisfied by a PTY echo of the command.
        await socket.send(
            json.dumps({"type": "input", "data": "printf 'terminal-%s\\n' verified\r"})
        )
        output = ""
        async with asyncio.timeout(12):
            while "terminal-verified" not in output:
                output += json.loads(await socket.recv()).get("data", "")
        await socket.send(json.dumps({"type": "input", "data": "exit\r"}))
        async with asyncio.timeout(10):
            while True:
                event = json.loads(await socket.recv())
                if event["type"] == "terminal_session_lost":
                    break


async def _check_signed_grant(client, commands_url, scope, run):
    # Docker reports Running before ttyd starts listening. Only retry that transient error.
    async with asyncio.timeout(60):
        while True:
            result = await client.post(
                commands_url,
                json={
                    **scope,
                    "command_id": "authorize-run-terminal",
                    "payload": run,
                },
            )
            if result.status_code != 503 or "502" not in result.text:
                break
            await asyncio.sleep(0.4)
    result.raise_for_status()
    grant = result.json()
    assert set(grant) == {
        "contract_version",
        "project_id",
        "run_id",
        "run_revision",
        "expires_at",
    }
    assert (grant["project_id"], grant["run_id"], grant["run_revision"]) == (
        scope["project_id"],
        "run",
        1,
    )


async def _check_signed_shell(post, commands, run):
    handle = await post(
        commands,
        command_id="authorize-run-terminal",
        payload={**run, "open_channel": True},
    )
    assert set(handle) == {"channel"}

    async def transfer(action, **data):
        return await post(
            commands,
            command_id="project-terminal",
            payload={**handle, "action": action, **data},
        )

    try:
        await transfer(
            "write",
            data=json.dumps({"type": "input", "data": "printf '%d\\n' $((357*439))\r"}),
        )
        output = ""
        async with asyncio.timeout(20):
            while "156723" not in output:
                frame = await transfer("read")
                if frame.get("message"):
                    output += json.loads(frame["message"]).get("data", "")
        await transfer("write", data=json.dumps({"type": "input", "data": "exit\r"}))
    finally:
        await transfer("close")


async def test_signed_command_authorizes_run_and_host_can_use_ttyd(
    rust_authority,
    environment_release,  # noqa: F811
    monkeypatch,
):
    db, origin = rust_authority
    registry, public, archive, _ = environment_release
    monkeypatch.setattr(get_settings(), "project_sandbox_authority_url", origin)
    monkeypatch.setattr(get_settings(), "plugin_worker_allowed_registries", (registry,))
    engine = create_async_engine(db)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            user, tenant, project = await create_initial_owner(
                session,
                email="owner@example.org",
                password=secrets.token_hex(16),
                tenant_name="Terminal test",
                project_name="Terminal test",
            )
            key, _ = await create_api_key(session, user, "terminal-test", [])
            await session.commit()

            async def database():
                return session

            app = FastAPI()
            app.include_router(project_package_router)
            app.dependency_overrides[get_db] = database
            app.state.plugin_marketplace_trusted_public_keys_v2 = (public,)
            app.state.package_operations_v1 = {
                **SANDBOX_OPERATIONS,
                "app.environments.terminal.interact": project_terminal,
            }
            headers = {"Authorization": "Bearer " + key}
            scope = {"tenant_id": tenant, "project_id": project}
            authority_path = f"/api/v1/projects/{project}/sandbox"
            package = "/api/v1/platform-plugins/v2/optional-business"
            async with (
                httpx.AsyncClient(
                    base_url="http://test", transport=httpx.ASGITransport(app=app), headers=headers
                ) as client,
                httpx.AsyncClient(
                    base_url=origin, headers=headers, trust_env=False, timeout=60
                ) as rust,
            ):

                async def post(suffix, **payload):
                    response = await client.post(package + suffix, json={**scope, **payload})
                    response.raise_for_status()
                    return response.json()

                inspected = await post("/inspect", archive_base64=archive)
                await post(
                    "/install",
                    archive_base64=archive,
                    approved_permissions=inspected["permissions"],
                )
                await post("/memstack-environments/enable")
                commands = "/memstack-environments/commands"
                prepared = await post(
                    commands, command_id="prepare-sandbox", payload={"profile": "standard"}
                )
                try:
                    await _running_plan(session, scope, user, prepared["sandbox"]["sandbox_id"])
                    run = {"run_id": "run", "expected_run_revision": 1}
                    wrong = await client.post(
                        package + commands,
                        json={
                            **scope,
                            "command_id": "authorize-run-terminal",
                            "payload": {**run, "expected_run_revision": 2},
                        },
                    )
                    assert wrong.status_code == 409
                    await _check_signed_grant(client, package + commands, scope, run)
                    await _check_signed_shell(post, commands, run)
                    # The shell is a separate trusted-client action: it obtains its own private handle.
                    private = await rust.post(authority_path + "/terminal/sessions", json=run)
                    private.raise_for_status()
                    await _shell_round_trip(origin, authority_path, key, private.json())
                finally:
                    (await rust.delete(authority_path)).raise_for_status()
    finally:
        await engine.dispose()
