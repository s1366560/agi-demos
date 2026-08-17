# Plugin Capability Inventory

This is the Phase 0 ownership map. Rows marked **Kernel** stay deterministic platform
infrastructure or trusted builtin capability; they are not exposed to untrusted plugins.

| Capability kind | Current owner | Current consumers | Scope | Trust | Migration |
| --- | --- | --- | --- | --- | --- |
| `agent_loop` | `src/infrastructure/agent/core/react_agent.py`, `src/infrastructure/agent/processor/processor.py` | Agent worker, Ray actors, workspace runtime | session | Kernel / builtin | Phase 3 interface extraction. |
| `tool` | `src/infrastructure/agent/tools/define.py`, `tool_provider.py`, `plugin_tools.py`, `pipeline.py` | ReAct processor, tool selection, MCP runtime | tenant / project / session | builtin or isolated | Phase 3 capability-provider bridge. |
| `skill_provider` | `src/infrastructure/agent/plugins/registry.py`, `plugin_skill_loader.py`, skill filesystem/database loaders | Agent routing and prompt assembly | tenant / project | builtin or isolated | Phase 3. |
| `subagent_provider` | `src/infrastructure/agent/subagent/`, `plugins/registry.py` | SubAgent router, delegation tools, workflows | project / session | builtin or isolated | Phase 3. |
| `hook` | `AgentPluginRegistry`, processor hook call sites | Runtime plugins, workspace, memory, skill evolution | global / tenant | builtin or isolated | Context bridge implemented; event modes remain Phase 3. |
| `policy` | Tool pipeline, permission manager, sandbox gates | Tool execution, subprocess, filesystem, approval | global / tenant / project | Kernel | Phase 3/4 typed enforcement. |
| `llm_provider` | `src/application/services/llm_provider_manager.py`, `provider_resolution_service.py`, LiteLLM adapters | Agent, embeddings, health, resilience | tenant | builtin or signed | Phase 4. |
| `embedder` | graph embedding services and provider manager | Graph ingestion, retrieval | tenant | builtin or signed | Phase 4. |
| `reranker` | retrieval services and provider manager | Hybrid search | tenant | builtin or signed | Phase 4. |
| `channel` | `src/infrastructure/agent/plugins/registry.py`, channel adapter modules, connection manager | Channel APIs, Feishu/IM routing, HITL | tenant / project | builtin or signed | Phase 4. |
| `http_route` | FastAPI `main.py` static imports and `PluginHttpRoute` registry | API gateway and browser clients | global / tenant | Kernel / builtin | Phase 4 route capability migration. |
| `cli_command` | agent plugin registry and ACP/CLI command surfaces | Automation and CLI | global | builtin | Phase 4. |
| `ui_slot` / `ui_renderer` | React and desktop feature modules | Web and Electron rendering | tenant / project | frontend | Phase 5. |
| `storage` | storage services and repositories | Artifacts, attachments, workspace data | tenant / project | Kernel / builtin or signed | Phase 4. |
| `graph_backend` | graph backend factory and native adapter | Memory graph, extraction, search | tenant / project | builtin or signed | Phase 4. |
| `retrieval_backend` | retrieval registry and stores | Recall, hybrid search, reranking | tenant / project | builtin or signed | Phase 4. |
| `workflow_engine` | workflow engine and background/runtime managers | Automation, jobs, workflows | project | builtin or isolated | Phase 4. |
| `credential_source` | application vault/provider credential paths | Provider calls, desktop vault, HITL env flows | tenant | Kernel | Reference-only seam; never an untrusted provider. |
| `telemetry_exporter` | telemetry config/exporters | Observability and product telemetry | global / tenant | builtin or signed | Phase 4. |
| Wasm tool host | `agi-stack/crates/plugin-host`, `adapters-wasmtime` | Rust registry, desktop sidecar, sandboxed tools | project / session | isolated | Phase 5 reconcile integration. |

## Explicit non-plugin kernel surfaces

- Authentication and authorization enforcement.
- Tenant membership and project access checks.
- Alembic migrations and schema authority.
- Credential vault encryption and secret grant enforcement.
- Plugin host lifecycle and profile composition engine.
- Versioned control-plane protocol and audit storage.

These surfaces may be represented by trusted builtin capabilities for observability, but
tenant-approved or untrusted plugins cannot replace them.
