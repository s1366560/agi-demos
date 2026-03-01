# Domain Layer - Pure Business Logic (Zero External Dependencies)

## Structure

| Directory | Purpose |
|-----------|---------|
| `model/` | Domain entities by bounded context (8 contexts) |
| `ports/` | Repository (25) and service (20) interfaces for dependency inversion |
| `events/` | Domain event system — types, serialization, SSE conversion |
| `exceptions/` | Domain-specific exception hierarchy |
| `llm_providers/` | LLM provider enum/value objects |
| `shared_kernel.py` | Base classes: `Entity` (identity-based equality), `ValueObject` (frozen), `DomainEvent` (immutable) |

## Bounded Contexts in model/

| Context | Key Entities | Files |
|---------|-------------|-------|
| `agent/` | Conversation, Message, Task, Skill, SubAgent, HITL, Planning, Execution | 26+ files, 7 subdirs |
| `memory/` | Memory, Entity, Episode, Community | 5 files |
| `sandbox/` | ProjectSandbox, ResourcePool, StateMachine | 10 files |
| `mcp/` | MCPServer, MCPTool, MCPServerConfig | 6 files |
| `auth/` | User, ApiKey, Permissions | 5 files |
| `project/` | Project, SandboxConfig | 2 files |
| `artifact/` | Artifact with status/category enums | 2 files |
| `tenant/` | Tenant | 2 files |

## Patterns

- All entities use `@dataclass(kw_only=True)` and extend `shared_kernel.Entity`
- Value objects use `@dataclass(frozen=True)` and extend `shared_kernel.ValueObject`
- Enums for statuses/modes — never raw strings
- Domain logic lives on entities (e.g., `sandbox.StateMachine` transitions)
- No infrastructure imports — ever. SQLAlchemy, FastAPI, Redis are forbidden here

## Gotchas

- `model/agent/` is the largest context (26+ files) with subdirs for conversation/, execution/, hitl/, planning/, skill/
- `ports/` has both `repositories/` (persistence) and `services/` (cross-cutting domain services) plus `agent/` and `mcp/` sub-ports
- `shared_kernel.Entity.id` defaults to `uuid4()` — override in constructor if ID comes from external source
- Multi-tenancy: entities that need tenant scope carry `project_id` or `tenant_id` fields
