# Todo Tools 文档

> ReActAgent 待办事项管理工具
> 实现位置: `src/infrastructure/agent/tools/todo_tools.py`
> 绑定流程与 Workspace 退役边界核对日期：2026-10-19

## 概述

Todo 工具为 ReActAgent 提供会话级别的待办事项管理功能，允许 Agent 在对话过程中跟踪任务进度。

> 说明：名称沿用历史 "todo" 语义，底层由 `AgentTask`（持久化任务实体）承担。旧 Workspace authority SQL 路径已退役，工具会拒绝该路径并提示使用 Avernet Workspace Core（见下文「Workspace Authority 退役边界」）。

## 工具列表

### 1. todoread - 读取待办事项

读取当前会话的待办事项列表，支持按状态过滤。会话范围由运行时提供的 `ToolContext` 决定，取 `ctx.conversation_id`，缺省时取 `ctx.session_id`。

**输入参数**：
```python
{
    "status": str,         # 可选：过滤状态 (pending/in_progress/completed/failed/cancelled)
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
- 同优先级按 `order_index` 排序
- 返回的待办事项包含完整时间戳

---

### 2. todowrite - 写入待办事项

写入、追加或更新会话的待办事项列表。

**输入参数**：
```python
{
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

> 会话任务列表通过 `AgentTask.to_dict()` 序列化，实际 JSON 字段以该方法返回为准。旧 Workspace 任务映射与派发辅助逻辑已随退役路径移除。

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

工具由 `make_todo_tools(session_factory=...)` 创建。工厂返回 `todoread` / `todowrite` 两个 `ToolInfo`，各自捕获同一不可变 `TodoToolRuntime` 中的会话工厂；执行期间通过 `ContextVar` 绑定该运行时，并在结束时恢复，隔离并发调用和不同 generation 的依赖。

如果当前已固定 V2 operation，绑定执行器会检查其为 SESSION scope，并核对会话及上下文中提供的 tenant/project 标识；不匹配时抛出 `todo_operation_scope_mismatch`。直接执行未绑定的工具模板会返回 `Task storage not configured`。

### Workspace Authority 退役边界

当 `task_authority == "workspace"` 且 `workspace_id`、`root_goal_task_id` 均为字符串时，工具识别旧 Workspace authority 标记。在依赖已绑定且参数校验通过的调用中：

- `todoread` 抛出 `LegacyWorkspaceRuntimeRetiredError`，提示使用 Avernet Workspace Core。
- `todowrite` 保留结构性写入限制：角色不是 leader，且角色为 worker 或同时带有 `workspace_task_id` / `attempt_id` 时，`replace` / `add` 返回工具错误，引导使用 `workspace_report_progress/complete/blocked`；其余进入旧 Workspace 写入路径的调用抛出同一退役异常。
- 退役异常发生后不会读写 Workspace SQL、回退到会话任务仓库、提交事务或发布任务事件。插件 generation 切换不会恢复旧路径。

---

## 使用示例

先通过工厂创建绑定工具。生产运行时提供每次调用的 `ToolContext`，直接执行示例如下：

```python
from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.todo_tools import make_todo_tools

tools = make_todo_tools(session_factory=async_session_factory)
todoread = tools["todoread"]
todowrite = tools["todowrite"]
ctx = ToolContext(
    session_id="conv-123",
    conversation_id="conv-123",
    message_id="message-1",
    call_id="call-1",
    agent_name="example-agent",
)
```

### 示例 1：创建初始待办列表

```python
# 使用 replace 操作创建初始列表
await todowrite.execute(
    ctx,
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
    ctx,
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
    ctx,
    action="update",
    todo_id="uuid-of-design-task",
    todos=[{"status": "completed"}]
)
```

### 示例 4：读取全部待办

```python
# 返回列表已按优先级和 order_index 排序
result = await todoread.execute(ctx)
```

### 示例 5：读取进行中的任务

```python
# 读取所有进行中的任务
result = await todoread.execute(
    ctx,
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

相关单元测试：

- `src/tests/unit/infrastructure/agent/tools/test_todo_tools.py`：会话读写、工厂绑定隔离、旧 Workspace authority 拒绝及无 SQL 回退、提交或事件副作用。
- `src/tests/unit/infrastructure/plugins/v2/test_agent_todo_redis_authority_v2.py`：generation 切换期间，旧 Workspace 读写继续拒绝且不发布 Redis 任务事件。
- `src/tests/unit/infrastructure/agent/processor/test_processor_goal_completion.py`：旧 Workspace 目标读取拒绝后，不回退到会话任务读取或 LLM 判断。

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
2. **父子关系**：支持会话待办的父子层级结构
3. **标签系统**：为待办添加标签分类
4. **提醒功能**：基于时间的待办提醒
