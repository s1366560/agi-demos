# ADR-0008 · Agent Runtime 即可插拔 Harness(embedded vs CLI-backend,可选 runtime_id)

- 状态:**已接受**(设计决策,基于 OpenClaw 调研)
- 日期:2026-06
- 关联:[07-plugin-runtime-architecture §1/§4](../architecture/07-plugin-runtime-architecture.md)、[research/openclaw-runtime-internals](../research/openclaw-runtime-internals.md)、[06-agent-core-design §6](../architecture/06-agent-core-design.md)、[ADR-0007](0007-capability-registration-plugin-model.md)

## 背景

[06 §6](../architecture/06-agent-core-design.md) 把"重型服务器 runner"与"轻量端上 runner"看成同一 `SessionProcessor` 的两种**部署形态**。这解决了"一份核心跑两端",但隐含一个假设:**只有一个 Agent 执行循环**。真实需求更复杂:用户可能想用 Claude Code CLI、Codex、或某个 provider 自带的原生 agent 后端来执行一轮,而不是内置 ReAct 循环。若把"换执行循环"做成 if/else 开关或硬编码分支,会导致:无法第三方扩展执行器、provider 特定的循环逻辑污染核心、整会话锁定某后端的隐式状态。

OpenClaw 揭示"Agent Runtime 是与 Provider/Model/Channel 正交的一层",其实现称 **harness**,分两家族(`openclaw/openclaw:docs/concepts/agent-runtimes.md`、`docs/plugins/sdk-agent-harness.md`、`docs/plugins/cli-backend-plugins.md`):
- **Embedded harness**:进程内 prepared loop(内置 `openclaw`、插件 `codex`/`copilot`),`api.registerAgentHarness(...)`。
- **CLI backend**:spawn 外部 CLI 子进程(`claude-cli`),`api.registerCliBackend(...)`。

关键设计:**host 准备 / harness 执行 分离** —— host 解析 provider/auth/session/workspace/tool-policy/channel,打包 host-owned `runtimePlan`,harness 只收**完全准备好的 attempt**(`docs/plugins/sdk-agent-harness.md` "What core still owns")。且 **runtime 永远按 `(provider, model)` 解析,整会话 pin 一律忽略**(`docs/concepts/agent-runtimes.md`)。

## 决策

### 1. `RuntimeHarness` trait + 可选 `runtime_id`

```rust
pub trait RuntimeHarness: Send + Sync {
    fn runtime_id(&self) -> &str;                          // "openclaw" / "codex" / "claude-cli"
    fn supports(&self, ctx: &HarnessCtx) -> Option<u32>;   // Some(priority) 表示可处理
    async fn run_attempt(&self, attempt: PreparedAttempt) -> CoreResult<TurnOutcome>;
}
```
内置 `SessionProcessor` 实现此 trait 作默认 harness;第三方经 [ADR-0007](0007-capability-registration-plugin-model.md) 的 `CapabilityImpl::AgentHarness` 注册(bundled-only 信任)。

### 2. host 准备 / harness 执行 分离

Host 解析全部上下文并打包 `Arc<RuntimePlan>{ normalize_tools, classify_outcome, is_silent }`,harness 只收 `PreparedAttempt`。harness **不**碰 provider 解析、auth、session 加载、channel 回调。CLI backend harness 置 `owns_native_compaction` → host compactor 跳过,避免双重压缩。

### 3. `auto` 选择 + 回退,runtime 按 `(provider, model)` scoped

选择优先级:model-scoped policy > provider-scoped policy > `auto`(问所有 harness `supports(ctx)` 取最高 priority)> 回退内置 `SessionProcessor`。**采纳不变量**:每轮重解析 runtime,**忽略整会话/整 agent 的 runtime pin**,契合轮次边界原子换([06](../architecture/06-agent-core-design.md))。

### 4. 二分:embedded 上端,CLI-backend 仅服务器

- **Embedded harness**(`SessionProcessor` 及同类)= 端上 + 服务器都能跑,无子进程、无 JIT 依赖。
- **CLI backend harness** = spawn 子进程,**仅服务器**;违反 [06](../architecture/06-agent-core-design.md)"核心运行时无关"不变量者不上端。
- 端上**永远** embedded + Wasmi + `dyn Trait`。

## 后果

- ➕ 执行循环可第三方扩展(Codex/Copilot/Claude-CLI 等),核心只认 `RuntimeHarness` trait,provider 特定逻辑被隔离在插件内。
- ➕ host 准备/harness 执行分离 → 同一套 auth/session/tool-policy 服务所有 harness,无重复实现。
- ➕ `runtime` 按 `(provider,model)` scoped + 每轮重解析 → 无整会话隐式锁定,天然契合轮次边界热换(可在轮次边界换 harness,如同换工具表)。
- ➕ 与既有"重/轻分叉"正交:`SessionProcessor` 是上端 embedded harness;CLI backend 是服务器专属的另一可选 harness。二者不冲突。
- ➖ `PreparedAttempt`/`RuntimePlan` 契约需精心设计(host 与 harness 的边界),早期可只暴露内置 `SessionProcessor` 一个 harness,契约随第二个 harness(如 CLI backend)落地再固化。
- ➖ CLI backend 的子进程管理(spawn/session resume/watchdog/MCP bridge)是服务器侧重型工程,端上不获益。
- ⚠️ "选哪个 harness 执行本轮"在 `auto` 之外可含**语义**偏好 → 归 agent/配置决策;"`supports()` 谁优先级最高 / 回退到哪个"是结构/算术事实,保持确定性(Agent First 铁律)。
