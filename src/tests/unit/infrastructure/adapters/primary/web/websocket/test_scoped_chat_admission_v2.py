"""Real SQL scope checks before scoped publication and reservation admission."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import delete, update

from src.infrastructure.adapters.primary.web.startup.scoped_profile_runtime_v2 import (
    ScopedProfileRuntimeV2,
)
from src.infrastructure.adapters.primary.web.websocket.message_context import MessageContext
from src.infrastructure.adapters.primary.web.websocket.scoped_chat_admission_v2 import (
    acquire_scoped_chat_turn_v2,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    Conversation,
    Project,
    Tenant,
    User,
    UserProject,
    UserTenant,
)
from src.infrastructure.plugins.v2.agent_turn_requirements_v2 import (
    AGENT_TURN_REQUIRED_SERVICES_V2,
    AGENT_WORKSPACE_REQUIRED_SERVICES_V2,
)
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error

pytestmark = pytest.mark.unit


@pytest.fixture
async def chat_context(db_session):
    db_session.add(User(id="u", email="scoped-chat@test.invalid", hashed_password="unused"))
    await db_session.flush()
    db_session.add(Tenant(id="t", name="Tenant", slug="scoped-chat", owner_id="u"))
    await db_session.flush()
    db_session.add(Project(id="p", tenant_id="t", owner_id="u", name="Project"))
    await db_session.flush()
    db_session.add_all(
        [
            Conversation(id="s", tenant_id="t", project_id="p", user_id="u", title="Session"),
            UserTenant(id="ut", user_id="u", tenant_id="t"),
            UserProject(id="up", user_id="u", project_id="p"),
        ]
    )
    await db_session.commit()
    runtime = MagicMock(spec=ScopedProfileRuntimeV2)
    runtime.prepare_current = AsyncMock(
        return_value=SimpleNamespace(publication=SimpleNamespace(accepted=True))
    )
    runtime.acquire = AsyncMock(return_value=object())
    return MessageContext(
        websocket=MagicMock(),
        user_id="u",
        tenant_id="t",
        session_id="connection",
        db=db_session,
        container=MagicMock(),
        scoped_profile_runtime_v2=runtime,
    )


@pytest.mark.parametrize("workspace", [False, True])
async def test_authorized_session_uses_persisted_scope_and_explicit_roots(chat_context, workspace):
    context = chat_context
    if workspace:
        await context.db.execute(update(Conversation).values(workspace_id="workspace"))
        await context.db.commit()
    result = await acquire_scoped_chat_turn_v2(context, conversation_id="s", project_id="p")
    runtime = context.scoped_profile_runtime_v2
    assert result is runtime.acquire.return_value
    scope = runtime.acquire.call_args.args[0]
    assert scope.session_id == "s"
    assert scope.tenant_id == "t" and scope.project_id == "p"
    runtime.prepare_current.assert_awaited_once_with(
        scope,
        actor_id="u",
        required_services=(
            AGENT_WORKSPACE_REQUIRED_SERVICES_V2 if workspace else AGENT_TURN_REQUIRED_SERVICES_V2
        ),
    )


@pytest.mark.parametrize(
    "denied",
    [
        "user",
        "tenant",
        "project",
        "conversation",
        "tenant_membership",
        "project_membership",
        "project_ancestry",
    ],
)
async def test_denied_scope_never_initializes_or_acquires(chat_context, denied):
    context = chat_context
    conversation_id, project_id = "s", "p"
    if denied == "user":
        context.user_id = "other"
    elif denied == "tenant":
        context.tenant_id = "other"
    elif denied == "project":
        project_id = "other"
    elif denied == "conversation":
        conversation_id = "other"
    elif denied == "tenant_membership":
        await context.db.execute(delete(UserTenant))
    elif denied == "project_membership":
        await context.db.execute(delete(UserProject))
    else:
        context.db.add(Tenant(id="other", name="Other", slug="other", owner_id="u"))
        await context.db.flush()
        await context.db.execute(update(Project).values(tenant_id="other"))
    await context.db.commit()
    with pytest.raises(RuntimeV2Error) as error:
        await acquire_scoped_chat_turn_v2(
            context, conversation_id=conversation_id, project_id=project_id
        )
    assert error.value.code == "CONVERSATION_ACCESS_DENIED"
    context.scoped_profile_runtime_v2.prepare_current.assert_not_awaited()
    context.scoped_profile_runtime_v2.acquire.assert_not_awaited()


async def test_membership_revoked_during_prepare_prevents_acquisition(chat_context):
    context = chat_context
    runtime = context.scoped_profile_runtime_v2

    async def revoke(*args, **kwargs):
        await context.db.execute(delete(UserTenant))
        await context.db.commit()
        return SimpleNamespace(publication=SimpleNamespace(accepted=True))

    runtime.prepare_current.side_effect = revoke
    with pytest.raises(RuntimeV2Error) as error:
        await acquire_scoped_chat_turn_v2(context, conversation_id="s", project_id="p")
    assert error.value.code == "CONVERSATION_ACCESS_DENIED"
    runtime.acquire.assert_not_awaited()


@pytest.mark.parametrize("failure", ["missing", "nack", "receipt"])
async def test_runtime_failures_do_not_fall_back_to_root(chat_context, failure):
    context = chat_context
    runtime = context.scoped_profile_runtime_v2
    if failure == "missing":
        context.scoped_profile_runtime_v2 = None
    elif failure == "nack":
        runtime.prepare_current.return_value.publication.accepted = False
    else:
        runtime.prepare_current.side_effect = RuntimeV2Error("scope_receipt_pending", "pending")
    with pytest.raises(RuntimeV2Error):
        await acquire_scoped_chat_turn_v2(context, conversation_id="s", project_id="p")
    runtime.acquire.assert_not_awaited()


def test_fresh_db_copy_preserves_scoped_manager():
    runtime = MagicMock(spec=ScopedProfileRuntimeV2)
    context = MessageContext(
        websocket=MagicMock(),
        user_id="u",
        tenant_id="t",
        session_id="c",
        db=MagicMock(),
        container=MagicMock(),
        scoped_profile_runtime_v2=runtime,
    )
    fresh = MagicMock()
    copied = context.with_db(fresh)
    assert copied.db is fresh
    assert copied.scoped_profile_runtime_v2 is runtime


async def test_authorized_chat_materializes_real_source_and_admits_production_bundle(
    chat_context, monkeypatch
):
    from fastapi import FastAPI
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2, ServiceRequiredV2
    from src.infrastructure.adapters.primary.web.startup import scoped_profile_runtime_v2 as startup
    from src.infrastructure.adapters.primary.web.startup.plugin_trust_v2 import (
        configure_plugin_trust_v2,
    )
    from src.infrastructure.adapters.secondary.persistence.platform_plugin_desired_bundle_repository_v2 import (
        PlatformPluginDesiredBundleSetRepositoryV2,
    )
    from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
    from src.infrastructure.plugins.v2.composer import compose_profile_v2
    from src.infrastructure.plugins.v2.graph_runtime import (
        GRAPH_RUNTIME_MODULE_V2,
        graph_runtime_definition_v2,
    )
    from src.infrastructure.plugins.v2.layer_composer import compose_profile_sources_v2
    from src.infrastructure.plugins.v2.production_bundle import production_bundle_sources_v2
    from src.infrastructure.plugins.v2.protocol import control_envelope_v2
    from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2
    from src.infrastructure.plugins.v2.scoped_boundary import pin_scoped_agent_turn_operation_v2
    from src.infrastructure.plugins.v2.service_closure import project_service_closure_v2

    context = chat_context
    source = production_bundle_sources_v2()
    root = ScopeV2(kind=ScopeKindV2.ROOT)
    composition = compose_profile_sources_v2(
        desired_set=source.desired_set,
        bundles=(source.bundle,),
        profile_source=source.profile_source,
        scope=root,
    )
    full = compose_profile_v2(
        composition.document, {m.plugin_id: m for m in composition.manifests}, generation=1
    )
    snapshot = project_service_closure_v2(
        full,
        scope=root,
        required_services=(
            ServiceRequiredV2(alias="sandbox", service="service:sandbox.runtime", version="1.0.0"),
        ),
    )
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    assert (await host.apply(snapshot, control_envelope_v2(snapshot, version=1))).accepted
    factory = async_sessionmaker(context.db.bind, expire_on_commit=False)
    async with factory() as db:
        await PlatformPluginDesiredBundleSetRepositoryV2(db).record_desired_set(
            scope=root, desired_set=source.desired_set, expected_revision=None, actor_id="u"
        )
        await db.commit()
    original = startup.scoped_builtin_runtime_definitions_v2

    def definitions(*args, **kwargs):
        # Network-free typed graph provider only; trust, source, coordinator and Loader are real.
        return tuple(
            graph_runtime_definition_v2() if item.module_ref == GRAPH_RUNTIME_MODULE_V2 else item
            for item in original(*args, **kwargs)
        )

    monkeypatch.setattr(startup, "scoped_builtin_runtime_definitions_v2", definitions)
    app = FastAPI()
    app.state.platform_plugin_runtime_v2 = host
    configure_plugin_trust_v2(app, key_files=(), allowed_registries=())
    runtime = startup.initialize_scoped_profile_runtime_v2(
        app, session_factory=factory, redis_client=None
    )
    context.scoped_profile_runtime_v2 = runtime
    try:
        reservation = await acquire_scoped_chat_turn_v2(
            context, conversation_id="s", project_id="p"
        )
        assert reservation.lease.generation is not host.manager.current
        async with pin_scoped_agent_turn_operation_v2(
            reservation,
            operation_id="chat-real-source",
            tenant_id="t",
            project_id="p",
            session_id="s",
        ) as operation:
            assert operation.require("service:tool-set-catalog").contributions()
        assert reservation.lease._released
        async with factory() as db:
            record = await PlatformPluginDesiredBundleSetRepositoryV2(db).current_desired_set(
                reservation.scope
            )
            assert record is not None and record.scope == reservation.scope
    finally:
        await runtime.close()
        await host.close()
