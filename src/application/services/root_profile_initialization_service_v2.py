"""Persist the explicit initial ROOT configuration; never rewrite an existing choice."""

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import replace

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.model.plugins.generated_v2 import (
    ProfileEntryV2,
    ProfileLayerKindV2,
    ProfileLayerV2,
    ProfileSourceReferenceV2,
    ScopeKindV2,
    ScopeV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_desired_bundle_repository_v2 import (
    PlatformPluginDesiredBundleSetRecordV2,
    PlatformPluginDesiredBundleSetRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_profile_source_repository_v2 import (
    PlatformPluginProfileSourceRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_scope_ledger_v2 import (
    ScopeLedgerBindingV2,
)
from src.infrastructure.plugins.v2.agent_pool_profile import (
    AGENT_POOL_RUNTIME_ENTRY_ID_V2,
    project_agent_pool_runtime_v2,
)
from src.infrastructure.plugins.v2.agent_pool_runtime import default_agent_pool_runtime_config_v2
from src.infrastructure.plugins.v2.composer import ProfileDocumentV2
from src.infrastructure.plugins.v2.layer_composer import (
    compose_profile_sources_v2,
    desired_bundle_set_digest_v2,
    profile_source_digest_v2,
)
from src.infrastructure.plugins.v2.production_bundle import ProductionBundleSourcesV2
from src.infrastructure.plugins.v2.protocol import canonical_json_v2
from src.infrastructure.plugins.v2.workspace_contract_actor_services import (
    WORKSPACE_CONTRACT_ACTOR_RESOLVER_MODULE_V2,
)
from src.infrastructure.plugins.v2.workspace_core_runtime import WORKSPACE_CORE_RUNTIME_MODULE_V2
from src.infrastructure.plugins.v2.workspace_core_shadow import (
    WORKSPACE_CORE_CONTRACT_ACTOR_RESOLVER_ENTRY_ID_V2,
    WORKSPACE_CORE_RUNTIME_ENTRY_ID_V2,
    WORKSPACE_PROMPT_CONTEXT_ENTRY_ID_V2,
)
from src.infrastructure.plugins.v2.workspace_prompt_context_services import (
    WORKSPACE_PROMPT_CONTEXT_MODULE_V2,
)


class RootProfileInitializationV2Error(ValueError):
    """Explicit initial configuration cannot be composed safely."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class RootProfileInitializationServiceV2:
    """First-write-only configuration, not runtime activation or an upgrade policy."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        production_sources: ProductionBundleSourcesV2,
    ) -> None:
        super().__init__()
        self._sessions = session_factory
        self._sources = production_sources

    async def ensure_initialized(
        self,
        *,
        workspace_core_enabled: bool,
        agent_pool_runtime_enabled: bool = False,
        agent_pool_runtime_config: Mapping[str, object] | None = None,
        actor_id: str | None = None,
    ) -> PlatformPluginDesiredBundleSetRecordV2:
        if type(workspace_core_enabled) is not bool or type(agent_pool_runtime_enabled) is not bool:
            raise RootProfileInitializationV2Error(
                "root_initialization_invalid", "enabled must be boolean"
            )
        scope = ScopeV2(kind=ScopeKindV2.ROOT)
        async with self._sessions() as session:
            _ = await ScopeLedgerBindingV2(scope, RootProfileInitializationV2Error).lock(session)
            repository = PlatformPluginDesiredBundleSetRepositoryV2(session)
            existing = await repository.current_desired_set(scope)
            if existing is not None:
                return existing
            expected = (
                (WORKSPACE_CORE_RUNTIME_ENTRY_ID_V2, WORKSPACE_CORE_RUNTIME_MODULE_V2),
                (
                    WORKSPACE_CORE_CONTRACT_ACTOR_RESOLVER_ENTRY_ID_V2,
                    WORKSPACE_CONTRACT_ACTOR_RESOLVER_MODULE_V2,
                ),
                (WORKSPACE_PROMPT_CONTEXT_ENTRY_ID_V2, WORKSPACE_PROMPT_CONTEXT_MODULE_V2),
            )
            entries = [entry for layer in self._sources.bundle.layers for entry in layer.entries]
            replacements: list[ProfileEntryV2] = []
            for entry_id, module in expected:
                matches = [entry for entry in entries if entry.entry_id == entry_id]
                if (
                    len(matches) != 1
                    or matches[0].module_ref != module
                    or matches[0].scope != scope
                ):
                    raise RootProfileInitializationV2Error(
                        "root_initialization_baseline_invalid",
                        "Workspace Core baseline entry is missing or inconsistent",
                    )
                replacements.append(replace(matches[0], enabled=workspace_core_enabled))
            pool_config = (
                deepcopy(dict(agent_pool_runtime_config))
                if agent_pool_runtime_config is not None
                else default_agent_pool_runtime_config_v2()
            )
            projected = project_agent_pool_runtime_v2(
                ProfileDocumentV2(
                    profile_id=self._sources.profile_source.profile_id, entries=tuple(entries)
                ),
                enabled=agent_pool_runtime_enabled,
                config=pool_config,
            )
            replacements.extend(
                entry
                for entry in projected.entries
                if entry.entry_id == AGENT_POOL_RUNTIME_ENTRY_ID_V2
            )
            source = replace(
                self._sources.profile_source,
                source_id="memstack-root-initialized-profile-source-v2",
                revision=1,
                provenance=canonical_json_v2(
                    {
                        "kind": "explicit-root-initialization",
                        "workspace_core_enabled": workspace_core_enabled,
                        "agent_pool_runtime_enabled": agent_pool_runtime_enabled,
                        "agent_pool_runtime_config": pool_config,
                        "original_provenance": self._sources.profile_source.provenance,
                    }
                ).decode("utf-8"),
                layers=(
                    *self._sources.profile_source.layers,
                    ProfileLayerV2(
                        layer_id="explicit-root-workspace-core",
                        kind=ProfileLayerKindV2.PROFILE,
                        scope=scope,
                        entries=(),
                        replacements=tuple(replacements),
                        disabled_entry_ids=(),
                    ),
                ),
            )
            source = replace(source, digest=profile_source_digest_v2(source))
            desired = replace(
                self._sources.desired_set,
                revision=1,
                profile_source=ProfileSourceReferenceV2(
                    source_id=source.source_id, revision=1, digest=source.digest
                ),
            )
            desired = replace(desired, digest=desired_bundle_set_digest_v2(desired))
            _ = compose_profile_sources_v2(
                desired_set=desired,
                bundles=(self._sources.bundle,),
                profile_source=source,
                scope=scope,
            )
            _ = await PlatformPluginProfileSourceRepositoryV2(session).record_source(
                scope=scope, source=source, expected_revision=None
            )
            record = await repository.record_desired_set(
                scope=scope, desired_set=desired, expected_revision=None, actor_id=actor_id
            )
            await session.commit()
            return record
