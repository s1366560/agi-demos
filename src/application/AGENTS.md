# Application Layer - Orchestration and Use Cases

Orchestrates domain logic. Services here are "thick" — some embed infrastructure concerns
(noted deviation from pure DDD).

## Structure

| Directory | Purpose |
|-----------|---------|
| `services/` | 33+ application services (see services/AGENTS.md for detail) |
| `use_cases/` | Use case implementations (thin wrappers over services) |
| `schemas/` | Pydantic request/response DTOs for API layer |
| `constants/` | Application-level constants |
| `ports/` | Application-level port interfaces |

## Service Domains (in services/)

| Domain | Key Services |
|--------|-------------|
| Agent | `agent_service.py`, `agent/` subdirectory |
| Sandbox | `sandbox_orchestrator.py` + 8 sandbox_* services |
| Memory | `memory_service.py`, `memory_index_service.py`, `search_service.py` |
| Skills | `skill_service.py`, `skill_resource_sync_service.py`, `filesystem_skill_loader.py` |
| Auth | `auth_service_v2.py`, `authorization_service.py` |
| MCP | `mcp_app_service.py`, `mcp_runtime_service.py` |
| LLM | `llm_provider_manager.py`, `provider_service.py`, `provider_resolution_service.py` |
| SubAgent | `subagent_service.py` |
| Project | `project_service.py`, `project_sandbox_lifecycle_service.py` |

## Patterns

- Services receive repository interfaces (ports) via constructor injection
- Services are stateless — all state flows through domain entities
- `schemas/` DTOs validate API input and shape API output (Pydantic v2)
- Use cases in `use_cases/` are thin — most logic lives in services

## Gotchas

- Sandbox has the most services (8+) reflecting complex sandbox lifecycle
- `agent/` subdirectory exists within services for agent-specific decomposition
- `channels/` subdirectory handles multi-channel (Feishu, etc.) integrations
- Service constructors accept port interfaces but are typically instantiated by DI container
- Some services have grown "thick" with infrastructure concerns — this is known and accepted
