# Steer 注入 WS 协议草案（P1-1 Queue vs Steer)

> 状态：草案，待后端评审。前端已按本草案实现完整 UX 与容错回退；后端未实现前，
> steer 消息会被忽略，前端在确认超时后自动回退为排队语义。

## 1. 背景与语义

- **Queue（排队）**：运行中发送的消息进入 compose-ahead 队列，等当前 run 结束后按顺序
  以普通 `send_message` 发出（现状语义，不变）。
- **Steer（引导）**：运行中发送的消息在当前工具调用结束后的**下一个 turn 边界**注入为
  最新的用户引导，成为 agent 后续推理的活跃输入，而不是排队等 run 结束。

参照：Codex queued chips + 每 chip 的 Steer 动作；VS Code 发送按钮下拉
（Add to Queue / Steer with Message（默认）/ Stop and Send）。

## 2. 消息定义（前端 → 后端）

```json
{
  "type": "steer_message",
  "conversation_id": "<conversation id>",
  "project_id": "<project id>",
  "message": "<用户引导文本>",
  "message_id": "<desktop-steer-{promptId}>"
}
```

- 命名与字段风格对齐现有 `send_message` / `stop_session`（snake_case、`type` 区分动作）。
- `message_id` 幂等键：与 `send_message` 一致，后端去重、ack、以及 durable
  `user_message` 事件回显均以其为准。
- steer 是**turn 边界时效性**消息：前端**不**将其放入重连 outbox（重连后补发一条过时
  的 steer 会把引导注入错误的 turn）。发送失败（socket 未连接）直接判定失败。

## 3. 后端应答约定（ack / 事件）

前端通过会话事件流判定 steer 结果（`message_id` 匹配）：

| 结果 | 事件形态 |
|---|---|
| 接受 | `{type:"ack", action:"steer_message", outcome:"accepted", message_id, conversation_id}` |
| 接受（兜底） | durable `user_message` 事件携带同一 `message_id`（turn 边界注入成功落库） |
| 拒绝 | `{type:"ack", action:"steer_message", outcome:"rejected", message_id, ...}` |
| 拒绝 | `{type:"error", code: "STEER_UNSUPPORTED" \| "STEER_NOT_SUPPORTED" \| "INVALID_STEER_MESSAGE" \| "UNKNOWN_MESSAGE_TYPE", message_id, ...}` |

建议的拒绝原因码（供后端扩展）：`STEER_UNSUPPORTED`（该 runtime 不支持注入）、
`STEER_TURN_ALREADY_COMMITTED`（越过 turn 边界，建议客户端回退为排队）。

## 4. 前端回退行为（已实现）

steer 发出后，任一以下情况触发**回退为排队**：

1. 收到拒绝类事件（上表）；
2. 10 秒 ack 超时仍无接受事件；
3. run 结束（streaming 终止）时 steer 仍未被接受——turn 边界已错过。

回退动作是原子的：chip 从 `dispatching`（引导中）恢复为 `queued` 且 intent 降级为
`queue`，随后按普通排队消息在 run 结束后发送；同时 toast 告知用户「Steer 未被接受，
消息已保留在队列」。**不做假成功**：只有收到接受类事件才移除 chip。

## 5. Timeline 呈现要求（验收相关）

后端在 turn 边界注入 steer 时，产出的 `user_message` 事件建议携带
`metadata: { "injected_via": "steer", "steer_message_id": "<message_id>" }`，
以便 timeline 将该用户消息标识为「steer 注入」，满足 P1-1 验收
「timeline 中可辨识其为 steer 注入」。前端当前接受逻辑不依赖该字段，但 UI 标注需要它。

## 6. 与现有 `runInputDelivery = steer_now` 的关系

计划模式（plan mode）下已有 `steer_now` / `queue_next` 投递选项，作用于 run-input
队列，与本文档的 compose-ahead steer 是两条路径。两者并存时 compose-ahead 被禁用
（现状逻辑）。建议后端统一 turn 边界注入原语，让两条路径复用同一协议动词。

## 7. 开放问题（请后端确认）

1. **注入时机定义**：turn 边界的精确定义（当前工具调用 observe 完成之后、下一次 LLM
   调用之前）？多个 steer 先后到达时是覆盖还是排队注入？
2. **steer 与 HITL 阻塞**：会话处于 HITL pending 时收到 steer，是拒绝
   （`HITL_PENDING` 风格错误码）还是延后注入？
3. **权限与审计**：steer 是否需要在审计日志中单独标记（引导改变了 agent 行为路径）？
4. **上下文项**：当前 steer 仅携带纯文本；skill / subagent 等 composer context 不支持
   steer（前端跳过这类条目，留在队列中随 run 结束发送）。是否需要协议扩展支持？
5. **本地 runtime（loopback HTTP）路径**：本地模式 `send_message` 有 HTTP 兜底；steer
   是否也需要 HTTP 端点，还是仅 cloud WS 支持？
6. **ack 超时基准**：前端暂定 10 秒。若后端在长工具调用场景下 turn 边界可能远超该值，
   请提供建议值或改为「接受前事件驱动、无超时」模型。
