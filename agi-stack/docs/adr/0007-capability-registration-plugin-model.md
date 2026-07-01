# ADR-0007 · 能力注册模型 + 插件形态分类(优先于 ad-hoc hook 堆叠)

- 状态:**已接受**(设计决策,基于 OpenClaw 调研;能力注册/形态分类已 Spike 证伪)
- 日期:2026-06
- 关联:[07-plugin-runtime-architecture §2/§3](../architecture/07-plugin-runtime-architecture.md)、[research/openclaw-runtime-internals](../research/openclaw-runtime-internals.md)、[ADR-0003](0003-plugin-host-as-hexagonal-port.md)、[ADR-0006](0006-hot-plug-via-arcswap-and-proxy-wasm-abi.md)

## 背景

[ADR-0003](0003-plugin-host-as-hexagonal-port.md) 确立"插件宿主 = `ToolHost` 端口",[ADR-0006](0006-hot-plug-via-arcswap-and-proxy-wasm-abi.md) 确立"热插拔 = ArcSwap 原子换表"。但二者只覆盖**工具**这一种扩展点。真实平台有十几类扩展:文本 Provider、Embedding、语音、图像生成、Channel、Hook、Command、Service、HttpRoute、甚至替换整个 Agent 循环的 Harness。若用"匿名 hook 堆叠"承载这些异质扩展(早期 OpenClaw 的 `before_agent_start` legacy 模式),会导致:无法枚举"插件贡献了什么"、无法按类型查找实现、无法对能力类型做信任门控、无法整批卸载。

OpenClaw(`openclaw/openclaw`,380K★)给出被验证的工业模式(`openclaw/openclaw:docs/plugins/architecture.md:36-114`):
- **能力注册**:约 15 类 typed `api.register*`(`registerProvider`/`registerChannel`/`registerAgentHarness`/…),把贡献变成可枚举、可卸载的事实。
- **plugin ≠ capability**:*"plugin = ownership boundary; capability = core contract that multiple plugins can implement or consume"*(`docs/plugins/architecture.md:262`)。
- **插件形态分类**:按 `register(api)` 后的**实际注册行为**(非静态声明)把插件分为 `plain-capability`/`hybrid-capability`/`hook-only`/`non-capability`,`plugins inspect <id>` 可观测(`docs/plugins/architecture.md:70-89`)。

## 决策

### 1. typed `CapabilityRegistry`(替代匿名 hook 堆叠)

每个扩展贡献落为 `(PluginId, CapabilityKind, CapId) → CapabilityImpl`:
```rust
pub enum CapabilityKind { Tool, Skill, Provider, Channel, Harness, Hook, HttpRoute, Command, Service /* ... */ }
pub enum CapabilityImpl {
    Tool(Arc<dyn Tool>), Provider(Arc<dyn TextProvider>), Channel(Arc<dyn Channel>),
    AgentHarness(Arc<dyn RuntimeHarness>), Hook { phase: HookPhase, hook: Arc<dyn Hook> }, /* ... */
}
```
- `PluginId` = 所有权边界,用于 enable/disable/卸载的**整批**操作。
- `CapabilityKind` = 契约类型,核心按类型查找实现。
- 键有序(`BTreeMap`),保证确定性遍历;变更经 [ADR-0006](0006-hot-plug-via-arcswap-and-proxy-wasm-abi.md) 的 ArcSwap 原子换表。

### 2. 插件形态由实际注册行为计算

`PluginShape` 由能力种类计数推导(非清单静态声明):0+hooks=`HookOnly`、0=`NonCapability`、1=`PlainCapability`、≥2=`HybridCapability`。`inspect` 暴露 shape 作为运维/安全抓手。

### 3. 信任门控落在能力类型上(沿用 [ADR-0002](0002-untrusted-plugins-wasm-only.md))

不可信 WASM 插件**禁**注册 `AgentHarness`/`HttpRoute`/`TrustedToolPolicy`,只能落 `PlainCapability(Tool)` + 受限 `Hook`;`AgentHarness` 与 `TrustedToolPolicy` 是 bundled-only 最高信任。门控对象从"插件"细化到"能力类型"。

## 后果

- ➕ 贡献可枚举、可按 `PluginId` 整批 enable/disable/卸载;核心可按 `CapabilityKind` typed 查找,无需遍历匿名 hook。
- ➕ `PluginShape` + `inspect` 让"声称是工具插件却注册了 HttpRoute"等行为可观测、可告警。
- ➕ 信任门控精确到能力类型,不可信代码被结构性挡在"能替换整个 Agent 循环"之外。
- ➕ Spike 证伪通过(见 [04 #9](../architecture/04-spike-evidence.md)):`PluginManifest.shape()` 正确分类 `scorer`=`PlainCapability`、`notes`=`HybridCapability`;`PluginHost` enable/disable 按 `plugin_id → tools` 集合运算注册/注销。
- ➖ typed 枚举比匿名 hook 更"重":新增能力类型需扩 `CapabilityKind`/`CapabilityImpl` 枚举(但这正是要的——编译期穷尽、无隐式契约)。
- ➖ 形态分类需在 `register` 完成后才能定(运行时事实),清单只能给"声明意图",真实 shape 待加载后揭晓。
- ⚠️ "推哪个能力插件给哪个租户/会话"可含**语义**策略 → 归 agent/控制面决策;"enable 后注册表多了哪几个能力 / shape 是什么"是结构事实,保持确定性(Agent First 铁律)。
