# Project Sandbox Lifecycle Management Refactoring

## Overview

This document describes the refactoring of the sandbox lifecycle management system to ensure **each project has exactly one persistent sandbox** that remains running for the lifetime of the project.

## Architecture Changes

### Before
- Sandboxes were created on-demand without project association
- No persistent mapping between projects and sandboxes
- Sandboxes had to be managed manually by ID
- No automatic recovery or health monitoring

### After
- Each project has exactly one persistent sandbox
- Lazy creation on first use (`get_or_create_sandbox`)
- Automatic health monitoring and recovery
- Project-scoped sandbox operations (no need to manage sandbox IDs)

## New Components

### 1. Domain Model: `ProjectSandbox`
**Location:** `src/domain/model/sandbox/project_sandbox.py`

```python
@dataclass(kw_only=True)
class ProjectSandbox(Entity):
    project_id: str
    tenant_id: str
    sandbox_id: str
    status: ProjectSandboxStatus
    created_at: datetime
    last_accessed_at: datetime
    health_checked_at: Optional[datetime]
    error_message: Optional[str]
    metadata: Dict[str, Any]
```

**Status Lifecycle:**
```
PENDING → CREATING → RUNNING ←→ UNHEALTHY (auto-recover)
                    ↓
                STOPPED → (restart)
                    ↓
                TERMINATED
                    ↓
                   ERROR
```

### 2. Repository Port: `ProjectSandboxRepository`
**Location:** `src/domain/ports/repositories/project_sandbox_repository.py`

Provides persistent storage for Project-Sandbox associations with methods:
- `save(association)` - Create or update
- `find_by_project(project_id)` - Get project's sandbox
- `find_by_sandbox(sandbox_id)` - Get sandbox's project
- `find_stale(max_idle_seconds)` - Find inactive sandboxes
- `delete_by_project(project_id)` - Remove association

### 3. SQLAlchemy Model: `ProjectSandbox`
**Location:** `src/infrastructure/adapters/secondary/persistence/models.py`

Database table `project_sandboxes`:
```sql
- id (PK)
- project_id (FK, UNIQUE)
- tenant_id (FK)
- sandbox_id (UNIQUE)
- status (index)
- created_at
- started_at
- last_accessed_at (index)
- health_checked_at
- error_message
- metadata_json
```

### 4. Repository Implementation: `SqlAlchemyProjectSandboxRepository`
**Location:** `src/infrastructure/adapters/secondary/persistence/sql_project_sandbox_repository.py`

SQLAlchemy-based implementation with ORM-domain conversion.

### 5. Service: `ProjectSandboxLifecycleService`
**Location:** `src/application/services/project_sandbox_lifecycle_service.py`

Core service providing:

#### Primary Methods
- `get_or_create_sandbox(project_id, tenant_id)` - Lazy initialization
- `ensure_sandbox_running(project_id, tenant_id)` - Guarantee running state
- `get_project_sandbox(project_id)` - Get info if exists
- `execute_tool(project_id, tool_name, arguments)` - Execute MCP tools

#### Lifecycle Management
- `health_check(project_id)` - Check sandbox health
- `restart_project_sandbox(project_id)` - Restart sandbox
- `terminate_project_sandbox(project_id)` - Clean shutdown
- `sync_sandbox_status(project_id)` - Sync DB with container state

#### Bulk Operations
- `list_project_sandboxes(tenant_id)` - List tenant's sandboxes
- `cleanup_stale_sandboxes(max_idle_seconds)` - Clean up unused

### 6. REST API Router: `project_sandbox`
**Location:** `src/infrastructure/adapters/primary/web/routers/project_sandbox.py`

New API endpoints under `/api/v1/projects`:

#### Sandbox Management
```
GET    /{project_id}/sandbox              # Get sandbox info
POST   /{project_id}/sandbox              # Ensure/create sandbox
GET    /{project_id}/sandbox/health       # Health check
POST   /{project_id}/sandbox/execute      # Execute MCP tool
POST   /{project_id}/sandbox/restart      # Restart sandbox
DELETE /{project_id}/sandbox              # Terminate sandbox
GET    /{project_id}/sandbox/sync         # Sync status
```

#### Desktop/Terminal Services
```
POST   /{project_id}/sandbox/desktop      # Start desktop
DELETE /{project_id}/sandbox/desktop      # Stop desktop
POST   /{project_id}/sandbox/terminal     # Start terminal
DELETE /{project_id}/sandbox/terminal     # Stop terminal
```

#### Admin Operations
```
GET    /sandboxes                         # List all sandboxes
POST   /sandboxes/cleanup                 # Clean up stale
```

## Configuration

New settings in `src/configuration/config.py`:

```python
sandbox_profile_type: str = Field(default="standard")
sandbox_auto_recover: bool = Field(default=True)
sandbox_health_check_interval: int = Field(default=60)
```

## Usage Examples

### Python API

```python
from src.application.services.project_sandbox_lifecycle_service import (
    ProjectSandboxLifecycleService
)

# Get or create project's sandbox
service = container.project_sandbox_lifecycle_service()
sandbox = await service.get_or_create_sandbox(
    project_id="proj-123",
    tenant_id="tenant-456"
)

# Execute tools without managing sandbox_id
result = await service.execute_tool(
    project_id="proj-123",
    tool_name="bash",
    arguments={"command": "ls -la"}
)
```

### REST API

```bash
# Ensure sandbox exists for project
curl -X POST http://localhost:8000/api/v1/projects/proj-123/sandbox \
  -H "Authorization: Bearer $API_KEY"

# Execute command in project's sandbox
curl -X POST http://localhost:8000/api/v1/projects/proj-123/sandbox/execute \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "tool_name": "bash",
    "arguments": {"command": "echo Hello"},
    "timeout": 30
  }'

# Start desktop for project
curl -X POST http://localhost:8000/api/v1/projects/proj-123/sandbox/desktop \
  -H "Authorization: Bearer $API_KEY"
```

## Testing

New test files:
- `src/tests/unit/domain/model/test_project_sandbox.py` (17 tests)
- `src/tests/unit/repositories/test_project_sandbox_repository.py` (11 tests)
- `src/tests/unit/services/test_project_sandbox_lifecycle_service.py` (20 tests)

Total: **48 new unit tests**

Run tests:
```bash
uv run pytest src/tests/unit/domain/model/test_project_sandbox.py -v
uv run pytest src/tests/unit/repositories/test_project_sandbox_repository.py -v
uv run pytest src/tests/unit/services/test_project_sandbox_lifecycle_service.py -v
```

## Migration

The `project_sandboxes` table is automatically created by `initialize_database()` on application startup via SQLAlchemy's `create_all()`.

## Backward Compatibility

The existing sandbox router (`/api/v1/sandbox/*`) remains available for backward compatibility. New projects should use the project-scoped endpoints (`/api/v1/projects/{project_id}/sandbox/*`).

## Benefits

1. **Simplified API** - No need to track sandbox IDs
2. **Resource Efficiency** - One sandbox per project, no duplicates
3. **Automatic Recovery** - Health monitoring and auto-restart
4. **Lifecycle Management** - Sandboxes tied to project lifecycle
5. **Better Multi-tenancy** - Tenant-scoped sandbox management
