# ADR-0006 · 热插拔 = ArcSwap 原子换表 + proxy-wasm 风格 ToolHost ABI + CP/DP 配置推送

- 状态:**已接受**(设计决策,基于网关调研;ToolHost 端口已 Spike 证伪)
- 日期:2026-06
- 关联:[06-agent-core-design §2](../architecture/06-agent-core-design.md)、[research/gateways-internals](../research/gateways-internals.md)、[ADR-0003](0003-plugin-host-as-hexagonal-port.md)

## 背景

工具生态需要**热插拔**:启用/禁用/新增/升级工具,不重启核心、不打断在途会话。三类网关给出收敛机制:
- **ShenYu**:Copy-on-Write `volatile` list swap(读零锁),`PluginHandlerEvent` 驱动;运行时可改排序。
- **proxy-wasm/Higress**:`VMContext→PluginContext→HttpContext` 三级上下文 + 版本化 ABI;xDS/ECDS 触发新 VM,旧 VM drain 后销毁(线性内存隔离保证新旧并存)。
- **Kong Hybrid Mode**:CP/DP 分离,`push_config` + `calculate_config_hash` 幂等 + WebSocket 三线程。

[ADR-0003](0003-plugin-host-as-hexagonal-port.md) 已确立"插件宿主 = `ToolHost` 端口";本 ADR 补齐**热插拔机制**(如何换、如何下发)。

## 决策

热插拔由三件事组成:

### 1. 注册中心原子换表(借鉴 ShenYu Copy-on-Write)
工具注册中心用 `Arc<ArcSwap<ToolRegistry>>` 包裹**已排序**列表。变更 = clone → 增删/重排 → `ArcSwap` 单次原子写;**读路径 `registry.load()` 无锁**。新一轮 ReAct 在**轮次边界**([ADR-0005](0005-round-boundary-checkpoint.md))`load()` 到新表,不打断飞行轮次。`tool_config.priority: u32` 来自控制面,可运行时调序。

### 2. 跨宿主稳定 ABI(借鉴 proxy-wasm 三级上下文)
定义 proxy-wasm 风格的稳定 Rust trait ABI,Wasmtime(服务器)与 Wasmi(端上)实现**同一套 hostcall**:
- `WasmRuntime`(≈ VMContext)→ `WasmToolModule`(≈ PluginContext,`on_module_start(cfg)`)→ `WasmToolInvocation`(≈ HttpContext,`on_invoke(req)`)。
- `on_tick()` 后台维护;host 侧 `on_http_call_response(call_id, ...)` 作为 WASM 异步 hostcall 的回调(≈ `ActionPause`/resume)。

热换载体:收到 `.wasm` bytes → `Module::new()` → `Instance::new()` → `on_module_start` → 入 registry → ArcSwap 换;旧 `Instance` 待飞行调用完成后由 RAII drop。

### 3. CP/DP 配置推送(借鉴 Kong Hybrid Mode)
云端 `ToolConfig` 控制面 → 边缘/端上 `ToolHost` 数据面:推送 `ToolRegistrySnapshot{ tools, version: u64 }`,DP 比对 `version`/hash **幂等 apply**(跳过重复),断线重连全量重传。传输按平台:服务器 gRPC streaming / WebSocket;端上(iOS 后台限制)HTTP long-poll。

## 后果

- ➕ 启用/禁用/调序毫秒级(ArcSwap),升级工具零重启(WASM VM 隔离),配置下发幂等(version/hash)。
- ➕ 同一 `.wasm`(稳定 ABI)服务器 Wasmtime 跑、端上 Wasmi 跑,写一次到处跑(沿用 [ADR-0003](0003-plugin-host-as-hexagonal-port.md))。
- ➕ 全平台可行:ArcSwap/原子换表在 iOS、浏览器(单线程 WASM)均可用。
- ➖ 稳定 ABI 需吸收 Wasmtime/Wasmi 差异为统一 hostcall 抽象,设计需谨慎;PoC 期可用裸 `.wat` 过渡,正式用 WIT/Component Model。
- ➖ 内置(可信)工具仍**重编译**才能变更代码,但启用/禁用经同一 ArcSwap 换表;不可信工具一律 WASM(沿用 [ADR-0002](0002-untrusted-plugins-wasm-only.md))。
- ⚠️ 浏览器核心自身已是 wasm,第三方工具走 Web Worker / 服务器代理 / Wasmi 解释(沿用 [02 §4](../architecture/02-extensibility.md))。
- ⚠️ "推哪些工具给哪个租户/会话"可含**语义**策略 → 由 agent/控制面决策;DP 端 version 比对、幂等 apply、ArcSwap 换表保持确定性。
