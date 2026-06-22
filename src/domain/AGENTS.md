# Domain Layer - Pure Business Logic (Zero External Dependencies)

Last checked against code: 2026-06-22

## Structure

| Directory | Purpose |
|-----------|---------|
| `model/` | Domain entities by bounded context (~28 contexts — refer to actual code for the full list) |
| `ports/` | Repository and service interfaces for dependency inversion (refer to actual code for counts) |
| `events/` | Domain event system — types, serialization, frontend event conversion |
| `exceptions/` | Domain-specific exception hierarchy |
| `llm_providers/` | LLM provider enum/value objects |
| `shared_kernel.py` | Base classes: `Entity` (identity-based equality), `ValueObject` (frozen), `DomainEvent` (immutable) |

## Bounded Contexts in model/

The set of contexts grows over time; only the largest/most stable are listed below.
Run `ls src/domain/model/` for the authoritative list (~28 subdirectories plus a few
top-level modules such as `canonical_story.py` and `enums.py`).

| Context | Key Entities | Files |
|---------|-------------|-------|
| `agent/` | Conversation, Message, Task, Skill, SubAgent, HITL, Planning, Execution | ~95 .py files, 14 subdirs (largest context) |
| `memory/` | Memory, Entity, Episode, Community | 4 files |
| `sandbox/` | ProjectSandbox, ResourcePool, StateMachine | 9 files |
| `mcp/` | MCPServer, MCPTool, MCPServerConfig | 5 files |
| `auth/` | User, ApiKey, Permissions | 4 files |
| `project/` | Project, SandboxConfig | 1 file |
| `artifact/` | Artifact with status/category enums | 1 file |
| `tenant/` | Tenant, EventLog, Webhook, RegistryConfig | 5 files |

Additional contexts not enumerated here (refer to actual code): `audit/`, `channels/`,
`cluster/`, `cron/`, `delivery/`, `deploy/`, `flow/`, `gene/`, `instance/`,
`instance_template/`, `invitation/`, `lane_contract/`, `recovery/`, `review/`, `smtp/`,
`task/`, `trace/`, `trust/`, `workspace/`, `workspace_plan/`.

## Patterns

- All entities use `@dataclass(kw_only=True)` and extend `shared_kernel.Entity`
- Value objects use `@dataclass(frozen=True)` and extend `shared_kernel.ValueObject`
- Enums for statuses/modes — never raw strings
- Domain logic lives on entities (e.g., `sandbox.StateMachine` transitions)
- No infrastructure imports — ever. SQLAlchemy, FastAPI, Redis are forbidden here

## Gotchas

- `model/agent/` is the largest context (~95 .py files, 14 subdirs) including conversation/, execution/, hitl/, planning/, skill/
- `ports/` has both `repositories/` (persistence) and `services/` (cross-cutting domain services) plus `agent/` and `mcp/` sub-ports
- `shared_kernel.Entity.id` defaults to `uuid4()` — override in constructor if ID comes from external source
- Multi-tenancy: entities that need tenant scope carry `project_id` or `tenant_id` fields
