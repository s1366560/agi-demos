# Application Services

Stateless orchestration layer. Each service receives domain port interfaces via constructor.
Services own business workflows; repositories own persistence.

## Service Map

| Service | Ports Injected | Purpose |
|---------|---------------|---------|
| `agent_service.py` | ConversationRepo, ExecutionRepo, GraphService, LLM, SkillRepo, SubAgentRepo, Redis | Conversation lifecycle, agent execution coordination, and stream handoff to Redis/WebSocket paths. Largest service (~1500 lines, 30+ constructor params). |
| `memory_service.py` | MemoryRepo, GraphServicePort | Memory CRUD + graph episode creation. Creates Memory entity then queues background entity extraction. |
| `project_service.py` | ProjectRepo, UserRepo | Project CRUD + member management. Validates owner exists before creation. |
| `skill_service.py` | SkillRepo, TenantSkillConfigRepo, FileSystemSkillLoader | Three-level skill scoping: system < tenant < project. Progressive loading tiers (metadata/triggers/full content). |
| `search_service.py` | GraphServicePort | Hybrid search (semantic + keyword + graph). |
| [Sandbox orchestrator](../../../plugins/business/environments/backend/sandbox/sandbox_orchestrator.py) | SandboxPort, SandboxEventPublisher | Unified sandbox lifecycle used by both REST API and Agent tools. |
| `subagent_service.py` | SubAgentRepo | SubAgent CRUD and configuration. |
| `auth_service_v2.py` | UserRepo, ApiKeyRepo | Auth operations, token management. |
| `llm_provider_manager.py` | - | Multi-provider LLM key management, encryption/decryption. |
| `mcp_app_service.py` | MCPAppRepo | MCP server app registration and discovery. |
| `task_service.py` | TaskRepo | Background task tracking via TaskLog. |
| `tenant_service.py` | TenantRepo | Tenant CRUD. |
| [Workflow learner](../../../plugins/business/automation/backend/workflow_learner.py) | PatternRepo | Extracts reusable patterns from successful agent interactions. |

## Sandbox ownership

[Environments](../../../plugins/business/environments/) owns provisioning, leases, health, idle reaping, image management and MCP tools. The host issues scoped WebSocket credentials through `sandbox_token_service.py`.

## agent/ Subdirectory

Agent-specific application services decomposed from `agent_service.py`:
- `context_loader.py` -- loads conversation context (messages, skills, tools) for agent bootstrap
- `conversation_manager.py` -- conversation creation, listing, deletion
- `execution_resume_service.py` -- resumes interrupted agent executions (HITL, crash recovery)
- `runtime_bootstrapper.py` -- assembles ReActAgent instance with all dependencies
- `termination_service.py` -- terminates running agent sessions
- `tool_discovery.py` -- discovers available tools for a project (built-in + MCP + sandbox)
- `workspace_conversation_sweeper.py` -- cleans up workspace conversation state
- `workspace_hitl_defaults.py` -- default HITL configuration for workspaces
- `workspace_mention_candidates.py` -- resolves @mention candidates in a workspace
- `workspace_roster_validator.py` -- validates workspace participant rosters
- `workspace_termination_resolver.py` -- resolves termination decisions for workspaces

## channels/ Subdirectory

Multi-channel message routing (Feishu, webhook, etc.):
- `_session.py` -- shared session helpers for channel services
- `channel_service.py` -- channel instance CRUD per project
- `channel_service_factory.py` -- creates channel-specific service instances
- `channel_message_router.py` -- routes inbound messages to correct conversation
- `event_bridge.py` -- bridges agent runtime events to channel-specific outbound format
- `hitl_responder.py` -- routes HITL responses back from channel to agent
- `media_import_service.py` -- imports media attachments from channel messages

## Patterns

- Services return domain entities, not DTOs (DTOs live in `schemas/`)
- `agent_service.py` constructor has 30+ params (most None-defaulted for testability)
- Skill loading is lazy/tiered: metadata first, full content only at execution time
- Sandbox services form a directed dependency graph; `sandbox_orchestrator` is the entry point

## Gotchas

- `agent_service.py` accepts `db_session` but primarily for passing to sub-services, not direct queries
- `memory_service.py` creates an Episode inside `create_memory` -- this triggers async graph processing
- `skill_service.py` merges filesystem + DB skills with priority resolution; name collisions resolved by scope
- Sandbox cluster has circular-looking imports; use TYPE_CHECKING guards
- `workflow_learner.py` is tenant-scoped, not project-scoped
