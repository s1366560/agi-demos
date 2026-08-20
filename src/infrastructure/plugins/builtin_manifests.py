"""Manifests for trusted plugins shipped inside the MemStack process."""

from __future__ import annotations

from src.domain.model.plugins import PluginManifest, parse_plugin_manifest


def _manifest(payload: object) -> PluginManifest:
    return parse_plugin_manifest(payload)


def workspace_runtime_manifest() -> PluginManifest:
    """Return the manifest for the durable workspace runtime plugin."""
    return _manifest(
        {
            "schemaVersion": 1,
            "id": "workspace-runtime",
            "version": "1.0.0",
            "runtime": "python-trusted",
            "trust": "builtin",
            "provides": [
                {
                    "kind": "skill_provider",
                    "id": "workspace-task-harness",
                    "contract": "agent-skill:workspace-task-harness",
                },
                {"kind": "hook", "id": "on_session_start"},
                {"kind": "hook", "id": "before_response"},
                {"kind": "hook", "id": "after_tool_execution"},
            ],
            "activation": {"defaultScope": "tenant"},
        }
    )


def sisyphus_runtime_manifest() -> PluginManifest:
    """Return the manifest for the execution continuation plugin."""
    return _manifest(
        {
            "schemaVersion": 1,
            "id": "sisyphus-runtime",
            "version": "1.0.0",
            "runtime": "python-trusted",
            "trust": "builtin",
            "provides": [
                {
                    "kind": "system_prompt_section",
                    "id": "native-tool-protocol",
                    "contract": "prompt-section:native-tool-protocol",
                },
                {"kind": "hook", "id": "on_session_start"},
                {"kind": "hook", "id": "before_response"},
                {"kind": "hook", "id": "after_tool_execution"},
            ],
            "activation": {"defaultScope": "tenant"},
        }
    )


def memory_runtime_manifest() -> PluginManifest:
    """Return the manifest for the durable memory runtime plugin."""
    tool_contracts = [
        {"kind": "tool", "id": tool_id}
        for tool_id in (
            "memory_search",
            "memory_get",
            "memory_create",
            "memory_update",
            "memory_delete",
        )
    ]
    return _manifest(
        {
            "schemaVersion": 1,
            "id": "memory-runtime",
            "version": "1.0.0",
            "runtime": "python-trusted",
            "trust": "builtin",
            "provides": [
                *tool_contracts,
                {"kind": "hook", "id": "before_prompt_build"},
                {"kind": "hook", "id": "on_context_overflow"},
                {"kind": "hook", "id": "after_turn_complete"},
            ],
            "activation": {"defaultScope": "tenant"},
        }
    )


def skill_evolution_manifest() -> PluginManifest:
    """Return the manifest for periodic skill evolution capture."""
    return _manifest(
        {
            "schemaVersion": 1,
            "id": "skill-evolution",
            "version": "1.0.0",
            "runtime": "python-trusted",
            "trust": "builtin",
            "requires": [
                {
                    "capability": "agent-skill:workspace-task-harness@workspace-runtime",
                    "minVersion": "1.0.0",
                }
            ],
            "provides": [
                {"kind": "hook", "id": "after_tool_execution"},
                {"kind": "hook", "id": "after_turn_complete"},
            ],
            "activation": {"defaultScope": "tenant"},
        }
    )


def memory_backends_manifest() -> PluginManifest:
    """Return the manifest for the builtin memory backend providers (R3a).

    Declares the builtin ``embedder`` and ``reranker`` rows so the control
    plane inventory surfaces them; the runtime seam resolves these kinds
    through the capability registry with the LiteLLM implementations as the
    builtin fallback.
    """
    return _manifest(
        {
            "schemaVersion": 1,
            "id": "memory-backends",
            "version": "1.0.0",
            "runtime": "python-trusted",
            "trust": "builtin",
            "provides": [
                {
                    "kind": "embedder",
                    "id": "default",
                    "contract": "embedder:litellm",
                },
                {
                    "kind": "reranker",
                    "id": "default",
                    "contract": "reranker:litellm",
                },
            ],
            "activation": {"defaultScope": "tenant"},
        }
    )


def platform_backends_manifest() -> PluginManifest:
    """Return the manifest for the builtin platform backend providers (R3b/R3c).

    Declares the builtin ``graph_backend``, ``retrieval_backend``,
    ``workflow_engine``, and ``telemetry_exporter`` rows so the control
    plane inventory surfaces them. Runtime behavior: graph/retrieval
    factories consume plugin rows as additional engine builders; workflow
    engine resolves through the DI seam with builtin-absent preserved;
    telemetry falls back to a noop exporter.
    """
    return _manifest(
        {
            "schemaVersion": 1,
            "id": "platform-backends",
            "version": "1.0.0",
            "runtime": "python-trusted",
            "trust": "builtin",
            "provides": [
                {
                    "kind": "graph_backend",
                    "id": "default",
                    "contract": "graph-backend:neo4j",
                },
                {
                    "kind": "retrieval_backend",
                    "id": "default",
                    "contract": "retrieval-backend:pgvector",
                },
                {
                    "kind": "workflow_engine",
                    "id": "default",
                    "contract": "workflow-engine:none",
                },
                {
                    "kind": "telemetry_exporter",
                    "id": "default",
                    "contract": "telemetry-exporter:noop",
                },
            ],
            "activation": {"defaultScope": "tenant"},
        }
    )


def default_builtin_manifests() -> dict[str, PluginManifest]:
    """Return the deterministic first-party trusted plugin catalog."""
    manifests = (
        workspace_runtime_manifest(),
        sisyphus_runtime_manifest(),
        memory_runtime_manifest(),
        skill_evolution_manifest(),
        memory_backends_manifest(),
        platform_backends_manifest(),
    )
    return {manifest.id: manifest for manifest in manifests}
