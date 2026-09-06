"""Publication scope authorization against real persisted resource identities."""

import pytest

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.primary.web.dependencies.plugin_scope_auth_v2 import (
    resolve_plugin_publication_scope_v2,
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
async def resources(db_session):
    owner = User(id="scope-owner", email="scope-owner@example.com", hashed_password="unused")
    admin = User(
        id="scope-super",
        email="scope-super@example.com",
        hashed_password="unused",
        is_superuser=True,
    )
    db_session.add_all([owner, admin])
    await db_session.flush()
    db_session.add_all(
        [Tenant(id=i, name=i, slug=i, owner_id=owner.id) for i in ("scope-a", "scope-b")]
    )
    await db_session.flush()
    db_session.add(
        Project(id="scope-p", tenant_id="scope-a", owner_id=owner.id, name="Scope project")
    )
    await db_session.flush()
    db_session.add(
        Conversation(
            id="scope-c",
            tenant_id="scope-a",
            project_id="scope-p",
            user_id=owner.id,
            title="Scope conversation",
        )
    )
    await db_session.commit()
    return owner, admin


def scope(kind, tenant="scope-a", project="scope-p", session="scope-c"):
    kind = ScopeKindV2(kind)
    return ScopeV2(
        kind=kind,
        tenant_id=tenant if kind is not ScopeKindV2.ROOT else None,
        project_id=project if kind in (ScopeKindV2.PROJECT, ScopeKindV2.SESSION) else None,
        session_id=session if kind is ScopeKindV2.SESSION else None,
    )


@pytest.mark.parametrize("kind", ["tenant", "project"])
@pytest.mark.parametrize("role", ["owner", "admin", "member", "viewer"])
async def test_scoped_management_uses_exact_membership_roles(db_session, resources, kind, role):
    user, _admin = resources
    if kind == "project":
        db_session.add(
            UserTenant(
                id="project-tenant-member", user_id=user.id, tenant_id="scope-a", role="member"
            )
        )
    cls = UserTenant if kind == "tenant" else UserProject
    fields = {"tenant_id": "scope-a"} if kind == "tenant" else {"project_id": "scope-p"}
    db_session.add(cls(id="scope-membership", user_id=user.id, role=role, **fields))
    await db_session.commit()
    requested = scope(kind)
    if role in ("owner", "admin"):
        assert (
            await resolve_plugin_publication_scope_v2(
                db_session, current_user=user, requested_scope=requested
            )
            == requested
        )
    else:
        with pytest.raises(RuntimeV2Error, match="write is forbidden"):
            await resolve_plugin_publication_scope_v2(
                db_session, current_user=user, requested_scope=requested
            )


@pytest.mark.parametrize(
    "requested",
    [
        scope("tenant", tenant="missing"),
        scope("project", tenant="scope-b"),
        scope("project", project="missing"),
        scope("session", session="missing"),
    ],
)
async def test_superuser_cannot_invent_or_mismatch_resource_ancestry(
    db_session, resources, requested
):
    _user, admin = resources
    with pytest.raises(RuntimeV2Error, match="resource is unavailable"):
        await resolve_plugin_publication_scope_v2(
            db_session, current_user=admin, requested_scope=requested
        )


async def test_session_owner_and_project_manager_are_distinct_authorities(db_session, resources):
    owner, admin = resources
    db_session.add_all(
        [
            UserTenant(id="session-tenant", user_id=owner.id, tenant_id="scope-a", role="member"),
            UserProject(id="session-project", user_id=owner.id, project_id="scope-p", role="admin"),
        ]
    )
    await db_session.commit()
    requested = scope("session")
    assert (
        await resolve_plugin_publication_scope_v2(
            db_session, current_user=owner, requested_scope=requested
        )
        == requested
    )
    db_session.add(
        UserTenant(id="scope-admin-tenant", user_id=admin.id, tenant_id="scope-a", role="member")
    )
    db_session.add(
        UserProject(
            id="scope-admin-membership", user_id=admin.id, project_id="scope-p", role="admin"
        )
    )
    await db_session.commit()
    with pytest.raises(RuntimeV2Error, match="write is forbidden"):
        await resolve_plugin_publication_scope_v2(
            db_session, current_user=admin, requested_scope=requested
        )
    conversation = await db_session.get(Conversation, "scope-c")
    conversation.tenant_id = "scope-b"
    await db_session.commit()
    with pytest.raises(RuntimeV2Error, match="resource is unavailable"):
        await resolve_plugin_publication_scope_v2(
            db_session, current_user=owner, requested_scope=requested
        )


async def test_admin_bypass_is_limited_to_existing_root_and_tenant_semantics(db_session, resources):
    owner, admin = resources
    for kind in ("root", "tenant"):
        requested = scope(kind)
        assert (
            await resolve_plugin_publication_scope_v2(
                db_session, current_user=admin, requested_scope=requested
            )
            == requested
        )
    for user, requested in ((owner, scope("root")), (admin, scope("project"))):
        with pytest.raises(RuntimeV2Error, match="write is forbidden"):
            await resolve_plugin_publication_scope_v2(
                db_session, current_user=user, requested_scope=requested
            )


@pytest.mark.parametrize("kind", ["project", "session"])
@pytest.mark.parametrize("revoked", ["tenant", "project"])
async def test_membership_revocation_removes_publication_write_authority(
    db_session, resources, kind, revoked
):
    owner, _admin = resources
    tenant = UserTenant(id="revoked-tenant", user_id=owner.id, tenant_id="scope-a", role="member")
    project = UserProject(
        id="revoked-project", user_id=owner.id, project_id="scope-p", role="admin"
    )
    db_session.add_all([tenant, project])
    await db_session.commit()
    requested = scope(kind)
    assert (
        await resolve_plugin_publication_scope_v2(
            db_session, current_user=owner, requested_scope=requested
        )
        == requested
    )
    await db_session.delete(tenant if revoked == "tenant" else project)
    await db_session.commit()
    with pytest.raises(RuntimeV2Error, match="write is forbidden"):
        await resolve_plugin_publication_scope_v2(
            db_session, current_user=owner, requested_scope=requested
        )


async def test_conversation_owner_with_member_role_cannot_publish_plugins(db_session, resources):
    owner, _admin = resources
    db_session.add_all(
        [
            UserTenant(id="member-tenant", user_id=owner.id, tenant_id="scope-a", role="member"),
            UserProject(id="member-project", user_id=owner.id, project_id="scope-p", role="member"),
        ]
    )
    await db_session.commit()
    with pytest.raises(RuntimeV2Error, match="write is forbidden"):
        await resolve_plugin_publication_scope_v2(
            db_session, current_user=owner, requested_scope=scope("session")
        )
