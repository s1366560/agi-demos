# 多次 HITL 完整数据流

## 架构概览

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              前端 (Web)                                       │
├─────────────────────────────────────────────────────────────────────────────┤
│  AgentChatContent                                                          │
│       │                                                                     │
│       ▼                                                                     │
│  useUnifiedHITL ────────► UnifiedHITLPanel / InlineHITLCard                │
│       │                              │                                      │
│       ▼                              ▼                                      │
│  hitlStore.unified ◄─────── 用户交互 (提交/取消)                            │
│       │                                                                     │
│       ▼                                                                     │
│  hitlService.unified.respond()                                             │
│       │                                                                     │
└───────┬─────────────────────────────────────────────────────────────────────┘
        │ HTTP/WebSocket
        ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                             后端 (API)                                        │
├─────────────────────────────────────────────────────────────────────────────┤
│  HITL Router                                                                 │
│       │                                                                     │
│       ▼                                                                     │
│  Redis Stream (hitl:response:{tenant}:{project})                            │
│       │                                                                     │
└───────┬─────────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          后端 (Ray Actor)                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│  HITLStreamRouterActor                                                       │
│       │                                                                     │
│       ▼                                                                     │
│  ProjectAgentActor.continue_chat(request_id, response_data)                │
│       │                                                                     │
│       ▼                                                                     │
│  continue_project_chat()                                                   │
│       │                                                                     │
│       ├──► load_state_by_request(request_id) ◄──┐                          │
│       │                                         │                          │
│       ├──► delete_state(request_id)             │                          │
│       │                                         │                          │
│       └──► agent.execute_chat(hitl_response) ───┘                          │
│                       │                                                     │
│                       ▼                                                     │
│              ┌─────────────────┐                                           │
│              │  第二次 HITL ?  │                                           │
│              └────────┬────────┘                                           │
│                       │                                                     │
│         ┌─────────────┴─────────────┐                                      │
│         │                           │                                      │
│         ▼                           ▼                                      │
│   否：完成                 是：抛出 HITLPendingException                   │
│         │                           │                                      │
│         │                           ▼                                      │
│         │                   handle_hitl_pending()                          │
│         │                           │                                      │
│         │                           ▼                                      │
│         │                   save_state(新的 request_id)                    │
│         │                           │                                      │
│         │                           ▼                                      │
│         │                   返回 pending 结果                              │
│         │                           │                                      │
└─────────┼───────────────────────────┼──────────────────────────────────────┘
          │                           │
          ▼                           ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                             前端 (Web)                                        │
│  完成事件                    新的 HITL 事件                                  │
│       │                           │                                         │
│       ▼                           ▼                                         │
│  显示完成                    handleSSEEvent()                               │
│                                   │                                         │
│                                   ▼                                         │
│                            addRequest(新的 request)                        │
│                                   │                                         │
│                                   ▼                                         │
│                            显示新的 HITL UI                                 │
└─────────────────────────────────────────────────────────────────────────────┘
```

## 详细数据流

### 第一次 HITL

```
1. Agent 执行中
   └─► 调用 ask_clarification 工具
       └─► _execute_hitl_request() 
           ├─► 检查 preinjected_response (无)
           ├─► 创建 HITLRequest
           ├─► persist_hitl_request() [保存到 DB]
           ├─► emit SSE event (clarification_asked)
           └─► 抛出 HITLPendingException

2. handle_hitl_pending()
   ├─► 捕获 HITLPendingException
   ├─► 保存当前消息到 HITLAgentState
   ├─► state_store.save_state() [保存到 Redis]
   ├─► save_hitl_snapshot() [备份]
   └─► 返回 {hitl_pending: true, request_id: "xxx"}

3. 前端接收 SSE
   └─► clarification_asked 事件
       └─► handleSSEEvent()
           └─► addRequest()
               └─► UnifiedHITLPanel 显示

4. 用户提交响应
   └─► submitResponse()
       ├─► unifiedHitlService.respond()
       │   └─► POST /api/v1/hitl/respond
       └─► updateRequestStatus('answered')
```

### 恢复执行 (Continue)

```
5. 后端接收响应
   └─► HITL Stream Router
       └─► actor.continue_chat(request_id, response_data)

6. continue_project_chat()
   ├─► state_store.load_state_by_request(request_id)
   ├─► state_store.delete_state(request_id)
   ├─► 构建 hitl_response_for_agent
   ├─► 将 HITL 响应作为 tool result 添加到消息
   └─► agent.execute_chat(hitl_response=hitl_response_for_agent)

7. Agent 继续执行
   └─► 新的 SessionProcessor
       ├─► _get_hitl_handler() 
       │   └─► 从 langfuse_context 获取 hitl_response
       ├─► 使用 preinjected 响应继续 ReAct 循环
       └─► 处理 tool result，继续对话
```

### 第二次 HITL

```
8. Agent 触发第二个 HITL
   └─► 调用 request_decision 工具
       └─► _execute_hitl_request()
           ├─► 检查 preinjected_response (已消费，为 null)
           ├─► 创建新的 HITLRequest (不同的 request_id)
           ├─► persist_hitl_request()
           ├─► emit SSE event (decision_asked)
           └─► 抛出 HITLPendingException

9. 在 continue_project_chat 中捕获
   └─► 捕获 HITLPendingException
       ├─► 注意：此时已有 events 列表
       ├─► _persist_events() [保存已发出的事件]
       ├─► handle_hitl_pending()
       │   ├─► 保存新的 HITLAgentState
       │   ├─► 包含之前的事件序列号
       │   └─► 新的 request_id
       └─► 返回 {hitl_pending: true, request_id: "yyy"}

10. 前端接收第二个 SSE
    └─► decision_asked 事件
        └─► handleSSEEvent()
            └─► addRequest()
                └─► UnifiedHITLPanel 显示新的 HITL
```

## 关键状态

### Redis State 结构

```typescript
// 第一次 HITL
{
  "conversation_id": "conv-001",
  "hitl_request_id": "clar_001",
  "hitl_type": "clarification",
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "..."},
    {"role": "assistant", "content": null, "tool_calls": [...]}, // ask_clarification
  ],
  "pending_tool_call_id": "call_001",
  "last_sequence_number": 5,
  "step_count": 2
}

// 第二次 HITL
{
  "conversation_id": "conv-001",
  "hitl_request_id": "dec_002",  // 新的 ID
  "hitl_type": "decision",
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "..."},
    {"role": "assistant", "content": null, "tool_calls": [...]}, // ask_clarification
    {"role": "tool", "tool_call_id": "call_001", "content": "用户回答"},
    {"role": "assistant", "content": null, "tool_calls": [...]}, // request_decision
  ],
  "pending_tool_call_id": "call_002",  // 新的 tool call
  "last_sequence_number": 12,  // 继续递增
  "step_count": 4
}
```

### 前端 Store 结构

```typescript
// pendingRequests Map
{
  "clar_001": {
    requestId: "clar_001",
    hitlType: "clarification",
    status: "answered",  // 已回答
    // ...
  },
  "dec_002": {
    requestId: "dec_002",
    hitlType: "decision",
    status: "pending",   // 等待中
    // ...
  }
}

// requestsByConversation Map
{
  "conv-001": Set(["clar_001", "dec_002"])
}
```

## 时序图

```
用户    前端    Agent Actor    Redis    后端API    LLM
 │       │          │           │         │        │
 │──────►│          │           │         │        │
 │ 消息   │          │           │         │        │
 │       │─────────►│           │         │        │
 │       │  chat()  │           │         │        │
 │       │          │──────────►│         │        │
 │       │          │  保存状态  │         │        │
 │       │          │           │         │        │
 │       │◄─────────│           │         │        │
 │       │SSE:      │           │         │        │
 │       │clar_asked│           │         │        │
 │◄──────│          │           │         │        │
 │显示HITL│          │           │         │        │
 │       │          │           │         │        │
 │──────►│          │           │         │        │
 │ 回答   │          │           │         │        │
 │       │─────────────────────►│         │        │
 │       │      POST /respond   │         │        │
 │       │          │           │─────────►│       │
 │       │          │◄──────────│         │        │
 │       │          │   读取响应 │         │        │
 │       │          │           │         │        │
 │       │          │────────────────────────────────►
 │       │          │      继续执行 (带响应)          │
 │       │          │◄───────────────────────────────│
 │       │          │       触发第二个 HITL          │
 │       │          │           │         │        │
 │       │          │──────────►│         │        │
 │       │          │  保存新状态 │         │        │
 │       │          │           │         │        │
 │       │◄─────────│           │         │        │
 │       │SSE:      │           │         │        │
 │       │dec_asked │           │         │        │
 │◄──────│          │           │         │        │
 │显示新HITL         │           │         │        │
 │       │          │           │         │        │
 │──────►│          │           │         │        │
 │ 回答   │          │           │         │        │
 │       │─────────────────────►│         │        │
 │       │          │           │         │        │
 │       │          │... (重复) │         │        │
 │       │          │           │         │        │
 │       │◄─────────│           │         │        │
 │       │SSE:      │           │         │        │
 │       │complete  │           │         │        │
 │◄──────│          │           │         │        │
 │完成   │          │           │         │        │
```

## 常见问题排查

### 问题 1: 第二个 HITL 不显示

**检查点**:
1. 后端是否正确发送了第二个 SSE 事件？
2. 前端 `handleSSEEvent` 是否被调用？
3. `addRequest` 是否成功添加？
4. `pendingRequests` 中是否存在两个请求？

**调试命令**:
```typescript
// 在浏览器控制台
const store = window.__ZUSTAND_STORES__?.unifiedHitlStore;
store?.getState()?.pendingRequests.forEach((v, k) => 
  console.log(k, v.hitlType, v.status)
);
```

### 问题 2: 第二个 HITL 显示为第一个

**检查点**:
1. `useUnifiedHITL` 中的 `currentRequest` 逻辑
2. 是否按 `createdAt` 正确排序？
3. 第一个 HITL 的状态是否已更新为 'answered'？

### 问题 3: 响应提交后状态不更新

**检查点**:
1. `submitResponse` 是否先调用 API 后更新状态？
2. API 调用是否成功？
3. `updateRequestStatus` 是否被调用？
4. 组件是否正确监听状态变化？

### 问题 4: 序列号不连续

**检查点**:
1. `batchConvertSSEEvents` 是否重置了计数器？
2. `continue_project_chat` 是否传递了 `last_sequence_number`？
3. 新的事件是否使用了正确的起始序列号？

## 性能考虑

1. **状态存储**: 每个 HITL 请求占用约 1-2KB 内存
2. **Redis 存储**: 默认 5 分钟 TTL
3. **事件流**: 大量事件时使用虚拟滚动
4. **重连处理**: WebSocket 断开后恢复 pending HITL 状态

## 安全考虑

1. **权限验证**: 每个 HITL 响应都验证用户权限
2. **超时处理**: 自动清理过期 HITL 状态
3. **XSS 防护**: 所有用户输入都经过转义
4. **敏感信息**: env_var 中的密码字段加密传输
