"""V2 Provider/Consumer and behavior coverage for memory share services."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.secondary.persistence.models import (
    Memory,
    MemoryShare,
    Project,
    User,
    UserProject,
)
from src.infrastructure.plugins.v2.boundary import OPERATION_DB_SESSION_SERVICE_V2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.runtime import (
    LoaderV2,
    OperationContextV2,
    RuntimeV2Error,
)
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2
from src.infrastructure.plugins.v2.shares_services import (
    SHARES_APPLICATION_MODULE_V2,
    SHARES_APPLICATION_SERVICE_V2,
    SHARES_PROVIDER_MODULE_V2,
    SharesApplicationResolverV2,
    SharesApplicationServiceV2,
    SharesServiceErrorV2,
    SqlSharesPersistenceV2,
)

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"
_SERVICE_PATH = _ROOT / "src/infrastructure/plugins/v2/shares_services.py"
_NOW = datetime(2026, 8, 26, 8, 0, tzinfo=UTC)


def _service(db: AsyncSession) -> SharesApplicationServiceV2:
    return SharesApplicationServiceV2(persistence=SqlSharesPersistenceV2(_session=db))


async def _add_project(
    db: AsyncSession,
    *,
    project_id: str,
    owner_id: str,
) -> Project:
    project = Project(
        id=project_id,
        tenant_id=f"tenant-{project_id}",
        name=f"Project {project_id}",
        description="Shares V2 test project",
        owner_id=owner_id,
        is_public=False,
    )
    db.add(project)
    await db.flush()
    return project


async def _add_memory(
    db: AsyncSession,
    *,
    memory_id: str,
    project_id: str,
    author_id: str,
) -> Memory:
    memory = Memory(
        id=memory_id,
        project_id=project_id,
        title=f"Memory {memory_id}",
        content="Share service content",
        author_id=author_id,
        content_type="text",
        is_public=False,
    )
    db.add(memory)
    await db.flush()
    return memory


async def _add_share(
    db: AsyncSession,
    *,
    share_id: str,
    memory_id: str,
    shared_by: str,
    token: str,
    permissions: object | None = None,
    expires_at: datetime | None = None,
    created_at: datetime | None = None,
) -> MemoryShare:
    share = MemoryShare(
        id=share_id,
        memory_id=memory_id,
        share_token=token,
        shared_by=shared_by,
        permissions={"view": True} if permissions is None else permissions,
        expires_at=expires_at,
        access_count=0,
        **({"created_at": created_at} if created_at is not None else {}),
    )
    db.add(share)
    await db.flush()
    return share


async def test_application_resolver_builds_shares_service_from_operation_db() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=104,
        version=104,
    )
    assert publication.accepted is True
    db = AsyncSession()
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="http-shares:resolver",
                scope=ScopeV2(kind=ScopeKindV2.ROOT),
            ) as operation,
        ):
            _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
            resolver = operation.require(SHARES_APPLICATION_SERVICE_V2)
            assert isinstance(resolver, SharesApplicationResolverV2)

            services = resolver.resolve(operation)

            assert services.shares.persistence._session is db
    finally:
        await db.close()
        await host.close()


def test_provider_and_consumer_are_independent_explicit_profile_entries() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    enabled_modules = tuple(entry.module_ref for entry in document.entries if entry.enabled)

    assert SHARES_PROVIDER_MODULE_V2 in enabled_modules
    assert SHARES_APPLICATION_MODULE_V2 in enabled_modules
    assert enabled_modules.index(SHARES_PROVIDER_MODULE_V2) < enabled_modules.index(
        SHARES_APPLICATION_MODULE_V2
    )


async def test_application_resolver_rejects_missing_provider_without_fallback() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    disabled = replace(
        document,
        entries=tuple(
            replace(entry, enabled=False)
            if entry.module_ref == SHARES_PROVIDER_MODULE_V2
            else entry
            for entry in document.entries
        ),
    )
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(
        disabled,
        {manifest.plugin_id: manifest},
        generation=105,
    )

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)

    assert error.value.code == "missing_inject_provider"
    assert "builtin-shares-services" in str(error.value)


async def test_application_resolver_requires_operation_db_session() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=106,
        version=106,
    )
    assert publication.accepted is True
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="http-shares:no-db",
                scope=ScopeV2(kind=ScopeKindV2.ROOT),
            ) as operation,
        ):
            resolver = operation.require(SHARES_APPLICATION_SERVICE_V2)

            with pytest.raises(RuntimeV2Error) as error:
                resolver.resolve(operation)

            assert error.value.code == "missing_service"
    finally:
        await host.close()


async def test_application_resolver_rejects_non_async_operation_db_session() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=107,
        version=107,
    )
    assert publication.accepted is True
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="http-shares:invalid-db",
                scope=ScopeV2(kind=ScopeKindV2.ROOT),
            ) as operation,
        ):
            _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, object())
            resolver = operation.require(SHARES_APPLICATION_SERVICE_V2)

            with pytest.raises(RuntimeV2Error) as error:
                resolver.resolve(operation)

            assert error.value.code == "invalid_operation_db_session"
    finally:
        await host.close()


async def test_author_can_create_user_target_and_duplicate_is_rejected(
    test_db: AsyncSession,
    test_memory_with_project: Memory,
    test_user: User,
    another_user: User,
) -> None:
    shares = _service(test_db)

    created = await shares.create_share(
        memory_id=test_memory_with_project.id,
        user_id=test_user.id,
        share_data={
            "target_type": "user",
            "target_id": another_user.id,
            "permission_level": "edit",
        },
        now=_NOW,
    )

    assert created["memory_id"] == test_memory_with_project.id
    assert created["shared_with_user_id"] == another_user.id
    assert created["shared_with_project_id"] is None
    assert created["permissions"] == {"view": True, "edit": True}
    assert isinstance(created["share_token"], str)
    assert len(created["share_token"]) >= 32

    with pytest.raises(SharesServiceErrorV2):
        await shares.create_share(
            memory_id=test_memory_with_project.id,
            user_id=test_user.id,
            share_data={
                "target_type": "user",
                "target_id": another_user.id,
                "permission_level": "view",
            },
            now=_NOW,
        )

    count = await test_db.scalar(
        select(func.count())
        .select_from(MemoryShare)
        .where(
            MemoryShare.memory_id == test_memory_with_project.id,
            MemoryShare.shared_with_user_id == another_user.id,
        )
    )
    assert count == 1


async def test_create_rejects_non_author_and_unknown_or_unauthorized_targets(
    test_db: AsyncSession,
    test_memory_with_project: Memory,
    test_user: User,
    another_user: User,
) -> None:
    shares = _service(test_db)

    with pytest.raises(SharesServiceErrorV2):
        await shares.create_share(
            memory_id=test_memory_with_project.id,
            user_id=another_user.id,
            share_data={"permissions": {"view": True}},
            now=_NOW,
        )

    for target_type, target_id in (
        ("user", "missing-share-user"),
        ("project", "missing-share-project"),
    ):
        with pytest.raises(SharesServiceErrorV2):
            await shares.create_share(
                memory_id=test_memory_with_project.id,
                user_id=test_user.id,
                share_data={
                    "target_type": target_type,
                    "target_id": target_id,
                    "permission_level": "view",
                },
                now=_NOW,
            )

    target = await _add_project(
        test_db,
        project_id="shares-target-denied",
        owner_id=another_user.id,
    )
    with pytest.raises(SharesServiceErrorV2):
        await shares.create_share(
            memory_id=test_memory_with_project.id,
            user_id=test_user.id,
            share_data={
                "target_type": "project",
                "target_id": target.id,
                "permission_level": "view",
            },
            now=_NOW,
        )


@pytest.mark.parametrize("role", ("admin", "owner"))
async def test_project_admin_or_owner_can_be_selected_as_share_target(
    role: str,
    test_db: AsyncSession,
    test_memory_with_project: Memory,
    test_user: User,
    another_user: User,
) -> None:
    target = await _add_project(
        test_db,
        project_id=f"shares-target-{role}",
        owner_id=another_user.id,
    )
    test_db.add(
        UserProject(
            id=str(uuid4()),
            user_id=test_user.id,
            project_id=target.id,
            role=role,
        )
    )
    await test_db.flush()

    created = await _service(test_db).create_share(
        memory_id=test_memory_with_project.id,
        user_id=test_user.id,
        share_data={
            "target_type": "project",
            "target_id": target.id,
            "permission_level": "view",
        },
        now=_NOW,
    )

    assert created["shared_with_project_id"] == target.id
    assert created["permissions"] == {"view": True, "edit": False}


async def test_create_parses_absolute_and_relative_expiration_and_rejects_invalid_value(
    test_db: AsyncSession,
    test_memory_with_project: Memory,
    test_user: User,
) -> None:
    shares = _service(test_db)
    absolute = _NOW + timedelta(hours=6)

    absolute_share = await shares.create_share(
        memory_id=test_memory_with_project.id,
        user_id=test_user.id,
        share_data={"permissions": {"view": True}, "expires_at": absolute.isoformat()},
        now=_NOW,
    )
    relative_share = await shares.create_share(
        memory_id=test_memory_with_project.id,
        user_id=test_user.id,
        share_data={"permissions": {"view": True}, "expires_in_days": 3},
        now=_NOW,
    )

    assert absolute_share["expires_at"] == absolute.isoformat()
    assert relative_share["expires_at"] == (_NOW + timedelta(days=3)).isoformat()

    with pytest.raises(SharesServiceErrorV2):
        await shares.create_share(
            memory_id=test_memory_with_project.id,
            user_id=test_user.id,
            share_data={"permissions": {"view": True}, "expires_at": "not-a-date"},
            now=_NOW,
        )


async def test_list_is_newest_first_for_author(
    test_db: AsyncSession,
    test_memory_with_project: Memory,
    test_user: User,
) -> None:
    await _add_share(
        test_db,
        share_id="shares-oldest",
        memory_id=test_memory_with_project.id,
        shared_by=test_user.id,
        token="shares-oldest-token",
        created_at=_NOW - timedelta(minutes=1),
    )
    await _add_share(
        test_db,
        share_id="shares-newest",
        memory_id=test_memory_with_project.id,
        shared_by=test_user.id,
        token="shares-newest-token",
        created_at=_NOW,
    )

    result = await _service(test_db).list_shares(
        memory_id=test_memory_with_project.id,
        user_id=test_user.id,
    )

    assert [item["id"] for item in result["shares"]] == ["shares-newest", "shares-oldest"]


@pytest.mark.parametrize("role", ("admin", "owner"))
async def test_project_admin_or_owner_can_list_and_delete_share(
    role: str,
    test_db: AsyncSession,
    test_user: User,
    another_user: User,
) -> None:
    project = await _add_project(
        test_db,
        project_id=f"shares-admin-project-{role}",
        owner_id=another_user.id,
    )
    memory = await _add_memory(
        test_db,
        memory_id=f"shares-admin-memory-{role}",
        project_id=project.id,
        author_id=another_user.id,
    )
    test_db.add(
        UserProject(
            id=str(uuid4()),
            user_id=test_user.id,
            project_id=project.id,
            role=role,
        )
    )
    share = await _add_share(
        test_db,
        share_id=f"shares-admin-share-{role}",
        memory_id=memory.id,
        shared_by=another_user.id,
        token=f"shares-admin-token-{role}",
    )
    shares = _service(test_db)

    listed = await shares.list_shares(memory_id=memory.id, user_id=test_user.id)
    deleted = await shares.delete_share(
        memory_id=memory.id,
        share_id=share.id,
        user_id=test_user.id,
    )

    assert [item["id"] for item in listed["shares"]] == [share.id]
    assert deleted is None
    assert await test_db.get(MemoryShare, share.id) is None


async def test_delete_rejects_non_owner_and_memory_mismatch(
    test_db: AsyncSession,
    test_memory_with_project: Memory,
    test_memory_share: MemoryShare,
    test_user: User,
    another_user: User,
) -> None:
    shares = _service(test_db)

    with pytest.raises(SharesServiceErrorV2):
        await shares.delete_share(
            memory_id=test_memory_with_project.id,
            share_id=test_memory_share.id,
            user_id=another_user.id,
        )

    other_memory = await _add_memory(
        test_db,
        memory_id="shares-delete-other-memory",
        project_id=test_memory_with_project.project_id,
        author_id=test_user.id,
    )
    with pytest.raises(SharesServiceErrorV2):
        await shares.delete_share(
            memory_id=other_memory.id,
            share_id=test_memory_share.id,
            user_id=test_user.id,
        )

    assert await test_db.get(MemoryShare, test_memory_share.id) is not None


async def test_public_read_requires_view_and_increments_access_count(
    test_db: AsyncSession,
    test_memory_with_project: Memory,
    test_memory_share: MemoryShare,
) -> None:
    result = await _service(test_db).get_shared_memory(
        share_token=test_memory_share.share_token,
        now=_NOW,
    )

    await test_db.refresh(test_memory_share)
    assert result.payload["memory"]["id"] == test_memory_with_project.id
    assert result.payload["memory"]["content"] == test_memory_with_project.content
    assert result.payload["share"]["permissions"] == {"view": True}
    assert test_memory_share.access_count == 1


@pytest.mark.parametrize("permissions", ({"view": False, "edit": True}, {}))
async def test_public_read_fails_closed_without_explicit_view_permission(
    permissions: dict[str, bool],
    test_db: AsyncSession,
    test_memory_share: MemoryShare,
) -> None:
    test_memory_share.permissions = permissions
    await test_db.flush()

    with pytest.raises(SharesServiceErrorV2):
        await _service(test_db).get_shared_memory(
            share_token=test_memory_share.share_token,
            now=_NOW,
        )

    await test_db.refresh(test_memory_share)
    assert test_memory_share.access_count == 0


async def test_public_read_rejects_expired_missing_and_orphan_shares(
    test_db: AsyncSession,
    test_memory_share: MemoryShare,
    test_user: User,
) -> None:
    shares = _service(test_db)
    test_memory_share.expires_at = _NOW - timedelta(seconds=1)
    await test_db.flush()

    with pytest.raises(SharesServiceErrorV2):
        await shares.get_shared_memory(share_token=test_memory_share.share_token, now=_NOW)
    with pytest.raises(SharesServiceErrorV2):
        await shares.get_shared_memory(share_token="missing-share-token", now=_NOW)

    orphan = await _add_share(
        test_db,
        share_id="shares-orphan",
        memory_id="shares-deleted-memory",
        shared_by=test_user.id,
        token="shares-orphan-token",
    )
    with pytest.raises(SharesServiceErrorV2):
        await shares.get_shared_memory(share_token=orphan.share_token, now=_NOW)

    await test_db.refresh(orphan)
    assert orphan.access_count == 0


async def test_mutations_flush_but_leave_commit_to_http_transaction_boundary(
    test_db: AsyncSession,
    test_memory_with_project: Memory,
    test_user: User,
) -> None:
    created = await _service(test_db).create_share(
        memory_id=test_memory_with_project.id,
        user_id=test_user.id,
        share_data={"permissions": {"view": True}},
        now=_NOW,
    )
    assert await test_db.get(MemoryShare, created["id"]) is not None

    await test_db.rollback()

    assert await test_db.get(MemoryShare, created["id"]) is None


def test_delete_service_has_no_http_user_agent_compatibility_branch() -> None:
    source = _SERVICE_PATH.read_text(encoding="utf-8")

    assert "user-agent" not in source
    assert "testclient" not in source
    assert "python-requests" not in source
    assert "fastapi" not in source
    assert "Response" not in source
