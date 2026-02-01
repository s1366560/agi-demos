# Agent 事件类型完整列表

本文档记录 MemStack Agent 系统中所有的事件类型定义。

**最后更新**: 2026-02-01  
**事件总数**: 52 种

## 事件类型概览

| 类别 | 事件数量 | 前端已处理 |
|------|---------|-----------|
| 状态事件 | 4 | 2 |
| 思考事件 | 2 | 2 |
| 工作计划 | 4 | 3 |
| 工具事件 | 2 | 2 |
| 文本流 | 3 | 3 |
| 消息事件 | 3 | 3 |
| 权限事件 | 2 | 0 |
| Doom Loop | 2 | 0 |
| 人机交互 (HITL) | 4 | 4 |
| 环境变量 | 2 | 2 |
| 成本追踪 | 1 | 0 |
| 重试 | 1 | 0 |
| 上下文 | 2 | 1 |
| 模式匹配 | 1 | 1 |
| 技能执行 | 4 | 4 |
| Plan Mode | 14 | 7 |
| 标题生成 | 1 | 1 |
| 沙箱 | 9 | 0 |
| **总计** | **52** | **33** |

---

## 详细事件列表

### 状态事件 (Status Events)

| 枚举值 | 事件值 | 前端处理 | 说明 |
|--------|--------|---------|------|
| `STATUS` | `status` | ❌ | 内部状态跟踪 |
| `START` | `start` | ❌ | Agent 执行开始 |
| `COMPLETE` | `complete` | ✅ | Agent 执行完成 |
| `ERROR` | `error` | ✅ | 执行错误 |

### 思考事件 (Thinking Events)

| 枚举值 | 事件值 | 前端处理 | 说明 |
|--------|--------|---------|------|
| `THOUGHT` | `thought` | ✅ | 完整思考内容 |
| `THOUGHT_DELTA` | `thought_delta` | ✅ | 思考内容增量流 |

### 工作计划事件 (Work Plan Events)

| 枚举值 | 事件值 | 前端处理 | 说明 |
|--------|--------|---------|------|
| `WORK_PLAN` | `work_plan` | ✅ | 工作计划创建/更新 |
| `STEP_START` | `step_start` | ✅ | 步骤开始执行 |
| `STEP_END` | `step_end` | ✅ | 步骤执行结束 |
| `STEP_FINISH` | `step_finish` | ❌ | 步骤完成（含 token/cost） |

### 工具事件 (Tool Events)

| 枚举值 | 事件值 | 前端处理 | 说明 |
|--------|--------|---------|------|
| `ACT` | `act` | ✅ | Agent 调用工具 |
| `OBSERVE` | `observe` | ✅ | 工具执行结果 |

### 文本流事件 (Text Streaming Events)

| 枚举值 | 事件值 | 前端处理 | 说明 |
|--------|--------|---------|------|
| `TEXT_START` | `text_start` | ✅ | 文本流开始 |
| `TEXT_DELTA` | `text_delta` | ✅ | 文本增量内容 |
| `TEXT_END` | `text_end` | ✅ | 文本流结束 |

### 消息事件 (Message Events)

| 枚举值 | 事件值 | 前端处理 | 说明 |
|--------|--------|---------|------|
| `MESSAGE` | `message` | ✅ | 通用消息 |
| `USER_MESSAGE` | `user_message` | ✅ | 用户消息（DB 存储，历史加载时渲染） |
| `ASSISTANT_MESSAGE` | `assistant_message` | ✅ | 助手消息（DB 存储，历史加载时渲染） |

### 权限事件 (Permission Events)

| 枚举值 | 事件值 | 前端处理 | 说明 |
|--------|--------|---------|------|
| `PERMISSION_ASKED` | `permission_asked` | ❌ | 请求权限 |
| `PERMISSION_REPLIED` | `permission_replied` | ❌ | 权限回复 |

### Doom Loop 事件

| 枚举值 | 事件值 | 前端处理 | 说明 |
|--------|--------|---------|------|
| `DOOM_LOOP_DETECTED` | `doom_loop_detected` | ❌ | 检测到死循环 |
| `DOOM_LOOP_INTERVENED` | `doom_loop_intervened` | ❌ | 死循环干预 |

### 人机交互事件 (HITL Events)

| 枚举值 | 事件值 | 前端处理 | 说明 |
|--------|--------|---------|------|
| `CLARIFICATION_ASKED` | `clarification_asked` | ✅ | 请求澄清 |
| `CLARIFICATION_ANSWERED` | `clarification_answered` | ✅ | 澄清回复 |
| `DECISION_ASKED` | `decision_asked` | ✅ | 请求决策 |
| `DECISION_ANSWERED` | `decision_answered` | ✅ | 决策回复 |

### 环境变量事件 (Environment Variable Events)

| 枚举值 | 事件值 | 前端处理 | 说明 |
|--------|--------|---------|------|
| `ENV_VAR_REQUESTED` | `env_var_requested` | ✅ | 请求环境变量 |
| `ENV_VAR_PROVIDED` | `env_var_provided` | ✅ | 环境变量已提供 |

### 成本追踪事件 (Cost Events)

| 枚举值 | 事件值 | 前端处理 | 说明 |
|--------|--------|---------|------|
| `COST_UPDATE` | `cost_update` | ❌ | 成本更新 |

### 重试事件 (Retry Events)

| 枚举值 | 事件值 | 前端处理 | 说明 |
|--------|--------|---------|------|
| `RETRY` | `retry` | ❌ | 重试操作 |

### 上下文事件 (Context Events)

| 枚举值 | 事件值 | 前端处理 | 说明 |
|--------|--------|---------|------|
| `COMPACT_NEEDED` | `compact_needed` | ❌ | 需要压缩（内部信号） |
| `CONTEXT_COMPRESSED` | `context_compressed` | ✅ | 上下文已压缩 |

### 模式匹配事件 (Pattern Events)

| 枚举值 | 事件值 | 前端处理 | 说明 |
|--------|--------|---------|------|
| `PATTERN_MATCH` | `pattern_match` | ✅ | 模式匹配成功 |

### 技能执行事件 (Skill Execution Events)

| 枚举值 | 事件值 | 前端处理 | 说明 |
|--------|--------|---------|------|
| `SKILL_MATCHED` | `skill_matched` | ✅ | 技能匹配成功 |
| `SKILL_EXECUTION_START` | `skill_execution_start` | ✅ | 技能执行开始 |
| `SKILL_EXECUTION_COMPLETE` | `skill_execution_complete` | ✅ | 技能执行完成 |
| `SKILL_FALLBACK` | `skill_fallback` | ✅ | 技能降级回退 |

### Plan Mode 事件

| 枚举值 | 事件值 | 前端处理 | 说明 |
|--------|--------|---------|------|
| `PLAN_MODE_ENTER` | `plan_mode_enter` | ✅ | 进入计划模式 |
| `PLAN_MODE_EXIT` | `plan_mode_exit` | ✅ | 退出计划模式 |
| `PLAN_CREATED` | `plan_created` | ✅ | 计划创建 |
| `PLAN_UPDATED` | `plan_updated` | ✅ | 计划更新 |
| `PLAN_STATUS_CHANGED` | `plan_status_changed` | ❌ | 计划状态变更 |
| `PLAN_EXECUTION_START` | `plan_execution_start` | ✅ | 计划执行开始 |
| `PLAN_EXECUTION_COMPLETE` | `plan_execution_complete` | ✅ | 计划执行完成 |
| `PLAN_STEP_READY` | `plan_step_ready` | ❌ | 计划步骤就绪 |
| `PLAN_STEP_COMPLETE` | `plan_step_complete` | ❌ | 计划步骤完成 |
| `PLAN_STEP_SKIPPED` | `plan_step_skipped` | ❌ | 计划步骤跳过 |
| `PLAN_SNAPSHOT_CREATED` | `plan_snapshot_created` | ❌ | 计划快照创建 |
| `PLAN_ROLLBACK` | `plan_rollback` | ❌ | 计划回滚 |
| `REFLECTION_COMPLETE` | `reflection_complete` | ✅ | 反思完成 |
| `ADJUSTMENT_APPLIED` | `adjustment_applied` | ❌ | 调整已应用 |

### 标题生成事件 (Title Events)

| 枚举值 | 事件值 | 前端处理 | 说明 |
|--------|--------|---------|------|
| `TITLE_GENERATED` | `title_generated` | ✅ | 标题生成完成 |

### 沙箱事件 (Sandbox Events)

| 枚举值 | 事件值 | 前端处理 | 说明 |
|--------|--------|---------|------|
| `SANDBOX_CREATED` | `sandbox_created` | ❌ | 沙箱创建 |
| `SANDBOX_TERMINATED` | `sandbox_terminated` | ❌ | 沙箱终止 |
| `SANDBOX_STATUS` | `sandbox_status` | ❌ | 沙箱状态 |
| `DESKTOP_STARTED` | `desktop_started` | ❌ | 桌面启动 |
| `DESKTOP_STOPPED` | `desktop_stopped` | ❌ | 桌面停止 |
| `DESKTOP_STATUS` | `desktop_status` | ❌ | 桌面状态 |
| `TERMINAL_STARTED` | `terminal_started` | ❌ | 终端启动 |
| `TERMINAL_STOPPED` | `terminal_stopped` | ❌ | 终端停止 |
| `TERMINAL_STATUS` | `terminal_status` | ❌ | 终端状态 |

---

## 统计摘要

- **总计**: 52 种事件类型
- **前端已处理**: 33 种 (63%)
- **前端未处理**: 19 种 (37%)
  - 内部事件: 3 种 (`status`, `start`, `compact_needed`)
  - 预留功能: 9 种 (沙箱相关)
  - 待实现: 7 种 (`step_finish`, `permission_*`, `doom_loop_*`, `cost_update`, Plan 相关)

---

## 事件流架构

```
┌─────────────────────────────────────────────────────────────────┐
│                    EVENT FLOW ARCHITECTURE                       │
│                                                                  │
│   ReActAgent (agent_session.py)                                  │
│       │                                                          │
│       ▼                                                          │
│   stream_add(Redis Stream)                                       │
│   "agent:events:{conversation_id}"                               │
│       │                                                          │
│       ├──► PostgreSQL (重要事件持久化)                            │
│       │                                                          │
│       ▼                                                          │
│   connect_chat_stream() → XREAD                                  │
│       │                                                          │
│       ▼                                                          │
│   stream_agent_to_websocket()                                    │
│       │                                                          │
│       ▼                                                          │
│   EventDispatcher → WebSocket                                    │
│       │                                                          │
│       ▼                                                          │
│   Frontend: agentService.handleMessage()                         │
│       │                                                          │
│       ▼                                                          │
│   routeToHandler() → AgentStreamHandler callbacks                │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 相关文件

- 后端事件定义: `src/domain/events/agent_events.py`
- 前端事件类型: `web/src/types/agent.ts`
- 前端事件路由: `web/src/services/agentService.ts` (`routeToHandler`)
- 前端事件处理: `web/src/stores/agentV3.ts`
