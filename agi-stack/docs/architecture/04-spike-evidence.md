# 04 · 决策 Spike 已验证结论

> 本架构不是空想:其两条主轴([01](01-portable-core.md) 可移植核心、[02](02-extensibility.md) 可扩展性)均已用**可运行、可测试**的 Rust Spike 证伪通过。Spike 代码在仓库根 `spikes/rust-portable-core/`(`README.md` 含完整命令与结论)。

切片选定:**Episode → Memory 提取 + 语义存储/检索**,锚定真实代码 `src/domain/model/memory/{episode,memory}.py`、`src/domain/ports/repositories/memory_repository.py`。故意覆盖所有跨平台难点:纯领域实体、存储端口双实现、一步 async LLM 边界、语义检索、跨 WASM/UniFFI 序列化。

## 1. 验证结论表

| # | 受验命题 | 结论 | 证据 |
|---|---|---|---|
| 1 | **核心 async 运行时无关**(不绑 tokio) | ✅ 通过 | `adapters-mem` 测试在 `futures::executor::block_on` 下跑完整流水线;核心零 `tokio`/`std::time` 依赖 |
| 2 | 同一核心编为**原生服务器** | ✅ 通过 | `apps/server`(axum+tokio)curl 验证 `/health`、`POST /episodes`、`GET /memories/search` |
| 3 | 同一核心**不改一行**编为**浏览器 WASM** | ✅ 通过 | `cargo build --target wasm32-unknown-unknown`,核心零改动 |
| 4 | WASM 构建**可被 JS 调用**且**小** | ✅ 通过 | wasm-pack nodejs 构建 + node smoke 测试 round-trip;体积 **95 KB raw / ~49 KB gzip** |
| 5 | **真实嵌入式 DB** 可背同一端口 | ✅ 通过 | `adapters-sqlite`(rusqlite bundled C)实现 `MemoryRepository`,SQL 下推 `search_by_project`,测试绿 |
| 6 | 适配器**确按平台替换**(非一刀切) | ✅ 通过(by construction) | bundled-SQLite **无法**编 `wasm32`(`stdio.h` 缺)→ 浏览器必须换存储适配器,六边形边界生效 |
| 7 | 核心打包为**原生移动库**(Swift/Kotlin) | ✅ 通过(codegen + iOS arch)/ ⏳ 设备产物阻塞 | `bindings-uffi`(UniFFI)对真实核心编译;Swift+Kotlin 绑定已生成;核心交叉编到 `aarch64-apple-ios`。最终 `.a`/`.so` 需 full Xcode SDK / Android NDK(本机未装) |
| 8 | **插件宿主自身是可移植端口**(不可信工具 WASM 沙箱,宿主跑全平台含浏览器) | ✅ 通过 | `adapters-wasmi` 经 `ToolHost` 端口跑通沙箱 `.wat` 工具(测试绿),且**同样编到 `wasm32`** —— 同一宿主 native + wasm-in-wasm 双目标。Wasmtime 后续可在同端口后换入提速 |

## 2. 实测指标(interim · 数量级口径)

> 当前为 stub LLM + 8 维 hash-embedding 的最小切片,数值用于"数量级"判断,非最终性能承诺。

| 指标 | 阈值 | 实测 | 结论 |
|---|---|---|---|
| WASM 体积(gzip) | ≤ 2.5 MB | **~49 KB**(raw 95 KB) | ✅ 远优于阈值(切片) |
| 原生 server 二进制 | — | **640 KB**(release,opt=z+lto+strip) | ✅ 对比 Python 运行时(数十–数百 MB)极小 |
| 单步 ingest 延迟 | ≤ 50 ms | **~0.49 ms**(含 localhost HTTP,剔 LLM) | ✅ 远优于阈值 |
| 单步 search 延迟 | — | **~0.51 ms**(同上) | ✅ |
| async 跨 runtime | 原生、不阻塞 | 核心仅 `async-trait`+`futures`,**零 tokio**,`block_on` 即可在 WASM/FFI 跑通 | ✅ 风险 #1 证伪 |
| 每端口平台胶水 | 低且可复制 | server/wasm/sqlite/uffi 各 adapter ≈ 一个文件;核心跨目标**零改动** | ✅ |
| iOS lib / Android .so 体积 | ≤ 8 MB/arch | 未测 — 需 full Xcode SDK / NDK | ⏳ 环境阻塞 |
| 端上向量检索(N=10k) | P50 ≤ 20 ms | 未测 — 待接 sqlite-vec | ⏳ 待办 |
| 移动端冷启动首调 | ≤ 300 ms | 未测 — 需设备/模拟器 | ⏳ 待办 |

## 3. 工具链备注(复现实验所需)

- `rustc`/`cargo` **1.96**:Homebrew(仅 host)+ rustup(加 `wasm32-unknown-unknown`、`aarch64-apple-ios`、`aarch64-apple-ios-sim`)。跨目标须用 `~/.cargo/bin`。
- `wasm-pack` 0.15、`wasm-bindgen` 0.2。
- `uniffi` 0.28(proc-macro 模式 `setup_scaffolding!`,library-mode bindgen)。
- `rusqlite` 0.32(`bundled`)需 C 编译器;iOS 设备构建另需 **full Xcode iOS SDK**。
- `wasmi` 1.1 + `wat` 1(插件宿主 PoC,纯 Rust)。
- **wasm-opt bulk-memory 坑**:`bindings-wasm/Cargo.toml` 加 `[package.metadata.wasm-pack.profile.release] wasm-opt=['-Oz','--enable-bulk-memory','--enable-nontrapping-float-to-int']`。

## 4. 总评

make-or-break 风险(**运行时无关核心 → 一份代码,server + 浏览器 + 设备**)已**确认**,有跨 server / 浏览器-WASM / 嵌入式 DB / 原生移动绑定的可运行、可测试产物。**可扩展性轴**亦确认:不可信工具经 `ToolHost` 端口沙箱化,其 WASM 宿主编到每个目标(含浏览器核心)。无任何观察与"Rust 作可移植核心语言"的建议相悖。

剩余为**广度**(SDK/NDK 后的设备产物、Tauri 桌面、Wasmtime 宿主 + WIT 契约)与**量化指标**,非根本性未知。详见 [05-roadmap](05-roadmap.md)。
