# Todo Tools 文档

> ReActAgent 待办事项管理工具
> 实现位置: `src/infrastructure/agent/tools/todo_tools.py`

## 概述

Todo 工具为 ReActAgent 提供会话级别的待办事项管理功能，允许 Agent 在对话过程中跟踪任务进度。

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

### TodoItem

```python
@dataclass
class TodoItem:
    id: str                  # 唯一标识符
    content: str             # 任务描述
    status: str = "pending"  # 状态
    priority: str = "medium" # 优先级
    created_at: str          # 创建时间（ISO 8601）
    updated_at: str          # 更新时间（ISO 8601）
```

**有效状态值**：
- `pending` - 待处理
- `in_progress` - 进行中
- `completed` - 已完成
- `cancelled` - 已取消

**有效优先级值**：
- `high` - 高优先级
- `medium` - 中等优先级
- `low` - 低优先级

---

## 存储机制

### TodoStorage

当前使用内存存储，按会话 ID 隔离：

```python
storage.get(session_id)        # 获取会话的所有待办
storage.set(session_id, todos)  # 设置会话的待办（替换）
storage.add(session_id, todo)   # 添加单个待办
storage.update(session_id, todo_id, updates)  # 更新待办
storage.delete(session_id, todo_id)  # 删除待办
storage.clear(session_id)       # 清空会话待办
```

**注意**：当前存储为内存实现，服务重启后数据会丢失。生产环境建议使用 Redis 或数据库持久化。

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

| 测试类 | 测试数量 | 覆盖内容 |
|--------|----------|----------|
| `TestTodoItem` | 8 | 数据模型创建、验证、序列化 |
| `TestTodoStorage` | 9 | 存储CRUD、会话隔离 |
| `TestTodoReadTool` | 10 | 读取、过滤、排序 |
| `TestTodoWriteTool` | 13 | replace/add/update 操作 |
| `TestTodoIntegration` | 1 | 完整工作流 |
| **总计** | **36** | **100% 通过** |

---

## 与 OpenCode 规范的对应

| OpenCode | 本项目 | 状态 |
|----------|--------|------|
| `todoread` | `TodoReadTool` | ✅ |
| `todowrite` | `TodoWriteTool` | ✅ |

规范来源：`vendor/opencode/packages/opencode/src/session/todo.ts`

---

## 未来改进

1. **持久化存储**：使用 Redis 或数据库替代内存存储
2. **过期清理**：自动清理长时间未活动的会话待办
3. **父子关系**：支持待办的父子层级结构
4. **标签系统**：为待办添加标签分类
5. **提醒功能**：基于时间的待办提醒
