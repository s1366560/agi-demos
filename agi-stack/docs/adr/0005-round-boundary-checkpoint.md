# ADR-0005 · 以"轮次边界 checkpoint(状态即真相)"为健壮性原语

- 状态:**已接受**(设计决策,基于 Flink + Argo 调研)
- 日期:2026-06
- 关联:[06-agent-core-design §1/§4](../architecture/06-agent-core-design.md)、[research/flink-internals](../research/flink-internals.md)、[research/argo-internals](../research/argo-internals.md)

## 背景

长时运行的 Agent 会话需要崩溃恢复:进程/标签页/App 被杀后,不应丢失对话进度,更不应**重复执行已完成的工具调用**(重复调用 = 重复副作用 + 重复 API 费用)。

两套成熟系统对"何时落盘"给出**收敛**答案:
- **Flink**:在算子边界插入 Chandy-Lamport **barrier**,barrier 对齐处做一致快照(exactly-once)。
- **Argo**:每次 `operate()`(reconcile)末尾 `persistUpdates`,**状态即真相**,崩溃后重新 reconcile 即恢复。
- **Higress**:in-proxy ReAct 的轮次计数器存 per-request context,工具回调 resume。

三者都把"**一轮的边界**"作为持久化点。若在轮次中途持久化,会捕获"已执行 Tool 但未记录 Observe"的不一致状态。

## 决策

**把 `Think → Act → Observe` 一轮作为原子"微 epoch",在 Observe 完成处(且仅在此)写 checkpoint。** 会话/Plan 全状态可序列化、可从存储重建;崩溃恢复 = 从最近轮次边界重新 reconcile,不依赖内存态。

```
轮次边界 = checkpoint 点 = reconcile 持久化点 = 配置热应用点
```

- **快照内容**:`SessionSnapshot{ checkpoint_id: u64(单调递增), conversation_id, messages, plan, pending_tools, created_at_ms(外部注入) }`。
- **增量写**(借鉴 Flink incremental checkpoint):每轮只写 delta(append 新消息 + 更新 plan/pending_tools),每 N 轮写一次全量。
- **恢复**:读最新 `checkpoint_id` → 重放未 ack 的 `pending_tools`(at-least-once + 工具幂等/查重)→ 单会话串行执行天然一致,**无需 Flink 的分布式 barrier 对齐**。
- **存储按平台换**(沿用六边形端口):服务器 Redis/Postgres;端上 SQLite / IndexedDB(经端口,核心不直接碰 FS)。

## 后果

- ➕ 一个原语同时支撑健壮(崩溃恢复)、可编排(Plan 可暂停/恢复)、热插拔(配置在轮次边界原子生效,不打断飞行轮次)。
- ➕ 单进程单会话串行 → 省去分布式 barrier 对齐的全部复杂度(50+ pending checkpoint 追踪、channel state)。
- ➕ 增量写降低 I/O;全量兜底防 delta 链过长。
- ➖ 工具必须**幂等或可查重**,否则崩溃后重放 `pending_tools` 会重复副作用;有副作用工具需声明幂等键。
- ⚠️ 核心**禁 `std::time`**:`checkpoint_id` 用 `AtomicU64`,时间戳由宿主注入(`created_at_ms`),保持运行时无关([01](../architecture/01-portable-core.md))。
- ⚠️ "本轮是否健康 / 是否 doom-loop / 是否该中止"是**语义判断**,由 agent 工具调用裁决;轮次计数、`checkpoint_id` 递增、版本比对保持确定性(Agent First 铁律)。
