"""Existing-session consumers cannot acquire a lease before persisted authorization."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import delete, update

from src.infrastructure.adapters.primary.web.startup.scoped_profile_runtime_v2 import (
    ScopedProfileRuntimeV2,
)
from src.infrastructure.adapters.primary.web.websocket.scoped_session_admission_v2 import (
    acquire_existing_scoped_session_v2,
    authorize_existing_scoped_session_v2,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    Conversation,
    Project,
    Tenant,
    User,
    UserProject,
    UserTenant,
)
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error

pytestmark = pytest.mark.unit


@pytest.fixture
async def existing_session(db_session):
    db_session.add(User(id="u", email="existing-session@test.invalid", hashed_password="unused"))
    await db_session.flush()
    db_session.add_all(
        [
            Tenant(id="t", name="Tenant", slug="existing-session", owner_id="u"),
            Tenant(id="other", name="Other", slug="existing-other", owner_id="u"),
        ]
    )
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
    runtime.acquire = AsyncMock(return_value=object())
    runtime.prepare_current = AsyncMock()
    return SimpleNamespace(
        user_id="u", tenant_id="t", db=db_session, scoped_profile_runtime_v2=runtime
    )


async def test_existing_session_acquires_without_republishing(existing_session):
    context = existing_session
    result = await acquire_existing_scoped_session_v2(context, conversation_id="s", project_id="p")
    runtime = context.scoped_profile_runtime_v2
    assert result is runtime.acquire.return_value
    scope = runtime.acquire.call_args.args[0]
    assert (scope.tenant_id, scope.project_id, scope.session_id) == ("t", "p", "s")
    runtime.prepare_current.assert_not_awaited()
    await context.db.execute(delete(UserTenant))
    await context.db.commit()
    with pytest.raises(RuntimeV2Error) as error:
        await authorize_existing_scoped_session_v2(context, conversation_id="s", project_id="p")
    assert error.value.code == "CONVERSATION_ACCESS_DENIED"


@pytest.mark.parametrize(
    "denied",
    [
        "owner",
        "tenant",
        "conversation",
        "project",
        "ancestry",
        "tenant_member",
        "project_member",
    ],
)
async def test_denied_scope_never_acquires(existing_session, denied):
    context = existing_session
    conversation_id, project_id = "s", "p"
    if denied == "owner":
        context.user_id = "other"
    elif denied == "tenant":
        context.tenant_id = "other"
    elif denied == "conversation":
        conversation_id = "other"
    elif denied == "project":
        project_id = "other"
    elif denied == "ancestry":
        await context.db.execute(update(Project).values(tenant_id="other"))
    elif denied == "tenant_member":
        await context.db.execute(delete(UserTenant))
    else:
        await context.db.execute(delete(UserProject))
    await context.db.commit()
    with pytest.raises(RuntimeV2Error) as error:
        await acquire_existing_scoped_session_v2(
            context, conversation_id=conversation_id, project_id=project_id
        )
    assert error.value.code == "CONVERSATION_ACCESS_DENIED"
    context.scoped_profile_runtime_v2.acquire.assert_not_awaited()
    context.scoped_profile_runtime_v2.prepare_current.assert_not_awaited()


@pytest.mark.parametrize("missing", [True, False])
async def test_runtime_unavailable_never_prepares_or_falls_back(existing_session, missing):
    context = existing_session
    runtime = context.scoped_profile_runtime_v2
    if missing:
        context.scoped_profile_runtime_v2 = None
    else:
        runtime.acquire.side_effect = RuntimeV2Error("scope_not_admitted", "No durable receipt")
    with pytest.raises(RuntimeV2Error):
        await acquire_existing_scoped_session_v2(context, conversation_id="s", project_id="p")
    runtime.prepare_current.assert_not_awaited()


@pytest.mark.parametrize(
    "change",
    [None, "user_id", "tenant_id", "project_id", "conversation_id", "status", "request_id"],
)
async def test_assigned_hitl_recipient_requires_exact_persisted_request(existing_session, change):
    from datetime import UTC, datetime, timedelta

    from src.infrastructure.adapters.secondary.persistence.models import HITLRequest

    context = existing_session
    # u is a member and the designated recipient; the conversation belongs to another user.
    context.db.add(User(id="owner", email="hitl-owner@test.invalid", hashed_password="unused"))
    await context.db.flush()
    await context.db.execute(update(Conversation).values(user_id="owner"))
    request = HITLRequest(
        id="h",
        request_type="decision",
        conversation_id="s",
        tenant_id="t",
        project_id="p",
        user_id="u",
        question="Proceed?",
        status="answered",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    context.db.add(request)
    await context.db.commit()
    if change not in (None, "request_id"):
        setattr(request, change, "cancelled" if change == "status" else "other")
        # Foreign scope checks do not depend on FK enforcement in the SQLite fixture.
        await context.db.commit()
    if change is None:
        result = await acquire_existing_scoped_session_v2(
            context, conversation_id="s", project_id="p", hitl_request_id="h"
        )
        assert result is context.scoped_profile_runtime_v2.acquire.return_value
        with pytest.raises(RuntimeV2Error):
            await authorize_existing_scoped_session_v2(context, conversation_id="s", project_id="p")
    else:
        with pytest.raises(RuntimeV2Error) as error:
            await acquire_existing_scoped_session_v2(
                context,
                conversation_id="s",
                project_id="p",
                hitl_request_id="missing" if change == "request_id" else "h",
            )
        assert error.value.code == "CONVERSATION_ACCESS_DENIED"
        context.scoped_profile_runtime_v2.acquire.assert_not_awaited()
