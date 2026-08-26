"""Generation-owned Artifact HTTP application composition coverage."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, Mock

import pytest

from src.application.services.artifact_content_authority_service import (
    ArtifactContentSaveOutcome,
)
from src.application.services.artifact_content_contract import ArtifactContentSaveReceipt
from src.application.services.artifact_service import ArtifactService
from src.domain.ports.repositories.artifact_content_authority_repository import (
    ArtifactContentScope,
)
from src.infrastructure.plugins.v2.artifact_content_services import (
    ArtifactContentApplicationServicesV2,
)
from src.infrastructure.plugins.v2.artifact_http_services import (
    ARTIFACT_HTTP_APPLICATION_MODULE_V2,
    ARTIFACT_HTTP_APPLICATION_SERVICE_V2,
    ARTIFACT_HTTP_PROVIDER_MODULE_V2,
    ARTIFACT_HTTP_PROVIDER_SERVICE_V2,
    ArtifactHttpApplicationResolverV2,
    ArtifactHttpPersistenceServicesV2,
    ArtifactProjectAccessDeniedV2,
    ArtifactProjectAccessProtocolV2,
    ArtifactRequestTransactionProtocolV2,
)
from src.infrastructure.plugins.v2.artifact_lifecycle_services import (
    ArtifactLifecycleApplicationServiceV2,
)
from src.infrastructure.plugins.v2.composer import load_profile_document_v2
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.runtime import OperationContextV2

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


def _operation(identity: dict[str, object]) -> OperationContextV2:
    operation = SimpleNamespace(require=Mock(return_value=identity))
    return cast(OperationContextV2, operation)


def _resolver(
    *,
    access: ArtifactProjectAccessProtocolV2,
    transaction: ArtifactRequestTransactionProtocolV2,
    content: object,
    reconciler: object,
) -> ArtifactHttpApplicationResolverV2:
    lifecycle = cast(ArtifactService, SimpleNamespace())
    provider = SimpleNamespace(
        build=Mock(
            return_value=ArtifactHttpPersistenceServicesV2(
                access=access,
                transaction=transaction,
            )
        )
    )
    content_resolver = SimpleNamespace(
        resolve=Mock(
            return_value=ArtifactContentApplicationServicesV2(
                content=content,
                reconciler=reconciler,
            )
        )
    )
    return ArtifactHttpApplicationResolverV2(
        provider=provider,
        lifecycle=ArtifactLifecycleApplicationServiceV2(artifact=lifecycle),
        content=content_resolver,
    )


async def test_application_resolver_owns_identity_access_and_transaction() -> None:
    access = cast(
        ArtifactProjectAccessProtocolV2,
        SimpleNamespace(require_project_access=AsyncMock()),
    )
    transaction = cast(
        ArtifactRequestTransactionProtocolV2,
        SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock()),
    )
    content = SimpleNamespace(resolve_scope=AsyncMock())
    reconciler = SimpleNamespace(reconcile=AsyncMock())
    resolver = _resolver(
        access=access,
        transaction=transaction,
        content=content,
        reconciler=reconciler,
    )
    operation = _operation(
        {
            "tenant_id": None,
            "user_id": "user-a",
            "is_superuser": False,
        }
    )

    services = resolver.resolve(operation)
    await services.require_project_access("project-a")
    await services.commit()
    await services.rollback()

    access.require_project_access.assert_awaited_once_with(
        project_id="project-a",
        user_id="user-a",
        is_superuser=False,
    )
    transaction.commit.assert_awaited_once_with()
    transaction.rollback.assert_awaited_once_with()
    assert services.content is content
    assert services.reconciler is reconciler


async def test_content_scope_is_authorized_by_the_profile_selected_access_provider() -> None:
    access = cast(
        ArtifactProjectAccessProtocolV2,
        SimpleNamespace(
            require_project_access=AsyncMock(side_effect=ArtifactProjectAccessDeniedV2)
        ),
    )
    transaction = cast(
        ArtifactRequestTransactionProtocolV2,
        SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock()),
    )
    scope = ArtifactContentScope(
        artifact_id="artifact-a",
        tenant_id="tenant-a",
        project_id="project-a",
        conversation_id=None,
    )
    content = SimpleNamespace(resolve_scope=AsyncMock(return_value=scope))
    services = _resolver(
        access=access,
        transaction=transaction,
        content=content,
        reconciler=SimpleNamespace(reconcile=AsyncMock()),
    ).resolve(
        _operation(
            {
                "tenant_id": None,
                "user_id": "user-a",
                "is_superuser": False,
            }
        )
    )

    with pytest.raises(ArtifactProjectAccessDeniedV2):
        await services.resolve_content_scope("artifact-a")

    content.resolve_scope.assert_awaited_once_with("artifact-a")
    access.require_project_access.assert_awaited_once()


async def test_failed_content_commit_rolls_back_and_reconciles_the_provisional_object() -> None:
    commit_error = RuntimeError("commit failed")
    transaction = cast(
        ArtifactRequestTransactionProtocolV2,
        SimpleNamespace(
            commit=AsyncMock(side_effect=commit_error),
            rollback=AsyncMock(),
        ),
    )
    reconciler = SimpleNamespace(reconcile=AsyncMock())
    services = _resolver(
        access=cast(
            ArtifactProjectAccessProtocolV2,
            SimpleNamespace(require_project_access=AsyncMock()),
        ),
        transaction=transaction,
        content=SimpleNamespace(resolve_scope=AsyncMock()),
        reconciler=reconciler,
    ).resolve(
        _operation(
            {
                "tenant_id": None,
                "user_id": "user-a",
                "is_superuser": False,
            }
        )
    )
    outcome = ArtifactContentSaveOutcome(
        scope=ArtifactContentScope(
            artifact_id="artifact-a",
            tenant_id="tenant-a",
            project_id="project-a",
            conversation_id=None,
        ),
        receipt=ArtifactContentSaveReceipt(
            artifact_id="artifact-a",
            revision=2,
            content_hash=f"sha256:{'a' * 64}",
            duplicate=False,
        ),
        uploaded_object_key="artifacts/tenant-a/project-a/revision-2",
        idempotency_key="request-a",
        request_hash=f"sha256:{'b' * 64}",
    )

    with pytest.raises(RuntimeError, match="commit failed"):
        await services.commit_content_outcome(outcome)

    transaction.rollback.assert_awaited_once_with()
    reconciler.reconcile.assert_awaited_once_with(outcome)


def test_profile_and_manifest_declare_the_artifact_http_provider_consumer_seam() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    entries = {entry.entry_id: entry for entry in document.entries}
    provider_entry = entries["builtin-artifact-http-provider"]
    application_entry = entries["builtin-artifact-http-services"]

    assert provider_entry.module_ref == ARTIFACT_HTTP_PROVIDER_MODULE_V2
    assert application_entry.module_ref == ARTIFACT_HTTP_APPLICATION_MODULE_V2
    assert application_entry.inject == {
        "provider": ARTIFACT_HTTP_PROVIDER_SERVICE_V2,
        "lifecycle": "service:application.artifact-lifecycle-services",
        "content": "service:application.artifact-content-services",
    }

    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    modules = {module.module_ref: module for module in manifest.modules}
    assert modules[ARTIFACT_HTTP_PROVIDER_MODULE_V2].contract.services.provides[0].service == (
        ARTIFACT_HTTP_PROVIDER_SERVICE_V2
    )
    assert modules[ARTIFACT_HTTP_APPLICATION_MODULE_V2].contract.services.provides[0].service == (
        ARTIFACT_HTTP_APPLICATION_SERVICE_V2
    )
