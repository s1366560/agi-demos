# HITL (Human-in-the-Loop) 系统

HITL 允许 AI Agent 在关键步骤暂停并请求人类输入。当前实现基于 Ray Actors + Redis Streams + Postgres 快照，不再依赖 Temporal。

## 请求类型

| 类型 | 用途 | 典型场景 |
|------|------|----------|
| Clarification | 澄清用户意图 | "删除还是移动文件？" |
| Decision | 关键决策点 | "部署到 staging 还是 production？" |
| EnvVar | 收集环境变量 | "请提供 OPENAI_API_KEY" |
| Permission | 授权敏感操作 | "允许执行 rm -rf ?" |

## 核心流程

```mermaid
sequenceDiagram
    participant User as 用户
    participant Frontend as 前端
    participant API as REST API
    participant Actor as ProjectAgentActor
    participant Redis as Redis Streams
    participant Router as HITLStreamRouterActor

    User->>Frontend: 发送消息
    Frontend->>API: POST /agent/chat
    API->>Actor: chat(request)
    Actor->>Redis: 事件流输出

    Note over Actor: 需要人类输入

    Actor->>API: HITLPendingException
    API->>Frontend: SSE hitl_requested

    User->>Frontend: 提交响应
    Frontend->>API: POST /agent/hitl/respond
    API->>Redis: hitl:response stream
    Router->>Actor: continue_chat(request_id, response)
    Actor->>Redis: 事件流输出
    Actor->>API: complete
    API->>Frontend: SSE complete
```

## 快速开始 (Backend)

```python
from src.infrastructure.agent.hitl.ray_hitl_handler import RayHITLHandler

handler = RayHITLHandler(...)

decision = await handler.request_decision(
    question="选择部署环境",
    options=[
        {"id": "staging", "label": "Staging", "recommended": True},
        {"id": "production", "label": "Production"},
    ],
    decision_type="branch",
    timeout_seconds=300,
)
```

## 文档目录

| 文档 | 说明 |
|------|------|
| [架构设计](./architecture.md) | 组件职责和数据流 |
| [请求类型](./request-types.md) | 请求参数和字段说明 |
| [Ray 集成](./ray-integration.md) | 恢复流程与快照机制 |
| [前端指南](./frontend-guide.md) | 组件与状态管理 |
| [API 参考](./api-reference.md) | REST API 端点 |
| [故障排除](./troubleshooting.md) | 常见问题与诊断 |

## 核心组件 (Backend)

| 组件 | 文件 | 职责 |
|------|------|------|
| HITLType | `hitl_types.py` | 类型定义 |
| HITLRequest | `hitl_request.py` | 请求实体 |
| RayHITLHandler | `ray_hitl_handler.py` | 统一处理 4 类 HITL 请求 |
| HITLStateStore | `state_store.py` | Redis 状态存储 |
| HITLStreamRouterActor | `hitl_router_actor.py` | 读取响应并恢复执行 |
| ProjectAgentActor | `project_agent_actor.py` | Agent 运行时 |

## 设计原则

1. 统一入口: 所有 HITL 请求通过 RayHITLHandler
2. 实时事件: Redis Streams 推送事件
3. 可恢复: Postgres 快照兜底
4. 多租户隔离: tenant_id/project_id 全链路隔离
