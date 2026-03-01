# Domain Ports - Dependency Inversion Interfaces

All interfaces that infrastructure must implement. The domain never imports infrastructure.

## Structure

| Directory | Count | Purpose |
|-----------|-------|---------|
| `repositories/` | 25 files | One interface per aggregate root for persistence |
| `services/` | 20 files | Cross-cutting domain service interfaces |
| `agent/` | Agent-specific port interfaces |
| `mcp/` | MCP-specific port interfaces |
| `tool_port.py` | Tool execution port interface |

## Repository Interfaces (repositories/)

Each file defines an abstract class with async methods. Implementations live in
`infrastructure/adapters/secondary/persistence/sql_*_repository.py`.

Key repositories: `ConversationRepository`, `MessageRepository`, `MemoryRepository`,
`ProjectRepository`, `UserRepository`, `SkillRepository`, `SubAgentRepository`,
`TaskRepository`, `MCPServerRepository`, `AgentExecutionRepository`

Pattern: All repos follow `find_by_id()`, `save()`, `delete()`, `list_by_*()` method naming.

## Service Interfaces (services/)

Abstract service classes that may have multiple implementations.
Key services: `GraphServicePort`, `EmbeddingServicePort`, `EventBusPort`,
`SearchServicePort`, `LLMServicePort`

## Gotchas

- Repository interfaces accept and return DOMAIN entities, never SQLAlchemy models
- All methods are `async` — sync implementations must be wrapped
- `__init__.py` files re-export all interfaces for convenient importing
- Some ports in `agent/` and `mcp/` subdirs are agent-system-specific
- `tool_port.py` at top level defines the generic tool execution interface
