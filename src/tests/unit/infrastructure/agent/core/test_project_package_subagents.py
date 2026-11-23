"""Run signed SubAgent declarations through project admission and actual delegate dispatch."""

import base64
import hashlib
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from memstack_plugin_sdk.contract import ContractError, parse_contribution
from sqlalchemy import update
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.domain.events.agent_events import AgentTextEndEvent
from src.domain.model.agent.spawn_policy import SpawnPolicy
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentRunAuthorityModel,
    Conversation,
    PlatformPluginPackageModel,
    UserProject,
)
from src.infrastructure.agent.core.project_package_subagents import require_signed_continuation
from src.infrastructure.agent.core.project_package_tools import bind_project_packages
from src.infrastructure.agent.core.subagent_tool_set_v2 import SubAgentToolSetBindingV2
from src.infrastructure.agent.subagent.process import SubAgentProcess
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
    restrict_tool_set_v2,
)
from src.tests.unit.infrastructure.agent.core.test_react_agent_runtime_profile import (
    _make_agent,
    _make_react_agent,
)
from src.tests.unit.infrastructure.agent.tools.test_subagent_tool_runtime_isolation import (
    _context,
    _execute_with_context,
)
from src.tests.unit.infrastructure.plugins.v2.test_runtime import (
    _definition,
    _entry,
    _loader,
    _snapshot,
)
from src.tests.unit.routers.test_optional_business_http_v2 import (  # noqa: F401
    _body,
    http,
    publisher,
)

pytestmark = pytest.mark.unit


def declaration(prompt="Review the supplied document.", **fields):
    return {
        "id": "review",
        "name": "Reviewer",
        "description": "Review the supplied document.",
        "instructions": prompt,
        "permissions": ["subagents.register"],
        **fields,
    }


@pytest.mark.parametrize(
    "fields",
    [
        {"tools": ["*"]},
        {"tools": ["terminal"]},
        {"permissions": ["tools.execute"]},
        {"role": "admin"},
        {"allowed_skills": ["*"]},
        {"model": "provider/other"},
        {"spawn_policy": {}},
    ],
)
def test_publisher_rejects_unowned_tools_and_authority_fields(fields):
    document = _body()["contribution"]
    with pytest.raises(ContractError):
        parse_contribution({**document, "subagents": [declaration(**fields)]})


@pytest.fixture
async def project_turn(db_session, publisher):  # noqa: F811
    db_session.add(Conversation(id="c", tenant_id="t", project_id="p", user_id="viewer", title="t"))
    await db_session.flush()
    for run_id in ("first", "second", "third"):
        db_session.add(
            AgentRunAuthorityModel(
                id=run_id,
                tenant_id="t",
                project_id="p",
                conversation_id="c",
                run_kind="chat",
                idempotency_key=run_id,
                message_id=run_id,
                request_message="test",
                status="running",
                permission_profile="full_access",
                authorization_snapshot={},
            )
        )
    await db_session.commit()
    entry = _entry("root", "builtin://runtime/root")
    snapshot = _snapshot(1, (entry,))
    generation = await _loader(
        snapshot, [_definition(snapshot, entry.module_ref, lambda *_: None)]
    ).stage(snapshot)
    sessions = async_sessionmaker(db_session.bind, expire_on_commit=False)

    @asynccontextmanager
    async def turn(run_id, *, operation_id=None, user="viewer", public_key=None):
        async with OperationContextV2(
            generation=generation,
            operation_id=operation_id or run_id,
            scope=ScopeV2(kind=ScopeKindV2.SESSION, tenant_id="t", project_id="p", session_id="c"),
        ) as operation:
            with bind_operation_context_v2(operation):
                operation.provide(OPERATION_IDENTITY_SERVICE_V2, {"user_id": user})
                catalog = bind_operation_tool_set_catalog_v2(operation)
                capabilities = await bind_project_packages(
                    operation, catalog, run_id, sessions, trusted_keys=(public_key or publisher[0],)
                )
                tool_set = ToolSetCatalogV2().resolve(
                    agent=None,
                    selection_context=None,
                    prepared_tool_provider=PreparedToolProviderV2(tools={}),
                    operation_catalog=catalog,
                )
                yield capabilities, tool_set

    try:
        yield turn
    finally:
        await generation.dispose()


def delegate_for(capabilities, tools, allowed_ids, *, role=None):
    react = _make_react_agent(enable_subagent_as_tool=True)
    react._tool_builder.deps.agent_role = role
    binding = SubAgentToolSetBindingV2(operation=capabilities.operation)
    binding.bind(tools)
    options = react._stream_inject_subagent_tools(
        tools_to_use=[],
        available_subagents=list(capabilities.subagents.values()),
        project_id="p",
        tenant_id="t",
        conversation_id="c",
        conversation_context=[],
        abort_signal=None,
        tool_set_binding=binding,
        selected_agent=_make_agent(
            can_spawn=True, spawn_policy=SpawnPolicy(allowed_subagents=allowed_ids)
        ),
    )
    return next(
        (definition for definition in options if definition.name == "delegate_to_subagent"), None
    )


async def test_signed_delegate_rechecks_release_role_and_parent_tool_subset(  # noqa: PLR0915
    http,  # noqa: F811
    publisher,  # noqa: F811
    project_turn,
    db_session,
    monkeypatch,
):
    client, tokens = http
    headers = {"Authorization": f"Bearer {tokens['owner']}"}
    scope = {"tenant_id": "t", "project_id": "p"}
    base = "/api/v1/platform-plugins/v2/optional-business"

    async def publish(version, word, **fields):
        body, _ = publisher[1](
            version, result=word, subagents=[declaration(f"Edition {word}.", **fields)]
        )
        without_grant = {**body, "approved_permissions": ["tools.execute", "ui.slot"]}
        denied = await client.post(base + "/install", json=without_grant, headers=headers)
        assert denied.status_code == 400 and "subagents.register" in denied.text, denied.text
        record = await client.post(base + "/install", json=body, headers=headers)
        assert record.status_code == 200, record.text
        await change("enable")
        return hashlib.sha256(base64.b64decode(body["archive_base64"])).hexdigest()

    async def change(action):
        response = await client.post(f"{base}/sample.notes/{action}", json=scope, headers=headers)
        assert response.status_code == 200, response.text

    async def role(new_role):
        await db_session.execute(
            update(UserProject).where(UserProject.user_id == "viewer").values(role=new_role)
        )
        await db_session.commit()

    calls = []

    def build_processor(process, **_kwargs):
        async def run(messages, **_kwargs):
            names = [tool.name for tool in process._tools]
            output = (
                json.loads(await process._tools[0].execute(op="ping"))["op"]
                if names
                else "no-tools"
            )
            calls.append((messages[0]["content"], names, output))
            yield AgentTextEndEvent(full_text=output)

        return SimpleNamespace(process=run)

    monkeypatch.setattr(SubAgentProcess, "_build_processor", build_processor)

    async def dispatch(tool, agent):
        return await _execute_with_context(
            tool, _context("c"), subagent_name=agent.name, task="review"
        )

    await publish("1.0.0", "ping", tools=["note.ping"])
    async with project_turn("first") as (view, _):
        assert not view.subagents
    await role("member")
    async with project_turn("first") as (current, tools):
        (agent,) = current.subagents.values()
        assert agent.allowed_skills == [] and agent.spawn_policy.max_depth == 0
        assert delegate_for(current, tools, frozenset()) is None
        from src.domain.model.agent.agent_role import AgentRole

        assert delegate_for(current, tools, None, role=AgentRole.LEAF) is None
        assert delegate_for(current, tools, frozenset({agent.display_name})) is None
        visible = delegate_for(current, tools, frozenset({agent.id}))
        assert not (await dispatch(visible, agent)).is_error
        assert calls[-1][0].startswith("Edition ping.") and calls[-1][1:] == (
            agent.allowed_tools,
            "ping",
        )
        constrained = delegate_for(current, restrict_tool_set_v2(tools, ()), None)
        assert not (await dispatch(constrained, agent)).is_error
        assert calls[-1][1:] == ([], "no-tools")
        continuation = SimpleNamespace(
            subagent_name=agent.name, metadata={"signed_subagent_release": agent.release_binding()}
        )
        await require_signed_continuation(continuation)
        digest = await publish("1.1.0", "pong")  # Default child tool ceiling is empty.
        async with project_turn("second") as (new, new_tools):
            (replacement,) = new.subagents.values()
            assert replacement.id == agent.id and replacement.name != agent.name
            assert replacement.allowed_tools == []
            with pytest.raises(RuntimeV2Error, match="outside this run"):
                await require_signed_continuation(continuation)
            assert not (await dispatch(delegate_for(new, new_tools, None), replacement)).is_error
            assert calls[-1][0].startswith("Edition pong.") and calls[-1][1:] == ([], "no-tools")
        assert not (await dispatch(visible, agent)).is_error
        assert calls[-1][1:] == (agent.allowed_tools, "ping")

    async with project_turn("first", operation_id="recovered-first") as (restored, tools):
        await require_signed_continuation(continuation)
        visible = delegate_for(restored, tools, None)
        assert not (await dispatch(visible, agent)).is_error
        await role("viewer")
        before = len(calls)
        assert (await dispatch(visible, agent)).is_error
        assert len(calls) == before
        await role("member")
        await change("disable")
        await change("enable")
        assert (await dispatch(visible, agent)).is_error
        with pytest.raises(OptionalBusinessError, match="authorization has ended"):
            await require_signed_continuation(continuation)

    async with project_turn("third") as (fresh, tools):
        (active,) = fresh.subagents.values()
        visible = delegate_for(fresh, tools, None)
        db_session.add(
            PlatformPluginPackageModel(
                plugin_id="sample.notes",
                version="1.1.0",
                publisher="test",
                artifact_digest=digest,
                artifact_registry="registry.example.test",
                artifact_repository="sample/notes",
                oci_manifest_digest=digest,
                security_scan_status="passed",
                revoked=True,
            )
        )
        await db_session.commit()
        assert (await dispatch(visible, active)).is_error and len(calls) == before


async def test_detached_signed_child_can_use_pinned_tool_after_parent_closes(  # noqa: PLR0915
    http,  # noqa: F811
    publisher,  # noqa: F811
    project_turn,
    db_session,
    monkeypatch,
    tmp_path,
):
    import asyncio
    from dataclasses import replace

    from src.infrastructure.agent.subagent.run_registry import SubAgentRunRegistry
    from src.infrastructure.plugins.v2.boundary import (
        clear_process_generation_host_v2,
        current_operation_context_v2,
        install_process_generation_host_v2,
        pin_agent_turn_operation_v2,
    )
    from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
    from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2
    from src.tests.unit.infrastructure.agent.core import (
        test_subagent_registry_authority_v2 as setup,
    )

    client, tokens = http
    headers = {"Authorization": f"Bearer {tokens['owner']}"}
    base = "/api/v1/platform-plugins/v2/optional-business"
    scope = {"tenant_id": "t", "project_id": "p"}

    async def publish(version, word):
        body, _ = publisher[1](
            version, result=word, subagents=[declaration(word, tools=["note.ping"])]
        )
        assert (await client.post(base + "/install", json=body, headers=headers)).is_success
        assert (
            await client.post(base + "/sample.notes/enable", json=scope, headers=headers)
        ).is_success

    await publish("1.0.0", "ping")
    registry = SubAgentRunRegistry()
    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(subagent_run_registry_factory=lambda _config: registry)
    )
    runtime = json.loads(setup._MANIFEST_PATH.read_bytes())
    runtime["modules"] = [
        module
        for module in runtime["modules"]
        if module["module_ref"]
        in {
            "builtin://memstack/runtime/generation-boundary",
            "builtin://memstack/agent/subagent-run-registry",
        }
    ]
    manifest = tmp_path / "runtime.json"
    manifest.write_text(json.dumps(runtime))
    publication = await host.bootstrap(
        profile_path=setup._PROFILE_PATH,
        manifest_paths=(manifest,),
        generation=201,
        version=201,
        nonce="signed-detached",
        profile_projector=lambda document: replace(
            document,
            entries=tuple(
                entry
                for entry in document.entries
                if entry.entry_id
                in {"runtime-generation-boundary", "builtin-subagent-run-registry"}
            ),
        ),
    )
    assert publication.accepted
    install_process_generation_host_v2(host)
    sessions = async_sessionmaker(db_session.bind, expire_on_commit=False)
    react = setup._agent(session_factory=sessions)
    react._session_runner.deps.subagent_run_registry_resolver = (
        lambda: current_operation_context_v2().require("service:agent.subagent-run-registry")
    )
    entered = asyncio.Event()
    release = asyncio.Event()
    observed = []

    def build_processor(process, **_kwargs):
        async def run(**_kwargs):
            entered.set()
            await release.wait()
            value = json.loads(await process._tools[0].execute(op="ping"))
            observed.append((current_operation_context_v2().operation_id, value["op"]))
            yield AgentTextEndEvent(full_text=value["op"])

        return SimpleNamespace(process=run)

    monkeypatch.setattr(SubAgentProcess, "_build_processor", build_processor)
    try:
        async with pin_agent_turn_operation_v2(
            operation_id="parent",
            tenant_id="t",
            project_id="p",
            session_id="c",
            services={OPERATION_IDENTITY_SERVICE_V2: {**scope, "user_id": "owner"}},
        ) as operation:
            catalog = bind_operation_tool_set_catalog_v2(operation)
            capabilities = await bind_project_packages(
                operation, catalog, "first", sessions, trusted_keys=(publisher[0],)
            )
            (agent,) = capabilities.subagents.values()
            selected = ToolSetCatalogV2().resolve(
                agent=None,
                selection_context=None,
                prepared_tool_provider=PreparedToolProviderV2(tools={}),
                operation_catalog=catalog,
            )
            inherited = SubAgentToolSetBindingV2(operation=operation).bind(selected)
            run = registry.create_run(conversation_id="c", subagent_name=agent.name, task="review")
            registry.mark_running("c", run.run_id)
            await react._launch_subagent_session(
                run_id=run.run_id,
                subagent=agent,
                available_subagents=[agent],
                user_message="review",
                conversation_context=[],
                conversation_id="c",
                tenant_id="t",
                project_id="p",
                inherited_tool_set=inherited,
            )
            task = react._subagent_session_tasks[run.run_id]
            await asyncio.wait_for(entered.wait(), timeout=8)
        await publish("1.1.0", "pong")
        release.set()
        await asyncio.wait_for(task, timeout=8)
        assert observed == [(f"detached-subagent:{run.run_id}", "ping")]
        completed = registry.get_run("c", run.run_id)
        assert completed.status.value == "completed"
        assert completed.metadata["signed_subagent_release"] == agent.release_binding()
    finally:
        release.set()
        await react._detached_subagent_task_supervisor.shutdown()
        clear_process_generation_host_v2(host)
        await host.close()
        registry.close()
