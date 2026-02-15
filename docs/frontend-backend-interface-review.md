# 前后端接口一致性审阅

## 审阅目标

确保 `memstack-agent` 后端框架与 `memstack-agent-ui` 前端框架的接口一致性。

## 审阅结果

### 1. 事件类型一致性

| 分类 | 后端 | 前端 | 状态 |
|------|------|------|------|
| 核心事件 | 50+ (AgentEventType) | 50+ (EVENT_TYPES) | ✅ 一致 |
| 事件分类 | 4 类 (AGENT/HITL/SANDBOX/MESSAGE) | 4 类 (EventCategory) | ✅ 一致 |
| 事件过滤 | `is_terminal_event()`, `is_delta_event()`, `is_hitl_event()` | `isTerminalEvent()`, `isDeltaEvent()`, `isHitlEvent()` | ✅ 一致 |

**后端定义** (`src/domain/events/types.py`):
```python
class AgentEventType(str, Enum):
    START = "start"
    COMPLETE = "complete"
    # ... 50+ types
```

**前端定义** (`packages/core/src/types/events.ts`):
```typescript
export const EVENT_CATEGORIES: Record<EventType, EventCategory> = {
  [EventType.START]: EventCategory.AGENT,
  [EventType.COMPLETE]: EventCategory.AGENT,
  // ... 50+ types
};
```

### 2. WebSocket 消息格式一致性

| 字段 | 后端 (SSE) | 前端 | 状态 |
|------|-------------|------|------|
| type | 事件类型 | 事件类型 | ✅ 一致 |
| conversation_id | 会话 ID | 会话 ID | ✅ 一致 |
| data | 事件数据 | 事件数据 | ✅ 一致 |
| event_time_us | 单调时间戳 | 支持 | ✅ 一致 |
| event_counter | 事件计数器 | 支持 | ✅ 一致 |

**后端发送格式** (`chat_handler.py`):
```python
ws_event = {
    "type": event.get("type"),
    "conversation_id": conversation_id,
    "data": event_data,
    "timestamp": event.get("timestamp"),
    "event_time_us": evt_time_us,
    "event_counter": evt_counter,
}
```

**前端接收格式** (`packages/websocket/src/client.ts`):
```typescript
interface WebSocketMessage {
  type: string;
  conversation_id: string;
  data: any;
  event_time_us?: number;
  event_counter?: number;
}
```

### 3. 状态管理一致性

| 概念 | 后端 | 前端 | 状态 |
|------|------|------|------|
| AgentState | IDLE/THINKING/ACTING/OBSERVING | IDLE/THINKING/ACTING/OBSERVING | ✅ 一致 |
| ToolCall | name, arguments, call_id | name, arguments, callId | ✅ 一致 |
| ConversationState | timeline, messages, agentState | timeline, messages, agentState | ✅ 一致 |

### 4. 需要补充的点

#### 4.1 前端缺少 SSE Delta 事件类型

后端有 `TEXT_DELTA`, `THOUGHT_DELTA`, `ACT_DELTA`，但前端设计文档中未明确定义这些 Delta 事件的合并逻辑。

**建议**：在前端 `createDeltaBufferMiddleware` 中明确支持的事件类型：
```typescript
// packages/core/src/state/middleware.ts
export const DELTA_EVENT_TYPES: EventType[] = [
  EventType.TEXT_DELTA,
  EventType.THOUGHT_DELTA,
  EventType.ACT_DELTA,
  // ... 其他 delta 事件
];
```

#### 4.2 事件类型命名风格

后端使用 `snake_case` (如 `artifact_created`)，前端设计文档使用 `camelCase` (如 `artifactCreated`)。

**建议**：在前端 `events.ts` 中添加命名转换映射，或统一使用一种风格。

#### 4.3 WebSocket 心跳参数

后端默认心跳间隔 30s，前端设计文档默认 30s (一致)。

### 5. 建议的改进

1. **共享类型定义包**
   - 创建 `memstack-agent-shared` 包
   - 后端和前端都依赖此包
   - 确保 100% 类型一致性

2. **事件类型生成器**
   - 后端定义事件类型为 Single Source of Truth
   - 前端通过脚本从后端生成 TypeScript 类型

## 总结

| 审阅项 | 状态 | 说明 |
|---------|------|------|
| 事件类型 | ✅ 一致 | 50+ 类型完全匹配 |
| WebSocket 格式 | ✅ 一致 | 字段定义一致 |
| 状态管理 | ✅ 一致 | AgentState 匹配 |
| Delta 事件处理 | ⚠️ 需补充 | 前端需明确 delta 合并逻辑 |
| 命名风格 | ⚠️ 需统一 | snake_case vs camelCase |

## 建议下一步

1. 前端框架实现时，确保 Delta 事件合并逻辑与后端一致
2. 考虑创建共享类型包，避免前后端各自定义
3. 后端优先作为类型定义的 Single Source of Truth
