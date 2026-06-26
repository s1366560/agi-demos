# Argo Workflows 内部设计调研 → 可编排(orchestratable)· 健壮

> 目标:学习 Argo Workflows 的 reconcile 编排引擎如何做到 **DAG 编排 · 暂停恢复 · 重试 · 记忆化 · 状态可恢复**,提炼到 Rust AI Agent 的 Plan 编排。综合落地见 [06-agent-core-design §5](../architecture/06-agent-core-design.md)。引用基于 `argoproj/argo-workflows`(抓取时 SHA `326c5d77`)。

## 一、架构概览(Operator 模式)

| 组件 | 职责 | 源码 |
|---|---|---|
| `WorkflowController` | 持有 informer + rate-limited workqueue,驱动 reconcile | `workflow/controller/controller.go:91-254,307-425` |
| `wfOperationCtx` | 单次 reconcile 上下文(per-workflow) | `workflow/controller/operator.go:71-119` |
| `operate()` | reconcile 主循环:从头遍历节点树 | `operator.go:194-551` |
| `NodeStatus` 树 | 所有执行单元统一为节点,经 `BoundaryID` 组织成树 | `pkg/apis/.../workflow_types.go:2447-2552` |
| `persistUpdates` | 乐观锁持久化(reapplyUpdate 重试) | `operator.go:744-958` |

**调和而非命令**:控制器不发命令,而是观察期望 vs 实际,执行动作收敛。`operate()` 每次从头遍历,根据当前状态决定下一步,**天然幂等**。崩溃恢复 = 重新 reconcile,状态从 CRD 读取。

## 二、编排模型

### 2.1 Steps vs DAG
- **Steps**:顺序/并行组 `[[a],[b,c],[d]]`,组内并行、组间顺序。`steps.go:41-200`(含 scope 传播)。
- **DAG**:`depends: "A.Succeeded && B.Succeeded"` 表达式定义依赖;`executeDAGTask` 用 **DFS 后序**(先确认依赖完成再执行当前)。`dag.go:230-394,421-671`;依赖解析 `common/ancestry.go:49-145`。
- **`assessDAGPhase` BFS** 聚合整图状态;`failFast` 控失败策略。`dag.go:134-228`。

### 2.2 NodePhase 状态机
`Pending / Running / Succeeded / Failed / Error / Skipped / Omitted`。所有执行单元(steps/dag/pod/suspend)统一为 `NodeStatus`,经 `BoundaryID` 组织成层级树,支持任意嵌套与 template 复用。

### 2.3 控制流
- `when` 条件分支(`when: "{{tasks.classify.outputs.result}} == 'route_a'"`)。
- Fan-out:`withItems`/`withParam`(运行时从上一步 output 读列表)/`withSequence`;结果聚合为 JSON list。
- 递归模板。

## 三、健壮性原语

| 原语 | 机制 | 源码 |
|---|---|---|
| **RetryStrategy** | `Backoff{Duration, Factor, Cap}` + `RetryPolicy(OnError/OnFailure)`,指数退避 | `operator.go:972-1148`(`processNodeRetries`) |
| **Suspend / Resume** | `NodeTypeSuspend`:进入时 `phase=Running` 挂起,外部写 Resume 信号 → `phase=Succeeded` → informer 重新入队 → 继续推进 | `workflow_types.go:2730-2732`(`IsActiveSuspendNode`) |
| **Memoization** | key 是表达式运行时 evaluate;命中**跳过整个节点**(`markNodeSucceeded + copy outputs`,连子节点都不建);miss 执行后 `Save`;`LastHitTimestamp` LRU GC | `controller/cache/configmap_cache.go` |
| **onExit / LifecycleHook** | 无论成败都执行的清理/审计 handler | controller |
| **parallelism + syncManager** | 并发上限 + 信号量/互斥锁(共享资源) | controller |
| **hydrator** | 大 node tree 超 CRD 限制时 offload 到 S3/Blob | controller |
| **ShutdownStrategy** | Terminate(立即失败)/ Stop(允许 cleanup 完成) | controller |

## 四、机制 → AI Agent 映射(节选)

| Argo 机制 | 目标 | AI Agent(MemStack)映射 |
|---|---|---|
| reconcile loop + wfOperationCtx | 可编排/健壮 | ReAct 推进;状态全量持久化,崩溃恢复 |
| NodePhase 状态机 | 可编排 | `ToolNode.phase` |
| DAG + `depends` | 可编排 | `Plan{Enter}` 生成工具序列 → DAG;依赖表达式 |
| steps 组 | 可编排 | L2 Skill 执行步骤 `[[a],[b,c],[d]]` |
| withItems/withParam fan-out | 可编排 | 并行调多子 Agent/工具,结果聚合 |
| when 条件分支 | 可编排 | LLM 判定驱动路由 |
| **suspend/resume** | 健壮 | **HITL 四类**(clarification/decision/env_var/permission)= 挂起 Suspend 节点等外部输入 |
| **retryStrategy** | 健壮 | 工具/LLM 429 限流指数退避 |
| **memoization** | 健壮 | 工具结果缓存,key = `hash(tool_name + canonical(inputs))` |
| onExit | 健壮 | `Plan{Exit}` 清理/审计 |
| assessDAGPhase BFS | 可编排 | Plan 状态聚合;`failFast` |
| hydrator offload | 健壮 | 大 Plan(数百工具)node tree offload |
| parallelism + sync | 健壮 | 并发工具上限 = Semaphore |
| reapplyUpdate 乐观锁 | 健壮 | 多 Actor 并发更新 Plan 的乐观并发 |
| ShutdownStrategy | 健壮 | 用户取消 = Terminate;Graceful = Stop |

## 五、四个关键问题的回答

### 5.1 Plan = 动态 DAG(Argo 是静态)
Argo 假设 DAG 静态(spec 预声明)。Agent 是 LLM 边执行边规划的**动态 DAG**。三方案:
- **A(最轻)**:ReAct = 单步,无预规划,线性节点链,无需 DAG。
- **B(推荐,MemStack 方向)**:**Plan as append-only DAG**。`Plan{Enter}` 生成初步 N 步存 `PlanState{nodes, edges, frontier}`;调和循环取 `frontier` 找 ready 节点(依赖全 Succeeded)派发,收集结果调 LLM 生成 delta(新节点/边)合并,persist;`Plan{Update}` **追加节点**(append-only,已执行节点不可改 → 幂等)。
- **C(最重)**:类 Argo `withParam` 全动态,`depends` 引用 LLM 输出动态解锁,过重。

→ 选 **B**:`Plan{Enter/Update/Exit}` 精确对应 DAG 创建/变更/完成三生命周期。详见 [ADR-0004](../adr/0004-plan-as-append-only-dag.md)。

### 5.2 suspend/resume = HITL
HITL 节点生命周期:进入 `initializeNode(Suspend, Running)` → `operate()` 检测 `IsActiveSuspendNode()` 进入等待不推进 → 外部写 Resume → `phase=Succeeded/Failed` → informer 重新入队 → 下次 `operate()` 继续。Rust:`SuspendNode` 持久化(SQLite/PG),executor 检测到 → 等异步信号(`tokio::oneshot` 或 DB 轮询;WASM 用 JS Promise + `wasm-bindgen-futures`)。

### 5.3 memoization = 工具结果缓存
要点:key 是表达式(运行时 evaluate)→ 存储可替换接口(ConfigMap/Redis/SQLite)→ 命中跳过整节点 → miss 执行后写入 → LastHitTimestamp LRU。AI 场景 key = `hash(tool_name + canonical(inputs))`,canonical 化保证语义等价输入命中同一条目。

### 5.4 reconcile-loop vs ReAct
MemStack 的 PLAN_MODE 实质是"在 reconcile-loop 框架内嵌 ReAct 推理":reconcile-loop 管 Plan 生命周期(持久化/重试/HITL/超时),LLM ReAct 负责规划判断,两者经 `Plan{Update}` 工具接口连接。

## 六、Rust 落地一对一映射

**服务器重型版**:`WorkflowController → ExecutionController(Kameo supervisor)`;`wfOperationCtx → PlanOperationCtx`;`wfQueue → tokio mpsc(rate-limited)`;`informer → tokio broadcast`;`Nodes → HashMap<NodeId, NodeStatus>(serde)`;`MemoizationCache → trait(SQLite/Redis)`;`SyncManager → tokio Semaphore`;`hydrator → serde + lz4 + blob`。

**端上轻量版**:`MiniOrchestrator{state, store, cache}`,`step()` = 找 ready 节点 → 限并发 `join_all` 派发 → apply 结果 → `assess_phase()`。**保留** NodePhase/RetryStrategy(`sleep` 替 requeueAfter)/Memoize(HashMap)/suspend(`Future::pending()` 等 wasm-bindgen 回调);**丢弃** informer/workqueue(直接 loop+await)/hydrator/archive。

## 七、5 个核心设计原则

1. **状态即真相**:全状态持久化,无内存态;崩溃恢复 = 重新 reconcile。
2. **调和而非命令**:观察期望 vs 实际,收敛;`operate()` 从头遍历,天然幂等。
3. **层级节点树 + BoundaryID**:统一 NodeStatus,树形组织,支持嵌套/复用/递归。
4. **惰性求值**:DFS 后序,依赖完成才执行;下游参数引用 lazy resolve。
5. **机制与策略分离**:retry/memo/suspend 是通用机制,具体策略由 template/工具声明。

## 八、关键引用汇总

| 概念 | 源码路径 | 行号 |
|---|---|---|
| `wfOperationCtx` 结构 | `workflow/controller/operator.go` | 71-119 |
| `operate()` 主循环 | `workflow/controller/operator.go` | 194-551 |
| `processNodeRetries` 退避 | `workflow/controller/operator.go` | 972-1148 |
| `executeDAG` / `executeDAGTask` | `workflow/controller/dag.go` | 230-394 / 421-671 |
| `GetTaskDependencies` | `workflow/common/ancestry.go` | 49-145 |
| `executeSteps` / scope | `workflow/controller/steps.go` | 41-200 |
| `NodeStatus` 结构 | `pkg/apis/workflow/v1alpha1/workflow_types.go` | 2447-2552 |
| `RetryStrategy` / `Backoff` | `workflow_types.go` | 2274-2307 |
| `WorkflowController` + 队列 | `workflow/controller/controller.go` | 91-254 / 307-425 |
| Memoization 缓存 | `workflow/controller/cache/configmap_cache.go` | 全文 |
| `assessDAGPhase` BFS | `workflow/controller/dag.go` | 134-228 |
| `persistUpdates` 乐观锁 | `workflow/controller/operator.go` | 744-958 |
| `IsActiveSuspendNode` | `workflow_types.go` | 2730-2732 |
