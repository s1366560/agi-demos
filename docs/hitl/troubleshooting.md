# HITL 故障排除

本指南针对 Ray Actor 路径的 HITL 相关问题。

## 快速诊断

```bash
# API
curl http://localhost:8000/health

# Ray
make status

# Redis
redis-cli ping

# Actor Worker 日志
docker compose -f docker-compose.yml -f docker-compose.ray.yml -f docker-compose.agent-actor.yml logs -f agent-actor-worker
```

## 常见问题

### 1) 提交响应返回 400

原因: request_id 不存在或状态不是 pending。

### 2) HITL 卡片没有显示已回答

原因: 前端未读取 answered 字段或事件没有回填 answer/decision。

### 3) 响应提交成功但 Agent 不恢复

排查步骤:

```bash
# Redis 响应流
redis-cli XRANGE hitl:response:{tenant}:{project} - + COUNT 5

# Redis 状态
redis-cli GET hitl:agent_state:request:{request_id}
```

常见原因:
- HITLStreamRouterActor 未运行
- Redis consumer group 未初始化
- Actor 不可用或重启中

### 4) 状态恢复失败

原因: Redis TTL 过期且快照缺失。

检查:
- Redis key TTL
- Postgres 快照是否存在

### 5) WebSocket 事件未接收

原因: 共享 Agent WebSocket 未连接、未订阅对应 conversation，或事件桥任务已停止。

检查:
- 浏览器网络面板中 `/api/v1/agent/ws` 是否保持连接
- 前端是否已发送 `subscribe` 或 `send_message` 并带有正确的 `conversation_id`
- `agent:events:{conversation_id}` 是否有新事件
