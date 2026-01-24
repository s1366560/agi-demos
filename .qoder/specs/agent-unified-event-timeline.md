# Agent 统一事件时间线重构方案

## 问题背景

1. **多轮对话问题**：原方案只能支持单轮对话，timeline 排序存在问题
2. **性能问题**：`agent_execution_events` 表存储了大量 `text_delta` 事件（每个 token 一条），造成数据膨胀

**核心问题**：
- 用户消息存储在 `messages` 表，无 sequence_number
- Agent 事件存储在 `agent_execution_events` 表，有 sequence_number
- `text_delta` 事件过多导致表膨胀，但 Redis 已有完整流数据

## 解决方案

### 1. 扩展 events 表支持消息事件

将用户消息和助手消息也写入 `agent_execution_events` 表，统一使用 sequence_number 排序。

### 2. 只持久化完整内容事件

**PostgreSQL 持久化**（用于历史查询）：
- `user_message` - 用户消息
- `thought` - 完整思考内容
- `act` - 工具调用
- `observe` - 工具结果
- `assistant_message` - 助手最终回复

**Redis 流式缓存**（用于实时推送，不持久化到 PostgreSQL）：
- `text_start` - 文本流开始
- `text_delta` - 文本增量
- `text_end` - 文本流结束

### 事件持久化决策表

| 事件类型 | PostgreSQL | Redis | 说明 |
|---------|------------|-------|------|
| user_message | ✅ | ❌ | 新增，用户消息 |
| thought | ✅ | ✅ | 完整思考内容 |
| act | ✅ | ✅ | 工具调用 |
| observe | ✅ | ✅ | 工具结果 |
| assistant_message | ✅ | ❌ | 新增，完整回复 |
| text_start | ❌ | ✅ | 仅流式推送 |
| text_delta | ❌ | ✅ | 仅流式推送 |
| text_end | ❌ | ✅ | 仅流式推送 |
| work_plan | ✅ | ✅ | 工作计划 |
| step_start | ✅ | ✅ | 步骤开始 |
| step_end | ✅ | ✅ | 步骤结束 |

---

## 数据流设计

```
用户发送消息
  ├─→ messages 表：保存完整消息（用于 LLM context）
  └─→ events 表：保存 user_message 事件（用于 timeline）

Agent 思考
  └─→ events 表：保存 thought 事件（完整内容）

Agent 工具调用
  ├─→ events 表：保存 act 事件
  └─→ events 表：保存 observe 事件

Agent 文本流式输出
  ├─→ Redis：text_start → text_delta × N → text_end（实时推送）
  └─→ 不写入 PostgreSQL！

Agent 完成
  ├─→ messages 表：保存助手消息（用于 LLM context）
  └─→ events 表：保存 assistant_message 事件（完整内容）
```

---

## 实现步骤

### Step 1: 修改事件持久化逻辑

**文件**: `src/infrastructure/adapters/secondary/temporal/activities/agent.py`

在保存事件时过滤 delta 类事件：

```python
# 定义需要持久化的事件类型
PERSISTENT_EVENT_TYPES = {
    "user_message",      # 新增
    "thought",
    "act", 
    "observe",
    "assistant_message", # 新增
    "work_plan",
    "step_start",
    "step_end",
    "pattern_match",
    "skill_matched",
    "skill_execution_start",
    "skill_execution_complete",
    "complete",
    "error",
}

async def _save_event_to_db(...):
    # 跳过非持久化事件
    if event_type not in PERSISTENT_EVENT_TYPES:
        return  # text_delta 等不写入 PostgreSQL
    
    # 正常保存逻辑...
```

### Step 2: 用户消息写入 events 表

**文件**: `src/application/services/agent_service.py`

```python
# 现有代码：保存用户消息到 messages 表
user_msg = Message(...)
await self._message_repo.save_and_commit(user_msg)

# 新增：同时写入 events 表
next_seq = await self._event_repo.get_next_sequence(conversation_id)
await self._event_repo.save(AgentExecutionEvent(
    id=str(uuid.uuid4()),
    conversation_id=conversation_id,
    message_id=user_msg.id,
    event_type="user_message",
    event_data={"content": user_message, "message_id": user_msg.id},
    sequence_number=next_seq,
    created_at=datetime.utcnow(),
))
```

### Step 3: 助手消息写入 events 表

**文件**: `src/infrastructure/adapters/secondary/temporal/activities/agent.py`

在 COMPLETE 事件之前添加 assistant_message 事件：

```python
# 保存 assistant_message 事件
sequence_number += 1
await _save_event_to_db(
    conversation_id=conversation_id,
    message_id=message_id,
    event_type="assistant_message",
    event_data={"content": final_content, "message_id": assistant_msg_id},
    sequence_number=sequence_number,
)
```

### Step 4: 简化后端 API

**文件**: `src/infrastructure/adapters/primary/web/routers/agent.py`

```python
@router.get("/conversations/{conversation_id}/messages")
async def get_conversation_messages(...) -> dict:
    # 直接从 events 表获取所有事件
    events = await event_repo.get_events(conversation_id, from_sequence=0)
    
    # 构建 timeline（events 已按 sequence_number 排序）
    timeline = []
    for event in events:
        event_type = event.event_type
        data = event.event_data or {}
        
        # 跳过不需要在 timeline 显示的事件
        if event_type not in ("user_message", "thought", "act", "observe", "assistant_message"):
            continue
        
        item = {
            "id": f"{event_type}-{event.sequence_number}",
            "sequenceNumber": event.sequence_number,
            "timestamp": int(event.created_at.timestamp() * 1000),
        }
        
        if event_type == "user_message":
            item["type"] = "user_message"
            item["content"] = data.get("content")
            item["id"] = data.get("message_id", item["id"])
        
        elif event_type == "thought":
            thought = data.get("thought", "")
            if not thought or not thought.strip():
                continue
            item["type"] = "thought"
            item["content"] = thought
        
        elif event_type == "act":
            item["type"] = "tool_call"
            item["toolName"] = data.get("tool_name")
            item["toolInput"] = data.get("tool_input")
        
        elif event_type == "observe":
            item["type"] = "tool_result"
            item["toolName"] = data.get("tool_name")
            item["toolOutput"] = data.get("observation")
            item["isError"] = data.get("is_error", False)
        
        elif event_type == "assistant_message":
            item["type"] = "assistant_message"
            item["content"] = data.get("content")
            item["id"] = data.get("message_id", item["id"])
        
        timeline.append(item)
    
    return {
        "conversationId": conversation_id,
        "timeline": timeline,
        "total": len(timeline),
    }
```

### Step 5: 前端适配

已完成的前端修改保持不变：
- `web/src/types/agent.ts` - TimelineItem 类型定义
- `web/src/services/agentService.ts` - 返回 ConversationTimelineResponse
- `web/src/stores/agentV3.ts` - 使用 timeline 数据
- `web/src/components/agentV3/MessageList.tsx` - 渲染 timeline

---

## 关键文件

| 文件 | 修改类型 | 说明 |
|------|----------|------|
| `src/infrastructure/adapters/secondary/temporal/activities/agent.py` | 写入过滤 | 跳过 delta 事件持久化 |
| `src/application/services/agent_service.py` | 写入逻辑 | 用户消息写入 events |
| `src/infrastructure/adapters/primary/web/routers/agent.py` | API 逻辑 | 简化为只读 events |
| `web/src/stores/agentV3.ts` | Store | 直接使用 timeline |
| `web/src/components/agentV3/MessageList.tsx` | 渲染 | timeline 渲染 |

---

## 性能优化效果

**优化前**（以一次包含 1000 token 输出的对话为例）：
```
events 表记录数：
  1 × thought
  1 × act
  1 × observe
  1 × text_start
  1000 × text_delta  ← 性能瓶颈！
  1 × text_end
  1 × complete
合计：~1006 条记录
```

**优化后**：
```
events 表记录数：
  1 × user_message
  1 × thought
  1 × act
  1 × observe
  1 × assistant_message
合计：5 条记录

性能提升：~200x 减少写入量
```

---

## 数据一致性

**messages 表保留**：
- 用于 LLM context 构建（聚合内容）
- 用于对话历史列表查询
- 用于 message_count 统计

**events 表优化**：
- 新增 user_message、assistant_message 事件类型
- 移除 text_delta 等流式事件的持久化
- 统一 timeline 排序
- 支持多轮对话

**Redis 职责**：
- 存储流式事件（text_delta）用于实时 WebSocket 推送
- 提供事件重放能力（短期）
- 不作为持久化存储

---

## 验证方案

1. **后端测试**:
   ```bash
   # 发送多轮对话
   curl -X POST .../chat -d '{"message": "第一轮"}'
   curl -X POST .../chat -d '{"message": "第二轮"}'
   
   # 验证 events 表只有聚合事件
   SELECT event_type, COUNT(*) FROM agent_execution_events 
   WHERE conversation_id = 'xxx' GROUP BY event_type;
   # 应该不包含 text_delta
   
   # 获取 timeline
   curl .../messages?project_id=xxx | jq '.timeline'
   ```

2. **前端测试**:
   - 多轮对话后刷新页面
   - 验证所有消息和事件按正确顺序显示
   - 验证 思考→工具→结果 的卡片循环

3. **性能验证**:
   - 对比优化前后 events 表记录数
   - 验证历史加载速度提升
