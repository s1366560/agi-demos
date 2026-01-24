# Agent 执行架构升级：后端 Worker + SSE 重放

## 概述

将 Agent 执行从内存模式迁移到后端 Worker 执行，支持多个 Agent 并行执行。执行过程保存到数据库中，前端连接时通过 SSE 重放已执行的消息，直至追赶到最新状态。

---

## 当前架构分析

### 现有执行流程

```
用户请求 → POST /api/v1/agent/chat
  → AgentService.stream_chat_v2()
    → ReActAgent.stream() [内存执行]
      → SessionProcessor.process() [主循环]
        → LLM 调用
        → 工具执行
        → SSE 事件 → 前端
```

**关键特征：**
- **100% 内存执行**：Agent 运行完全在 API 服务器进程中
- **SSE 实时推送**：事件通过 Server-Sent Events 发送到前端
- **状态持久化不足**：消息仅在完成后保存，执行状态不持久化
- **不可恢复**：SSE 连接断开后，执行状态丢失

### 已有数据库表

PostgreSQL 中已存在以下表：
- `conversations` - 会话信息
- `messages` - 消息记录（含 tool_calls, tool_results）
- `agent_executions` - Agent 执行记录
- `work_plans` - 工作计划
- `tool_execution_records` - 工具执行记录

**当前未持久化：**
- ❌ 进行中的执行状态
- ❌ 中间 SSE 事件（thoughts, observations）
- ❌ 执行检查点（用于故障恢复）

---

## 实施方案

### 方案选择

| 方案 | 复杂度 | 可恢复性 | 并行支持 | 推荐度 |
|------|--------|----------|----------|--------|
| A. 事件持久化 | 低 | 部分 | 支持 | ⭐⭐⭐ |
| B. Temporal 工作流 | 高 | 完全 | 支持 | ⭐⭐⭐⭐ |
| C. 混合方案 | 中 | 完全 | 支持 | ⭐⭐⭐⭐⭐ |

**推荐：混合方案**（分阶段实施）

---

## 第一阶段：事件持久化 + SSE 重放（1-2周）

### 目标
- 持久化所有 SSE 事件到数据库
- 提供事件重放 API
- 前端切换会话时自动重放已执行的事件

### 数据库变更

**新增表：`agent_execution_events`**

```sql
CREATE TABLE agent_execution_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID NOT NULL REFERENCES conversations(id),
    message_id UUID NOT NULL REFERENCES messages(id),
    event_type VARCHAR(50) NOT NULL,  -- thought, act, observe, etc.
    event_data JSONB NOT NULL,
    sequence_number INT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    INDEX idx_conversation_sequence (conversation_id, sequence_number)
);
```

### 后端变更

**1. 修改 AgentService 保存事件**

```python
# src/application/services/agent_service.py

async def stream_chat_v2(self, request: ChatRequest):
    async for event in react_agent.stream(...):
        # 保存事件到数据库
        await agent_event_repo.save_event(
            conversation_id=request.conversation_id,
            message_id=message_id,
            event_type=event["type"],
            event_data=event["data"],
            sequence_number=current_sequence
        )
        yield event  # 继续流式传输
```

**2. 新增事件重放 API**

```python
# src/infrastructure/adapters/primary/web/routers/agent.py

@router.get("/conversations/{conversation_id}/events")
async def get_conversation_events(
    conversation_id: str,
    from_sequence: int = 0,
    limit: int = 1000
):
    """获取会话事件用于重放"""
    events = await agent_event_repo.get_events(
        conversation_id=conversation_id,
        from_sequence=from_sequence,
        limit=limit
    )
    return {"events": events, "has_more": len(events) == limit}
```

**3. 新增执行状态查询 API**

```python
@router.get("/conversations/{conversation_id}/execution-status")
async def get_execution_status(conversation_id: str):
    """获取会话当前执行状态"""
    return {
        "is_running": bool(active_executions.get(conversation_id)),
        "last_sequence": await agent_event_repo.get_last_sequence(conversation_id),
        "current_message_id": await get_current_message_id(conversation_id)
    }
```

### 前端变更

**1. 新增事件重放服务**

```typescript
// web/src/services/agentEventReplayService.ts

export class AgentEventReplayService {
  async replayEvents(
    conversationId: string,
    onEvent: (event: SSEEvent) => void,
    fromSequence = 0
  ): Promise<void> {
    let hasMore = true;
    let sequence = fromSequence;

    while (hasMore) {
      const response = await fetch(
        `/api/v1/agent/conversations/${conversationId}/events?` +
        `from_sequence=${sequence}&limit=100`
      );
      const data = await response.json();

      for (const event of data.events) {
        onEvent(event);
        sequence = Math.max(sequence, event.sequence_number + 1);
      }

      hasMore = data.has_more;
    }
  }
}
```

**2. 修改会话切换逻辑**

```typescript
// web/src/stores/agentV3.ts

loadMessages: async (conversationId, projectId) => {
  set({ isLoadingHistory: true, messages: [] });

  // 1. 获取执行状态
  const status = await agentService.getExecutionStatus(conversationId);

  // 2. 加载历史消息
  const response = await agentService.getConversationMessages(conversationId, projectId);
  const processedMessages = processHistory(response.messages);
  set({ messages: processedMessages });

  // 3. 如果正在执行，重放事件并连接 SSE
  if (status.is_running) {
    // 重放历史事件
    await replayService.replayEvents(conversationId, (event) => {
      // 应用历史事件到 store
      applyEventToStore(event);
    }, status.last_sequence + 1);

    // 连接实时 SSE
    connectToSSE(conversationId);
  } else {
    set({ isLoadingHistory: false });
  }
}
```

---

## 第二阶段：执行检查点（2-3周）

### 目标
- 在关键执行点保存检查点
- 支持从检查点恢复执行
- 断线重连后可继续执行

### 数据库变更

**新增表：`execution_checkpoints`**

```sql
CREATE TABLE execution_checkpoints (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID NOT NULL REFERENCES conversations(id),
    message_id UUID NOT NULL REFERENCES messages(id),
    checkpoint_type VARCHAR(50) NOT NULL,  -- llm_complete, tool_start, etc.
    execution_state JSONB NOT NULL,  -- 完整执行状态快照
    step_number INT,
    created_at TIMESTAMP DEFAULT NOW()
);
```

### 后端变更

**1. 在 ReActAgent 中添加检查点保存**

```python
# src/infrastructure/agent/core/processor.py

class SessionProcessor:
    async def process(self):
        # LLM 调用后保存检查点
        thought = await self.llm.generate(...)
        await checkpoint_repo.save({
            "type": "llm_complete",
            "state": self.get_state_snapshot(),
            "thought": thought
        })

        # 工具执行前保存
        if thought.tool_call:
            await checkpoint_repo.save({
                "type": "tool_start",
                "state": self.get_state_snapshot()
            })
            result = await self.execute_tool(thought.tool_call)
```

**2. 添加恢复 API**

```python
@router.post("/conversations/{conversation_id}/resume")
async def resume_execution(conversation_id: str):
    """从最后检查点恢复执行"""
    checkpoint = await checkpoint_repo.get_latest(conversation_id)
    if not checkpoint:
        raise HTTPException(404, "No checkpoint found")

    # 从检查点恢复执行
    await react_agent.resume_from(checkpoint.execution_state)
    return {"status": "resuming", "from_step": checkpoint.step_number}
```

---

## 第三阶段：Temporal 工作流迁移（4-6周）

### 目标
- 将 Agent 执行迁移到 Temporal 工作流
- 利用 Temporal 的自动重试和恢复能力
- 支持长时间运行的 Agent

### Temporal 工作流定义

```python
# src/infrastructure/temporal/workflows/agent_execution.py

@workflow.defn(name="agent-execution")
class AgentExecutionWorkflow:
    @workflow.run
    async def run(self, input: AgentInput) -> AgentOutput:
        # 执行循环
        while not self.is_complete():
            # LLM 思考活动
            thought = await workflow.execute_activity(
                llm_thinking_activity,
                input,
                start_to_close_timeout=60s,
                retry_policy=RetryPolicy(...)
            )

            # 发送信号到前端
            workflow.signal_event("thought", thought)

            # 工具执行活动
            if thought.tool_call:
                result = await workflow.execute_activity(
                    tool_execution_activity,
                    thought.tool_call,
                    start_to_close_timeout=300s
                )
                workflow.signal_event("observation", result)

        return final_result

    @workflow.signal
    async def signal_event(self, event_type: str, data: dict):
        """发送事件到前端"""
        # 通过活动保存到数据库
        await workflow.execute_activity(
            save_event_activity,
            event_type, data
        )
```

### 前端连接逻辑

```typescript
// 连接到正在运行的 Temporal 工作流
async function connectToWorkflow(conversationId: string) {
  // 1. 获取工作流状态
  const status = await temporal.getWorkflowStatus(conversationId);

  // 2. 重放历史事件
  await replayEvents(conversationId, status.last_event_sequence);

  // 3. 订阅新事件
  const subscription = temporal.subscribeWorkflowEvents(conversationId, {
    onEvent: (event) => applyEventToStore(event),
    onComplete: () => set({ isStreaming: false })
  });

  return subscription;
}
```

---

## 文件修改清单

### 后端
1. **新建文件**
   - `src/domain/model/agent/agent_execution_event.py`
   - `src/domain/repositories/agent_event_repository.py`
   - `src/infrastructure/adapters/secondary/persistence/agent_event_repo.py`
   - `src/application/services/agent_event_replay_service.py`

2. **修改文件**
   - `src/application/services/agent_service.py` - 添加事件保存
   - `src/infrastructure/agent/core/processor.py` - 添加检查点保存
   - `src/infrastructure/adapters/primary/web/routers/agent.py` - 添加新 API
   - `alembic/versions/xxx_add_agent_events.py` - 数据库迁移

### 前端
1. **新建文件**
   - `web/src/services/agentEventReplayService.ts`
   - `web/src/services/agentExecutionService.ts`

2. **修改文件**
   - `web/src/stores/agentV3.ts` - 集成事件重放
   - `web/src/pages/project/AgentChatV3.tsx` - 更新切换逻辑
   - `web/src/services/agentService.ts` - 添加新 API 调用

---

## 验证步骤

### 第一阶段验证
1. **事件持久化**
   - 发送消息后检查 `agent_execution_events` 表有记录
   - 刷新页面后事件 timeline 正常显示

2. **会话切换**
   - 在会话 A 发送消息（执行中）
   - 切换到会话 B，再切回 A
   - 验证：A 的执行状态和 timeline 正确显示

3. **重放功能**
   - 执行中的会话断开 SSE 连接
   - 重新连接后从断点继续

### 第二阶段验证
1. **检查点保存**
   - 每次工具执行前后有检查点记录
   - 检查点包含完整状态快照

2. **恢复执行**
   - 执行中手动终止进程
   - 调用 resume API 从检查点恢复

---

## 架构优势

| 特性 | 当前架构 | 升级后 |
|------|----------|--------|
| 并行执行 | ❌ 单进程 | ✅ Worker 池 |
| 状态持久化 | 部分 | 完整 |
| 断线恢复 | ❌ | ✅ |
| 事件重放 | ❌ | ✅ |
| 长时间运行 | ❌ | ✅ |
| 多设备同步 | ❌ | ✅ |
