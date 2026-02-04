# HITL 故障排除指南

本文档帮助排查和解决 HITL (Human-in-the-Loop) 系统中的常见问题。

## 目录

- [快速诊断](#快速诊断)
- [常见问题](#常见问题)
- [日志分析](#日志分析)
- [调试技巧](#调试技巧)
- [性能优化](#性能优化)
- [错误恢复](#错误恢复)

---

## 快速诊断

### 系统健康检查清单

```bash
# 1. 检查 API 服务
curl http://localhost:8000/health

# 2. 检查 Temporal 服务
curl http://localhost:7233/health

# 3. 检查 Redis 连接
redis-cli ping

# 4. 检查 Agent Worker 状态
make status | grep agent-worker

# 5. 检查 HITL Activity 注册
tail -100 logs/agent-worker.log | grep "hitl_activity"
```

### 常见状态指示

| 状态 | 含义 | 可能原因 |
|------|------|----------|
| ✅ 200 OK | 服务正常 | - |
| ❌ 404 Not Found | 请求不存在 | request_id 错误或已过期 |
| ❌ 400 Bad Request | 请求无效 | 状态不是 pending，或格式错误 |
| ❌ 500 Internal Error | 服务器错误 | Temporal 连接失败 |
| ⏳ Timeout | 请求超时 | 用户未及时响应 |

---

## 常见问题

### 1. 前端提交响应返回 400 Bad Request

**症状**：点击 HITL 卡片的确认按钮，返回 400 错误。

**原因**：
- HITL 请求已不在 `pending` 状态（已回答、已超时、已取消）
- 历史消息中的 HITL 卡片被点击

**解决方案**：

```typescript
// 前端应检查 isAnswered 状态
if (event.answered === true) {
  // 显示已回答状态，禁用交互
  return <AnsweredState value={event.answer} />;
}
```

**后端检查**：

```python
# src/infrastructure/adapters/primary/web/routers/agent/hitl.py
if hitl_request.status != HITLRequestStatus.PENDING:
    raise HTTPException(
        status_code=400,
        detail=f"HITL request is not pending, current status: {hitl_request.status}"
    )
```

### 2. HITL 卡片不显示历史回答

**症状**：重新加载对话历史时，HITL 卡片显示为可交互状态，而非已回答状态。

**原因**：
- API 没有正确返回 `answered` 字段
- 前端没有读取 `answered` 字段

**解决方案**：

1. 检查 API 响应：
```bash
curl -H "Authorization: Bearer $API_KEY" \
  "http://localhost:8000/api/v1/agent/conversations/{id}/messages" | jq '.events[] | select(.type | contains("asked"))'
```

2. 确认包含 `answered: true` 和 `answer`/`decision` 字段

3. 前端正确传递：
```tsx
// MessageBubble.tsx
case 'clarification_asked':
  return (
    <InlineHITLCard
      isAnswered={e.answered === true}
      answeredValue={e.answer}
      // ...
    />
  );
```

### 3. Temporal Signal 未收到

**症状**：提交响应后，Agent 没有继续执行。

**诊断步骤**：

```bash
# 1. 检查 Signal 是否发送
tail -100 logs/api.log | grep "send_signal"

# 2. 检查 Workflow 状态
# 打开 Temporal UI: http://localhost:8080
# 查找 workflow_id: project_agent_{tenant}_{project}_{session}
# 检查 Events 标签页的 Signal 事件

# 3. 检查 Workflow 是否在等待
# 查看 Pending Activities 或 Waiting 状态
```

**常见原因**：
- Workflow 已完成或终止
- Signal 名称不匹配
- Temporal 连接问题

**解决方案**：

```python
# 确认 Signal 名称一致
HITL_RESPONSE_SIGNAL = "hitl_response"

# 发送端
await workflow_handle.signal(HITL_RESPONSE_SIGNAL, response_data)

# 接收端
@workflow.signal(name=HITL_RESPONSE_SIGNAL)
async def handle_hitl_response(self, response: dict):
    # ...
```

### 4. Agent 状态恢复失败

**症状**：HITL 响应后，Agent 报错 "Failed to restore state"。

**原因**：
- Redis 中的状态已过期（TTL）
- 状态序列化/反序列化失败
- 状态 Key 不匹配

**诊断**：

```bash
# 检查 Redis 中的状态
redis-cli
> KEYS hitl:agent_state:*
> GET hitl:agent_state:{conversation_id}:{message_id}
> TTL hitl:agent_state:{conversation_id}:{message_id}
```

**解决方案**：

```python
# 增加 TTL (默认 300s + 60s buffer)
class HITLStateStore:
    def save(self, key: str, state: HITLAgentState, ttl: int = 360):
        self._redis.setex(key, ttl, self._serialize(state))
```

### 5. 前端 SSE 事件未接收

**症状**：HITL 请求创建成功，但前端没有显示卡片。

**诊断**：

```javascript
// 浏览器控制台检查 SSE 连接
console.log('SSE readyState:', eventSource.readyState);
// 0 = CONNECTING, 1 = OPEN, 2 = CLOSED

// 添加错误处理
eventSource.onerror = (e) => console.error('SSE error:', e);
```

**常见原因**：
- SSE 连接断开
- 事件类型名称不匹配
- CORS 问题

**解决方案**：

```typescript
// 添加重连逻辑
useEffect(() => {
  let eventSource: EventSource;
  let reconnectTimeout: NodeJS.Timeout;

  const connect = () => {
    eventSource = new EventSource(`/api/v1/agent/stream?conversation_id=${conversationId}`);
    
    eventSource.onopen = () => console.log('SSE connected');
    eventSource.onerror = () => {
      eventSource.close();
      reconnectTimeout = setTimeout(connect, 3000);
    };
  };

  connect();
  
  return () => {
    eventSource?.close();
    clearTimeout(reconnectTimeout);
  };
}, [conversationId]);
```

### 6. Request ID 不匹配

**症状**：日志显示 "Request ID mismatch" 或 "Request not found"。

**原因**：
- Processor 和 Handler 生成不同的 ID
- ID 在传递过程中丢失

**解决方案**：

确保 ID 由单一来源生成并传递：

```python
# processor.py - 生成 ID
request_id = self._generate_request_id("decision")

# 传递给 handler
result = await handler.request_decision(
    request_id=request_id,  # 显式传递
    ...
)
```

---

## 日志分析

### 关键日志位置

| 日志文件 | 内容 |
|----------|------|
| `logs/api.log` | API 请求/响应，HITL 端点调用 |
| `logs/agent-worker.log` | Agent 执行，HITL Activity |
| `logs/temporal.log` | Temporal Workflow/Signal |

### 有用的日志过滤

```bash
# HITL 相关日志
grep -i "hitl" logs/*.log

# 特定请求 ID
grep "deci_12345678" logs/*.log

# 错误日志
grep -E "(ERROR|WARN)" logs/agent-worker.log | tail -50

# Temporal Signal
grep "signal" logs/temporal.log

# 状态变更
grep "status.*pending\|answered\|timeout" logs/*.log
```

### 日志时间线分析

```bash
# 追踪单个 HITL 请求的完整生命周期
REQUEST_ID="deci_12345678"

echo "=== 请求创建 ==="
grep "Creating.*$REQUEST_ID" logs/*.log

echo "=== 状态保存 ==="
grep "Saved state.*$REQUEST_ID" logs/*.log

echo "=== SSE 发布 ==="
grep "publish.*$REQUEST_ID" logs/*.log

echo "=== 响应提交 ==="
grep "respond.*$REQUEST_ID" logs/*.log

echo "=== Signal 发送 ==="
grep "signal.*$REQUEST_ID" logs/*.log

echo "=== 恢复执行 ==="
grep "continue.*$REQUEST_ID" logs/*.log
```

---

## 调试技巧

### 1. 启用详细日志

```python
# src/configuration/config.py
LOGGING = {
    "level": "DEBUG",
    "handlers": {
        "hitl": {
            "level": "DEBUG",
            "filters": ["hitl_filter"],
        }
    }
}
```

### 2. 使用 Temporal UI

```
http://localhost:8080/namespaces/default/workflows
```

- 查看 Workflow 状态和历史
- 检查 Signal 是否收到
- 查看 Activity 执行结果
- 手动发送 Signal 测试

### 3. Redis 状态检查

```bash
redis-cli
> KEYS hitl:*
> GET hitl:agent_state:{key}
> TTL hitl:agent_state:{key}
> MONITOR  # 实时监控 Redis 操作
```

### 4. 手动测试 API

```bash
# 完整 E2E 测试脚本
#!/bin/bash
set -e

API_KEY="ms_sk_xxx"
BASE_URL="http://localhost:8000/api/v1"
CONV_ID="your-conversation-id"

# 1. 发送触发 HITL 的消息
echo "Sending message..."
curl -X POST "$BASE_URL/agent/chat" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "conversation_id": "'$CONV_ID'",
    "message": "请帮我做一个需要确认的操作"
  }'

sleep 3

# 2. 获取 pending 请求
echo "Getting pending..."
PENDING=$(curl -s "$BASE_URL/agent/hitl/conversations/$CONV_ID/pending" \
  -H "Authorization: Bearer $API_KEY")
echo $PENDING | jq .

REQUEST_ID=$(echo $PENDING | jq -r '.data.pending_requests[0].request_id')

if [ "$REQUEST_ID" != "null" ]; then
  # 3. 提交响应
  echo "Submitting response..."
  curl -X POST "$BASE_URL/agent/hitl/respond" \
    -H "Authorization: Bearer $API_KEY" \
    -H "Content-Type: application/json" \
    -d '{
      "request_id": "'$REQUEST_ID'",
      "response": {"decision": "proceed"}
    }'
fi
```

### 5. 前端调试

```typescript
// 添加 HITL 调试日志
const DEBUG_HITL = true;

if (DEBUG_HITL) {
  console.group('HITL Debug');
  console.log('Event:', event);
  console.log('isAnswered:', event.answered);
  console.log('answeredValue:', event.answer || event.decision);
  console.log('Status:', hitlStore.getState().requestStatuses.get(event.request_id));
  console.groupEnd();
}
```

---

## 性能优化

### 1. 减少 Redis 往返

```python
# 批量获取状态
async def get_multiple_states(keys: list[str]) -> dict:
    pipeline = self._redis.pipeline()
    for key in keys:
        pipeline.get(key)
    results = await pipeline.execute()
    return dict(zip(keys, results))
```

### 2. SSE 事件去重

```typescript
// 使用 Set 去重
const processedEvents = new Set<string>();

eventSource.onmessage = (event) => {
  const data = JSON.parse(event.data);
  const eventKey = `${data.type}:${data.request_id}`;
  
  if (processedEvents.has(eventKey)) return;
  processedEvents.add(eventKey);
  
  // 处理事件...
};
```

### 3. 合理设置超时

```python
# 根据操作复杂度设置不同超时
TIMEOUT_CONFIG = {
    "clarification": 120,   # 简单问题
    "decision": 300,        # 需要思考
    "env_var": 600,         # 可能需要查找
    "permission": 60,       # 快速决定
}
```

---

## 错误恢复

### 1. 清理僵尸状态

```bash
# 清理过期的 HITL 状态
redis-cli KEYS "hitl:agent_state:*" | xargs -I {} redis-cli DEL {}

# 或使用 TTL 让 Redis 自动清理
```

### 2. 重置 Workflow

```bash
# 通过 Temporal CLI 终止卡住的 Workflow
temporal workflow terminate --workflow-id <workflow_id> --reason "Manual reset"
```

### 3. 数据库清理

```sql
-- 清理过期的 HITL 请求
UPDATE hitl_requests 
SET status = 'timeout', updated_at = NOW()
WHERE status = 'pending' 
  AND created_at < NOW() - INTERVAL '10 minutes';
```

### 4. 服务重启

```bash
# 重启相关服务
make dev-stop
make dev

# 或单独重启 Agent Worker
pkill -f "agent_worker"
make dev-agent-worker
```

---

## 联系支持

如果问题仍未解决：

1. 收集以下信息：
   - 完整错误日志
   - Request ID
   - 时间戳
   - 复现步骤

2. 检查 GitHub Issues

3. 提交新 Issue 并附上诊断信息

---

## 相关链接

- [HITL 架构设计](./architecture.md)
- [API 参考文档](./api-reference.md)
- [前端集成指南](./frontend-guide.md)
- [Temporal 集成](./temporal-integration.md)
