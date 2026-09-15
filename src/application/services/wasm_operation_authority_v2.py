"""Fresh SQL authorization for an immutable, signed WASM tool lease."""

from __future__ import annotations

from collections.abc import Mapping

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.application.services.agent.conversation_manager import ConversationManager
from src.domain.model.plugins.generated_v2 import (
    DataPlaneTargetV2,
    ProfileSnapshotV2,
    RuntimeKindV2,
    ScopeKindV2,
    ScopeV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_governance_repository import (
    PlatformPluginGovernanceRepository,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository_v2 import (
    PlatformPluginRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.sql_agent_execution_repository import (
    SqlAgentExecutionRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_conversation_repository import (
    SqlConversationRepository,
)
from src.infrastructure.plugins.v2.boundary import OPERATION_IDENTITY_SERVICE_V2
from src.infrastructure.plugins.v2.project_access_services import (
    ProjectAccessDeniedV2,
    SqlProjectAccessTransactionV2,
)
from src.infrastructure.plugins.v2.protocol import (
    parse_bundle_manifest_v2,
    parse_profile_snapshot_v2,
)
from src.infrastructure.plugins.v2.runtime import OperationContextV2, RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_context import scope_contains_v2
from src.infrastructure.plugins.v2.wasm_tool_runtime import (
    WasmToolAttributionV2,
    prepare_wasm_operation_tools_v2,
)


class SqlWasmOperationAuthorityV2:
    """Never cache SQL grants, installed state, membership, or publication heads.

    The signed factory supplies bundle identity. An independent database session
    on each call avoids an Agent transaction's repeatable snapshot or identity
    map. Latest requested publications may withdraw an old tool immediately;
    an unrelated generation increment retains tools whose exact entry matches.
    """

    def __init__(self, *, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = session_factory

    async def authorize(  # noqa: C901, PLR0911, PLR0912 -- independent fail-closed checks
        self, *, operation: OperationContextV2, attribution: WasmToolAttributionV2
    ) -> bool:
        scope = operation.context.scope
        if scope.kind is not ScopeKindV2.SESSION or not all(
            (scope.tenant_id, scope.project_id, scope.session_id)
        ):
            return False
        try:
            identity = operation.require(OPERATION_IDENTITY_SERVICE_V2)
        except RuntimeV2Error:
            return False
        if not isinstance(identity, Mapping):
            return False
        user_id = identity.get("user_id")
        if (
            not isinstance(user_id, str)
            or not user_id.strip()
            or identity.get("tenant_id") != scope.tenant_id
            or identity.get("project_id") != scope.project_id
        ):
            return False
        assert scope.tenant_id
        assert scope.project_id
        assert scope.session_id
        reference = attribution.bundle_reference
        if reference.source != f"marketplace://{reference.bundle_id}/{reference.version}":
            return False
        captured = operation.generation.snapshot
        entry = next((e for e in captured.entries if e.entry_id == attribution.entry_id), None)
        if entry is None or not _snapshot_allows(captured, captured, attribution, scope):
            return False
        async with self._sessions() as session:
            try:
                await SqlProjectAccessTransactionV2(db=session).require_access(
                    project_id=scope.project_id, tenant_id=scope.tenant_id, user_id=user_id
                )
            except ProjectAccessDeniedV2:
                return False
            conversation = await ConversationManager(
                SqlConversationRepository(session), SqlAgentExecutionRepository(session)
            ).get_conversation(scope.session_id, scope.project_id, user_id)
            if conversation is None or conversation.tenant_id != scope.tenant_id:
                return False
            governance = PlatformPluginGovernanceRepository(session)
            package = await governance.get_package_version(reference.bundle_id, reference.version)
            if package is None or package.install_status != "installed" or package.revoked:
                return False
            bundle = parse_bundle_manifest_v2(package.manifest)
            if (bundle.bundle_id, bundle.version, bundle.digest) != (
                reference.bundle_id,
                reference.version,
                reference.digest,
            ):
                return False
            manifest = next(
                (m for m in bundle.manifests if m.plugin_id == attribution.plugin_id), None
            )
            captured_manifest = next(
                (m for m in captured.manifests if m.plugin_id == attribution.plugin_id), None
            )
            if manifest is None or manifest != captured_manifest:
                return False
            module = next(
                (m for m in manifest.modules if m.module_ref == attribution.module_ref), None
            )
            if module is None or (module.artifact.digest, module.artifact.source) != (
                attribution.artifact_digest,
                attribution.artifact_source,
            ):
                return False
            if not await governance.permission_is_granted(
                plugin_id=reference.bundle_id,
                permission="tools.execute",
                scope_type="tenant",
                scope_id=scope.tenant_id,
            ):
                return False
            found_publication = False
            for owner in _scope_chain(scope):
                if not scope_contains_v2(entry.scope, owner):
                    continue
                payload = await PlatformPluginRepositoryV2(
                    session, scope=owner
                ).latest_requested_distribution()
                if payload is None:
                    continue
                found_publication = True
                current = parse_profile_snapshot_v2(payload.get("snapshot"))
                if not _snapshot_allows(current, captured, attribution, scope):
                    return False
            return found_publication


def _scope_chain(scope: ScopeV2) -> tuple[ScopeV2, ...]:
    return (
        ScopeV2(kind=ScopeKindV2.ROOT),
        ScopeV2(kind=ScopeKindV2.TENANT, tenant_id=scope.tenant_id),
        ScopeV2(kind=ScopeKindV2.PROJECT, tenant_id=scope.tenant_id, project_id=scope.project_id),
        scope,
    )


def _snapshot_allows(
    current: ProfileSnapshotV2,
    captured: ProfileSnapshotV2,
    attribution: WasmToolAttributionV2,
    scope: ScopeV2,
) -> bool:
    original = next((e for e in captured.entries if e.entry_id == attribution.entry_id), None)
    entries = {e.entry_id: e for e in current.entries}
    entry = entries.get(attribution.entry_id)
    if entry is None or entry != original or not scope_contains_v2(entry.scope, scope):
        return False
    if entry.plugin_ref != attribution.plugin_id or entry.module_ref != attribution.module_ref:
        return False
    # Explicit parent enablement is structural policy, not semantic tool routing.
    while True:
        if not entry.enabled:
            return False
        if entry.parent_entry_id is None:
            break
        parent = entries.get(entry.parent_entry_id)
        if parent is None:
            return False
        entry = parent
    original_manifest = next(
        (m for m in captured.manifests if m.plugin_id == attribution.plugin_id), None
    )
    manifest = next((m for m in current.manifests if m.plugin_id == attribution.plugin_id), None)
    return manifest is not None and manifest == original_manifest


async def prepare_agent_wasm_tools_v2(operation: OperationContextV2) -> int:
    """Production boundary used before Agent initialization and ToolSet resolution."""
    if not any(
        manifest.runtime is RuntimeKindV2.WASM
        and any(DataPlaneTargetV2.PYTHON in module.targets for module in manifest.modules)
        for manifest in operation.generation.snapshot.manifests
    ):
        return 0
    from src.infrastructure.adapters.secondary.persistence.database import async_session_factory

    return await prepare_wasm_operation_tools_v2(
        operation, SqlWasmOperationAuthorityV2(session_factory=async_session_factory)
    )
