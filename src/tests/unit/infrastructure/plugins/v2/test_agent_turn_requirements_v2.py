"""Production profile service roots and explicit contribution-closure limitations."""

import pytest

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2, ServiceRequiredV2
from src.infrastructure.plugins.v2.agent_turn_requirements_v2 import (
    AGENT_TURN_REQUIRED_SERVICES_V2,
    AGENT_WORKSPACE_REQUIRED_SERVICES_V2,
)
from src.infrastructure.plugins.v2.composer import compose_profile_v2
from src.infrastructure.plugins.v2.layer_composer import compose_profile_sources_v2
from src.infrastructure.plugins.v2.production_bundle import production_bundle_sources_v2
from src.infrastructure.plugins.v2.service_closure import project_service_closure_v2

pytestmark = pytest.mark.unit
SCOPE = ScopeV2(kind=ScopeKindV2.SESSION, tenant_id="t", project_id="p", session_id="s")


def _snapshot():
    source = production_bundle_sources_v2()
    composition = compose_profile_sources_v2(
        desired_set=source.desired_set,
        bundles=(source.bundle,),
        profile_source=source.profile_source,
        scope=SCOPE,
    )
    return compose_profile_v2(
        composition.document, {m.plugin_id: m for m in composition.manifests}, generation=1
    )


def test_all_explicit_agent_service_versions_match_actual_production_contracts():
    snapshot = _snapshot()
    declarations = {
        (p.service, p.version)
        for manifest in snapshot.manifests
        for module in manifest.modules
        for p in module.contract.services.provides
    }
    assert len({r.alias for r in AGENT_TURN_REQUIRED_SERVICES_V2}) == len(
        AGENT_TURN_REQUIRED_SERVICES_V2
    )
    for requirement in AGENT_WORKSPACE_REQUIRED_SERVICES_V2:
        assert (requirement.service, requirement.version) in declarations
    projected = project_service_closure_v2(
        snapshot, scope=SCOPE, required_services=AGENT_TURN_REQUIRED_SERVICES_V2
    )
    assert projected.entries
    from src.infrastructure.plugins.v2.runtime import RuntimeV2Error

    # Record the real production gap; do not weaken the declared Agent roots to hide it.
    with pytest.raises(RuntimeV2Error) as error:
        project_service_closure_v2(
            snapshot, scope=SCOPE, required_services=AGENT_WORKSPACE_REQUIRED_SERVICES_V2
        )
    assert error.value.code == "missing_inject_provider"
    assert "service:agent.workspace-prompt-context@1.0.0" in str(error.value)


async def test_actual_scoped_loader_builds_prompt_and_tool_resolvers_without_external_resources():
    from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
    from src.infrastructure.plugins.v2.graph_runtime import (
        GRAPH_RUNTIME_MODULE_V2,
        graph_runtime_definition_v2,
    )
    from src.infrastructure.plugins.v2.protocol import control_envelope_v2
    from src.infrastructure.plugins.v2.runtime import LoaderV2
    from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2
    from src.infrastructure.plugins.v2.sandbox_runtime import SANDBOX_RUNTIME_SERVICE_V2
    from src.infrastructure.plugins.v2.scoped_builtin_runtime import (
        scoped_builtin_runtime_definitions_v2,
    )
    from src.infrastructure.plugins.v2.system_prompt import (
        SYSTEM_PROMPT_BUILDER_SERVICE_V2,
        SYSTEM_PROMPT_SECTIONS_SERVICE_V2,
        SystemPromptBuilderProtocolV2,
        SystemPromptSectionsProtocolV2,
    )
    from src.infrastructure.plugins.v2.tool_set import (
        TOOL_SET_RESOLVER_SERVICE_V2,
        PreparedToolProviderV2,
        ToolSetResolverProtocolV2,
    )

    snapshot = _snapshot()
    owner = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    owner_snapshot = project_service_closure_v2(
        snapshot,
        scope=SCOPE,
        required_services=(
            ServiceRequiredV2(alias="sandbox", service=SANDBOX_RUNTIME_SERVICE_V2, version="1.0.0"),
        ),
    )
    assert (
        await owner.apply(owner_snapshot, control_envelope_v2(owner_snapshot, version=1))
    ).accepted
    definitions = scoped_builtin_runtime_definitions_v2(
        SCOPE, sandbox_owner_host=owner, redis_client=None
    )
    # An explicit unavailable typed graph provider replaces network construction in this test.
    definitions = tuple(
        graph_runtime_definition_v2() if d.module_ref == GRAPH_RUNTIME_MODULE_V2 else d
        for d in definitions
    )
    requirements = AGENT_TURN_REQUIRED_SERVICES_V2
    projected = project_service_closure_v2(snapshot, scope=SCOPE, required_services=requirements)
    generation = None
    try:
        generation = await LoaderV2(definitions).stage(projected)
        for requirement in requirements:
            assert (
                generation.resolve(requirement.service, SCOPE, version=requirement.version)
                is not None
            )
        prompt = generation.resolve(SYSTEM_PROMPT_BUILDER_SERVICE_V2, SCOPE)
        sections = generation.resolve(SYSTEM_PROMPT_SECTIONS_SERVICE_V2, SCOPE)
        tools = generation.resolve(TOOL_SET_RESOLVER_SERVICE_V2, SCOPE)
        assert isinstance(prompt, SystemPromptBuilderProtocolV2)
        assert isinstance(sections, SystemPromptSectionsProtocolV2)
        assert isinstance(tools, ToolSetResolverProtocolV2)
        resolved = tools.resolve(
            agent=object(),
            selection_context=None,
            prepared_tool_provider=PreparedToolProviderV2(tools={"prepared-tool": object()}),
        )
        assert resolved.tools == {}
        # Existing enabled consumers inject the catalog, but forward dependency closure
        # cannot infer that they register contributions into its provider.
        module_map = {
            (m.plugin_id, module.module_ref): module
            for m in snapshot.manifests
            for module in m.modules
        }
        dependents = {
            entry.entry_id
            for entry in snapshot.entries
            if entry.enabled
            and any(
                r.service == "service:tool-set-catalog"
                for r in module_map[(entry.plugin_ref, entry.module_ref)].contract.services.requires
            )
        }
        assert dependents
        assert dependents.isdisjoint({entry.entry_id for entry in projected.entries})
    finally:
        if generation is not None:
            await generation.dispose()
        await owner.close()
