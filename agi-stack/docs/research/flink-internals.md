# Flink 内部设计调研 → 健壮(robust)

> 目标:学习 Apache Flink 的有状态流处理如何做到 **exactly-once 容错 · 状态可恢复 · 反压 · 失败隔离**,提炼到 Rust AI Agent 核心的健壮性。综合落地见 [06-agent-core-design §4](../architecture/06-agent-core-design.md)。

## 一、核心机制概览

| 机制 | 作用 | 源码锚点 |
|---|---|---|
| **StreamGraph → JobGraph → ExecutionGraph** | 逻辑图 → 优化(算子链合并)→ 运行实例图 | `JobVertex.java`、`OperatorChain.java` |
| **Operator Chain** | 同线程串联算子,无跨进程通信 | `streaming/runtime/tasks/OperatorChain.java` |
| **Keyed State vs Operator State** | 按 key 分区的状态 vs 算子级状态 | `state/StateBackend.java`、`KeyedStateBackend.java` |
| **State Backend**(HashMap / RocksDB) | 内存态 vs 超大态溢写磁盘 | `state/StateBackend.java` |
| **Chandy-Lamport Barrier Checkpoint** | 分布式一致快照,exactly-once | `CheckpointBarrier.java`、`CheckpointBarrierTracker.java` |
| **Aligned / Unaligned / At-Least-Once** | checkpoint 对齐模式 | `CheckpointOptions.java`(`AlignmentType`) |
| **增量 Checkpoint** | 只持久化新增 SST,共享 + 引用计数 | `IncrementalRemoteKeyedStateHandle.java` |
| **Watermark + StatusWatermarkValve** | 事件时间 + 多路 min-watermark 对齐 | `StatusWatermarkValve.java` |
| **Credit-Based Flow Control** | 消费侧 credit 反压 | `InputGate.getAvailableFuture()`、`RecordWriter` |
| **Region Failover** | 失败只重启受影响 pipelined region | `RestartPipelinedRegionFailoverStrategy.java` |

## 二、关键机制详解

### 2.1 Barrier Checkpoint(Chandy-Lamport)
`CheckpointBarrier` 携带单调递增 `checkpointId`,在数据流中作为"分界标记":barrier 之前的数据计入本次快照,之后的不计。
- **Aligned(exactly-once)**:算子等所有输入 channel 的 barrier 到齐再快照,保证状态一致;代价是对齐期间阻塞快 channel。
- **Unaligned**:把"飞行中"的 channel 数据也纳入快照,不等对齐,低延迟但快照更大。
- **At-Least-Once**(`CheckpointBarrierTracker`):不阻塞 channel,最多追踪 ~50 个 pending checkpoint。

### 2.2 增量 Checkpoint + Shared State Registry
`IncrementalRemoteKeyedStateHandle` 分 `sharedState`(SST 共享)/`privateState`/`metaStateHandle`;`SharedStateRegistry` 用**引用计数**管理共享 SST,只在所有引用删除后清理。→ 只写本次新增,不重复全量。

### 2.3 Watermark min-alignment
`StatusWatermarkValve` 用堆优先队列求多路输入的 **min-watermark**,只在所有 channel 都推进后才输出新 watermark;`WatermarkStatus.IDLE` 标记空闲/超时 channel,不再等待(allowed lateness)。

### 2.4 Credit-Based 反压
消费侧 `InputGate.getAvailableFuture()` 暴露可用性 future,无可用 buffer 时 backpressure 上游;`RecordWriter.getAvailableFuture()` 是生产侧反压信号;`OutputFlusher` 定时强制 flush 保证延迟上界。

### 2.5 Region Failover
`RestartPipelinedRegionFailoverStrategy` 把 ExecutionGraph 切成 pipelined region,失败只重启受影响 region(`getTasksNeedingRestart()`),而非全图。

## 三、ReAct = 有状态 Dataflow

```
[源] ─ UserMessage → [Think 算子] ─ ThinkResult → [Act 算子] ─ ToolCall → [Tool 执行器]
                          ↑                                                      │
                          └──────────────── [Observe 算子] ← ToolResult ─────────┘
                                   状态读写: conv_history, plan, tool_calls
```
- `Think` = 读 `KeyedState[conv_id].history` → 调 LLM → 出 `ThinkResult`
- `Act` = 展开 ToolCalls,发起 async I/O
- `Observe` = 聚合 ToolResults(类 `StatusWatermarkValve` min-watermark 等待)→ 写状态 → 决定下一轮
- **Think→Act→Observe 是一个"微 epoch"**,在 Observe 完成后触发 checkpoint(类 barrier)→ 崩溃从轮次边界恢复,不重复已完成工具。

## 四、机制 → AI Agent 映射(节选)

| Flink 机制 | AI Agent 映射 | 目标 | MemStack 场景 |
|---|---|---|---|
| keyBy(conversation_id) | 会话级有状态路由 | 正确性 | 同 conversation 事件路由到同一 SessionProcessor,避并发冲突 |
| Keyed State(Value/List) | 会话状态 | 可恢复 | 对话历史(List)、当前 Plan(Value)、待办 ToolCall(List)按 conv_id keyed |
| Operator State | 全局/跨会话状态 | 可扩展 | CostTracker 全局 token 计数、DoomLoop 全局调用图 |
| CheckpointBarrier(Aligned) | 完整 ReAct 轮次原子快照 | 精确一次 | 等 Think+Act+Observe 结束再 checkpoint,避免"已执行 Tool 未记录 Observe" |
| Unaligned Checkpoint | 异步工具调用期间快照 | 健壮 | LLM/工具慢时把飞行中 pending 调用纳入快照,崩溃后重试该调用而非重跑对话 |
| 增量 Checkpoint | 增量会话持久化 | 高效 | 只写本轮新增事件,共享 embedding 文件 |
| StatusWatermarkValve(min) | 异步工具回调对齐 | 正确性 | 多并发工具返回时等最慢一个(或 timeout)才推进 Observe |
| Credit-Based 反压 | 事件流反压 | 资源安全 | Redis Stream/WS 推送慢时背压到 LLM 速率,避免 pending_events OOM |
| RestartPipelinedRegion | 会话级失败隔离 | 可用性 | 一个 conversation 崩溃只影响自己;对应 Kameo supervisor |
| FailureRate 退避重启 | DoomLoopDetector + 指数退避 | 安全 | 检测工具循环后退避重试,防 API 费用爆炸 |
| Shared State Registry(引用计数) | Episode/Memory 文件去重 | 存储效率 | 多 Memory 引用同一 embedding,ref=0 才清理 |

## 五、Rust 取舍:借鉴的 vs 不照搬的

**借鉴并轻量实现**:Keyed State → `HashMap<ConvId, SessionState>` + serde 到 SQLite/Redis;轮次 checkpoint → Observe 结束原子写 + `AtomicU64` 版本号;增量 checkpoint → 只写本轮 delta;At-Least-Once → Redis `XACK` + 幂等 event_id;反压 → bounded `mpsc` / `Semaphore`;工具对齐 → `FuturesUnordered + timeout`;Region failover → Kameo actor-per-conversation;退避 → `tokio-retry`。

**不照搬(过重)**:分布式 barrier 对齐(单进程 `Mutex<SessionState>` + 轮次原子写即可);Netty credit RPC(Redis Streams 足够);JobManager/TaskManager 分布式调度(Kameo 单进程监督足够);RocksDB 后端(SQLite/`sled`/IndexedDB);窗口 Trigger/Evictor(只有轮次边界触发点);算子并行度/重分区(单 Agent 顺序,多会话靠 actor pool)。

## 六、端上轻量版最小持久化(借鉴增量 checkpoint)
约束:无 tokio/`std::time`、可能在 WASM(无直接 FS)、单机 local-first。
```
SessionSnapshot { checkpoint_id: u64, conversation_id, messages: Vec<Message>(全量),
                  plan: Option<Plan>, pending_tools: Vec<ToolCall>, created_at_ms: u64(外部注入) }
持久化: 每轮结束写 delta(append messages + 更新 plan/pending);每 N 轮写 full;
        WASM → postMessage → IndexedDB;服务端 → Redis Hash。
恢复:  读最新 checkpoint → 重放未 ack pending_tools(幂等/查重)→ 单会话串行天然一致。
```

## 七、关键引用汇总

| 文件 | 内容 |
|---|---|
| `apache/flink:flink-runtime/.../api/CheckpointBarrier.java` | Chandy-Lamport barrier 结构;checkpointId 单调递增;pre/post 分界 |
| `apache/flink:flink-runtime/.../checkpointing/CheckpointBarrierTracker.java` | at-least-once;不阻塞 channel;最多 50 pending |
| `apache/flink:flink-runtime/.../checkpoint/CheckpointOptions.java` | `AlignmentType`:ALIGNED/UNALIGNED/AT_LEAST_ONCE;`needsChannelState()` |
| `apache/flink:flink-runtime/.../state/StateBackend.java` | Keyed vs Operator State 工厂 |
| `apache/flink:flink-runtime/.../state/KeyedStateBackend.java` | `setCurrentKey()`;key context 切换 |
| `apache/flink:flink-runtime/.../state/IncrementalRemoteKeyedStateHandle.java` | 增量 checkpoint:sharedState/privateState;引用计数 |
| `apache/flink:flink-runtime/.../watermarkstatus/StatusWatermarkValve.java` | min-watermark 聚合;IDLE/ACTIVE |
| `apache/flink:flink-runtime/.../failover/RestartPipelinedRegionFailoverStrategy.java` | pipelined region 失败传播;`getTasksNeedingRestart()` |
| `apache/flink:flink-runtime/.../writer/RecordWriter.java` | `OutputFlusher` 定时刷;`getAvailableFuture()` 反压 |
| `apache/flink:flink-runtime/.../consumer/InputGate.java` | credit-based 消费侧反压 |
| `apache/flink:flink-runtime/.../runtime/tasks/OperatorChain.java` | 同线程算子链串联 |
