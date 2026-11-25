"""Drive project package revisions through the persisted conversation execution statistics route."""

import base64
import os
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.application.services.agent.conversation_manager import ConversationManager
from src.configuration.config import get_settings
from src.infrastructure.adapters.primary.web.dependencies import create_api_key
from src.infrastructure.adapters.primary.web.routers.agent import messages
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentExecution,
    Conversation,
    Message,
    Project,
    Tenant,
    User,
    UserProject,
    UserTenant,
)
from src.infrastructure.adapters.secondary.persistence.sql_agent_execution_repository import (
    SqlAgentExecutionRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_conversation_repository import (
    SqlConversationRepository,
)
from src.infrastructure.plugins.v2.agent_execution_query_services import (
    AgentExecutionQueryApplicationServicesV2,
)
from src.tests.integration.test_oci_mcp_worker_docker import disposable_worker_registry
from src.tests.unit.infrastructure.agent.core import (
    test_project_package_subagents as agent_fixtures,
)
from src.tests.unit.routers import test_optional_business_http_v2 as package_api

project_turn = agent_fixtures.project_turn
http = package_api.http
publisher = package_api.publisher
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.getenv("OCI_WORKER_DOCKER_TESTS") != "1", reason="requires Docker"),
]
PACKAGE = Path(__file__).resolve().parents[3] / "plugins/business/agent"
PLUGIN = "memstack-agent"


@pytest.fixture(scope="module")
def releases(tmp_path_factory):
    from plugins.business.agent.release import build_release

    folder = tmp_path_factory.mktemp("execution-statistics-publisher")
    shutil.copytree(
        PACKAGE,
        folder,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__", "*.egg-info", "build", "node_modules"),
    )
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    signed = []
    with disposable_worker_registry() as (publish, url, _):
        for version in ("1.0.0", "1.1.0"):
            if version == "1.1.0":
                code = folder / "execution_statistics/aggregate.py"
                before = code.read_text()
                after = before.replace("BUCKET_MINUTES = 60", "BUCKET_MINUTES = 15")
                assert before != after
                code.write_text(after)
                driver = folder / "react_loop.py"
                contents = driver.read_text()
                assert "MAX_ROUNDS_PER_TURN: int | None = None" in contents
                driver.write_text(
                    contents.replace(
                        "MAX_ROUNDS_PER_TURN: int | None = None",
                        "MAX_ROUNDS_PER_TURN: int | None = 1",
                    )
                )
            image = publish(folder)
            signed.append(build_release(image, version, private))
        yield public, url, signed


async def _history(db):
    db.add(User(id="other", email="other@example.test", hashed_password="unused", is_active=True))
    await db.flush()
    db.add(
        Tenant(id="other-tenant", name="Other tenant", slug="other-statistics", owner_id="other")
    )
    await db.flush()
    db.add(UserTenant(id="ut-other", user_id="other", tenant_id="other-tenant", role="owner"))
    db.add(Project(id="unselected", tenant_id="other-tenant", name="Unselected", owner_id="other"))
    await db.flush()
    db.add(
        UserProject(id="owner-unselected", project_id="unselected", user_id="other", role="owner")
    )
    for project in ("p", "unselected"):
        db.add(
            Conversation(
                id="conv-" + project,
                project_id=project,
                tenant_id="t" if project == "p" else "other-tenant",
                user_id="owner" if project == "p" else "other",
                title="History",
                agent_config={"execution_stats_package": PLUGIN} if project == "p" else {},
            )
        )
        await db.flush()
        db.add(
            Message(
                id="message-" + project,
                conversation_id="conv-" + project,
                role="assistant",
                content="Sensitive message body",
            )
        )
        await db.flush()
        for index, status in enumerate(("completed", "failed")):
            started = datetime(2026, 1, 1, 11, 2 + index * 20, tzinfo=UTC)
            db.add(
                AgentExecution(
                    id=f"run-{project}-{index}",
                    conversation_id="conv-" + project,
                    message_id="message-" + project,
                    status=status,
                    tool_name="project-tool",
                    tool_input={"sensitive": "private argument"},
                    tool_output="private output",
                    thought="private thought",
                    started_at=started,
                    completed_at=started + timedelta(seconds=index + 1),
                )
            )
    other_key, _ = await create_api_key(db, "other", "test", [])
    await db.commit()
    return other_key


async def test_real_history_statistics_follow_project_release(
    http, db_session, releases, monkeypatch, tmp_path
):
    client, users = http
    public, registry, (first, second) = releases
    app = client._transport.app
    app.include_router(messages.router, prefix="/api/v1/agent")
    app.state.plugin_marketplace_trusted_public_keys_v2 = (public.decode(),)
    pem = tmp_path / "analytics.pem"
    pem.write_bytes(public)
    monkeypatch.setattr(get_settings(), "plugin_marketplace_trusted_key_files", (pem,))
    monkeypatch.setattr(get_settings(), "plugin_worker_allowed_registries", (registry,))
    users["other"] = await _history(db_session)

    def query():
        manager = ConversationManager(
            conversation_repo=SqlConversationRepository(db_session),
            execution_repo=SqlAgentExecutionRepository(db_session),
        )
        return SimpleNamespace(services=AgentExecutionQueryApplicationServicesV2(manager=manager))

    app.dependency_overrides[messages.agent_execution_query_application_authority_dependency_v2] = (
        query
    )
    headers = {"Authorization": "Bearer " + users["owner"]}
    base = "/api/v1/platform-plugins/v2/optional-business"
    scope = {"project_id": "p", "tenant_id": "t"}

    async def read(project, *, user="owner", claim=None):
        return await client.get(
            f"/api/v1/agent/conversations/conv-{project}/execution/stats",
            headers={"Authorization": "Bearer " + users[user]},
            params={"project_id": claim or project},
        )

    unselected = await read("unselected", user="other")
    assert unselected.is_success, unselected.text
    assert unselected.json()["total_executions"] == 2
    for raw, expected in ((first, 1), (second, 2)):
        installed = await client.post(
            base + "/install",
            headers=headers,
            json={
                **scope,
                "approved_permissions": [
                    "ui.slot",
                    "tools.execute",
                    "subagents.register",
                    "agent.loop.drive",
                    "app.agent.list",
                    "app.agent.create",
                    "app.agent.history",
                    "app.agent.turn",
                    "app.agent.attachments",
                    "app.agent.attachments.turn",
                    "app.agent.activity.read",
                    "app.agent.activity.receipts",
                    "app.agent.review.latest",
                    "app.agent.review.details",
                    "app.agent.composer.read",
                    "app.agent.composer.save",
                    "app.agent.composer.models",
                    "app.agent.composer.context",
                    "app.agent.composer.welcome",
                    "app.agent.lifecycle.control",
                    "app.agent.voice.authorize",
                    "ui.media.microphone",
                    "app.agent.interactions",
                    "app.agent.respond",
                    "app.agent.cancel",
                    "app.agent.rename",
                    "device.local-chat",
                ],
                "archive_base64": base64.b64encode(raw).decode(),
            },
        )
        assert installed.is_success, installed.text
        enabled = await client.post(f"{base}/{PLUGIN}/enable", headers=headers, json=scope)
        assert enabled.is_success and enabled.json()["runtime_phase"] == "active", enabled.text
        review = await client.post(
            f"{base}/{PLUGIN}/invoke",
            headers=headers,
            json={
                **scope,
                "tool_name": "validate_skill",
                "payload": {"content": "# Missing metadata"},
            },
        )
        assert review.is_success and review.json()["is_valid"] is False, review.text
        stats = await read("p")
        assert stats.is_success, stats.text
        output = stats.json()
        assert output["completed_count"] == output["failed_count"] == 1
        assert output["average_duration_ms"] == 1500.0
        assert output["tool_usage"] == {"project-tool": 2}
        assert output["status_distribution"] == {"completed": 1, "failed": 1}
        assert len(output["timeline_data"]) == expected
        assert (await read("unselected", user="other")).json() == unselected.json()
    # The public history endpoint can return 1,000 rows. Exercise the largest ordinal
    # tables in a real supervised worker, including distinct tool slots and time buckets.
    maximal = [[index, index, 1_000_000 + index * 1440, 123456789012345] for index in range(1000)]
    capacity = await client.post(
        f"{base}/{PLUGIN}/invoke",
        headers=headers,
        json={**scope, "tool_name": "execution_statistics", "payload": {"events": maximal}},
    )
    assert capacity.is_success, capacity.text
    assert len(capacity.json()["time_buckets"]) == 1000
    assert (await read("p", user="viewer")).status_code == 403
    assert (await read("p", user="other")).status_code == 404
    assert (await read("p", claim="unselected")).status_code == 403
    rolled = await client.post(f"{base}/{PLUGIN}/rollback", headers=headers, json=scope)
    assert rolled.is_success, rolled.text
    assert len((await read("p")).json()["timeline_data"]) == 1


async def test_turn_obeys_run_pinned_loop_after_upgrade_rollback_and_revocation(
    http, project_turn, releases, monkeypatch
):
    from unittest.mock import AsyncMock

    from plugins.business.agent.engine.processor.processor import ProcessorResult
    from src.domain.events.agent_events import AgentErrorEvent
    from src.infrastructure.agent.core.llm_stream import StreamEventType
    from src.infrastructure.plugins.v2.boundary import OPERATION_METADATA_SERVICE_V2
    from src.tests.unit.infrastructure.agent.processor.test_model_step_steering_v2 import (
        event,
        setup_processor,
    )

    client, users = http
    public, registry, versions = releases
    client._transport.app.state.plugin_marketplace_trusted_public_keys_v2 = (public.decode(),)
    monkeypatch.setattr(get_settings(), "plugin_worker_allowed_registries", (registry,))
    base = "/api/v1/platform-plugins/v2/optional-business"
    headers = {"Authorization": "Bearer " + users["owner"]}
    scope = {"project_id": "p", "tenant_id": "t"}
    active = f"{base}/{PLUGIN}"

    async def install(raw):
        response = await client.post(
            base + "/install",
            headers=headers,
            json={
                **scope,
                "approved_permissions": [
                    "ui.slot",
                    "tools.execute",
                    "subagents.register",
                    "agent.loop.drive",
                    "app.agent.list",
                    "app.agent.create",
                    "app.agent.history",
                    "app.agent.turn",
                    "app.agent.attachments",
                    "app.agent.attachments.turn",
                    "app.agent.activity.read",
                    "app.agent.activity.receipts",
                    "app.agent.review.latest",
                    "app.agent.review.details",
                    "app.agent.composer.read",
                    "app.agent.composer.save",
                    "app.agent.composer.models",
                    "app.agent.composer.context",
                    "app.agent.composer.welcome",
                    "app.agent.lifecycle.control",
                    "app.agent.voice.authorize",
                    "ui.media.microphone",
                    "app.agent.interactions",
                    "app.agent.respond",
                    "app.agent.cancel",
                    "app.agent.rename",
                    "device.local-chat",
                ],
                "archive_base64": base64.b64encode(raw).decode(),
            },
        )
        response.raise_for_status()
        (await client.post(active + "/enable", headers=headers, json=scope)).raise_for_status()

    async def turn(run):
        rounds = []

        async def model(_stream, messages, **kwargs):
            rounds.append(len(messages))
            yield event(StreamEventType.TEXT_END, full_text="model response")
            yield event(StreamEventType.FINISH, reason="stop")

        async with project_turn(run, user="owner", public_key=public.decode()) as (capabilities, _):
            capabilities.operation.provide(
                OPERATION_METADATA_SERVICE_V2, {"kind": "chat", "run_id": run}
            )
            assert capabilities.loop_pin is not None
            assert not any("react_loop" in tool.name for tool in capabilities.tools)
            processor, _, _ = setup_processor(monkeypatch)
            monkeypatch.setattr(
                "plugins.business.agent.engine.processor.processor.LLMStream.generate", model
            )
            processor._evaluate_goal_progress = AsyncMock(
                side_effect=[(ProcessorResult.CONTINUE, []), (ProcessorResult.COMPLETE, [])]
            )
            events = [
                e
                async for e in processor._run_native_loop("c", [{"role": "user", "content": "hi"}])
            ]
            return len(rounds), [e.code for e in events if isinstance(e, AgentErrorEvent)]

    await install(versions[0])
    assert await turn("first") == (2, [])
    await install(versions[1])
    assert await turn("second") == (1, ["AGENT_LOOP_STOPPED"])
    assert await turn("first") == (2, [])
    (await client.post(active + "/rollback", headers=headers, json=scope)).raise_for_status()
    assert await turn("third") == (2, [])
    (await client.post(active + "/disable", headers=headers, json=scope)).raise_for_status()
    rounds, errors = await turn("first")
    assert rounds == 0 and errors
