# ADR-0004 · Plan 编排模型选 append-only DAG

- 状态:**已接受**(设计决策,基于 Argo 调研)
- 日期:2026-06
- 关联:[06-agent-core-design §5](../architecture/06-agent-core-design.md)、[research/argo-internals](../research/argo-internals.md)

## 背景

L4 Agent 需要"可编排":多工具依赖、并行 fan-out、条件分支、HITL 暂停。Argo Workflows 提供成熟的 DAG 编排,但其**根本假设是 DAG 静态**(spec 在执行前全声明,`executeDAGTask` 只发现状态、不创建新节点类型)。

AI Agent 的 Plan 本质不同:LLM **边执行边规划**,每步输出决定下一步的工具与参数 —— 这是**动态 DAG**(runtime graph mutation)。直接照搬 Argo 静态 DAG 不成立;但放弃编排退回纯线性 ReAct 又丢失并行/依赖/可恢复能力。

三个候选:
- **方案 A · 纯线性 ReAct**:每次 LLM 只生成"当前一步",无预规划,线性节点链。简单,但无编排(不能表达并行/依赖,Plan 不可视化、不可整体重试)。
- **方案 B · Plan as append-only DAG**:`Plan{Enter}` 生成初步 DAG,`Plan{Update}` 运行中**追加**节点,已执行节点不可改。
- **方案 C · 类 Argo 全动态**:`depends` 表达式可引用 LLM 输出动态解锁节点(把 token stream 当参数源)。最灵活但最重,实现与心智成本高。

## 决策

**采用方案 B:Plan = append-only DAG。** `Plan{Enter/Update/Exit}` 三个工具精确对应 DAG 的**创建 / 追加 / 完成**三个生命周期阶段。

```
PlanState {
    nodes:    HashMap<NodeId, PlanNode>,  // 存量节点(含已完成)
    edges:    Vec<(NodeId, NodeId)>,      // 依赖关系
    frontier: Vec<NodeId>,                // 当前可执行节点
}
```

调和循环(借鉴 Argo `operate()`):取 `frontier` → 找 `ready_nodes`(依赖全 `Succeeded`)→ 限并发派发执行 → 收集结果 → 调 LLM 生成 delta(新节点/边)→ 合并到 `PlanState` → persist。

**关键约束:append-only。** 节点 ID 在追加时生成,**已执行节点不可修改** —— 保证 reconcile 幂等(重新遍历不会重复执行已完成节点),与 Argo "状态即真相 + 调和幂等"一致。

## 后果

- ➕ 兼得编排(并行/依赖/条件/HITL/整体重试)与动态性(LLM 运行时扩图)。
- ➕ `Plan{Enter/Update/Exit}` 工具语义与 DAG 生命周期一一对应,与现有 Plan 工具族契合。
- ➕ append-only + 节点状态机 → reconcile 幂等,直接支撑崩溃恢复([ADR-0005](0005-round-boundary-checkpoint.md))。
- ➖ 需实现依赖就绪判定、frontier 推进、delta 合并;比方案 A 复杂。
- ⚠️ "下一步该追加哪些节点 / 走哪条 `when` 分支"是**语义判断**,必须由 agent 工具调用裁决(Agent First 铁律);引擎只做依赖就绪、拓扑推进等**结构**计算。
- ⚠️ 端上轻量版用 `MiniOrchestrator::step()`(单线程 async)跑同一 `PlanState`,不引入 Kameo;服务器版用 Kameo actor 承载(见 [06 §6](../architecture/06-agent-core-design.md))。
