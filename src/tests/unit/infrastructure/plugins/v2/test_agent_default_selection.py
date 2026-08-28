"""Profile-owned default selection coverage for the V2 agent runtime."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.application.services.agent.runtime_bootstrapper import AgentRuntimeBootstrapper
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.agent.sisyphus.builtin_agent import BUILTIN_ALL_ACCESS_ID
from src.infrastructure.plugins.v2.agent_default_selection import (
    AGENT_DEFAULT_SELECTION_MODULE_V2,
    AGENT_DEFAULT_SELECTION_SERVICE_V2,
    AgentDefaultSelectionResolutionV2,
)
from src.infrastructure.plugins.v2.agent_definition import (
    AGENT_DEFINITION_CONTRIBUTION_MODULE_V2,
)
from src.infrastructure.plugins.v2.boundary import pin_operation_context_v2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.runtime import GenerationManagerV2, LoaderV2, RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"
_BOOTSTRAPPER_PATH = _ROOT / "src/application/services/agent/runtime_bootstrapper.py"


def _conversation(*, selected_agent_id: str | None = None) -> SimpleNamespace:
    agent_config = {} if selected_agent_id is None else {"selected_agent_id": selected_agent_id}
    return SimpleNamespace(
        tenant_id="tenant-a",
        project_id="project-a",
        agent_config=agent_config,
    )


def test_explicit_and_conversation_selection_precede_profile_default() -> None:
    resolution = AgentDefaultSelectionResolutionV2(
        agent_id=BUILTIN_ALL_ACCESS_ID,
        source="profile-default",
    )

    with patch(
        "src.infrastructure.plugins.v2.agent_default_selection_consumer."
        "resolve_current_agent_default_selection_v2",
        return_value=resolution,
    ) as resolve_default:
        assert (
            AgentRuntimeBootstrapper._resolve_agent_id_v2(
                conversation=_conversation(selected_agent_id="conversation-agent"),
                explicit_agent_id="explicit-agent",
            )
            == "explicit-agent"
        )
        assert (
            AgentRuntimeBootstrapper._resolve_agent_id_v2(
                conversation=_conversation(selected_agent_id="conversation-agent"),
                explicit_agent_id=None,
            )
            == "conversation-agent"
        )

    resolve_default.assert_not_called()


def test_profile_default_requires_a_pinned_operation() -> None:
    with pytest.raises(RuntimeV2Error) as error:
        AgentRuntimeBootstrapper._resolve_agent_id_v2(
            conversation=_conversation(),
            explicit_agent_id=None,
        )

    assert error.value.code == "operation_context_not_pinned"


async def test_bootstrapper_resolves_default_from_pinned_profile() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=81,
        version=81,
    )
    assert publication.accepted is True

    try:
        async with pin_operation_context_v2(
            host,
            operation_id="agent-default-selection",
            scope=ScopeV2(
                kind=ScopeKindV2.PROJECT,
                tenant_id="tenant-a",
                project_id="project-a",
            ),
        ):
            result = AgentRuntimeBootstrapper._resolve_agent_id_v2(
                conversation=_conversation(),
                explicit_agent_id=None,
            )
        with pytest.raises(RuntimeV2Error) as scope_error:
            async with pin_operation_context_v2(
                host,
                operation_id="agent-default-scope-mismatch",
                scope=ScopeV2(
                    kind=ScopeKindV2.PROJECT,
                    tenant_id="tenant-a",
                    project_id="project-b",
                ),
            ):
                AgentRuntimeBootstrapper._resolve_agent_id_v2(
                    conversation=_conversation(),
                    explicit_agent_id=None,
                )
    finally:
        await host.close()

    assert result == BUILTIN_ALL_ACCESS_ID
    assert scope_error.value.code == "agent_default_scope_mismatch"


@pytest.mark.parametrize(
    ("disabled_module", "expected_code"),
    [
        (AGENT_DEFAULT_SELECTION_MODULE_V2, "missing_service"),
        (AGENT_DEFINITION_CONTRIBUTION_MODULE_V2, "agent_default_definition_not_found"),
    ],
)
async def test_disabling_default_authority_fails_without_builtin_fallback(
    disabled_module: str,
    expected_code: str,
) -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    disabled = replace(
        document,
        entries=tuple(
            replace(entry, enabled=False)
            if entry.module_ref == disabled_module
            and (
                disabled_module != AGENT_DEFINITION_CONTRIBUTION_MODULE_V2
                or entry.config.get("agent_id") == BUILTIN_ALL_ACCESS_ID
            )
            else entry
            for entry in document.entries
        ),
    )
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(
        disabled,
        {manifest.plugin_id: manifest},
        generation=82,
    )
    generation = await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)
    manager = GenerationManagerV2()
    await manager.publish(generation)

    try:
        with pytest.raises(RuntimeV2Error) as error:
            async with pin_operation_context_v2(
                manager,
                operation_id=f"disabled-{disabled_module}",
                scope=ScopeV2(
                    kind=ScopeKindV2.PROJECT,
                    tenant_id="tenant-a",
                    project_id="project-a",
                ),
            ):
                AgentRuntimeBootstrapper._resolve_agent_id_v2(
                    conversation=_conversation(),
                    explicit_agent_id=None,
                )
    finally:
        await manager.close()

    assert error.value.code == expected_code


def test_bootstrapper_source_has_no_hardcoded_default_agent() -> None:
    source = _BOOTSTRAPPER_PATH.read_text(encoding="utf-8")

    assert "DEFAULT_GENERAL_AGENT_ID" not in source
    assert "or DEFAULT_GENERAL_AGENT_ID" not in source
    assert AGENT_DEFAULT_SELECTION_SERVICE_V2 not in source
