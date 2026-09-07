"""V2 Provider/Consumer coverage for invitation services."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.configuration.di_container import DIContainer
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.secondary.persistence.models import (
    InvitationModel,
    Project,
    User,
    UserTenant,
)
from src.infrastructure.plugins.v2 import invitation_services as invitation_subject
from src.infrastructure.plugins.v2.boundary import OPERATION_DB_SESSION_SERVICE_V2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.invitation_services import (
    INVITATION_APPLICATION_MODULE_V2,
    INVITATION_APPLICATION_SERVICE_V2,
    INVITATION_PROVIDER_MODULE_V2,
    InvitationApplicationResolverV2,
    SqlInvitationMembershipWriterV2,
)
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.runtime import (
    ContextV2,
    LoaderV2,
    OperationContextV2,
    RuntimeV2Error,
)
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


async def test_application_resolver_builds_invitation_services_from_operation_db() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=71,
        version=71,
    )
    assert publication.accepted is True
    db = AsyncSession()
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="http-invitations:tenant-a",
                scope=ScopeV2(kind=ScopeKindV2.TENANT, tenant_id="tenant-a"),
            ) as operation,
        ):
            _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
            resolver = operation.require(INVITATION_APPLICATION_SERVICE_V2)
            assert isinstance(resolver, InvitationApplicationResolverV2)

            services = resolver.resolve(operation)

            assert services.invitations._repo._session is db
            assert isinstance(services.memberships, SqlInvitationMembershipWriterV2)
            assert services.memberships.db is db
    finally:
        await db.close()
        await host.close()


def test_provider_and_consumer_are_independent_explicit_profile_entries() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    enabled_modules = tuple(entry.module_ref for entry in document.entries if entry.enabled)

    assert INVITATION_PROVIDER_MODULE_V2 in enabled_modules
    assert INVITATION_APPLICATION_MODULE_V2 in enabled_modules
    assert enabled_modules.index(INVITATION_PROVIDER_MODULE_V2) < enabled_modules.index(
        INVITATION_APPLICATION_MODULE_V2
    )


async def test_application_resolver_rejects_missing_provider_without_fallback() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    disabled = replace(
        document,
        entries=tuple(
            replace(entry, enabled=False)
            if entry.module_ref == INVITATION_PROVIDER_MODULE_V2
            else entry
            for entry in document.entries
        ),
    )
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(
        disabled,
        {manifest.plugin_id: manifest},
        generation=72,
    )

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)

    assert error.value.code == "missing_inject_provider"
    assert "builtin-invitation-services" in str(error.value)


async def test_application_resolver_requires_operation_db_session() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=73,
        version=73,
    )
    assert publication.accepted is True
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="http-invitations:no-db",
                scope=ScopeV2(kind=ScopeKindV2.ROOT),
            ) as operation,
        ):
            resolver = operation.require(INVITATION_APPLICATION_SERVICE_V2)

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
        generation=76,
        version=76,
    )
    assert publication.accepted is True
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="http-invitations:invalid-db",
                scope=ScopeV2(kind=ScopeKindV2.ROOT),
            ) as operation,
        ):
            _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, object())
            resolver = operation.require(INVITATION_APPLICATION_SERVICE_V2)

            with pytest.raises(RuntimeV2Error) as error:
                resolver.resolve(operation)

            assert error.value.code == "invalid_operation_db_session"
    finally:
        await host.close()


async def test_accept_and_membership_write_share_session_and_membership_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
    another_user: User,
) -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=77,
        version=77,
    )
    assert publication.accepted is True
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="http-invitations:accept",
                scope=ScopeV2(kind=ScopeKindV2.ROOT),
            ) as operation,
        ):
            _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, test_db)
            resolver = operation.require(INVITATION_APPLICATION_SERVICE_V2)
            services = resolver.resolve(operation)
            invitation = await services.invitations.create_invitation(
                tenant_id=test_project_db.tenant_id,
                email=another_user.email,
                role="member",
                invited_by=test_user.id,
            )
            monkeypatch.setattr(
                services.invitations,
                "validate_token",
                AsyncMock(return_value=invitation),
            )

            accepted = await services.invitations.accept_invitation(
                invitation.token,
                another_user.id,
            )
            await services.memberships.ensure_membership(
                user_id=another_user.id,
                tenant_id=accepted.tenant_id,
                role=accepted.role,
            )
            await services.memberships.ensure_membership(
                user_id=another_user.id,
                tenant_id=accepted.tenant_id,
                role=accepted.role,
            )
            await test_db.flush()

            stored = await test_db.scalar(
                select(InvitationModel).where(InvitationModel.id == invitation.id)
            )
            membership_count = await test_db.scalar(
                select(func.count())
                .select_from(UserTenant)
                .where(
                    UserTenant.user_id == another_user.id,
                    UserTenant.tenant_id == test_project_db.tenant_id,
                )
            )

            assert stored is not None
            assert stored.status == "accepted"
            assert stored.accepted_by == another_user.id
            assert membership_count == 1
    finally:
        await host.close()


async def test_later_invitation_candidate_failure_keeps_last_good_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_apply = invitation_subject._apply_invitation_provider_v2
    apply_count = 0

    def flaky_apply(context: ContextV2, config: dict[str, object]) -> None:
        nonlocal apply_count
        apply_count += 1
        if apply_count > 1:
            raise RuntimeError("invitation provider unavailable")
        original_apply(context, config)

    monkeypatch.setattr(invitation_subject, "_apply_invitation_provider_v2", flaky_apply)
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    first = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=78,
        version=78,
    )
    assert first.accepted is True
    active = host.manager.current
    assert active is not None

    failed = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=79,
        version=79,
    )

    assert failed.accepted is False
    assert failed.receipt.error_code == "staging_failed"
    assert host.manager.current is active
    assert host.manager.current.descriptor.generation == 78
    await host.close()


def test_static_invitation_accessors_are_absent_after_v2_cutover() -> None:
    assert not hasattr(DIContainer, "invitation_repository")
    assert not hasattr(DIContainer, "invitation_service")
