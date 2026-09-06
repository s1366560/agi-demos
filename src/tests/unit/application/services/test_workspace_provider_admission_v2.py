"""Provider authorization uses real SQL membership before scoped preparation."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import delete

from src.application.services.workspace_provider_admission_v2 import WorkspaceProviderAdmissionV2
from src.infrastructure.adapters.primary.web.startup.scoped_profile_runtime_v2 import (
    ScopedProfileRuntimeV2,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    Project,
    Tenant,
    User,
    UserProject,
    UserTenant,
)
from src.infrastructure.plugins.v2.agent_turn_requirements_v2 import (
    AGENT_WORKSPACE_REQUIRED_SERVICES_V2,
)
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.workspace_core.agent_runtime_provider import ProviderWorkspaceScope
from src.infrastructure.workspace_core.client import WorkspaceCoreClient, WorkspaceCoreProfile

pytestmark = pytest.mark.unit


@pytest.fixture
async def admission_case(db_session):
    db_session.add(User(id="u", email="provider-admission@test.invalid", hashed_password="unused"))
    await db_session.flush()
    db_session.add(Tenant(id="t", name="Tenant", slug="provider-admission", owner_id="u"))
    await db_session.flush()
    db_session.add(Project(id="p", tenant_id="t", owner_id="u", name="Project"))
    await db_session.flush()
    db_session.add_all(
        [
            UserTenant(id="ut", user_id="u", tenant_id="t"),
            UserProject(id="up", user_id="u", project_id="p"),
        ]
    )
    await db_session.commit()
    scope = ProviderWorkspaceScope(
        tenant_id="t",
        project_id="p",
        workspace_id="w",
        user_id="u",
        conversation_id="s",
        task_id=None,
        plan_id=None,
        plan_node_id=None,
    )
    client = MagicMock(spec=WorkspaceCoreClient)
    client.has_workspace_access = AsyncMock(return_value=True)
    client.read_workspace_profile = AsyncMock(
        return_value=WorkspaceCoreProfile(
            id="w",
            tenant_id="t",
            project_id="p",
            name="Workspace",
            created_by="u",
            is_archived=False,
        )
    )
    runtime = MagicMock(spec=ScopedProfileRuntimeV2)
    runtime.prepare_current = AsyncMock(
        return_value=SimpleNamespace(publication=SimpleNamespace(accepted=True))
    )
    runtime.acquire = AsyncMock(return_value=object())
    admission = WorkspaceProviderAdmissionV2(client, lambda: runtime)
    return admission, db_session, scope, client, runtime


async def test_membership_and_workspace_profile_allow_explicit_session_roots(admission_case):
    admission, db, scope, client, runtime = admission_case
    result = await admission.acquire(db, scope)
    assert result is runtime.acquire.return_value
    bound_scope = runtime.acquire.call_args.args[0]
    assert (bound_scope.tenant_id, bound_scope.project_id, bound_scope.session_id) == (
        "t",
        "p",
        "s",
    )
    runtime.prepare_current.assert_awaited_once_with(
        bound_scope,
        actor_id="u",
        required_services=AGENT_WORKSPACE_REQUIRED_SERVICES_V2,
    )
    assert client.has_workspace_access.await_count == 2
    assert client.read_workspace_profile.await_count == 2
    assert client.read_workspace_profile.call_args.kwargs["is_superuser"] is False


@pytest.mark.parametrize("field", ["tenant_id", "project_id", "user_id"])
async def test_forged_local_scope_never_calls_core_or_prepares(admission_case, field):
    admission, db, scope, client, runtime = admission_case
    with pytest.raises(RuntimeV2Error, match="permission|access"):
        await admission.acquire(db, replace(scope, **{field: "other"}))
    client.has_workspace_access.assert_not_awaited()
    runtime.prepare_current.assert_not_awaited()
    runtime.acquire.assert_not_awaited()


@pytest.mark.parametrize("model", [UserTenant, UserProject])
async def test_missing_membership_never_prepares(admission_case, model):
    admission, db, scope, client, runtime = admission_case
    await db.execute(delete(model))
    await db.commit()
    with pytest.raises(RuntimeV2Error) as error:
        await admission.acquire(db, scope)
    assert error.value.code == "WORKSPACE_ACCESS_DENIED"
    client.has_workspace_access.assert_not_awaited()
    runtime.prepare_current.assert_not_awaited()


@pytest.mark.parametrize("failure", ["membership", "id", "tenant_id", "project_id", "unavailable"])
async def test_core_denial_mismatch_or_failure_never_prepares(admission_case, failure):
    admission, db, scope, client, runtime = admission_case
    if failure == "membership":
        client.has_workspace_access.return_value = False
    elif failure == "unavailable":
        client.has_workspace_access.side_effect = TimeoutError("unavailable")
    else:
        profile = client.read_workspace_profile.return_value
        client.read_workspace_profile.return_value = profile.model_copy(update={failure: "other"})
    with pytest.raises((RuntimeV2Error, TimeoutError)):
        await admission.acquire(db, scope)
    runtime.prepare_current.assert_not_awaited()
    runtime.acquire.assert_not_awaited()


@pytest.mark.parametrize("authority", ["local", "core"])
async def test_revocation_during_prepare_prevents_acquire(admission_case, authority):
    admission, db, scope, client, runtime = admission_case

    async def revoke(*args, **kwargs):
        if authority == "local":
            await db.execute(delete(UserTenant))
            await db.commit()
        else:
            client.has_workspace_access.return_value = False
        return SimpleNamespace(publication=SimpleNamespace(accepted=True))

    runtime.prepare_current.side_effect = revoke
    with pytest.raises(RuntimeV2Error) as error:
        await admission.acquire(db, scope)
    assert error.value.code == "WORKSPACE_ACCESS_DENIED"
    runtime.acquire.assert_not_awaited()


@pytest.mark.parametrize("failure", ["missing", "nack", "receipt"])
async def test_runtime_failure_never_falls_back(admission_case, failure):
    admission, db, scope, client, runtime = admission_case
    if failure == "missing":
        admission = WorkspaceProviderAdmissionV2(client, lambda: None)
    elif failure == "nack":
        runtime.prepare_current.return_value.publication.accepted = False
    else:
        runtime.acquire.side_effect = RuntimeV2Error("receipt_missing", "Receipt unavailable")
    with pytest.raises(RuntimeV2Error):
        await admission.acquire(db, scope)
    if failure != "receipt":
        runtime.acquire.assert_not_awaited()
