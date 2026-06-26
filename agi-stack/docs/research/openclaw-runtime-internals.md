# OpenClaw 运行时 / 插件 / 热插拔 内部设计调研

> [07-plugin-runtime-architecture](../architecture/07-plugin-runtime-architecture.md) 的**证据基**。目的不是集成 OpenClaw,而是**学习其工业级多层运行时与插件机制**,映射到 agi-stack 的可移植 Rust 核心。
>
> 调研标的:`openclaw/openclaw`(commit `81e53202f25f216ddfd795cc28bdd06c856d9de1`,branch `main`)—— 一个 380K★ 的"个人 AI Agent 运行时"(TypeScript monorepo,`apps/{ios,android,macos,shared}` 多端 + `packages/{agent-core,llm-runtime,acp-core,plugin-sdk,...}` 分层 core)。与 Claude Code / Codex / OpenCode / Gemini CLI 同类。
>
> 引用格式 `openclaw/openclaw:path[:line]`,指向上游;行号为调研时点近似。三节(runtime / plugins / hotplug)各含:机制详解(带引用)→ 机制 → Rust 映射表 → 关键引用汇总。

---

## 第一节 · Agent 运行时分层(runtime)

### 1.1 四层正交分离 —— "各种 runtime" 的真正含义

OpenClaw 显式分离四个常被混淆的层(`openclaw/openclaw:docs/concepts/agent-runtimes.md` 顶部表):

| 层 | 例子 | 职责 |
|---|---|---|
| **Provider** | `openai`、`anthropic`、`github-copilot` | 认证、模型发现、model-ref 命名空间 |
| **Model** | `gpt-5.5`、`claude-opus-4-6` | 本轮选用的模型(`provider/model` 复合 ref) |
| **Agent runtime** | `openclaw`、`codex`、`copilot`、`claude-cli` | 执行已准备好的一轮的"底层循环或后端" |
| **Channel** | Telegram、Discord、Slack | 消息进出 OpenClaw 的传输面 |

> *"An agent runtime is the component that owns one prepared model loop: it receives the prompt, drives model output, handles native tool calls, and returns the finished turn to OpenClaw."* — `openclaw/openclaw:docs/concepts/agent-runtimes.md`

**Runtime ≠ Provider** 是核心区分:Provider 管"谁认证、怎么命名模型";Agent runtime 管"哪个循环执行这一轮"。Channel 投递**永远归 OpenClaw 所有**,与选哪个 runtime 无关。

### 1.2 Harness 模型 —— runtime 的实现

> *"A harness is the implementation that provides an agent runtime."* — `openclaw/openclaw:docs/concepts/agent-runtimes.md`
> *"An agent harness is the low level executor for one prepared OpenClaw agent turn. It is not a model provider, not a channel, and not a tool registry."* — `openclaw/openclaw:docs/plugins/sdk-agent-harness.md`

关键设计:把"host 侧准备"(provider 解析、auth、session 加载、workspace、tool policy、channel 回调)与"执行一次已准备的 attempt"分离。Harness 只收到一个**完全准备好的 attempt** 并运行它。准备阶段 host 已解析(`openclaw/openclaw:docs/plugins/sdk-agent-harness.md` "What core still owns"):provider/model、runtime auth、thinking level、transcript/session 文件、workspace/sandbox/tool policy、channel 回调、model fallback 策略。Harness 收到一个 host-owned 的 `params.runtimePlan` 策略包(`tools.normalize`、`transcript.resolvePolicy`、`delivery.isSilentPayload`、`outcome.classifyRunResult`)。

**两大 runtime 家族**:
- **Embedded harness**(进程内,跑在 OpenClaw 自己的循环里):内置 `openclaw` runtime + 插件注册的 `codex`/`copilot`。经 `api.registerAgentHarness(harness)` 注册。
- **CLI backend**(spawn 本地 CLI 进程,保持 model ref 规范):如 `claude-cli`。经 `api.registerCliBackend(config)` 注册,有独立的 `CliBackendConfig`(command/args/output parser/session resume/image args/MCP bridge/watchdog)。

> **铁律**:`claude-cli` 是 CLI backend id,**不是** embedded harness id。两者不可混淆。— `openclaw/openclaw:docs/plugins/cli-backend-plugins.md`

### 1.3 `AgentHarness` 接口与 `auto` 选择

```typescript
// openclaw/openclaw:docs/plugins/sdk-agent-harness.md ("Register a harness")
const myHarness: AgentHarness = {
  id: "my-harness",
  label: "My native agent harness",
  supports(ctx) {
    return ctx.provider === "my-provider"
      ? { supported: true, priority: 100 }
      : { supported: false };
  },
  async runAttempt(params) { return await runMyNativeTurn(params); },
};
export default definePluginEntry({
  id: "my-native-agent", name: "My Native Agent",
  register(api) { api.registerAgentHarness(myHarness); },
});
```

**`auto` 选择算法**(优先级,`openclaw/openclaw:docs/plugins/sdk-agent-harness.md` "Selection policy"):
1. Model-scoped policy 胜:`models["provider/model"].agentRuntime.id`
2. Provider-scoped policy:`models.providers.<provider>.agentRuntime`
3. `auto`:问所有注册 harness 的 `supports(ctx)`,**最高 priority 胜**
4. Fallback:无 harness 匹配则回退内置 `openclaw` runtime

> **关键不变量**:整会话/整 agent 的 runtime pin **全部被忽略**(`OPENCLAW_AGENT_RUNTIME`、`agents.defaults.agentRuntime`、session `agentHarnessId`)。runtime 永远按 `(provider, model)` 解析。— `openclaw/openclaw:docs/concepts/agent-runtimes.md`

### 1.4 Prepared model loop 与依赖注入

`runLoop`(`openclaw/openclaw:packages/agent-core/src/agent-loop.ts:298–431`)是干净的双 while 状态机:外层处理 turn 后到达的 follow-up,内层处理 tool-call 批次与 steering。发出事件流 `agent_start → turn_start → message_*/text_delta/toolcall_* → turn_end → ... → agent_end`(`agent-loop.ts:179–431`)。

**provider 无关的接缝**(`openclaw/openclaw:packages/agent-core/src/runtime-deps.ts`):
```typescript
export interface AgentCoreRuntimeDeps {
  streamSimple: StreamFn;        // agent turn 的流式补全
  completeSimple: CompleteSimpleFn; // summarization 用非流式
}
```
`agent-core` **从不** import 具体 HTTP transport,只收注入函数。Host 包(`llm-runtime`)提供实现。`llm-runtime` 的 `registerApiProvider`(`packages/llm-runtime/src/api-registry.ts`)是按 `model.api` keyed 的全局 dispatch 表,带 `sourceId` 支持插件卸载时批量注销。

### 1.5 一核多端(One-Core-Many-Ends)

OpenClaw 用单一 Gateway + embedded runtime 服务 web/PC/移动:Gateway(`src/`,Node)host 运行时/会话/工具/provider/插件/channel;各平台作为 **node** 连接。

> *"The iOS app is not a Codex Computer Use backend ... iOS exposes device capabilities as OpenClaw node commands through the gateway. Agents can drive the iPhone canvas, camera, screen, location ... with `node.invoke`."* — `openclaw/openclaw:apps/ios/README.md`

iOS app **不在本地跑 runtime**,而是作为 `role: node` 远程暴露设备能力。这与 agi-stack 的取舍互补:agi-stack 让**核心本身**可移植到端上(local-first 离线),OpenClaw 让端上作为 Gateway 的远程 node。两者都把"重运行时"留在原生侧。

### 1.6 机制 → Rust Agent 核心映射(runtime)

| OpenClaw 机制 | 来源 | Rust 落地 |
|---|---|---|
| 四层分离(Provider/Model/Runtime/Channel) | `docs/concepts/agent-runtimes.md` | 原样保留:`Provider` trait、`ModelRef{provider,model}`、`RuntimeId` newtype、`Channel` trait |
| `AgentHarness{supports,runAttempt}` | `packages/agent-core/src/harness/agent-harness.ts` | `trait RuntimeHarness { fn runtime_id()->&str; fn supports(&HarnessCtx)->Option<u32>; async fn run_attempt(PreparedAttempt)->Result<...> }` |
| `auto` 优先级选择 + 回退内置 | `docs/plugins/sdk-agent-harness.md` | `HarnessRegistry::select()` 遍历 `supports()` 取最高 priority,无匹配回退 embedded |
| `AgentCoreRuntimeDeps` 注入 | `packages/agent-core/src/runtime-deps.ts` | **直接复用既有不变量**:`RuntimeDeps{stream_fn, complete_fn}` 构造期注入,核心零 tokio |
| embedded vs CLI backend 二分 | `docs/plugins/cli-backend-plugins.md` | embedded → 端上/服务器均可的 in-process harness;CLI backend → **仅服务器** `CliBackendHarness`(spawn 子进程) |
| `runtimePlan` 策略包 | `docs/plugins/sdk-agent-harness.md` | `Arc<RuntimePlan>`:`normalize_tools`、`classify_outcome`、`is_silent` —— host 解析后传入 harness |
| `ownsNativeCompaction` 标志 | 同上 | CLI backend harness 置位,host compactor 跳过,避免双重压缩 |
| 整会话 runtime pin = 忽略 | `docs/concepts/agent-runtimes.md` | **采纳为不变量**:runtime 永远按 `(provider, model)` scoped |
| 一核多端(Gateway+node) | `apps/ios/README.md` | 服务器 = Gateway 等价(Kameo);端上 = embedded 单线程 runtime 本地执行(local-first,超越 OpenClaw 的纯 node 模型) |

---

## 第二节 · 多层插件 / 能力注册模型(plugins)

### 2.1 能力注册表(`api.register*`,约 15 类能力)

每个 native 插件对一个或多个**能力契约**注册(`openclaw/openclaw:docs/plugins/architecture.md:36-53`、`docs/plugins/sdk-overview.md:91-113`):

| 能力 | 注册方法 | 例 |
|---|---|---|
| 文本推理 | `api.registerProvider(...)` | `openai`、`anthropic`、`mistral` |
| CLI 推理后端 | `api.registerCliBackend(...)` | `openai`、`anthropic` |
| Embedding | `api.registerEmbeddingProvider(...)` | 向量插件 |
| 语音 TTS/STT | `api.registerSpeechProvider(...)` | `elevenlabs` |
| 实时转写/语音 | `api.registerRealtime{Transcription,Voice}Provider(...)` | `openai` |
| 媒体理解 | `api.registerMediaUnderstandingProvider(...)` | `openai`、`google` |
| 图/乐/视频生成 | `api.register{Image,Music,Video}GenerationProvider(...)` | `openai`、`google`、`qwen` |
| Web fetch/search | `api.registerWeb{Fetch,Search}Provider(...)` | `firecrawl`、`google` |
| 消息 channel | `api.registerChannel(...)` | `slack`、`discord` |
| Gateway 发现 | `api.registerGatewayDiscoveryService(...)` | `bonjour` |
| Agent harness(实验) | `api.registerAgentHarness(...)` | `codex` |

基础设施类(非能力)注册:`registerHook`、`registerHttpRoute`、`registerGatewayMethod`、`registerCli`、`registerService`、`registerCommand`、`registerToolMetadata`、`registerTrustedToolPolicy`(`openclaw/openclaw:docs/plugins/sdk-overview.md:164-176`)。

> **plugin ≠ capability**:*"**plugin** = ownership boundary. **capability** = core contract that multiple plugins can implement or consume."* — `openclaw/openclaw:docs/plugins/architecture.md:262-266`

### 2.2 插件形态分类(Plugin Shapes)—— 按实际注册行为

OpenClaw 把每个已加载插件分类为一个 **shape**,依据是 `register(api)` 后的**实际注册行为**,非静态元数据(`openclaw/openclaw:docs/plugins/architecture.md:70-89`):

| Shape | 定义 | 例 |
|---|---|---|
| **`plain-capability`** | 恰好注册**一种**能力类型 | `mistral`(仅文本)、`firecrawl`(仅 web-fetch) |
| **`hybrid-capability`** | 注册**多种**能力类型 | `openai`(文本+语音+实时+媒体+图像) |
| **`hook-only`** | 只注册 hook,无能力/工具/命令 | 合规日志、预算监控 |
| **`non-capability`** | 注册工具/命令/服务/路由但**无**能力 | 纯工具插件、webhook 处理器 |

`openclaw plugins inspect <id>` 输出 shape + 能力分解。兼容信号:`config valid` / `compatibility advisory`(如用了 hook-only) / `legacy warning`(用了废弃的 `before_agent_start`) / `hard error`。

### 2.3 清单契约(Manifest)

- `package.json` 的 `openclaw` 字段声明 `extensions`/`skills`/`prompts`/`themes`(`openclaw/openclaw:docs/plugins/manifest.md`、`docs/agent-runtime-architecture.md` "Manifests")。
- native 插件另有 `openclaw.plugin.json`(id、entry、能力声明、compatibility bars、`requiresPlugins`)。
- 设计意图:**清单是廉价静态元数据**,loader 在实例化任何代码**之前**就能发现"插件贡献了什么"。

### 2.4 多层插件类型(taxonomy)

`openclaw/openclaw:docs/plugins/*` 显示 7 类插件,信任与能力递增:Skills(纯数据/markdown)→ Tool 插件 → Extension/Provider 插件(全功能 native)→ Channel 插件 → **Agent Harness 插件**(实验,替换 agent 执行器,**bundled-only 信任**)→ Bundle 插件(内容包,窄信任)→ Hook-only/基础设施插件。

> **信任分级**:harness 与 trusted-tool-policy 是 **bundled-only**(随核心分发,最高信任);第三方市场插件不能注册 harness。这与 agi-stack 的"不可信只走 WASM、且不得宿主完整 agent loop"完全一致。

### 2.5 机制 → Rust 映射(plugins)

| OpenClaw 机制 | 来源 | Rust 落地 |
|---|---|---|
| `api.register*`(15 类能力) | `docs/plugins/architecture.md:36-53` | typed `CapabilityRegistry`:`enum CapabilityImpl { TextProvider(Arc<dyn ...>), Channel(...), Tool(...), AgentHarness(...), Hook(...), ... }`,按 `(plugin_id, kind, cap_id)` keyed |
| Plugin shapes(plain/hybrid/hook-only/non-capability) | `docs/plugins/architecture.md:70-89` | `enum PluginShape { PlainCapability, HybridCapability, HookOnly, NonCapability }`,**由实际贡献计算**(能力种类计数) |
| 兼容信号 | 同上 | `enum PluginCompatSignal { ConfigValid, CompatibilityAdvisory, LegacyWarning, HardError }` |
| manifest(`openclaw` 字段 + `openclaw.plugin.json`) | `docs/plugins/manifest.md` | `struct PluginManifest{ name, version, tools, skills, providers, channels, hooks }`(JSON,镜像 `openclaw` 字段) |
| plugin ≠ capability | `docs/plugins/architecture.md:262` | `plugin` = 所有权边界(`PluginId` + 贡献集);`capability` = 核心契约(多插件可实现/消费) |
| harness/trusted-policy = bundled-only | `docs/plugins/sdk-overview.md` | 信任轴:WASM(不可信)插件**禁**注册 `AgentHarness`/`HttpRoute`/`TrustedToolPolicy`;只能注册 `Tool` + 受限 `Hook`(沿用 [ADR-0002](../adr/0002-untrusted-plugins-wasm-only.md)) |
| 一注册中心 + 核心只读 | `docs/plugins/architecture-internals.md:170-174` | "plugin → registry(写)→ core(读)" 单向流;对应 `Arc<ArcSwap<Registry>>` 快照换表 |

---

## 第三节 · 加载管线 / 注册中心 / 热插拔生命周期(hotplug)

### 3.1 注册中心 = 不可变快照 + 原子指针换

`PluginRegistry`(`openclaw/openclaw:src/plugins/registry-types.ts`)是带扁平数组的纯对象(`plugins/tools/hooks/channels/providers/httpRoutes/services/...` 30+ typed 能力数组 + `diagnostics`)。每个 `PluginRecord` 有 `status: "loaded"|"disabled"|"error"`、`enabled`、`failurePhase?`、`toolNames[]` 等。

**变更 = 整体替换,非原地改**:
```typescript
// openclaw/openclaw:src/plugins/runtime.ts:183-206
export function setActivePluginRegistry(registry, cacheKey?, ...) {
  const previousRegistry = asPluginRegistry(state.activeRegistry);
  state.activeRegistry = registry;          // ← 原子指针换
  markPluginRegistryActive(registry);
  state.activeVersion += 1;                  // ← 单调版本号
  syncTrackedSurface(state.httpRoute, registry, true);
  // ...
  if (!retirePluginRegistryIfUnused(previousRegistry)) return;
  cleanupRetiredPluginHostRegistry(previousRegistry); // 异步 fire-and-forget
}
```
全局状态在 `globalThis[Symbol.for("openclaw.pluginRegistryState")]`,含 `activeVersion`(单调递增)与可 pin 的 surface(`httpRoute`/`channel`/`sessionExtension`)。

### 3.2 Surface pinning = drain 机制(in-flight 安全)

三个 surface 可 **pin** 到旧 registry,而 `activeRegistry` 前进:
```typescript
// openclaw/openclaw:src/plugins/runtime.ts:208-235
export function pinActivePluginHttpRouteRegistry(registry) {
  installSurfaceRegistry(state.httpRoute, registry, true); // pinned=true
  // 旧 registry 在 pin 释放前不被 retire
}
```
in-flight HTTP 请求、channel 连接、session extension 各自 hold 一个 pin,直到完成 —— 这是主要的 "drain" 机制,让旧 registry 存活到在途工作排空。

**异步 cleanup 带 guard**(`runtime.ts:90-106`):cleanup 前 re-check `state.activeRegistry !== previousRegistry`,若回滚则中止。**cleanup 原因区分**(`host-hook-cleanup.ts:319-341`):`restart`(插件在新旧 registry 都存在 → 保留持久 session state)vs `disable`(插件被移除 → 清空插件 session state)。`agent_end` hook 有 **30 秒超时**,卡死插件不能永久挂起。

### 3.3 生命周期状态机

| 操作 | 效果 | 热? | 来源 |
|---|---|---|---|
| `plugins install` | 写入 managed 路径 + SQLite index + config | managed Gateway 自动重启(若开 config-reload) | `docs/plugins/manage-plugins.md:37-44` |
| `plugins enable/disable <id>` | 改 `plugins.entries.<id>.enabled` | 需 Gateway 重启在运行进程生效 | `docs/cli/plugins.md:44-45` |
| Gateway config reload | `loadOpenClawPlugins()` 建新 `PluginRegistry` → `setActivePluginRegistry()` | **进程内热换**(原子替换) | `src/plugins/loader.ts:1808-1819` |

推断状态机:`DISCOVERED`(清单读、安全门过)→ `ENABLED` → `LOADING`(import 中,reentry guard)→ `LOADED`(`register(api)` 成功)→ `ACTIVE`(`setActivePluginRegistry`)→ `RETIRED`(`markRetired`,若 surface-pinned 仍 live)→ `CLEANED UP`(cleanup 回调、session state 清)。旁支 `DISABLED`、`ERROR{failurePhase}`。

> **关键发现**:`setActivePluginRegistry()` 机制本身**是**进程内原子的(指针换 + 版本递增)。但常规运维下 Gateway 作为 managed 子进程**整体重启**,真正的进程内热换主要在 config-reload 路径与测试(`resetPluginRuntimeStateForTest()`)中行使。— `docs/plugins/manage-plugins.md:37-44`

### 3.4 依赖解析与兼容门控

> *"OpenClaw keeps plugin dependency work at install/update time. Runtime loading does not run package managers."* — `openclaw/openclaw:docs/plugins/dependency-resolution.md:1-5`

`requiresPlugins`(软依赖,缺失发 diagnostic 不阻塞)、install-root 排序、cycle 检测、override 机制。Compatibility registry(`src/plugins/compat/registry.ts`)状态:`active/deprecated/removal-pending/removed`,manifest version bars,load-time + run-time 权限门控。

### 3.5 机制 → Rust 热插拔映射(hotplug)

| OpenClaw 机制 | 来源 | Rust 落地 |
|---|---|---|
| `PluginRegistry` 不可变快照(纯对象) | `src/plugins/registry-types.ts` | `Arc<ToolRegistry>`(不可变、引用计数);建新实例,从不原地改 |
| `setActivePluginRegistry()` 原子指针换 + 版本递增 | `src/plugins/runtime.ts:183-206` | `ArcSwap::store(Arc::new(new))` / `rcu(...)`;`AtomicU64` 版本号 |
| `getActivePluginRegistry()` 读 | 同上 | `arcswap.load_full() -> Arc<ToolRegistry>`;**hold 整轮 = round-boundary 快照** |
| Surface pinning(drain) | `runtime.ts:208-235` | **持有 `Arc<ToolRegistry>` snapshot**:in-flight 轮次 hold 旧快照,新表只对新轮次生效 |
| `markRetired`(`WeakSet`)+ 异步 cleanup | `registry-lifecycle.ts` | Arc refcount 归零 → **RAII Drop** 自动 cleanup,无需显式跟踪集 |
| cleanup 原因 `restart` vs `disable` | `host-hook-cleanup.ts:319` | `enum DisableReason { Reload, Uninstall }`:Reload 保留 KV state,Uninstall 清空 |
| 版本/hash 幂等 apply | `PluginLoaderCacheState` | key = `sha256(wasm_bytes ‖ manifest_json)`;hash 相同则跳过换表 |
| 生命周期状态机 | `manage-plugins.md` + 推断 | `DISCOVERED→TRUSTED→COMPILED→RESOLVED→ACTIVE→RETIRING→CLEANED UP` + `DISABLED`/`ERROR` |
| 30s `agent_end` 超时 | `docs/plugins/hooks.md:373` | host hook runner 套 `timeout(...)`,卡死插件不挂起轮次 |

### 3.6 调研给出的关键结论:agi-stack 的 round-boundary 比 OpenClaw 更强

> *"Our round-boundary invariant is strictly stronger: `ArcSwap::store(new_registry)` only happens when the ReAct loop reaches a checkpoint (between rounds) ... Eliminates the case OpenClaw doesn't prevent: `setActivePluginRegistry()` mid-turn."* — 调研结论(基于 `docs/plugins/architecture-internals.md` + `runtime.ts`)

OpenClaw 的 in-flight 安全靠 **Gateway 重启 + per-surface pinning**,且**未规定**"turn 开始时快照 registry 并 hold 引用"——是否能在 agent-turn 中途 `setActivePluginRegistry()` 而不影响当前 turn 的工具调用,OpenClaw 文档**未明确**(§6 "What is NOT specified")。agi-stack 把换表绑定到**ReAct 轮次边界**([ADR-0005](../adr/0005-round-boundary-checkpoint.md)):每轮工具调用对**恰好一个**冻结的 `Arc<ToolRegistry>` 快照解析,无轮次跨两代 registry。这是对 OpenClaw 模型的**确定性增强**,并已由 Spike 证伪通过([04 #9](../architecture/04-spike-evidence.md))。

---

## 关键引用汇总

- 运行时分层 / harness / 选择策略:`openclaw/openclaw:docs/concepts/agent-runtimes.md`、`docs/plugins/sdk-agent-harness.md`、`docs/plugins/cli-backend-plugins.md`
- prepared loop / DI:`packages/agent-core/src/agent-loop.ts:298-431`、`packages/agent-core/src/runtime-deps.ts`、`packages/llm-runtime/src/api-registry.ts`
- 一核多端:`apps/ios/README.md`、`apps/macos/README.md`、`apps/shared/OpenClawKit/`
- 能力注册 / shapes / manifest:`docs/plugins/architecture.md:36-114,262-266`、`docs/plugins/sdk-overview.md:91-224`、`docs/plugins/manifest.md`、`docs/agent-runtime-architecture.md`
- 注册中心 / 热插拔:`src/plugins/registry-types.ts`、`src/plugins/runtime.ts:90-280`、`src/plugins/runtime-state.ts`、`src/plugins/registry-lifecycle.ts`、`src/plugins/host-hook-cleanup.ts:319-341`、`docs/plugins/architecture-internals.md:152-178`、`docs/plugins/manage-plugins.md:37-82`、`docs/plugins/dependency-resolution.md`、`docs/plugins/hooks.md:139,373-380`

> 调研未能抓取(网络/体量):`docs/plugins/codex-harness-reference.md`、`docs/concepts/multi-agent.md`、`src/agents/{embedded-agent-runner,sessions,runtime}/` 个别源文件、`apps/shared/OpenClawKit` 细节。相关结论由 arch 文档与同级文档推断,已在正文标注。
