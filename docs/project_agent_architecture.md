# Project-Level ReActAgent Architecture

This document describes the refactored ReActAgent lifecycle architecture with project-level persistent Temporal instances.

## Overview

The new architecture introduces **Project-Level ReActAgent** instances, where each project has its own persistent Temporal workflow. This provides:

1. **Resource Isolation**: Each project has independent tool sets, skills, and configurations
2. **Persistent State**: Agent instances remain alive across multiple chat requests
3. **Project-Scoped Caching**: Caches are isolated per project
4. **Independent Lifecycle**: Each project agent can be started, paused, resumed, and stopped independently

## Architecture Components

### 1. Core Classes

#### ProjectReActAgent (`src/infrastructure/agent/core/project_react_agent.py`)

The main class for project-level agent instances:

```python
class ProjectReActAgent:
    def __init__(self, config: ProjectAgentConfig)
    async def initialize(self, force_refresh: bool = False) -> bool
    async def execute_chat(...) -> AsyncIterator[Dict[str, Any]]
    async def pause(self) -> bool
    async def resume(self) -> bool
    async def stop(self) -> bool
    async def refresh(self) -> bool
    def get_status(self) -> ProjectAgentStatus
    def get_metrics(self) -> ProjectAgentMetrics
```

**Key Features:**
- Lifecycle management (initialize, execute, pause, resume, stop)
- Project-scoped resource caching
- Metrics tracking (latency percentiles, success rates)
- Concurrent chat limiting
- Automatic cleanup on stop

#### ProjectAgentManager (`src/infrastructure/agent/core/project_react_agent.py`)

Manages multiple ProjectReActAgent instances:

```python
class ProjectAgentManager:
    async def get_or_create_agent(...) -> Optional[ProjectReActAgent]
    def get_agent(...) -> Optional[ProjectReActAgent]
    async def stop_agent(...) -> bool
    async def stop_all(self) -> None
    def list_agents(self) -> List[Dict[str, Any]]
```

**Key Features:**
- Global manager for all project agents
- Background cleanup of idle agents
- Centralized lifecycle management
- Statistics and monitoring

### 2. Temporal Workflows

#### ProjectAgentWorkflow (`src/infrastructure/adapters/secondary/temporal/workflows/project_agent_workflow.py`)

Long-running workflow for project-level agents:

```python
@workflow.defn(name="project_agent")
class ProjectAgentWorkflow:
    @workflow.run
    async def run(self, input: ProjectAgentWorkflowInput)
    
    @workflow.update
    async def chat(self, request: ProjectChatRequest) -> ProjectChatResult
    
    @workflow.update
    async def refresh(self) -> Dict[str, Any]
    
    @workflow.query
    def get_status(self) -> ProjectAgentWorkflowStatus
    
    @workflow.query
    def get_metrics(self) -> ProjectAgentMetrics
    
    @workflow.signal
    def stop(self)
    
    @workflow.signal
    def pause(self)
    
    @workflow.signal
    def resume(self)
```

**Workflow ID Pattern:**
```
project_agent_{tenant_id}_{project_id}_{agent_mode}
```

**Features:**
- Long-running workflow (stays alive until stop signal or idle timeout)
- Update handlers for synchronous chat requests
- Query handlers for status and metrics
- Signal handlers for lifecycle control
- Automatic recovery on session errors
- Idle timeout with configurable duration

### 3. Temporal Activities

#### Project Agent Activities (`src/infrastructure/adapters/secondary/temporal/activities/project_agent.py`)

```python
@activity.defn
async def initialize_project_agent_activity(input_data: Dict) -> Dict

@activity.defn
async def execute_project_chat_activity(input_data: Dict) -> Dict

@activity.defn
async def cleanup_project_agent_activity(input_data: Dict) -> Dict
```

**Features:**
- Activity-level caching of ProjectReActAgent instances
- Efficient reuse across workflow executions
- Proper cleanup on workflow completion

### 4. Application Service

#### ProjectAgentService (`src/application/services/project_agent_service.py`)

High-level service for managing project agents:

```python
class ProjectAgentService:
    async def start_project_agent(self, options: ProjectAgentStartOptions) -> ProjectAgentInfo
    async def stop_project_agent(self, tenant_id, project_id, ...) -> bool
    async def pause_project_agent(self, tenant_id, project_id, ...) -> bool
    async def resume_project_agent(self, tenant_id, project_id, ...) -> bool
    async def refresh_project_agent(self, tenant_id, project_id, ...) -> bool
    async def chat(self, options: ProjectAgentChatOptions) -> ProjectChatResult
    async def get_status(self, tenant_id, project_id, ...) -> Optional[ProjectAgentWorkflowStatus]
    async def get_metrics(self, tenant_id, project_id, ...) -> Optional[Dict]
    async def list_project_agents(self, tenant_id=None) -> List[ProjectAgentInfo]
```

## Usage Examples

### Starting a Project Agent

```python
from temporalio.client import Client
from src.application.services.project_agent_service import (
    ProjectAgentService,
    ProjectAgentStartOptions,
)

# Get Temporal client
client = await Client.connect("localhost:7233")

# Create service
service = ProjectAgentService(client)

# Start project agent
info = await service.start_project_agent(
    ProjectAgentStartOptions(
        tenant_id="tenant-123",
        project_id="project-456",
        agent_mode="default",
        idle_timeout_seconds=1800,  # 30 minutes
        max_concurrent_chats=10,
    )
)

print(f"Agent running: {info.is_running}")
print(f"Workflow ID: {info.workflow_id}")
```

### Sending a Chat Request

```python
from src.application.services.project_agent_service import ProjectAgentChatOptions

# Send chat request
result = await service.chat(
    ProjectAgentChatOptions(
        tenant_id="tenant-123",
        project_id="project-456",
        conversation_id="conv-789",
        message_id="msg-abc",
        user_message="Hello, agent!",
        user_id="user-xyz",
        conversation_context=[],
    )
)

if result.is_error:
    print(f"Error: {result.error_message}")
else:
    print(f"Response: {result.content}")
    print(f"Execution time: {result.execution_time_ms}ms")
```

### Querying Status and Metrics

```python
# Get status
status = await service.get_status("tenant-123", "project-456")
print(f"Initialized: {status.is_initialized}")
print(f"Active chats: {status.active_chats}")
print(f"Total chats: {status.total_chats}")

# Get metrics
metrics = await service.get_metrics("tenant-123", "project-456")
print(f"Avg latency: {metrics['avg_latency_ms']}ms")
print(f"P95 latency: {metrics['p95_latency_ms']}ms")
print(f"Success rate: {metrics['successful_requests'] / metrics['total_requests'] * 100}%")
```

### Stopping a Project Agent

```python
# Graceful stop
success = await service.stop_project_agent(
    tenant_id="tenant-123",
    project_id="project-456",
    graceful=True,
    timeout_seconds=30.0,
)

# Or force stop
success = await service.stop_project_agent(
    tenant_id="tenant-123",
    project_id="project-456",
    graceful=False,
)
```

## Configuration

### Environment Variables

```bash
# Agent Worker Configuration
AGENT_TEMPORAL_TASK_QUEUE=memstack-agent-tasks
AGENT_WORKER_CONCURRENCY=50
AGENT_SESSION_CLEANUP_INTERVAL=600

# Project Agent Defaults
PROJECT_AGENT_IDLE_TIMEOUT_SECONDS=1800
PROJECT_AGENT_MAX_CONCURRENT_CHATS=10
PROJECT_AGENT_MCP_TOOLS_TTL_SECONDS=300
```

### ProjectAgentConfig Options

```python
@dataclass
class ProjectAgentConfig:
    tenant_id: str                          # Required: Tenant identifier
    project_id: str                         # Required: Project identifier
    agent_mode: str = "default"             # Agent mode (default, plan, etc.)
    
    # LLM Configuration
    model: Optional[str] = None             # LLM model name
    api_key: Optional[str] = None           # API key (or use provider config)
    base_url: Optional[str] = None          # API base URL
    temperature: float = 0.7                # Sampling temperature
    max_tokens: int = 4096                  # Max output tokens
    max_steps: int = 20                     # Max ReAct steps
    
    # Session Configuration
    idle_timeout_seconds: int = 1800        # Workflow idle timeout
    max_concurrent_chats: int = 10          # Max concurrent chats
    
    # Tool Configuration
    mcp_tools_ttl_seconds: int = 300        # MCP tools cache TTL
    
    # Feature Flags
    enable_skills: bool = True              # Enable skill system
    enable_subagents: bool = True           # Enable subagent routing
```

## Architecture (Post-Refactoring 2026-02)

> **Note**: As of 2026-02, `AgentExecutionWorkflow` and `AgentSessionWorkflow` have been **removed**.
> `ProjectAgentWorkflow` is now the **only** agent workflow.

### Current Architecture

- **Workflow ID**: `project_agent_{tenant_id}_{project_id}_{agent_mode}`
- **Lifecycle states**: initialized, active, paused, stopped
- **Signals**: stop, pause, resume, extend_timeout, restart
- **Activities**: initialize, execute_chat, cleanup

### Metrics (OpenTelemetry)

| Metric | Type | Description |
|--------|------|-------------|
| `project_agent.init_latency_ms` | Histogram | Agent initialization latency |
| `project_agent.init_errors` | Counter | Initialization error count |
| `project_agent.chat_total` | Counter | Total chat requests |
| `project_agent.chat_latency_ms` | Histogram | Chat execution latency |
| `project_agent.chat_errors` | Counter | Chat error count |
| `project_agent.active_count` | Gauge | Active agent instances |

## Usage Guide

### For Service Layer

Use `ProjectAgentWorkflow` for all agent interactions:

```python
from src.infrastructure.adapters.secondary.temporal.workflows.project_agent_workflow import (
    ProjectAgentWorkflow,
    ProjectAgentWorkflowInput,
    ProjectChatRequest,
)

# Start workflow
handle = await client.start_workflow(
    ProjectAgentWorkflow.run,
    ProjectAgentWorkflowInput(
        tenant_id=tenant_id,
        project_id=project_id,
        agent_mode="default",
    ),
    id=f"project_agent_{tenant_id}_{project_id}_default",
)

# Send chat
result = await handle.execute_update(
    ProjectAgentWorkflow.chat,
    ProjectChatRequest(
        conversation_id=conversation_id,
        user_message=message,
    ),
)

# Stop/restart
await handle.signal(ProjectAgentWorkflow.stop)
await handle.signal(ProjectAgentWorkflow.restart)
```

### For Worker Configuration

Only `ProjectAgentWorkflow` is registered in `agent_worker.py`:

```python
workflows=[
    ProjectAgentWorkflow,  # The only agent workflow
],
activities=[
    initialize_project_agent_activity,
    execute_project_chat_activity,
    cleanup_project_agent_activity,
],
```

## Monitoring and Debugging

### List Active Project Agents

```python
agents = await service.list_project_agents(tenant_id="tenant-123")
for agent in agents:
    print(f"{agent.project_id}: {agent.is_running} (chats: {agent.total_chats})")
```

### Check Project Agent Health

```python
is_healthy = await service.is_project_agent_running(
    tenant_id="tenant-123",
    project_id="project-456",
)
```

### Log Analysis

Look for these log patterns:

```
ProjectReActAgent[{tenant}:{project}:{mode}]: Initialized in {ms}ms
ProjectReActAgent[{tenant}:{project}:{mode}]: Executing chat conversation={conv_id}
ProjectReActAgent[{tenant}:{project}:{mode}]: Chat completed in {ms}ms
ProjectAgentWorkflow: Starting {workflow_id}
ProjectAgentService: Started workflow {workflow_id}
```

## Performance Considerations

1. **First Request Latency**: ~300-800ms (includes initialization)
2. **Subsequent Requests**: <50ms (uses cached components)
3. **Memory per Project**: ~50-100MB (depends on tool count)
4. **Idle Timeout**: Default 30 minutes (configurable)

## Future Enhancements

1. **Auto-scaling**: Scale project agents based on load
2. **Cross-project Skills**: Shared skills across projects
3. **Project Templates**: Pre-configured agent templates
4. **Advanced Metrics**: Export to Prometheus/Grafana
5. **Circuit Breaker**: Automatic failover on errors
