# Sandbox-First Architecture Design

> **Status**: DRAFT  
> **Author**: Architecture Analysis Session  
> **Date**: 2026-03-01  
> **Companion Doc**: [Plugin Tool Pipeline Fix](./PLUGIN_TOOL_PIPELINE_FIX.md) (Phase 1)

---

## Executive Summary

MemStack's agent system currently executes tools across two distinct environments: the host
agent process and sandbox Docker containers. This split creates inconsistency in dependency
management, error handling, artifact extraction, and security isolation. Custom tools and
plugins fail silently because the host-side tool pipeline lacks the dependency installation,
parameter schema extraction, and result normalization that the sandbox path provides.

This document proposes a **sandbox-first architecture** where:

1. **ALL tool execution defaults to sandbox containers** -- custom tools, plugins, skills,
   and MCP tools all run inside isolated Docker containers.
2. **A small set of host-only tools** (memory, HITL, todo, env) remain on the host because
   they require direct access to PostgreSQL, Neo4j, Redis, or the actor event stream.
3. **A workspace persistence layer** ensures that files, artifacts, and work products survive
   sandbox destruction and recreation through stable bind mounts and manifest tracking.
4. **A unified artifact pipeline** replaces the current dual-upload-path architecture with a
   single flow through `ArtifactService` + `S3StorageAdapter`.

The design subsumes the [Plugin Tool Pipeline Fix](./PLUGIN_TOOL_PIPELINE_FIX.md) as a subset
of Phase 2 (Tool Migration).

---

## 1. Problem Statement

### 1.1 Fragmented Tool Execution

The agent system has **12 distinct tool loading steps** in `agent_worker_state.py`
(lines 411-453), each with its own execution semantics:

- Built-in tools run as Python objects in the agent process.
- Sandbox MCP tools delegate to containers via `sandbox_port.call_tool()`.
- Plugin tools attempt host-side execution with no dependency management.
- Custom tools load Python files from `.memstack/tools/` with no sandboxing.

This fragmentation means:
- Plugin tools crash because the host lacks their runtime dependencies.
- Custom tools have no security isolation -- they run with full agent process privileges.
- Each tool category has its own error handling, result format, and artifact extraction path.

### 1.2 Workspace Volatility

The workspace bind mount defaults to `/tmp/memstack-sandbox/{project_id}`, which is:
- Ephemeral on many Linux distributions (tmpfs, cleared on reboot).
- Not backed up or synced to persistent storage.
- Dependent on the host filesystem remaining intact across sandbox recreation.

If the host machine reboots or the `/tmp` directory is cleaned, all workspace data is lost.

### 1.3 Artifact Pipeline Duplication

Two co-existing upload paths create confusion:
1. `ArtifactHandler` in the processor uses synchronous boto3 in a thread pool.
2. `ArtifactService` uses async aioboto3 via `S3StorageAdapter`.

Both emit artifact events independently, risking duplicate uploads and inconsistent
artifact IDs across the `CREATED -> READY` lifecycle.

### 1.4 Security Gap

Custom tools from `.memstack/tools/` execute with the same privileges as the agent process
itself -- full access to the database connection, configuration secrets, and the host
filesystem. This is unacceptable for user-uploaded tool code.

---

## 2. Current Architecture Analysis

### 2.1 Tool Execution Topology (Current State / 当前工具执行拓扑)

The following table maps every tool category to its current execution location:

| # | Tool Category | Examples | Execution | Dispatch Mechanism | Loading Function | Source File |
|---|---|---|---|---|---|---|
| 1 | Built-in tools | `web_search`, `web_scrape`, `ask_clarification`, `request_decision` | HOST | Direct `AgentTool.execute()` | `_get_or_create_builtin_tools` | `agent_worker_state.py` |
| 2 | Sandbox MCP tools | `bash`, `read`, `write`, `edit`, `glob`, `grep`, `screenshot` | SANDBOX | `SandboxMCPToolWrapper` -> `sandbox_port.call_tool()` | `_add_sandbox_tools` -> `_load_project_sandbox_tools` | `sandbox_tool_wrapper.py` |
| 3 | Skill loader | `SkillLoaderTool` | HOST | `AgentTool.execute()` | `_add_skill_loader_tool` | `agent_worker_state.py` |
| 4 | Skill installer | `SkillInstallerTool` | HOST | `AgentTool.execute()` | `_add_skill_installer_tools` | `agent_worker_state.py` |
| 5 | Skill sync | `SkillSyncTool` | HOST | `AgentTool.execute()` (may use sandbox_adapter) | `_add_skill_sync_tool` | `agent_worker_state.py` |
| 6 | Environment tools | `GetEnvVarTool`, `RequestEnvVarTool` | HOST | `AgentTool.execute()` | `_add_env_var_tools` | `agent_worker_state.py` |
| 7 | HITL tools | `ClarificationTool`, `DecisionTool` | HOST | `AgentTool.execute()` + Redis pub/sub | `_add_hitl_tools` | `agent_worker_state.py` |
| 8 | Todo tools | `TodoReadTool`, `TodoWriteTool` | HOST | `AgentTool.execute()` + pending events -> actor stream | `_add_todo_tools` | `agent_worker_state.py` |
| 9 | Memory tools | `MemorySearchTool`, etc. | HOST | `AgentTool.execute()` (needs DB + Neo4j) | `_add_memory_tools` | `agent_worker_state.py` |
| 10 | Register MCP | `RegisterMCPServerTool` | HOST | `AgentTool.execute()` | `_add_register_mcp_server_tool` | `agent_worker_state.py` |
| 11 | Plugin tools (non-sandbox) | `PDFCreateTool`, etc. | HOST (BROKEN) | Raw object, no wrapper, no deps | `_add_plugin_tools` | `registry.py` lines 641-695 |
| 12 | Sandbox plugin tools | (declared sandbox tools) | SANDBOX | `create_sandbox_plugin_tool` -> `sandbox_port.call_tool()` | `_add_sandbox_plugin_tools` | `sandbox_plugin_tool_wrapper.py` |
| 13 | Custom tools | `.memstack/tools/*.py` | HOST | `CustomToolLoader` -> `ToolInfo.execute()` | `_add_custom_tools` | `custom_tool_loader.py` |

**Key observations:**
- Only categories 2 and 12 execute in the sandbox.
- Categories 11 and 13 are the most problematic: host-side execution with no isolation or dependency management.
- Category 11 is actively broken (5 root causes documented in the companion Phase 1 doc).

### 2.2 Sandbox Infrastructure (Current State / 当前沙箱基础设施)

#### Container Architecture

```
Host Machine
+------------------------------------------------------------+
|  Agent Process (Ray Actor)                                  |
|  +------------------------------------------------------+  |
|  | SessionProcessor                                      |  |
|  |   tools: dict[str, ToolDefinition]                   |  |
|  |   _execute_tool(name, args) -> result                |  |
|  +------+-----------------------------------------------+  |
|         |                                                   |
|         | sandbox_port.call_tool(sandbox_id, tool, args)    |
|         v                                                   |
|  +------+-----------------------------------------------+  |
|  | MCPSandboxAdapter                                     |  |
|  |   _workspace_base = /tmp/memstack-sandbox             |  |
|  |   _mcp_image = sandbox-mcp-server:latest              |  |
|  |   _max_concurrent_sandboxes = 10                      |  |
|  +------+-----------------------------------------------+  |
|         |                                                   |
|         | Docker API + WebSocket                             |
|         v                                                   |
|  +------+-----------------------------------------------+  |
|  | Docker Container (sandbox-mcp-server)                 |  |
|  |   /workspace  <-- bind mount from host                |  |
|  |   Port 18765: MCP WebSocket (tool execution)          |  |
|  |   Port 16080: Desktop (noVNC/KasmVNC)                 |  |
|  |   Port 17681: Terminal (ttyd)                         |  |
|  |   30+ MCP tools (bash, read, write, edit, etc.)       |  |
|  +------------------------------------------------------+  |
+------------------------------------------------------------+
```

#### Workspace Bind Mount

The workspace directory is created from configuration:

```python
# mcp_sandbox_adapter.py line 3042
host_workspace_path = f"{self._workspace_base}/{project_id}"

# config.py line 266-268
sandbox_workspace_base: str = Field(
    default="/tmp/memstack-sandbox", alias="SANDBOX_WORKSPACE_BASE"
)
```

This creates a stable, project-scoped directory on the host:
- Path pattern: `/tmp/memstack-sandbox/{project_id}`
- Mounted as: `/workspace` (read-write) inside the container
- The same host directory is reused when a sandbox is recreated for the same project

**Persistence characteristics:**
- Files survive sandbox container destruction/recreation (bind mount, not container storage).
- Files do NOT survive host reboot on systems where `/tmp` is tmpfs.
- Files do NOT survive if `workspace_base` directory is manually deleted.
- No backup or sync to durable storage exists by default.

#### Additional Volume Mounts

```python
# mcp_sandbox_adapter.py lines 565-578
# Read-only volumes from SandboxConfig.volumes
for host_path, container_path in config.volumes.items():
    volumes[host_path] = {"bind": container_path, "mode": "ro"}

# Read-write volumes from SandboxConfig.rw_volumes
for host_path, container_path in config.rw_volumes.items():
    volumes[host_path] = {"bind": container_path, "mode": "rw"}
```

Configuration also supports:
- `SANDBOX_HOST_SOURCE_PATH` -> mounted read-only at `/host_src` (project source code)
- `SANDBOX_HOST_MEMSTACK_PATH` -> mounted read-write at `/workspace/.memstack` (.memstack overlay)

#### State Machine

```
STARTING ──> RUNNING ──> ERROR
    |            |          |
    |            v          |
    +------> TERMINATED <--+
```

- Defined in `SimplifiedSandboxStateMachine` (`simplified_state_machine.py`)
- State transitions are NOT persisted -- container restart loses all state.
- Health monitoring via WebSocket ping with configurable interval (default 60s).
- Auto-recovery: `SANDBOX_AUTO_RECOVER=true` attempts container restart on failure.

#### Container Lifecycle

| Event | Handler | Behavior |
|-------|---------|----------|
| Create | `MCPSandboxAdapter.create_sandbox()` | Docker create + start, port allocation, MCP connect |
| Health check | `health_monitor.py` | WebSocket ping, transition to ERROR after N failures |
| Recover | `reconciler.py` | Restart container, reconnect MCP, restore state to RUNNING |
| Destroy | `container_manager.stop/remove` | Docker stop + remove, port deallocation |
| App shutdown | `MCPSandboxAdapter.cleanup()` | Remove all containers by label |

### 2.3 Artifact & Workspace Persistence (Current State / 当前制品与工作区持久化)

#### Artifact Extraction Flow

```
Tool Execution
    |
    v
SessionProcessor._execute_tool()
    |
    v
ArtifactHandler.process_tool_artifacts(tool_name, result)
    |
    +-- Parse result for artifact content:
    |     - export_artifact tool results (explicit export)
    |     - batch_export_artifacts results
    |     - MCP content arrays (embedded images/resources)
    |
    +-- Yield AgentArtifactCreatedEvent (immediate, placeholder)
    |
    +-- Schedule background upload:
          ArtifactHandler._threaded_upload()
              -> _sync_upload() (synchronous boto3 in thread)
              -> Publish AgentArtifactReadyEvent (via actor stream)
```

#### Dual Upload Paths (Problem)

**Path 1: ArtifactHandler (processor-level, synchronous boto3)**
- File: `src/infrastructure/agent/processor/artifact_handler.py`
- Uses `boto3.client("s3").put_object()` in `_sync_upload()`
- Runs in thread pool via `asyncio.run_in_executor()`
- Publishes `AgentArtifactReadyEvent` via `actor._publish_event_to_stream()`
- Tightly coupled to actor internals

**Path 2: ArtifactService (application-level, async aioboto3)**
- File: `src/application/services/artifact_service.py`
- Uses `S3StorageAdapter` (`src/infrastructure/adapters/secondary/storage/s3_storage_adapter.py`)
- Fully async via aioboto3
- Publishes events via injected `event_publisher`
- Clean hexagonal architecture

**Overlap risks:**
- `SandboxArtifactIntegration` (artifact_integration.py) uses `ArtifactService`
- `ArtifactHandler` in the processor uses its own boto3 path
- Both can process the same tool result, potentially creating duplicate artifacts

#### Sandbox Artifact Detection

`SandboxArtifactIntegration` (`artifact_integration.py`) monitors sandbox output directories:

```python
DEFAULT_OUTPUT_DIRS = [
    "/workspace/output",
    "/workspace/outputs",
    "/tmp/output",
    "/home/user/output",
    "/output",
]
```

Detection is **reactive** (post-tool-execution scan), not proactive (real-time filesystem watch).
It tracks known files per sandbox to avoid duplicate uploads.

#### Artifact Domain Model

```python
# src/domain/model/artifact/artifact.py
class ArtifactStatus(str, Enum):
    PENDING = "pending"
    UPLOADING = "uploading"
    READY = "ready"
    ERROR = "error"
    DELETED = "deleted"

# Storage key format:
# artifacts/{tenant_id}/{project_id}/{date}/{tool_execution_id_or_uuid}_{filename}
```

#### What Is Missing

1. **No centralized file sync** -- only targeted reads and output dir scanning.
2. **No workspace manifest** -- no tracking of what files exist, when they were modified.
3. **No backup to durable storage** -- workspace data exists only on the host bind mount.
4. **No lifecycle hooks** -- sandbox destruction does not trigger workspace preservation.
5. **No conflict resolution** -- concurrent writes from host and container are not handled.

---

## 3. Target Architecture

### 3.1 Design Principles (设计原则)

1. **Sandbox by default, host by exception.** Every tool executes in a sandbox container
   unless it requires direct access to host infrastructure (DB, Redis, graph, actor stream).

2. **Transparent routing.** The `SessionProcessor` should not know or care whether a tool
   runs in the sandbox or on the host. The execution layer handles routing transparently.

3. **Unified dependency management.** All sandbox tools use the same `DependencyOrchestrator`
   for runtime dependency installation. No separate paths for plugins vs. custom tools.

4. **Workspace durability.** Workspace data must survive sandbox destruction, host reboot,
   and planned migrations. The default configuration must be safe for production.

5. **Single artifact pipeline.** One upload path, one event lifecycle, one storage adapter.
   `ArtifactService` + `S3StorageAdapter` is the canonical path.

6. **Backward compatibility.** Existing sandbox MCP tools continue working unchanged.
   Host-only tools continue working unchanged. Migration is additive.

### 3.2 Execution Topology (Target State / 目标执行拓扑)

```
SessionProcessor
    |
    | tool_def.execute(args)
    v
ToolExecutionRouter
    |
    +-- tool.execution_mode == HOST_ONLY?
    |       |
    |       v
    |   HostToolExecutor
    |       -> Direct tool.execute(args)
    |       -> Return ToolResult
    |
    +-- tool.execution_mode == SANDBOX?
            |
            v
        SandboxToolExecutor
            -> DependencyOrchestrator.ensure_dependencies()
            -> sandbox_port.call_tool(sandbox_id, tool_name, args)
            -> Normalize result to ToolResult
            -> ArtifactService.extract_and_upload()
            -> Return ToolResult
```

**Target tool classification:**

| # | Tool Category | Target Execution | Rationale |
|---|---|---|---|
| 1 | web_search, web_scrape | HOST | Simple HTTP calls, no security concern, low migration value |
| 2 | Sandbox MCP tools | SANDBOX | Already sandbox-native, no change |
| 3 | SkillLoaderTool | HOST | Reads skill metadata for LLM prompt injection, no computation |
| 4 | SkillInstallerTool | HOST -> SANDBOX | Installs skill files -- should write to sandbox workspace |
| 5 | SkillSyncTool | HOST -> SANDBOX | Syncs resources between host and sandbox |
| 6 | Environment tools | HOST | Reads host process environment variables |
| 7 | HITL tools | HOST | Requires Redis pub/sub for real-time user interaction |
| 8 | Todo tools | HOST | Requires actor event stream for real-time frontend updates |
| 9 | Memory tools | HOST | Requires PostgreSQL + Neo4j connections |
| 10 | RegisterMCPServerTool | HOST | Manages sandbox-level MCP server registration |
| 11 | Plugin tools (non-sandbox) | SANDBOX | Fix broken path + migrate to sandbox execution |
| 12 | Sandbox plugin tools | SANDBOX | Already sandbox-native, no change |
| 13 | Custom tools | SANDBOX | Critical security fix -- user code must be sandboxed |

### 3.3 Unified Sandbox Execution Layer (统一沙箱执行层)

#### ToolExecutionRouter

A new component that wraps all tools before they enter the `SessionProcessor.tools` dict:

```python
# New file: src/infrastructure/agent/core/tool_execution_router.py

@dataclass
class ToolExecutionConfig:
    """Per-tool execution configuration."""
    execution_mode: Literal["host", "sandbox"]
    sandbox_dependencies: list[str] = field(default_factory=list)
    sandbox_tool_name: str | None = None  # Override name for sandbox dispatch

class ToolExecutionRouter:
    """Routes tool execution to host or sandbox based on tool metadata."""

    def __init__(
        self,
        sandbox_executor: SandboxToolExecutor,
        host_executor: HostToolExecutor,
    ) -> None:
        self._sandbox = sandbox_executor
        self._host = host_executor

    def wrap_tool(
        self,
        tool_info: ToolInfo,
        config: ToolExecutionConfig,
    ) -> ToolInfo:
        """Wrap a tool with execution routing."""
        if config.execution_mode == "sandbox":
            return self._sandbox.wrap(tool_info, config)
        return self._host.wrap(tool_info, config)
```

#### SandboxToolExecutor

Encapsulates the sandbox execution pattern currently split across `SandboxMCPToolWrapper`
and `create_sandbox_plugin_tool`:

```python
# New file: src/infrastructure/agent/core/sandbox_tool_executor.py

class SandboxToolExecutor:
    """Unified executor for all sandbox-bound tools."""

    def __init__(
        self,
        sandbox_port: SandboxPort,
        sandbox_id: str,
        dependency_orchestrator: DependencyOrchestrator,
        artifact_service: ArtifactService,
    ) -> None:
        self._sandbox_port = sandbox_port
        self._sandbox_id = sandbox_id
        self._dep_orchestrator = dependency_orchestrator
        self._artifact_service = artifact_service

    def wrap(self, tool_info: ToolInfo, config: ToolExecutionConfig) -> ToolInfo:
        """Create a ToolInfo that delegates execution to the sandbox."""
        original_execute = tool_info.execute

        async def sandbox_execute(ctx: Any = None, **kwargs: Any) -> ToolResult:
            # 1. Ensure runtime dependencies
            if config.sandbox_dependencies:
                await self._dep_orchestrator.ensure_dependencies(
                    self._sandbox_id, config.sandbox_dependencies
                )

            # 2. Execute in sandbox
            tool_name = config.sandbox_tool_name or tool_info.name
            mcp_result = await self._sandbox_port.call_tool(
                self._sandbox_id, tool_name, kwargs
            )

            # 3. Normalize result
            return self._normalize_result(mcp_result)

        return ToolInfo(
            name=tool_info.name,
            description=tool_info.description,
            parameters=tool_info.parameters,
            execute=sandbox_execute,
        )
```

#### HostToolExecutor

A thin pass-through for host-only tools. Exists for symmetry and future instrumentation:

```python
class HostToolExecutor:
    """Pass-through executor for host-only tools."""

    def wrap(self, tool_info: ToolInfo, config: ToolExecutionConfig) -> ToolInfo:
        # No wrapping needed -- host tools execute directly
        return tool_info
```

### 3.4 Tool Classification & Migration Strategy (工具分类与迁移策略)

#### Classification Criteria

A tool is classified as **HOST_ONLY** if it meets ANY of these criteria:

1. **Database access**: Requires `AsyncSession` (PostgreSQL) or Neo4j client.
2. **Actor coupling**: Emits events via actor internals (`_publish_event_to_stream`).
3. **Redis dependency**: Uses Redis pub/sub for real-time communication.
4. **Host environment**: Reads host process environment variables or filesystem.
5. **Sandbox management**: Manages sandbox lifecycle itself (chicken-and-egg).

All other tools are classified as **SANDBOX** (either already sandbox-native or migratable).

#### Classification Table

| Tool | Classification | Host Dependency | Migration Effort |
|------|---------------|-----------------|-----------------|
| `web_search` | HOST (optional SANDBOX) | HTTP only | Low (but low value) |
| `web_scrape` | HOST (optional SANDBOX) | HTTP only | Low (but low value) |
| `ask_clarification` | HOST_ONLY | Redis pub/sub | N/A |
| `request_decision` | HOST_ONLY | Redis pub/sub | N/A |
| `SkillLoaderTool` | HOST_ONLY | Reads skill metadata for LLM | N/A |
| `SkillInstallerTool` | SANDBOX | Writes files to workspace | Medium |
| `SkillSyncTool` | SANDBOX | Syncs files to sandbox | Medium |
| `GetEnvVarTool` | HOST_ONLY | Host process env | N/A |
| `RequestEnvVarTool` | HOST_ONLY | Redis pub/sub + host env | N/A |
| `TodoReadTool` | HOST_ONLY | Actor event stream | N/A |
| `TodoWriteTool` | HOST_ONLY | Actor event stream | N/A |
| `MemorySearchTool` | HOST_ONLY | PostgreSQL + Neo4j | N/A |
| `RegisterMCPServerTool` | HOST_ONLY | Sandbox management | N/A |
| `PluginManagerTool` | HOST_ONLY | Plugin registry, pip | N/A |
| Plugin tools (non-sandbox) | SANDBOX | None (pure computation) | High (fix 5 root causes first) |
| Custom tools | SANDBOX | None (user code) | Medium |
| Sandbox MCP tools | SANDBOX (native) | Already sandboxed | None |
| Sandbox plugin tools | SANDBOX (native) | Already sandboxed | None |

---

## 4. Workspace Persistence Strategy (工作区持久化策略)

### 4.1 Current Bind Mount Analysis

**Current behavior:**

```
Host: /tmp/memstack-sandbox/{project_id}/
                    |
                    | Docker bind mount (rw)
                    v
Container: /workspace/
```

**Problems with `/tmp` as workspace base:**

| Problem | Severity | Impact |
|---------|----------|--------|
| tmpfs on many Linux distros | HIGH | Data lost on reboot |
| Periodic cleanup by OS (systemd-tmpfiles) | HIGH | Data lost after inactivity |
| No backup integration | MEDIUM | No disaster recovery |
| No quota management | LOW | Disk exhaustion possible |

### 4.2 Persistence Layer Design

#### Tier 1: Persistent Host Directory (Required, Immediate)

Change the default `SANDBOX_WORKSPACE_BASE` from `/tmp/memstack-sandbox` to a persistent
directory:

```python
# config.py -- CHANGE
sandbox_workspace_base: str = Field(
    default="/var/lib/memstack/workspaces",  # was: /tmp/memstack-sandbox
    alias="SANDBOX_WORKSPACE_BASE"
)
```

Directory structure:

```
/var/lib/memstack/workspaces/
    {project_id}/
        .memstack/
            workspace-manifest.json   # NEW: tracks all files and sync state
            tools/                    # Custom tool files
            plugins/                  # Plugin files
            workspace/                # Agent bootstrap files
        output/                       # Tool output directory (monitored)
        outputs/                      # Alternative output directory (monitored)
        ...                           # User/agent created files
```

#### Tier 2: Workspace Manifest (Required, Phase 1)

A manifest file tracks workspace state for sync and recovery:

```json
{
    "version": 1,
    "project_id": "proj-abc123",
    "tenant_id": "tenant-xyz",
    "created_at": "2026-03-01T10:00:00Z",
    "last_sandbox_id": "mcp-sandbox-a1b2c3d4e5f6",
    "files": {
        "output/report.pdf": {
            "size": 1048576,
            "sha256": "abc123...",
            "created_at": "2026-03-01T10:30:00Z",
            "synced_to_s3": true,
            "s3_key": "artifacts/tenant-xyz/proj-abc123/2026-03-01/report.pdf"
        },
        ".memstack/tools/my_tool.py": {
            "size": 2048,
            "sha256": "def456...",
            "created_at": "2026-03-01T10:15:00Z",
            "synced_to_s3": false
        }
    },
    "last_sync_at": "2026-03-01T10:35:00Z"
}
```

#### Tier 3: S3 Backup (Recommended, Phase 3)

For production deployments, workspace contents are backed up to S3/MinIO:

```
S3 Bucket: memstack-workspaces
    {tenant_id}/
        {project_id}/
            manifest.json
            files/
                output/report.pdf
                .memstack/tools/my_tool.py
```

The `WorkspaceSyncService` manages bidirectional sync:
- **Host -> S3**: After tool execution, new/modified files are uploaded.
- **S3 -> Host**: On sandbox recreation, missing files are restored from S3.

### 4.3 Workspace Lifecycle Hooks (工作区生命周期钩子)

#### Pre-Destroy Hook

Before a sandbox container is destroyed:

```python
async def pre_destroy_hook(sandbox_id: str, project_id: str) -> None:
    """Ensure workspace state is captured before container destruction."""
    workspace_path = f"{workspace_base}/{project_id}"

    # 1. Update manifest with current file state
    manifest = WorkspaceManifest.scan(workspace_path)
    manifest.save()

    # 2. Upload any un-synced artifacts to S3
    for file_entry in manifest.unsynced_files():
        await artifact_service.upload_workspace_file(
            file_path=file_entry.path,
            project_id=project_id,
            tenant_id=tenant_id,
        )
        file_entry.mark_synced()

    manifest.save()
```

#### Post-Create Hook

After a new sandbox container is created for the same project:

```python
async def post_create_hook(sandbox_id: str, project_id: str) -> None:
    """Restore workspace state after container recreation."""
    workspace_path = f"{workspace_base}/{project_id}"

    # 1. Host directory already exists (bind mount) -- verify integrity
    manifest = WorkspaceManifest.load(workspace_path)

    if manifest is None:
        # First sandbox for this project -- create manifest
        manifest = WorkspaceManifest.create(workspace_path, project_id)
        manifest.save()
        return

    # 2. Check for missing files (host dir was cleaned)
    for file_entry in manifest.files_missing_on_disk():
        if file_entry.synced_to_s3:
            await restore_from_s3(file_entry)

    # 3. Install runtime dependencies from manifest
    for dep in manifest.runtime_dependencies:
        await sandbox_port.call_tool(sandbox_id, "bash", {
            "command": f"pip install {dep}"
        })
```

#### Periodic Sync Hook

Runs on a configurable interval (default: every 5 minutes during active sessions):

```python
async def periodic_sync_hook(sandbox_id: str, project_id: str) -> None:
    """Sync workspace changes to manifest and optional S3 backup."""
    workspace_path = f"{workspace_base}/{project_id}"
    manifest = WorkspaceManifest.load(workspace_path)

    # Scan for new/modified files
    changes = manifest.detect_changes(workspace_path)

    for change in changes:
        if change.is_artifact():  # In output dirs
            await artifact_service.create_artifact(...)
        manifest.update_entry(change)

    manifest.save()
```

---

## 5. Artifact Sync Layer (制品同步层)

### 5.1 Current Dual-Path Problem

```
                   Tool Result
                       |
          +------------+------------+
          |                         |
          v                         v
  ArtifactHandler              ArtifactService
  (processor-level)            (application-level)
  - sync boto3 in thread       - async aioboto3
  - actor._publish_event        - event_publisher
  - generate temp artifact_id   - generate stable artifact_id
          |                         |
          v                         v
     S3 Upload                 S3 Upload
     (may duplicate)           (canonical)
          |                         |
          v                         v
  ArtifactReadyEvent         ArtifactReadyEvent
  (via actor stream)          (via event publisher)
```

**Problems:**
1. Two upload implementations to maintain.
2. ArtifactHandler is coupled to actor internals (`_publish_event_to_stream`).
3. Artifact ID is generated independently by each path -- no guaranteed consistency.
4. SandboxArtifactIntegration uses ArtifactService, but ArtifactHandler does not.

### 5.2 Unified Artifact Pipeline (统一制品管线)

**Target: Single pipeline through ArtifactService.**

```
                   Tool Result
                       |
                       v
             ArtifactExtractor.process()
                       |
                       v
              ArtifactService.create_artifact()
                       |
                       +-- Generate artifact_id
                       +-- Yield AgentArtifactCreatedEvent
                       +-- async upload via S3StorageAdapter
                       +-- Yield AgentArtifactReadyEvent
                       |
                       v
              EventPublisher -> Redis Stream -> Frontend
```

**Changes required:**

1. **Remove `_sync_upload` and `_threaded_upload` from ArtifactHandler.**
   ArtifactHandler becomes a thin adapter that:
   - Extracts artifact content from tool results (parsing logic stays).
   - Delegates to `ArtifactService.create_artifact()` for upload and event emission.
   - No longer needs actor internals access.

2. **ArtifactService becomes the single upload authority.**
   - Generates artifact_id.
   - Performs async upload via `S3StorageAdapter`.
   - Publishes both `CREATED` and `READY` events.
   - Handles errors and publishes `ERROR` events.

3. **ArtifactExtractor feeds into ArtifactService.**
   - `ArtifactExtractor.process()` returns `ArtifactData` objects.
   - `ArtifactHandler` passes them to `ArtifactService.create_artifact()`.

4. **SandboxArtifactIntegration continues using ArtifactService** (already correct).

### 5.3 Real-time vs Batch Sync (实时 vs 批量同步)

#### Option A: Host-Side Filesystem Watch (Recommended)

Since the workspace is a bind mount, the HOST can watch for filesystem changes:

```python
# Using watchdog library (already in Python ecosystem)
class WorkspaceWatcher:
    """Watches workspace bind mount directory for changes."""

    def __init__(self, workspace_path: str, artifact_service: ArtifactService):
        self._path = workspace_path
        self._artifact_service = artifact_service
        self._observer = Observer()

    def start(self) -> None:
        handler = WorkspaceEventHandler(
            artifact_service=self._artifact_service,
            output_dirs=DEFAULT_OUTPUT_DIRS,
        )
        self._observer.schedule(handler, self._path, recursive=True)
        self._observer.start()
```

**Pros:** Real-time detection, no polling overhead, works with any tool.
**Cons:** Requires `watchdog` dependency, platform-specific (inotify on Linux, FSEvents on macOS).

#### Option B: Post-Execution Scan (Current, Improved)

Keep the current `SandboxArtifactIntegration` pattern but improve it:

```python
# After every tool execution in SandboxToolExecutor:
async def _post_execution_scan(self, tool_name: str) -> list[str]:
    """Scan for new artifacts after tool execution."""
    return await self._artifact_integration.scan_for_new_artifacts(
        sandbox_id=self._sandbox_id,
        list_files_fn=self._list_files,
        read_file_fn=self._read_file,
        project_id=self._project_id,
        tenant_id=self._tenant_id,
    )
```

**Pros:** Simple, no new dependencies, proven pattern.
**Cons:** Misses files created by background processes, slight delay.

#### Recommendation

**Phase 1**: Use Option B (improved post-execution scan) -- lower risk, works immediately.
**Phase 3**: Add Option A (filesystem watch) for real-time detection of background-generated files.

---

## 6. Tool Migration Details (工具迁移详细方案)

### 6.1 Tools That MUST Remain Host-Side

| Tool | Host Dependency | Why It Cannot Move |
|------|----------------|-------------------|
| `MemorySearchTool` | PostgreSQL + Neo4j | Requires DB session and graph client. Sandbox has no DB access. |
| `TodoReadTool` / `TodoWriteTool` | Actor event stream | Emits `AgentTaskListUpdatedEvent` via `_pending_events` pattern, consumed by processor and published to Redis. Moving to sandbox would break real-time task tracking. |
| `ClarificationTool` / `DecisionTool` (HITL) | Redis pub/sub | Publishes HITL request, waits for user response via Redis. Sandbox has no Redis access. |
| `GetEnvVarTool` / `RequestEnvVarTool` | Host process env | Reads environment variables from the host process. Sandbox has its own env. |
| `RegisterMCPServerTool` | Sandbox management | Registers MCP servers INTO the sandbox. Must run on host to manage container state. |
| `PluginManagerTool` | Plugin registry + pip | Manages plugin installation/enable/disable. Operates on host plugin state. |
| `SkillLoaderTool` | Skill metadata for LLM | Injects skill prompts into LLM context. No computation to sandbox. |
| `web_search` / `web_scrape` | HTTP only | COULD move to sandbox but low value. Keep host-side for simplicity and lower latency. |

### 6.2 Tools That Move to Sandbox

#### Plugin Tools (Non-Sandbox Path) -- HIGH PRIORITY

**Current state:** Broken. 5 root causes documented in
[PLUGIN_TOOL_PIPELINE_FIX.md](./PLUGIN_TOOL_PIPELINE_FIX.md).

**Migration plan:**
1. Fix the 5 root causes (ToolResult API, factory returns, __call__ resolution, dict return, deps).
2. Route ALL plugin tools through `create_sandbox_plugin_tool()` pattern.
3. Remove `_add_plugin_tools()` (non-sandbox path) entirely.
4. `_add_sandbox_plugin_tools()` becomes the only plugin tool loading path.

**Affected files:**
- `src/infrastructure/agent/state/agent_worker_state.py` -- remove `_add_plugin_tools`, keep `_add_sandbox_plugin_tools`
- `src/infrastructure/agent/plugins/registry.py` -- update `build_tools()` to always produce sandbox-compatible output
- `.memstack/plugins/*/plugin.py` -- update `register_tool_factory` calls to `register_sandbox_tool_factory`

#### Custom Tools (.memstack/tools/) -- HIGH PRIORITY

**Current state:** Loaded by `CustomToolLoader`, executed in host process with full privileges.

**Migration plan:**
1. `CustomToolLoader` scans `.memstack/tools/` and extracts tool metadata (name, description, parameters).
2. Instead of creating host-side `ToolInfo`, wrap each as a sandbox tool:
   - Copy tool source file into sandbox workspace (already there via bind mount if `.memstack` is mounted).
   - Register tool in sandbox MCP server's tool registry.
   - Create `ToolInfo` that delegates to `sandbox_port.call_tool()`.
3. Dependency management: Parse tool file header or companion `requirements.txt` for dependencies.

**New custom tool format (backward compatible):**

```python
# .memstack/tools/my_tool.py
# memstack:dependencies: requests>=2.28, beautifulsoup4
# memstack:sandbox: true  (default in new architecture)

from memstack_tools import tool_define, ToolResult

@tool_define(
    name="my_custom_tool",
    description="Does something useful",
    parameters={"url": {"type": "string", "description": "URL to process"}},
)
async def my_custom_tool(url: str) -> ToolResult:
    import requests
    resp = requests.get(url)
    return ToolResult(output=resp.text)
```

**Affected files:**
- `src/infrastructure/agent/tools/custom_tool_loader.py` -- Major rewrite to produce sandbox-wrapped tools
- `src/infrastructure/agent/state/agent_worker_state.py` -- `_add_custom_tools` delegates to sandbox executor

#### Skill Installer / Skill Sync -- MEDIUM PRIORITY

**Current state:** Host-side tools that write files to workspace.

**Migration plan:**
1. `SkillInstallerTool` installs skill files. These files go into `/workspace/.memstack/skills/`.
   Since workspace is a bind mount, installing via sandbox MCP `write` tool achieves the same result.
2. Wrap as sandbox tools that use MCP `write` to place files in the workspace.
3. `SkillSyncTool` synchronizes skill resources. Already has `sandbox_adapter` parameter --
   extend to fully delegate file operations to sandbox.

**Affected files:**
- `src/infrastructure/agent/tools/skill_installer.py`
- `src/infrastructure/agent/tools/skill_sync.py`
- `src/infrastructure/agent/state/agent_worker_state.py` -- `_add_skill_installer_tools`, `_add_skill_sync_tool`

### 6.3 Migration Pattern (Per-Tool Template)

For each tool being migrated from host to sandbox:

```
Step 1: Extract tool metadata
    - name, description, parameters schema
    - runtime dependencies (pip packages)
    - source file location

Step 2: Create sandbox-compatible tool definition
    - If tool is a Python file: sync to workspace, register in sandbox MCP
    - If tool is a plugin factory: use create_sandbox_plugin_tool pattern
    - Ensure parameters schema is complete (no empty {})

Step 3: Wire through ToolExecutionRouter
    - Add ToolExecutionConfig with execution_mode="sandbox"
    - Specify sandbox_dependencies list
    - Specify sandbox_tool_name if different from host name

Step 4: Update tool loading in agent_worker_state.py
    - Replace _add_X_tools() with sandbox-aware version
    - Remove host-side instantiation

Step 5: Test
    - Unit: Mock sandbox_port.call_tool, verify delegation
    - Integration: Real sandbox container, verify end-to-end
    - Regression: Existing tool behavior unchanged
```

---

## 7. Dependency Management Unification (依赖管理统一化)

### Current State: Two Paths

| Path | Entry Point | Has Deps? | Handler |
|------|-------------|-----------|---------|
| `register_tool_factory()` | Non-sandbox plugins | NO | None (crashes at runtime) |
| `register_sandbox_tool_factory()` | Sandbox plugins | YES | `DependencyOrchestrator` -> `SandboxDependencyInstaller` |

### Target State: Single Path

All sandbox tools (plugins, custom, migrated) use `DependencyOrchestrator`:

```
Plugin manifest (memstack.plugin.json)
    -> declares dependencies: ["pypdf2>=3.0", "reportlab"]
    -> DependencyOrchestrator.ensure_dependencies(sandbox_id, deps)
        -> SandboxDependencyInstaller.install(sandbox_id, deps)
            -> sandbox_port.call_tool(sandbox_id, "bash", {"command": "pip install ..."})

Custom tool header
    -> parsed: # memstack:dependencies: requests>=2.28
    -> Same DependencyOrchestrator path

Skill package
    -> optional requirements.txt in skill directory
    -> Same DependencyOrchestrator path
```

### Dependency Caching

To avoid reinstalling dependencies on every sandbox creation:

1. **Layer caching**: Build custom Docker images with common dependencies pre-installed.
2. **Volume caching**: Mount a shared pip cache volume across sandboxes:
   ```python
   volumes["/var/lib/memstack/pip-cache"] = {"bind": "/root/.cache/pip", "mode": "rw"}
   ```
3. **Manifest tracking**: Record installed dependencies in workspace manifest to skip
   redundant installs on sandbox recreation.

---

## 8. Implementation Plan (实施计划)

### 8.1 Phase 1: Foundation (Weeks 1-2)

**Goal:** Establish the execution routing infrastructure and fix workspace persistence.

| Task | Description | Effort | Files |
|------|-------------|--------|-------|
| 1.1 | Create `ToolExecutionRouter`, `SandboxToolExecutor`, `HostToolExecutor` | 3d | New files in `agent/core/` |
| 1.2 | Change `SANDBOX_WORKSPACE_BASE` default to `/var/lib/memstack/workspaces` | 0.5d | `config.py` |
| 1.3 | Implement `WorkspaceManifest` class | 2d | New file in `agent/workspace/` |
| 1.4 | Add pre-destroy and post-create lifecycle hooks | 2d | `mcp_sandbox_adapter.py` |
| 1.5 | Wire `ToolExecutionRouter` into `agent_worker_state.py` tool loading | 2d | `agent_worker_state.py` |
| 1.6 | Unit tests for routing, manifest, hooks | 1.5d | `tests/unit/` |

**Deliverables:**
- All existing tools continue working unchanged (routed through HOST path).
- Workspace manifest tracks file state.
- Persistent workspace directory by default.

### 8.2 Phase 2: Tool Migration (Weeks 3-4)

**Goal:** Migrate plugin tools and custom tools to sandbox execution.

| Task | Description | Effort | Files |
|------|-------------|--------|-------|
| 2.1 | Fix 5 plugin tool root causes (from Phase 1 doc) | 3d | `tool_converter.py`, `result.py`, `registry.py`, etc. |
| 2.2 | Merge `_add_plugin_tools` into `_add_sandbox_plugin_tools` | 2d | `agent_worker_state.py`, `registry.py` |
| 2.3 | Rewrite `CustomToolLoader` for sandbox execution | 3d | `custom_tool_loader.py` |
| 2.4 | Add dependency header parsing for custom tools | 1d | `custom_tool_loader.py` |
| 2.5 | Migrate `SkillInstallerTool` and `SkillSyncTool` | 1.5d | `skill_installer.py`, `skill_sync.py` |
| 2.6 | Integration tests with real sandbox containers | 1.5d | `tests/integration/` |

**Deliverables:**
- Plugin tools work correctly in sandbox.
- Custom tools execute in sandbox with dependency management.
- Skill tools write to workspace via sandbox.

### 8.3 Phase 3: Artifact Unification (Weeks 5-6)

**Goal:** Single artifact pipeline, workspace sync.

| Task | Description | Effort | Files |
|------|-------------|--------|-------|
| 3.1 | Refactor `ArtifactHandler` to delegate to `ArtifactService` | 3d | `artifact_handler.py` |
| 3.2 | Remove `_sync_upload` / `_threaded_upload` from ArtifactHandler | 1d | `artifact_handler.py` |
| 3.3 | Implement `WorkspaceSyncService` (post-execution scan) | 2d | New file in `agent/workspace/` |
| 3.4 | Add S3 backup for workspace files | 2d | `workspace/sync.py`, `s3_storage_adapter.py` |
| 3.5 | Update event pipeline for unified artifact flow | 1d | `agent_events.py`, `converter.py` |
| 3.6 | Tests for unified pipeline | 1d | `tests/` |

**Deliverables:**
- Single artifact upload path through `ArtifactService`.
- Workspace files backed up to S3.
- Consistent artifact event lifecycle.

### 8.4 Phase 4: Hardening (Weeks 7-8)

**Goal:** Production readiness, performance, resilience.

| Task | Description | Effort | Files |
|------|-------------|--------|-------|
| 4.1 | Persist sandbox state machine across container restarts | 2d | `simplified_state_machine.py`, persistence layer |
| 4.2 | Add pip cache volume sharing across sandboxes | 1d | `container_manager.py`, `config.py` |
| 4.3 | Implement filesystem watch (watchdog) for real-time sync | 2d | `workspace/watcher.py` |
| 4.4 | Performance benchmarking: host vs sandbox tool latency | 1.5d | `tests/performance/` |
| 4.5 | Workspace migration script for existing deployments | 1d | `scripts/migrate_workspaces.py` |
| 4.6 | Update AGENTS.md, README, and architecture docs | 1d | Docs |
| 4.7 | End-to-end testing with full tool suite | 1.5d | `tests/e2e/` |

**Deliverables:**
- State machine survives restarts.
- Real-time file sync via filesystem watch.
- Migration path for existing deployments.
- Performance baseline documented.

---

## 9. Affected Files (影响的文件)

### New Files

| File | Purpose |
|------|---------|
| `src/infrastructure/agent/core/tool_execution_router.py` | ToolExecutionRouter, ToolExecutionConfig |
| `src/infrastructure/agent/core/sandbox_tool_executor.py` | SandboxToolExecutor |
| `src/infrastructure/agent/core/host_tool_executor.py` | HostToolExecutor |
| `src/infrastructure/agent/workspace/manifest.py` | WorkspaceManifest class |
| `src/infrastructure/agent/workspace/sync.py` | WorkspaceSyncService |
| `src/infrastructure/agent/workspace/watcher.py` | WorkspaceWatcher (Phase 4) |
| `scripts/migrate_workspaces.py` | Migration script for existing deployments |

### Modified Files

| File | Change Description |
|------|-------------------|
| `src/configuration/config.py` | Change `SANDBOX_WORKSPACE_BASE` default; add workspace sync config |
| `src/infrastructure/agent/state/agent_worker_state.py` | Wire ToolExecutionRouter; merge plugin tool paths; update custom tool loading |
| `src/infrastructure/agent/core/tool_converter.py` | Add `__call__` to `_resolve_execute_method` candidates; improve parameter extraction |
| `src/infrastructure/agent/tools/result.py` | (Optional) Add deprecated `error` parameter for backward compatibility |
| `src/infrastructure/agent/tools/custom_tool_loader.py` | Rewrite for sandbox execution; add dependency header parsing |
| `src/infrastructure/agent/plugins/registry.py` | Update `build_tools()` to always produce sandbox-compatible output |
| `src/infrastructure/agent/processor/artifact_handler.py` | Remove `_sync_upload`/`_threaded_upload`; delegate to ArtifactService |
| `src/infrastructure/adapters/secondary/sandbox/mcp_sandbox_adapter.py` | Add lifecycle hooks (pre-destroy, post-create) |
| `src/infrastructure/adapters/secondary/sandbox/container_manager.py` | Add pip cache volume mount |
| `src/infrastructure/adapters/secondary/sandbox/artifact_integration.py` | Integration with WorkspaceSyncService |
| `src/domain/model/sandbox/simplified_state_machine.py` | Add state persistence (Phase 4) |
| `src/domain/events/agent_events.py` | Ensure artifact events support unified pipeline |
| `src/infrastructure/agent/events/converter.py` | Update transformations if event semantics change |

### Plugin/Tool Files (User-Facing)

| File | Change Description |
|------|-------------------|
| `.memstack/plugins/pdf-assistant/plugin.py` | Switch from `register_tool_factory` to `register_sandbox_tool_factory` |
| `.memstack/plugins/pdf-assistant/tools.py` | Fix `ToolResult` API, fix `dict` returns, add `get_parameters_schema()` |
| `.memstack/tools/pdf_tools.py` | Fix `ToolResult(output="", error=...)` to `ToolResult(output=..., is_error=True)` |

---

## 10. Risks & Mitigations (风险与缓解措施)

### Risk 1: Latency Increase

**Risk:** Sandbox tool calls add a network hop (host -> Docker -> MCP WebSocket -> tool -> response).
For tools that were previously direct function calls, this adds 10-50ms per call.

**Mitigation:**
- Keep latency-sensitive tools (HITL, todo) on host.
- Measure baseline latency in Phase 4 benchmarking.
- Connection pooling in MCP WebSocket client (already implemented).
- For high-frequency tools, batch operations where possible.

### Risk 2: Sandbox Unavailability

**Risk:** Container dies or becomes unresponsive mid-tool-execution. Tool call fails.

**Mitigation:**
- `SandboxMCPToolWrapper` already has retry logic with error classification.
- Auto-recovery (`SANDBOX_AUTO_RECOVER=true`) restarts containers.
- Workspace bind mount means data is not lost when container restarts.
- Health monitor detects unhealthy containers proactively.

### Risk 3: Workspace Corruption

**Risk:** Concurrent writes from host process and container to the same file on the bind mount.

**Mitigation:**
- Host-side tools that write to workspace should go through sandbox MCP `write` tool.
- Workspace manifest provides last-write tracking for conflict detection.
- In practice, tools rarely write to the same file simultaneously.

### Risk 4: Migration Complexity for Existing Deployments

**Risk:** Existing deployments have workspaces in `/tmp/memstack-sandbox`. Changing the default
breaks existing setups without a migration.

**Mitigation:**
- Provide `scripts/migrate_workspaces.py` that copies data from old to new location.
- Config change is a default only -- existing `.env` files with `SANDBOX_WORKSPACE_BASE` set
  will continue working.
- Document migration steps in release notes.

### Risk 5: Dependency Installation Latency

**Risk:** First tool call in a new sandbox triggers `pip install`, adding 10-60 seconds.

**Mitigation:**
- Shared pip cache volume across sandboxes.
- Pre-warm common dependencies in the sandbox Docker image.
- Manifest tracks installed dependencies to skip redundant installs.
- Parallel dependency installation during sandbox creation (post-create hook).

### Risk 6: Custom Tool Security

**Risk:** Even in sandbox, a custom tool could attempt network exfiltration or resource abuse.

**Mitigation:**
- Network isolation (`SANDBOX_NETWORK_ISOLATED=true` by default).
- Resource limits (2GB memory, 2 CPU cores per container).
- Timeout enforcement (300s default per tool call).
- Sandbox containers run as non-root user inside.

---

## 11. Open Questions (待定问题)

### Q1: Should web_search / web_scrape move to sandbox?

**Context:** These tools only need HTTP access. They could run in sandbox with
`SANDBOX_NETWORK_ISOLATED=false` or with a network proxy.

**Trade-off:** Lower latency on host vs. better isolation in sandbox.

**Recommendation:** Keep on host for now. Revisit if security audit requires isolation.

### Q2: How to handle MCP server registration in sandbox-first world?

**Context:** `RegisterMCPServerTool` allows the agent to add new MCP servers to the sandbox.
In the sandbox-first world, does this mean registering additional MCP servers INSIDE the
existing sandbox container, or spinning up new containers?

**Recommendation:** Continue current pattern (register in existing sandbox via
`mcp_manager` inside the container). No architecture change needed.

### Q3: Should the manifest be stored in the workspace or in PostgreSQL?

**Context:** The workspace manifest tracks file state. Storing in the workspace (bind mount)
makes it available to both host and container. Storing in PostgreSQL makes it queryable
and more durable.

**Recommendation:** Both. Primary copy in workspace (for container access), replicated to
PostgreSQL on sync (for query and durability).

### Q4: What happens when multiple sandboxes exist for the same project?

**Context:** The current architecture creates one sandbox per project. But
`_max_concurrent_sandboxes=10` suggests multiple sandboxes could exist.

**Recommendation:** Enforce one-sandbox-per-project for workspace consistency. Multiple
sandboxes would need separate workspace partitions or a locking mechanism.

### Q5: How to handle the transition period?

**Context:** During migration, some tools will be on host, others in sandbox. The
`ToolExecutionRouter` handles this, but there may be edge cases where a tool's host/sandbox
classification changes between agent sessions.

**Recommendation:** Tool classification is static per deployment (configured, not dynamic).
Changes require agent restart, which is acceptable for a migration period.

---

## 12. Relationship to Plugin Tool Pipeline Fix (与插件工具管线修复的关系)

The [Plugin Tool Pipeline Fix](./PLUGIN_TOOL_PIPELINE_FIX.md) document identified 5 root
causes for plugin tool failures:

| # | Root Cause | Phase 1 Fix | Sandbox-First Incorporation |
|---|------------|-------------|---------------------------|
| 1 | `ToolResult` API mismatch | Add backward-compat `error` param | Same fix, applied in Phase 2.1 |
| 2 | Factory returns raw objects, not `ToolInfo` | Wrap in `ToolInfo` during `build_tools()` | Subsumed: all plugins go through `create_sandbox_plugin_tool` |
| 3 | `__call__` not in execute method candidates | Add `__call__` to `_resolve_execute_method` | Subsumed: sandbox tools don't need `_resolve_execute_method` |
| 4 | Plugin tools return `dict`, not `ToolResult` | Normalize in wrapper | Subsumed: `SandboxToolExecutor` normalizes all results |
| 5 | No dependency management for non-sandbox plugins | Add `DependencyOrchestrator` to non-sandbox path | Subsumed: non-sandbox path eliminated entirely |

**The sandbox-first architecture makes Root Causes 2, 3, 4, and 5 irrelevant** by routing
all plugin tools through the sandbox path. Only Root Cause 1 (ToolResult API) still needs
a fix for backward compatibility with existing plugin code.

The Phase 1 document's 4-phase implementation plan (8-10 days) is compressed into
Phase 2 of this broader plan (2 weeks), with several fixes becoming unnecessary because
the unified sandbox execution layer handles them architecturally.

---

## Appendix A: Configuration Reference

### New Configuration Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SANDBOX_WORKSPACE_BASE` | `/var/lib/memstack/workspaces` | Base directory for workspace bind mounts (changed from `/tmp/memstack-sandbox`) |
| `WORKSPACE_SYNC_ENABLED` | `true` | Enable workspace manifest tracking |
| `WORKSPACE_SYNC_INTERVAL_SECONDS` | `300` | Periodic sync interval (0 to disable) |
| `WORKSPACE_S3_BACKUP_ENABLED` | `false` | Enable S3 backup for workspace files |
| `WORKSPACE_S3_BUCKET` | `memstack-workspaces` | S3 bucket for workspace backups |
| `SANDBOX_PIP_CACHE_ENABLED` | `true` | Share pip cache volume across sandboxes |
| `SANDBOX_PIP_CACHE_PATH` | `/var/lib/memstack/pip-cache` | Host path for shared pip cache |

### Existing Configuration (Unchanged)

| Variable | Default | Description |
|----------|---------|-------------|
| `SANDBOX_DEFAULT_PROVIDER` | `docker` | Sandbox provider |
| `SANDBOX_DEFAULT_IMAGE` | `sandbox-mcp-server:latest` | Container image |
| `SANDBOX_TIMEOUT_SECONDS` | `300` | Tool execution timeout |
| `SANDBOX_MEMORY_LIMIT` | `2G` | Container memory limit |
| `SANDBOX_CPU_LIMIT` | `2` | Container CPU limit |
| `SANDBOX_NETWORK_ISOLATED` | `true` | Network isolation |
| `SANDBOX_AUTO_RECOVER` | `true` | Auto-restart on failure |
| `SANDBOX_HEALTH_CHECK_INTERVAL` | `60` | Health check interval (seconds) |

---

## Appendix B: Glossary (术语表)

| Term | Chinese | Definition |
|------|---------|------------|
| Bind mount | 绑定挂载 | Docker volume type that maps a host directory into a container |
| Host-side | 宿主侧 | Code executing in the agent process on the host machine |
| Sandbox-side | 沙箱侧 | Code executing inside a Docker container |
| Workspace | 工作区 | The `/workspace` directory inside a sandbox container, bind-mounted from host |
| Artifact | 制品 | A file produced by tool execution (PDF, image, code, etc.) |
| MCP | 模型上下文协议 | Model Context Protocol -- the WebSocket protocol used for tool execution in sandbox |
| Manifest | 清单文件 | JSON file tracking workspace file state for sync and recovery |
| ToolInfo | 工具信息 | Dataclass wrapping a tool's name, description, parameters, and execute function |
| ToolDefinition | 工具定义 | Wrapper used by SessionProcessor, converted from ToolInfo by tool_converter.py |

---

## Appendix C: Decision Log

| # | Decision | Rationale | Alternatives Considered |
|---|----------|-----------|------------------------|
| D1 | Default workspace to `/var/lib/memstack/workspaces` | `/tmp` is ephemeral; `/var/lib` is standard for persistent app data | Named Docker volumes (complex), S3-only (requires network) |
| D2 | Unify on ArtifactService for uploads | Eliminate dual-path confusion; ArtifactService has cleaner architecture | Keep both paths with dedup (more complex) |
| D3 | Keep web_search/web_scrape on host | Low migration value; latency-sensitive; no security concern | Move to sandbox (adds latency, needs network access) |
| D4 | Use post-execution scan before filesystem watch | Lower risk, proven pattern; filesystem watch added in Phase 4 | Filesystem watch from start (more deps, platform-specific) |
| D5 | Store manifest in workspace AND PostgreSQL | Workspace copy for container access; DB copy for durability and query | Workspace-only (no query), DB-only (container can't access) |
| D6 | One sandbox per project | Simplifies workspace consistency | Multiple sandboxes per project (needs locking/partitioning) |
| D7 | Shared pip cache volume | Reduces dependency installation latency across sandboxes | Per-sandbox cache (wastes disk), pre-baked images (inflexible) |
