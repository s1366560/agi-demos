# Todo Tools 文档

> ReActAgent 待办事项管理工具
> 实现位置: `src/infrastructure/agent/tools/todo_tools.py`
> Last checked against code: 2026-06-22

## 概述

Todo 工具为 ReActAgent 提供会话级别的待办事项管理功能，允许 Agent 在对话过程中跟踪任务进度。

> 说明：名称沿用历史 "todo" 语义，但底层实现已由 `AgentTask`（持久化任务实体）承担，工具返回的字段也来自 `AgentTask.to_dict()`。在 workspace authority 场景下，读写会代理到 `WorkspaceTask`（见下文「Workspace Authority 模式」）。

## 工具列表

### 1. todoread - 读取待办事项

读取当前会话的待办事项列表，支持按状态和优先级过滤。

**输入参数**：
```python
{
    "session_id": str,     # 必需：会话ID（通常为 conversation_id）
    "status": str,         # 可选：过滤状态 (pending/in_progress/completed/cancelled)
    "priority": str,       # 可选：过滤优先级 (high/medium/low)
}
```

**输出格式**：
```json
{
  "session_id": "conv-123",
  "total_count": 3,
  "todos": [
    {
      "id": "uuid-1",
      "content": "实现用户认证功能",
      "status": "in_progress",
      "priority": "high",
      "created_at": "2025-01-28T10:00:00",
      "updated_at": "2025-01-28T11:30:00"
    }
  ]
}
```

**特性**：
- 自动按优先级排序（high > medium > low）
- 同优先级按创建时间排序
- 返回的待办事项包含完整时间戳

---

### 2. todowrite - 写入待办事项

写入、追加或更新会话的待办事项列表。

**输入参数**：
```python
{
    "session_id": str,     # 必需：会话ID
    "action": str,         # 必需：操作类型
    "todos": list,         # 可选：待办事项数组（replace/add 时需要）
    "todo_id": str,        # 可选：待办ID（update 时需要）
}
```

**操作类型 (action)**：

| 操作 | 描述 | 所需参数 |
|------|------|----------|
| `replace` | 替换整个待办列表 | `todos` |
| `add` | 添加新待办到现有列表 | `todos` |
| `update` | 更新现有待办 | `todo_id`, `todos[0]` |

**待办事项结构**：
```python
{
    "id": str,             # 可选：自动生成 UUID
    "content": str,        # 必需：任务描述
    "status": str,         # 可选：pending/in_progress/completed/cancelled
    "priority": str,       # 可选：high/medium/low
}
```

**输出格式**：
```json
{
  "success": true,
  "action": "add",
  "session_id": "conv-123",
  "added_count": 2,
  "total_count": 5,
  "message": "Added 2 new todos"
}
```

---

## 数据模型

### AgentTask

实现位置：`src/domain/model/agent/task.py`

```python
class TaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class TaskPriority(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

@dataclass
class AgentTask:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    conversation_id: str
    content: str
    status: TaskStatus = TaskStatus.PENDING
    priority: TaskPriority = TaskPriority.MEDIUM
    order_index: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
```

**有效状态值**（`TaskStatus`）：
- `pending` - 待处理
- `in_progress` - 进行中
- `completed` - 已完成
- `failed` - 失败（注意：旧文档遗漏了该值）
- `cancelled` - 已取消

**有效优先级值**（`TaskPriority`）：
- `high` - 高优先级
- `medium` - 中等优先级
- `low` - 低优先级

> 工具输出会经过 `AgentTask.to_dict()`，实际 JSON 字段以该方法返回为准；workspace 模式下则使用 `_workspace_task_to_todo(...)` 做映射，会额外携带 `workspace_task_id`、`workspace_agent_id`、worker 报告相关字段等。

---

## 存储机制

### 持久化（DB-backed）

当前为 DB 持久化实现，按 `conversation_id` 隔离，通过 `SqlAgentTaskRepository` 读写 `AgentTask` 记录，服务重启后数据保留。

- 读取 (`todoread`)：调用 `repo.find_by_conversation(conversation_id, status=...)`，按 `priority`（high > medium > low）再按 `order_index` 排序后返回。
- 写入 (`todowrite`)：
  - `replace` → `repo.save_all(conversation_id, task_items)`（覆盖整列）
  - `add` → 追加，`order_index` 接在现有列表末尾
  - `update` → `repo.update(todo_id, **updates)`，按 `todo_id` 精确定位
- 每次写入都会 `await session.commit()` 并通过 `ctx.emit(...)` 发送 `task_list_updated` / `task_updated` 事件到前端。

> 工具在启动时通过 `configure_todoread` / `configure_todowrite` 注入 DB 会话工厂 `_todoread_session_factory` / `_todowrite_session_factory`。

### Workspace Authority 模式

当运行时上下文满足 `task_authority == "workspace"` 且携带 `(workspace_id, root_goal_task_id)` 时，工具切换为 workspace 模式：

- 读写代理到 `WorkspaceTask`（由 `WorkspaceTaskCommandService` + `WorkspaceTaskService` 驱动），而非 `AgentTask`。
- `replace` / `add` 会创建派发给 worker agent 的 execution task（见 `_dispatch_created_workspace_tasks`），并受 leader/worker 角色权限约束（worker 不能 `replace` / `add`）。
- 字段经过映射：`WorkspaceTaskStatus` ↔ todo status，`WorkspaceTaskPriority` (P1..P4) ↔ priority (high/medium/low)。

---

## 使用示例

### 示例 1：创建初始待办列表

```python
# 使用 replace 操作创建初始列表
await todowrite.execute(
    session_id="conv-123",
    action="replace",
    todos=[
        {"content": "设计数据库 schema", "priority": "high"},
        {"content": "实现 API 接口", "priority": "medium"},
        {"content": "编写单元测试", "priority": "low"},
    ]
)
```

### 示例 2：添加新待办

```python
# 使用 add 操作追加新待办
await todowrite.execute(
    session_id="conv-123",
    action="add",
    todos=[
        {"content": "部署到生产环境", "priority": "high"},
    ]
)
```

### 示例 3：更新待办状态

```python
# 使用 update 操作更新状态
await todowrite.execute(
    session_id="conv-123",
    action="update",
    todo_id="uuid-of-design-task",
    todos=[{"status": "completed"}]
)
```

### 示例 4：读取高优先级待办

```python
# 读取所有高优先级待办
result = await todoread.execute(
    session_id="conv-123",
    priority="high"
)
```

### 示例 5：读取进行中的任务

```python
# 读取所有进行中的任务
result = await todoread.execute(
    session_id="conv-123",
    status="in_progress"
)
```

---

## 验证规则

1. **content**：不能为空字符串
2. **status**：必须是有效值之一
3. **priority**：必须是有效值之一

无效的待办事项会被自动跳过，不会存储。

---

## 测试覆盖

当前单元测试位于 `src/tests/unit/infrastructure/agent/tools/test_todo_tools.py`：

| 测试类 | 测试数量 | 覆盖内容 |
|--------|----------|----------|
| `TestTodoReadTool` | 6 | 读取、过滤、排序 |
| `TestTodoWriteTool` | 25 | replace / add / update / workspace authority / dispatch 等场景 |
| **总计** | **31** | （以实际测试为准） |

> 旧版文档列出的 `TestTodoItem` / `TestTodoStorage` / `TestTodoIntegration` 测试类已不存在——任务模型与存储已迁移至 `AgentTask` + `SqlAgentTaskRepository`，对应测试随实现路径调整。维护时请以 `test_todo_tools.py` 实际测试为参考，不要沿用历史数字。

---

## 历史：与 OpenCode 规范的对应

| OpenCode | 本项目 | 状态 |
|----------|--------|------|
| `todoread` | `todoread_tool` (`@tool_define`) | 历史命名来源 |
| `todowrite` | `todowrite_tool` (`@tool_define`) | 历史命名来源 |

> 旧文档引用 `vendor/opencode/packages/opencode/src/session/todo.ts` 作为「规范来源」，但当前仓库并无 `vendor/` 目录，该路径不可访问；OpenCode 对应关系仅作命名沿革说明。

---

## 未来改进

1. **过期清理**：自动清理长时间未活动的会话待办
2. **父子关系**：支持待办的父子层级结构（workspace authority 已部分实现 root goal → execution task 的树形结构）
3. **标签系统**：为待办添加标签分类
4. **提醒功能**：基于时间的待办提醒
