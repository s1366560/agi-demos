# ADR-0011 · Agent 监督裁决(结构性触发器确定 + 主观 verdict 归 agent 工具调用)

- 状态:**已接受**(设计决策,基于仓库顶层 Agent First 铁律 + Flink FailureRate 调研;doom-loop/cost/supervisor 已 Spike 证伪)
- 日期:2026-07
- 关联:[06-agent-core-design §4](../architecture/06-agent-core-design.md)(健壮轴)、[ADR-0005](0005-round-boundary-checkpoint.md)(轮次边界)、[04 §1 #28](../architecture/04-spike-evidence.md)、仓库根 `AGENTS.md`(Agent First 架构规则)

## 背景

[06 §4](../architecture/06-agent-core-design.md) 借 Flink 的 region failover / FailureRateRestartBackoff 提出 agent runtime 的**健壮性**要求,但落到代码时,`ReActEngine` 此前**唯一**的健壮机制是结构性 `max_rounds` 断路器 —— 无 doom-loop 检测(反复调同一工具打转)、无成本核算(token/轮次预算)、无"卡住了该怎么办"的裁决。

同时,仓库根 `AGENTS.md` 定义了顶层架构铁律 **Agent First**:

> 每个**主观**决策点 —— 任何需要语义理解、意图推断、质量评估、适当性判断、按语义归类、消解歧义的判断 —— **必须由 agent 经结构化工具调用做出**。硬编码启发式做主观判断被禁止。

且明确了确定性与主观的边界:

> 当确定性阈值作为廉价断路器有用时(如 doom-loop 重复计数、陈旧时间窗),它可以**点火 trigger**,但 **verdict(`healthy|stalled|looping|goal_drift`)和下一步动作(`continue|reassign|escalate`)必须来自 agent 工具调用**。

"agent 卡住了吗?卡住了该继续、换人、还是升级?"正是一个**主观质量判断**。若用硬编码规则(如"重复 3 次即判 looping 即终止")直接出结局,就违反了 Agent First。

## 决策

**agent runtime 的健壮性裁决拆成两层:确定性结构触发器 + agent 主观 verdict。**

1. **结构触发器(确定,纯结构/算术,不做 verdict)**:
   - `DoomLoopDetector::new(window, threshold)`:滑窗内重复 `(tool, canonical(input))` 计数达阈值即**点火** `TriggerReason::DoomLoop`。这是**集合/计数**事实,`AGENTS.md` 明列为确定性(非语义)。
   - `CostTracker`(`CostBudget{max_rounds, max_tool_calls, max_tokens}`):每轮 saturating 累加,`over_budget()` 达上限即点火 `TriggerReason::CostCeiling`。这是**纯算术**(budget counters),`AGENTS.md` 明列为确定性。
   - 触发器**只点火 trigger**,绝不自行判定结局。
2. **主观 verdict(语义,经工具调用)**:新增注入端口 `SupervisorPort::review(reason, round, transcript) -> SupervisorVerdict`(形同 `LlmPort` 的注入端口)。trigger 点火后引擎**不自行判定**,而是 call supervisor 得**结构化裁决** `SupervisorVerdict{ health: healthy|stalled|looping|goal_drift, next: continue|reassign|escalate, rationale }`。
3. **确定性地按 verdict 行动**:引擎读取 verdict 字段(读结构化工具调用 payload = `AGENTS.md` 明列的确定性动作)后确定性执行 —— `continue` → 存档续跑;`escalate`/`reassign` → push `Role::Answer` 升级说明 + `SessionStatus::Failed` + 存档收尾。
4. **审计**:每次裁决在 transcript 落一条 `supervisor[{reason}] health=… next=… : rationale` 审计行(`AGENTS.md`:记录每次判断工具调用的 input/output/rationale)。
5. **无 supervisor 时的确定性退化**:未注入 `SupervisorPort` 时,trigger 点火退回**纯结构性停机**(push `structural stop: {reason}` + `Failed`)—— 断路器本身仍是安全网,只是失去"续跑/换人"的语义弹性。
6. **触发点 = 轮次边界**:结构触发器在每轮边界求值(对齐 [ADR-0005](0005-round-boundary-checkpoint.md)),不打断飞行中的工具调用;裁决与后续动作同样落在边界 checkpoint。

## 后果

- ➕ **Agent First 铁律的字面落地**:主观 verdict("卡住了吗/怎么办")= agent 工具调用;结构 trigger(重复计数、预算算术)= 确定性。这是仓库定义性架构规则在 agent runtime 层的直接体现。
- ➕ 补齐 [06 §4](../architecture/06-agent-core-design.md) 健壮轴:从"仅 max_rounds"升为"doom-loop 触发 + 成本核算 + agent 裁决",对齐 Flink 的失败率退避思想(结构性检测 + 策略性响应分离)。
- ➕ `SupervisorPort` 是注入端口 → core 仍**零运行时依赖**、同编 `wasm32`;端上可注入轻量 supervisor(甚至复用 `LlmPort` 的模型),重型侧接真判定模型。
- ➕ 机制/策略分离:检测机制(窗口、阈值、预算)确定可测;响应策略(续跑/换人/升级)可换 supervisor 实现而不动引擎。
- ➖ 引入一次额外的 supervisor 调用开销(仅在 trigger 点火时,稀疏)→ 被"避免误杀健康会话 / 避免放任打转烧钱"正当化。
- ➖ 裁决质量取决于 supervisor 实现;本波用 fake supervisor 证伪机制,接真 LLM 判定标注 future。
- ⚠️ 结构阈值(window/threshold/budget)是可调参数,过紧会频繁打扰 supervisor、过松会晚点火 → 属运维调参,不改本 ADR 的机制/策略边界。
- ⚠️ **绝不**把 verdict 退化回硬编码规则(如"重复 N 次即终止"):那会把主观判断塞回确定性层,违反 Agent First。断路器只允许"点火 + 无 supervisor 时的结构性停机",不允许"确定性地判 looping/goal_drift"。
