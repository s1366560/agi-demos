"""Agent-first PluginSelectionJudgeV2 contract and lifecycle tests."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2
from src.infrastructure.plugins.v2.selection_judge import (
    PLUGIN_SELECTION_JUDGE_SERVICE_V2,
    AgentPluginSelectionJudgeV2,
    PluginSelectionCandidateV2,
    PluginSelectionRequestV2,
    resolve_plugin_selection_v2,
)

_ROOT = Path(__file__).resolve().parents[6]


def _request() -> PluginSelectionRequestV2:
    return PluginSelectionRequestV2(
        decision_type="agent-loop-auto",
        candidates=(
            PluginSelectionCandidateV2(
                candidate_id="loop-a",
                plugin_id="plugin-a",
                capability_id="agent-loop:a",
                metadata={"description": "general loop"},
            ),
            PluginSelectionCandidateV2(
                candidate_id="loop-b",
                plugin_id="plugin-b",
                capability_id="agent-loop:b",
                metadata={"description": "long-running loop"},
            ),
        ),
        scope=ScopeV2(
            kind=ScopeKindV2.PROJECT,
            tenant_id="tenant-a",
            project_id="project-a",
        ),
        explicit_constraints={"required_permissions": []},
        runtime_context={"provider_id": "deepseek", "model_id": "deepseek-chat"},
    )


@pytest.mark.unit
async def test_explicit_binding_is_deterministic_and_does_not_call_judge() -> None:
    judge = SimpleNamespace(select=AsyncMock())

    result = await resolve_plugin_selection_v2(
        _request(),
        explicit_candidate_id="loop-b",
        judge=judge,
    )

    assert result.selected.candidate_id == "loop-b"
    assert result.source == "explicit-binding"
    assert result.audit is None
    judge.select.assert_not_awaited()


@pytest.mark.unit
async def test_auto_selection_requires_structured_agent_tool_call_and_records_audit() -> None:
    candidate = SimpleNamespace(
        candidate_key="provider-row:judge-model",
        provider_config=object(),
        model_name="judge-model",
    )
    pool = SimpleNamespace(list_candidates=AsyncMock(return_value=[candidate]))
    client = SimpleNamespace(
        generate=AsyncMock(
            return_value={
                "tool_calls": [
                    {
                        "function": {
                            "name": "select_plugin_candidate_v2",
                            "arguments": {
                                "candidate_id": "loop-a",
                                "rationale": "Matches the structured runtime requirements.",
                                "confidence_explanation": "All declared constraints are present.",
                            },
                        }
                    }
                ]
            }
        )
    )
    audits: list[object] = []
    judge = AgentPluginSelectionJudgeV2(
        pool_service=pool,
        client_factory=lambda _config: client,
        audit_sink=audits.append,
    )

    result = await resolve_plugin_selection_v2(
        _request(),
        explicit_candidate_id=None,
        judge=judge,
    )

    assert result.selected.candidate_id == "loop-a"
    assert result.source == "agent-judge"
    assert result.audit is not None
    assert result.audit.agent_id == "provider-row:judge-model"
    assert result.audit.input_json["decision_type"] == "agent-loop-auto"
    assert result.audit.output_json["candidate_id"] == "loop-a"
    assert result.audit.rationale == "Matches the structured runtime requirements."
    assert len(audits) == 1
    client.generate.assert_awaited_once()


@pytest.mark.unit
async def test_auto_selection_fails_without_required_tool_call() -> None:
    candidate = SimpleNamespace(
        candidate_key="provider-row:judge-model",
        provider_config=object(),
        model_name="judge-model",
    )
    pool = SimpleNamespace(list_candidates=AsyncMock(return_value=[candidate]))
    client = SimpleNamespace(generate=AsyncMock(return_value={"content": "loop-a"}))
    judge = AgentPluginSelectionJudgeV2(
        pool_service=pool,
        client_factory=lambda _config: client,
    )

    with pytest.raises(RuntimeV2Error) as error:
        await resolve_plugin_selection_v2(
            _request(),
            explicit_candidate_id=None,
            judge=judge,
        )

    assert error.value.code == "plugin_selection_tool_call_required"


@pytest.mark.unit
async def test_selection_judge_provider_disappears_when_generation_unloads() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=1,
        version=1,
    )
    async with await host.acquire() as generation:
        assert isinstance(
            generation.resolve(
                PLUGIN_SELECTION_JUDGE_SERVICE_V2,
                ScopeV2(kind=ScopeKindV2.ROOT),
            ),
            AgentPluginSelectionJudgeV2,
        )

    await host.close()

    with pytest.raises(RuntimeError, match="generation is disposed"):
        generation.resolve(
            PLUGIN_SELECTION_JUDGE_SERVICE_V2,
            ScopeV2(kind=ScopeKindV2.ROOT),
        )
