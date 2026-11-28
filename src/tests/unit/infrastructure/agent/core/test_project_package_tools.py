"""Execute signed contributions through the same operation ToolSet and Skill loader as ReAct."""

import json
import logging
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentRunAuthorityModel,
    Conversation,
    UserProject,
)
from src.infrastructure.agent.core import project_package_tools
from src.infrastructure.agent.core.project_package_tools import bind_project_packages
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.skill_loader import make_skill_loader_tool
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_IDENTITY_SERVICE_V2,
    bind_operation_context_v2,
)
from src.infrastructure.plugins.v2.runtime import OperationContextV2, RuntimeV2Error
from src.infrastructure.plugins.v2.signed_optional_business_v2 import OptionalBusinessError
from src.infrastructure.plugins.v2.tool_set import (
    PreparedToolProviderV2,
    ToolSetCatalogV2,
    bind_operation_tool_set_catalog_v2,
)
from src.tests.unit.infrastructure.plugins.v2.test_runtime import (
    _definition,
    _entry,
    _loader,
    _snapshot,
)
from src.tests.unit.routers import test_optional_business_http_v2 as package_fixtures

http = package_fixtures.http
publisher = package_fixtures.publisher

pytestmark = pytest.mark.unit


async def test_signed_tools_and_skills_stay_with_run_and_recheck_live_role(  # noqa: PLR0915
    http,
    publisher,
    db_session,
    caplog,
    tmp_path,
    monkeypatch,
):
    caplog.set_level(logging.INFO, logger="plugin_audit")
    client, tokens = http
    assert str(db_session.get_bind().url) == "sqlite+aiosqlite:///:memory:"
    public, build = publisher
    trust_root = tmp_path / "publisher.pem"
    trust_root.write_text(public)
    settings = project_package_tools.get_settings().model_copy(
        update={"plugin_marketplace_trusted_key_files": (trust_root,)}
    )
    monkeypatch.setattr(project_package_tools, "get_settings", lambda: settings)
    base = "/api/v1/platform-plugins/v2/optional-business"
    scope = {"tenant_id": "t", "project_id": "p"}
    headers = {"Authorization": f"Bearer {tokens['owner']}"}

    async def change(action):
        response = await client.post(f"{base}/sample.notes/{action}", json=scope, headers=headers)
        assert response.status_code == 200, response.text

    async def release(version, value):
        body, _ = build(version, result=value, skill_instructions=f"Instructions for {value}.")
        response = await client.post(f"{base}/install", json=body, headers=headers)
        assert response.status_code == 200, response.text
        await change("enable")

    db_session.add(
        Conversation(
            id="conversation", tenant_id="t", project_id="p", user_id="owner", title="test"
        )
    )
    await db_session.flush()
    for run in ("first", "second", "third", "fresh"):
        db_session.add(
            AgentRunAuthorityModel(
                id=run,
                tenant_id="t",
                project_id="p",
                conversation_id="conversation",
                run_kind="chat",
                idempotency_key=run,
                message_id=run,
                request_message="ping",
                status="running",
                permission_profile="full_access",
                authorization_snapshot={},
            )
        )
    await db_session.commit()
    sessions = async_sessionmaker(db_session.bind, expire_on_commit=False)
    entry = _entry("root", "builtin://runtime/root")
    snapshot = _snapshot(1, (entry,))
    generation = await _loader(
        snapshot, [_definition(snapshot, entry.module_ref, lambda *_args: None)]
    ).stage(snapshot)
    context = ToolContext(
        session_id="conversation",
        message_id="msg",
        call_id="call",
        agent_name="test",
        conversation_id="conversation",
    )
    loader = make_skill_loader_tool(skill_service=SimpleNamespace(), tenant_id="t", project_id="p")

    @asynccontextmanager
    async def turn(run, user="owner", project="p"):
        async with OperationContextV2(
            generation=generation,
            operation_id=run,
            scope=ScopeV2(
                kind=ScopeKindV2.SESSION,
                tenant_id="t",
                project_id=project,
                session_id="conversation",
            ),
        ) as operation:
            with bind_operation_context_v2(operation):
                operation.provide(OPERATION_IDENTITY_SERVICE_V2, {"user_id": user})
                catalog = bind_operation_tool_set_catalog_v2(operation)
                bound = await bind_project_packages(operation, catalog, run, sessions)
                tools = ToolSetCatalogV2().resolve(
                    agent=None,
                    selection_context=None,
                    prepared_tool_provider=PreparedToolProviderV2(tools={}),
                    operation_catalog=catalog,
                )
                yield tools.definitions, list(bound.skills)

    async def load(name):
        return await loader.execute(context, name=name)

    try:
        async with turn("first") as empty:
            assert empty == ((), [])
            with pytest.raises(RuntimeV2Error, match="project has no authorized Agent loop"):
                await project_package_tools.current_loop_driver()("start", "continue", 0)
        await release("1.0.0", "ping")
        async with turn("first") as empty:
            assert empty == ((), [])
        async with turn("second") as ((old,), (skill,)):
            assert old.permission == "code_executor"
            assert old.description.endswith("Return the signed ping response.")
            assert (await load(skill)).output.find("Instructions for ping.") >= 0
            context.runtime_context["allowed_skills"] = ["another-skill"]
            assert (await load(skill)).is_error
            context.runtime_context.clear()
            await release("1.1.0", "pong")
            async with turn("third") as ((new,), (new_skill,)):
                assert new.name == old.name and new_skill == skill
                assert new.description.endswith("Return the signed pong response.")
                assert json.loads(await new.execute(op="ping"))["op"] == "pong"
                assert "Instructions for pong." in (await load(skill)).output
                with pytest.raises(RuntimeV2Error, match="scope changed"):
                    await old.execute(op="ping")
            assert json.loads(await old.execute(op="ping"))["op"] == "ping"
            receipts = [
                json.loads(r.getMessage())
                for r in caplog.records
                if r.name == "plugin_audit.project_package"
            ]
            assert [
                (e["run_id"], e["actor_id"], e["version"])
                for e in receipts
                if e.get("tool_id") == "note.ping"
            ] == [("third", "owner", "1.1.0"), ("second", "owner", "1.0.0")]
            assert "Instructions for ping." in (await load(skill)).output
        with pytest.raises(RuntimeV2Error):
            await old.execute(op="ping")
        async with turn("second") as ((resumed,), names):
            assert resumed.description == old.description
            assert names == [skill] and json.loads(await resumed.execute(op="ping"))["op"] == "ping"
            await db_session.execute(
                update(UserProject).where(UserProject.user_id == "owner").values(role="viewer")
            )
            await db_session.commit()
            with pytest.raises(RuntimeV2Error, match="execution permission"):
                await resumed.execute(op="ping")
            assert "Instructions for ping." in (await load(skill)).output
            async with turn("second") as viewer:
                assert viewer == ((), [skill])
            await db_session.execute(
                update(UserProject).where(UserProject.user_id == "owner").values(role="owner")
            )
            await db_session.commit()
            await change("disable")
            await change("enable")
            with pytest.raises(OptionalBusinessError, match="authorization has ended"):
                await resumed.execute(op="ping")
            assert (await load(skill)).is_error
        with pytest.raises(OptionalBusinessError, match="scope is unavailable"):
            async with turn("second", project="other"):
                pytest.fail("wrong project admitted")
        async with turn("fresh") as ((current,), _):
            assert json.loads(await current.execute(op="ping"))["op"] == "pong"
        for invalid_actor in (None, "deleted-user"):
            with pytest.raises(RuntimeV2Error, match="actor is unavailable"):
                async with turn("fresh", user=invalid_actor):
                    pytest.fail("signed tools exposed without a live actor")
        settings = settings.model_copy(update={"plugin_marketplace_trusted_key_files": ()})
        async with turn("fresh") as withdrawn:
            assert withdrawn == ((), [])
    finally:
        await generation.dispose()
