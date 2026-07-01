# ADR-0003 · 把插件宿主抽象为六边形端口 `ToolHost`

- 状态:**已接受**(决策 Spike 证伪通过)
- 日期:2026-06
- 关联:[02-extensibility](../architecture/02-extensibility.md)、[04-spike-evidence #8](../architecture/04-spike-evidence.md)

## 背景

不可信工具走 WASM([ADR-0002](0002-untrusted-plugins-wasm-only.md)),但**没有单一 WASM 运行时适配所有平台**:

- 服务器/桌面想要 **Wasmtime**(JIT、fuel/epoch 配额、生产级隔离);
- **iOS 禁 JIT**,Wasmtime 受限,需 **Wasmi(解释)/ Wasmer(JIT-less)**;
- **浏览器**核心自身已是 wasm,无法低成本在 wasm 内再起重型 wasm 运行时,须走 **Web Worker / 服务器代理 / Wasmi 解释**。

如果核心直接 import 某个具体运行时,就会绑死平台,破坏可移植性。

## 决策

**把"插件宿主"本身做成一个六边形端口 `ToolHost`(`PluginRuntime`),按平台换适配器。** 核心只依赖该 trait,绝不 import Wasmtime/Wasmi 等具体运行时。

```rust
#[async_trait]
pub trait ToolHost: Send + Sync {
    fn list_tools(&self) -> Vec<String>;
    async fn call(&self, tool: &str, input_json: &str) -> CoreResult<String>;
}
```

- 服务器/桌面:`adapters-wasmtime`;iOS:`adapters-wasmi`/wasmer;浏览器:`adapters-worker-proxy`/wasmi。
- 与 `MemoryRepository`/`LlmPort` 完全同构 —— **可扩展性因此干净折叠进既有六边形模型**,不引入新范式。

## 验证

Spike 已落地 `ToolHost` 端口 + `adapters-wasmi`(纯 Rust Wasmi),经端口跑通沙箱 `.wat` 工具(测试绿),且适配器**同样编到 `wasm32`** —— 证明:同一宿主 native + 浏览器 wasm-in-wasm 双目标成立。Wasmtime 后续可在同端口后无痛换入提速。提交 `42d1672e8`。

## 后果

- ➕ 平台轴折叠为"换适配器";核心保持运行时无关;Wasmtime/Wasmi 可按平台/性能自由替换。
- ➕ `Wasmi` 作通用兜底(编到任意目标),`Wasmtime` 作服务器/桌面提速,同一 `.wasm` 工具写一次到处跑。
- ➖ 端口需吸收运行时差异(配额、能力授予)为统一抽象,设计需谨慎。
- ⚠️ 浏览器路径性能受限(Wasmi 解释或代理),热的不可信工具在浏览器宜走服务器代理。
