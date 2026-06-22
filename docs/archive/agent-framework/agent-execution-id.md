# 工具执行唯一 ID (execution_id) 技术设计

## 概述

为解决前端工具执行结果显示 "unknown" 的问题，引入 `execution_id` 机制，确保 `act` 和 `observe` 事件能够精确匹配。

## 问题背景

### 当前问题
1. 前端 timeline 渲染模式下，`observe` 事件的 `toolName` 被硬编码为 `'unknown'`
2. 依赖 `toolName` 进行 act/observe 匹配不可靠
3. 当工具名称匹配失败时，前端显示 "unknown"

### 根本原因
```
后端 act 事件:  { type: "act", tool_name: "MemorySearch", ... }
后端 observe 事件: { type: "observe", observation: {...} }  // 缺少 tool_name
前端 SSE 适配器:  { type: "observe", toolName: "unknown", ... }  // 硬编码降级
前端匹配逻辑:    MemorySearch !== unknown  // 匹配失败
```

## 解决方案

### 设计原则
1. **最小侵入**: 只添加新字段，不破坏现有结构
2. **向后兼容**: 前端支持降级匹配（toolName）
3. **唯一性保证**: 使用 UUID 确保唯一性

### 架构设计

```
┌─────────────────────────────────────────────────────────────────┐
│                       SessionProcessor                           │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │  _execute_tool()                                           │ │
│  │    1. 生成 execution_id = f"exec_{uuid.uuid4().hex[:12]}"  │ │
│  │    2. 执行工具                                              │ │
│  │    3. yield AgentActEvent(execution_id, ...)                │ │
│  │    4. yield AgentObserveEvent(execution_id, ...)            │ │
│  └────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     AgentEvent Domain                           │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │  AgentActEvent                                              │ │
│  │    - tool_execution_id: str (新增)                          │ │
│  │    - tool_name: str                                         │ │
│  │    - tool_input: dict                                       │ │
│  │    - call_id: str                                           │ │
│  └────────────────────────────────────────────────────────────┘ │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │  AgentObserveEvent                                          │ │
│  │    - tool_execution_id: str (新增)                          │ │
│  │    - tool_name: str (新增)                                  │ │
│  │    - result: dict                                           │ │
│  │    - call_id: str                                           │ │
│  └────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     SSE Transport                               │
│  {                                                              │
│    "type": "act",                                              │
│    "execution_id": "exec_abc123",    // 新增字段                 │
│    "tool_name": "MemorySearch",                                  │
│    ...                                                          │
│  }                                                              │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Frontend                                    │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │  sseEventAdapter                                            │ │
│  │    - 提取 execution_id                                      │ │
│  │    - 提取 tool_name (从 observe 事件)                        │ │
│  └────────────────────────────────────────────────────────────┘ │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │  TimelineEventItem                                          │ │
│  │    - 优先使用 execution_id 匹配                             │ │
│  │    - 降级：使用 toolName 匹配                               │ │
│  └────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

## 实施计划（计划 B：后端优先）

### Phase 1: 后端事件定义扩展
**文件**: `src/domain/events/agent_events.py`

```python
@dataclass
class AgentActEvent(AgentDomainEvent):
    """事件：Agent 调用工具"""
    tool_execution_id: str  # 新增：工具执行唯一标识
    tool_name: str
    tool_input: dict
    call_id: str
    status: str = "running"

@dataclass
class AgentObserveEvent(AgentDomainEvent):
    """事件：工具执行结果"""
    tool_execution_id: str  # 新增：与 act 事件相同
    tool_name: str          # 新增：工具名称
    result: dict
    call_id: str
    duration_ms: int = 0
    is_error: bool = False
```

### Phase 2: SessionProcessor 修改
**文件**: `src/infrastructure/agent/core/processor.py`

```python
async def _execute_tool(self, tool_name: str, arguments: dict, call_id: str):
    # 生成唯一执行 ID
    import uuid
    execution_id = f"exec_{uuid.uuid4().hex[:12]}"

    # 发送 act 事件
    yield AgentActEvent(
        tool_execution_id=execution_id,  # 新增
        tool_name=tool_name,
        tool_input=arguments,
        call_id=call_id,
        status="running",
    )

    try:
        result = await self.tool_executor.execute(tool_name, arguments)
        # 发送 observe 事件
        yield AgentObserveEvent(
            tool_execution_id=execution_id,  # 与 act 相同
            tool_name=tool_name,             # 新增
            result=as_sse_result(result),
            call_id=call_id,
            duration_ms=...,
        )
    except Exception as e:
        yield AgentObserveEvent(
            tool_execution_id=execution_id,
            tool_name=tool_name,
            result={"error": str(e)},
            call_id=call_id,
            is_error=True,
        )
```

### Phase 3: 前端类型定义
**文件**: `web/src/types/agent.ts`

```typescript
export interface ActEvent extends BaseTimelineEvent {
  type: 'act';
  execution_id?: string;
  toolName: string;
  toolInput: Record<string, unknown>;
  execution: ToolExecutionInfo;
}

export interface ObserveEvent extends BaseTimelineEvent {
  type: 'observe';
  execution_id?: string;
  toolName: string;
  toolOutput: unknown;
  isError: boolean;
}
```

### Phase 4: 前端 SSE 适配器
**文件**: `web/src/utils/sseEventAdapter.ts`

```typescript
case 'observe': {
  return {
    type: 'observe',
    execution_id: data.execution_id,  // 新增
    toolName: data.tool_name || 'unknown',
    toolOutput: data.observation,
  };
}
```

### Phase 5: 前端匹配逻辑
**文件**: `web/src/components/agent/TimelineEventItem.tsx`

```typescript
function findMatchingObserve(actEvent: ActEvent, events: TimelineEvent[]): ObserveEvent | undefined {
  const actExecId = (actEvent as any).execution_id;

  for (let i = actIndex + 1; i < events.length; i++) {
    const event = events[i];
    if (event.type === 'observe') {
      const observeExecId = (event as any).execution_id;
      // 优先使用 execution_id 匹配
      if (actExecId && observeExecId && actExecId === observeExecId) {
        return event;
      }
      // 降级：使用 toolName 匹配
      if (!actExecId && !observeExecId && event.toolName === actEvent.toolName) {
        return event;
      }
    }
    if (event.type === 'act' || event.type === 'user_message') break;
  }
  return undefined;
}
```

## 测试计划

### 后端测试
1. **单元测试**: 验证 execution_id 生成唯一性
2. **集成测试**: 验证 act/observe 事件的 execution_id 匹配
3. **E2E 测试**: 验证完整工具执行流程

### 前端测试
1. **单元测试**: sseEventAdapter 正确提取 execution_id
2. **组件测试**: TimelineEventItem 正确匹配事件
3. **集成测试**: 完整 SSE 流程

## 兼容性保证

1. **新增字段为可选**: 前端适配器处理缺失情况
2. **降级匹配**: 保留 toolName 匹配作为后备
3. **版本兼容**: 旧版本前端忽略新字段

## 部署顺序

1. **后端部署**: 先部署包含 execution_id 的后端
2. **前端部署**: 再部署使用 execution_id 的前端
3. **验证**: 确认新版本正常工作

## 回滚计划

如果出现问题：
1. 前端可以忽略 `execution_id` 字段，使用原有逻辑
2. 后端可以保持生成 `execution_id`，前端不使用
3. 无需数据库迁移
