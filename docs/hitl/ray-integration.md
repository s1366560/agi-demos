# Ray Actor HITL Integration

> **历史实现:** 当前 SessionProcessor 不再以 `HITLPendingException` +
> `continue_chat` 作为主恢复模型；请从
> `src/infrastructure/agent/hitl/coordinator.py`、当前 HITL repository 和
> WebSocket/REST handlers 追踪 cooperative Future 流程。本文用于理解旧 Ray 恢复设计。

本页取代旧的 Temporal 集成说明。HITL 全链路基于 Ray Actors + Redis Streams。

## 关键组件

- RayHITLHandler: 创建 HITL 请求，保存状态，抛出 HITLPendingException
- HITLStateStore: Redis 状态存储
- AgentSessionSnapshots: Postgres 快照
- HITLStreamRouterActor: 读取响应并恢复执行
- ProjectAgentActor: Agent 执行主体

## 恢复流程

1. Agent 触发 HITL 并保存状态
2. API 返回 HITL 请求给前端
3. 前端提交响应到 `/agent/hitl/respond`
4. API 写入 `hitl:response:{tenant}:{project}` stream
5. HITLStreamRouterActor 调用 `ProjectAgentActor.continue_chat`
6. Actor 从 Redis 恢复状态，必要时从 Postgres 快照恢复

## 失败恢复

- Redis 过期时使用快照恢复
- Actor 异常时由 Ray 重新创建

## 可观测性

- Ray Dashboard: http://localhost:8265
- Redis stream: `agent:events:{conversation_id}`
