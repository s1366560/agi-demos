# 前后端接口一致性审阅

## 审阅目标

确保 `memstack-agent` 后端框架与 `memstack-agent-ui` 前端框架的接口一致性。

## 审阅结果

### 1. 事件类型一致性

| 分类 | 后端 | 前端 | 状态 |
|------|------|------|------|
| 核心事件 | 165 (AgentEventType) | 165 (AgentEventType union) | ✅ 一致 |
| 事件分类 | 5 类 (AGENT/HITL/SANDBOX/SYSTEM/MESSAGE) | 5 类 (EventCategory) | ✅ 一致 |
| 事件过滤 | `is_terminal_event()`, `is_delta_event()`, `is_hitl_event()` | `isTerminalEvent()`, `isDeltaEvent()`, `isHITLEvent()` | ✅ 一致 |

**后端定义** (`src/domain/events/types.py`):
```python
class AgentEventType(str, Enum):
    START = "start"
    COMPLETE = "complete"
    # ... 165 types
```

**前端定义** (`web/src/types/generated/eventTypes.ts`, auto-generated via `make generate-event-types`):
```typescript
export type EventCategory = 'agent' | 'hitl' | 'sandbox' | 'system' | 'message';

export const EVENT_CATEGORIES: Record<AgentEventType, EventCategory> = {
  start: 'agent',
  complete: 'agent',
  // ... 165 types
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

**后端发送格式** (`src/infrastructure/adapters/primary/web/websocket/handlers/chat_handler.py`):
```python
ws_event = {
    "type": event.get("type"),
    "conversation_id": conversation_id,
    "data": event_data,
    "seq": event.get("id"),
    "timestamp": event.get("timestamp", datetime.now(UTC).isoformat()),
    "event_time_us": event.get("event_time_us"),
    "event_counter": event.get("event_counter"),
}
```

**前端接收格式** (`web/src/services/agentService.ts` 及相关 WS 桥接代码):
```typescript
interface WebSocketMessage {
  type: string;
  conversation_id: string;
  data: any;
  seq?: string;
  timestamp?: string;
  event_time_us?: number;
  event_counter?: number;
}
```

### 3. 状态管理一致性

| 概念 | 后端 | 前端 | 状态 |
|------|------|------|------|
| AgentState | ExecutionStatus: THINKING/ACTING/OBSERVING/COMPLETED/FAILED (+ work_planning/step_executing/synthesizing) | AgentState: idle/thinking/preparing/acting/observing/awaiting_input/retrying | ✅ 概念一致（枚举值不同） |
| ToolCall | name, arguments, result | name, arguments, result | ✅ 一致 |
| ConversationState | timeline, messages, agentState | timeline, messages, agentState | ✅ 一致 |

### 4. 需要补充的点

#### 4.1 Delta 事件类型（已解决）

前端 `web/src/types/generated/eventTypes.ts` 已显式定义 Delta 事件集合：
```typescript
export const DELTA_EVENT_TYPES: AgentEventType[] = [
  'text_start',
  'text_end',
  'text_delta',
  'thought_delta',
  'act_delta',
  'thought_start',
];

export function isDeltaEvent(eventType: AgentEventType): boolean {
  return DELTA_EVENT_TYPES.includes(eventType);
}
```

Delta 合并逻辑由 `web/src/stores/agent/deltaBuffers.ts` 提供（`getDeltaBuffer` /
`clearDeltaBuffers` / `clearAllDeltaBuffers`），由 `agentV3` store 及
`messageSendActions` 在流式接收时消费。

#### 4.2 事件类型命名风格（已解决）

前后端统一使用 `snake_case`（如 `artifact_created`、`thought_delta`）。前端
生成的 `EVENT_CATEGORIES` 映射键全量为 `snake_case`，无需 camelCase 转换层。

#### 4.3 WebSocket 心跳参数

后端默认心跳间隔 30s，前端默认 30s（一致）。

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
| 事件类型 | ✅ 一致 | 165 类型完全匹配 |
| WebSocket 格式 | ✅ 一致 | 字段定义一致 |
| 状态管理 | ✅ 一致 | AgentState 匹配 |
| Delta 事件处理 | ✅ 已解决 | 前端 `DELTA_EVENT_TYPES` + `deltaBuffers` 已实现合并逻辑 |
| 命名风格 | ✅ 已解决 | 前后端统一 snake_case |

## 建议下一步

1. 前端框架实现时，确保 Delta 事件合并逻辑与后端一致
2. 考虑创建共享类型包，避免前后端各自定义
3. 后端优先作为类型定义的 Single Source of Truth
