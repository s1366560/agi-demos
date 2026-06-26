# 05 · 落地路径与风险

## 1. 绞杀者式增量迁移(语言无关)

**严禁大爆炸重写。** 新旧后端迁移期并行,逐能力绞杀替换。

```mermaid
graph LR
    P0[Phase 0<br/>决策 Spike + 架构文档] --> P1[Phase 1<br/>抽取可移植核心]
    P1 --> P2[Phase 2<br/>平台适配器]
    P2 --> P25[Phase 2.5<br/>扩展性/插件宿主]
    P25 --> P3[Phase 3<br/>AI/LLM 抽象]
    P3 --> P4[Phase 4<br/>同步层 local-first]
    P4 --> P5[Phase 5<br/>逐平台上线]
```

| Phase | 内容 | 状态 |
|---|---|---|
| **0 · 决策 Spike** | 最小核心切片编到 `服务器 + WASM + 移动端`,量化体积/性能/DX 后定语言 | ✅ 完成(Rust 选定,见 [04](04-spike-evidence.md)) |
| **1 · 抽取可移植核心** | domain(已纯净)+ application 纯逻辑迁入核心包;ports 落为跨平台 trait | 🚧 进行中(生产级 Cargo workspace 已落地于 `agi-stack/`:`core`+`plugin-host`+`adapters-mem`+`adapters-device`+`apps/server`,`cargo test` 25 绿、服务器全端点 curl 验证) |
| **2 · 平台适配器** | 每个端口两套实现(server 重型栈 / device 嵌入式栈) | 🎯 |
| **2.5 · 扩展性/插件宿主** | 落 `ToolHost`/`PluginRuntime` 端口 + WIT 工具契约;内置工具走 `dyn Trait`;第三方/MCP 走 WASM 沙箱;Skill 落为数据 + Rhai;**热插拔生命周期**(ArcSwap 原子换表 + CP/DP 配置推送 + proxy-wasm 风格 ABI,见 [06 §2](06-agent-core-design.md));**多层插件运行时**(typed 能力注册 + 插件形态分类 + 可插拔 Harness,见 [07](07-plugin-runtime-architecture.md));**控制面→数据面 reconcile**(xDS 风格 version/nonce + ACK/NACK + last-good,见 [08](08-control-data-plane-separation.md))。**绞杀点:现有 30+ 工具与 MCP 沙箱在此分批迁移到统一插件契约** | 🎯(热插拔 + CP/DP reconcile PoC 已验证,见 [02](02-extensibility.md)、[04 #9/#10](04-spike-evidence.md)) |
| **3 · AI/LLM 抽象** | LLM、embedding、向量检索的 cloud↔on-device 双适配 | 🎯 |
| **4 · 同步层** | local-first 同步、冲突解决、离线优先;**= 数据面断连自治**(最终一致 + 重连全量重同步,衔接 [08 §7](08-control-data-plane-separation.md) CP/DP 分离) | 🎯 |
| **5 · 逐平台上线** | 先服务器对齐现有功能(绞杀替换旧 Python),再 PC → 移动端 → web-WASM | 🎯 |

> **核心引擎质量(健壮 · 可编排)横跨多阶段**:会话 checkpoint/崩溃恢复(健壮)落在 Phase 1 核心 + 服务器/端上 runner;Plan append-only DAG 编排、HITL suspend/resume、retry/memoization(可编排)落在核心编排层。机制来源与综合设计见 [06-agent-core-design](06-agent-core-design.md),决策见 [ADR-0004](../adr/0004-plan-as-append-only-dag.md)/[0005](../adr/0005-round-boundary-checkpoint.md)/[0006](../adr/0006-hot-plug-via-arcswap-and-proxy-wasm-abi.md)。
>
> **控制流/数据流分离(第三系统轴)亦横跨多阶段**:配置 reconcile 协议(控制面=SSOT、数据面 level-triggered 收敛)落在 Phase 2.5;数据面断连自治(最终一致 + 重连重同步)落在 Phase 4 同步层。综合设计见 [08-control-data-plane-separation](08-control-data-plane-separation.md),决策见 [ADR-0009](../adr/0009-control-data-plane-separation.md)/[0010](../adr/0010-xds-style-config-distribution.md)。

## 2. 必须证伪的高风险项(按优先级)

| # | 风险 | 状态 |
|---|---|---|
| 1 | **运行时无关 async**:core 不绑 tokio 却能在 native/WASM/UniFFI 三处都跑 | ✅ 证伪通过 |
| 2 | **WASM + 本地存储/向量**:wa-sqlite/sqlite-vec 是否可用?否则降级 IndexedDB + 内存 hnsw | ⏳ 部分(内存路径已通,wa-sqlite 待接) |
| 3 | **端上向量检索**:sqlite-vec / usearch / hnsw-rs 在 iOS/Android 交叉编译 | ⏳ 待办 |
| 4 | **UniFFI 复杂类型 + async + 回调**:`Memory`(嵌套 list)能否干净导出?宿主端口能否回注? | ✅ 双端设备产物(`crates/bindings-uniffi`:Android 经 NDK 产真实 `aarch64-linux-android` `.so` + Kotlin 包,见 [04 #12](04-spike-evidence.md);iOS 经 full Xcode 产 XCFramework + Swift 包并在 iPhone 17 模拟器实跑,见 [04 #13](04-spike-evidence.md)) |
| 5 | **图依赖**:端上无 Neo4j,entities/relationships 用 SQLite 关系表或内存 petgraph 近似 | 🎯 待验证 |
| 6 | **端上 LLM**(可选):llama.cpp/Candle 移动端体积与可行性 | 🎯 后续 |
| 7 | **可移植插件宿主**:核心能否在不破坏"运行时无关+四端可移植"前提下宿主沙箱工具?WASM-in-WASM(浏览器,Wasmi)成立? | ✅ 证伪通过(见 [04 #8](04-spike-evidence.md)) |
| 8 | **会话 checkpoint 崩溃恢复**:轮次边界快照能否在不重复已完成工具的前提下恢复长会话?端上(无 tokio,WASM 无 FS)增量持久化是否成立? | ✅ 证伪通过(`ReActEngine` 轮次边界增量 + 边界 checkpoint;`adapters-mem/tests/agent_recovery.rs` 证内存路径杀进程→恢复**不重调已完成工具**[`CountingToolHost` 计数为 0],`adapters-device/tests/device.rs` 证 SQLite 耐久路径恢复;见 [04 #11](04-spike-evidence.md)、[06 §4](06-agent-core-design.md)、[ADR-0005](../adr/0005-round-boundary-checkpoint.md)) |
| 9 | **热换工具零中断**:ArcSwap 换表 + CP/DP 推送能否在不打断在途会话的前提下启用/禁用/升级工具? | ✅ 部分证伪(换表机制已通,CP/DP 网络下发待办)——`hotplug-demo` 证 v1→v2 热换 + 飞行轮次见旧版本 + enable/disable + shape 分类(见 [04 #9](04-spike-evidence.md)、[07](07-plugin-runtime-architecture.md)、[ADR-0006](../adr/0006-hot-plug-via-arcswap-and-proxy-wasm-abi.md)/[0007](../adr/0007-capability-registration-plugin-model.md)) |
| 11 | **可插拔 Harness**:Agent 执行循环能否做成可第三方替换的 `RuntimeHarness`(embedded vs CLI-backend),`auto` 选择 + 回退,且 runtime 按 `(provider,model)` scoped? | 🎯 待验证([07 §4](07-plugin-runtime-architecture.md)、[ADR-0008](../adr/0008-agent-runtime-as-pluggable-harness.md)) |
| 10 | **Plan 动态 DAG + HITL**:append-only DAG 的 reconcile 幂等、suspend/resume(四类 HITL)在重型(Kameo)与轻量(`MiniOrchestrator`)两版是否一致? | 🎯 待验证([06 §5](06-agent-core-design.md)、[ADR-0004](../adr/0004-plan-as-append-only-dag.md)) |
| 12 | **控制流/数据流分离**:控制面发期望态(SSOT)、数据面 level-triggered 自算 diff 收敛;坏配置 NACK 保留 last-good 不致瘫;同版本幂等、陈旧拒绝;断连重连全量重同步 —— 纯同步 reconciler 端上(无 tokio)是否成立? | ✅ 证伪通过(`cp-dp-demo` + `control_data_plane` 6 测试;见 [04 #10](04-spike-evidence.md)、[08](08-control-data-plane-separation.md)、[ADR-0009](../adr/0009-control-data-plane-separation.md)/[0010](../adr/0010-xds-style-config-distribution.md)) |

## 3. 量化指标与 go/no-go 阈值(示例,需团队定档)

| 指标 | 采集方式 | 建议 go 阈值 | 当前 |
|---|---|---|---|
| WASM 体积(gzip) | `wasm-opt -Oz` 后测 | ≤ 2.5 MB(切片) | ✅ ~49 KB |
| iOS lib / Android .so | 链接产物 | ≤ 8 MB/arch(不含本地模型) | ✅ Android 1.5 MB(aarch64 release,见 [04 #12](04-spike-evidence.md));iOS XCFramework 已构建 + 模拟器实跑,链接后体积待 app 实测(见 [04 #13](04-spike-evidence.md)) |
| 单步提取延迟(剔 LLM 网络) | 核心打点 | ≤ 50 ms | ✅ ~0.49 ms |
| 端上向量检索(N=10k, dim=768) | sqlite-vec/hnsw 计时 | P50 ≤ 20 ms | ⏳ 未测 |
| 移动端冷启动首调 | app 内打点 | ≤ 300 ms | ⏳ iPhone 17 模拟器已跑通,精确计时待 app 内打点 |
| 跨 FFI 复杂类型往返 | 微基准 | 无频繁拷贝瓶颈 | ⏳ 未测 |
| 每端口平台胶水 LOC | 统计 | 低且可复制 | ✅ ≈ 一个文件 |
| async 跨 UniFFI/WASM | 是否需 hack | 原生支持、不阻塞主线程 | ✅ 原生支持 |
| 会话崩溃恢复正确性 | 杀进程→恢复→比对 | 不丢轮次、不重复已完成工具 | ✅ 通过(内存 + SQLite 两路径,见 [04 #11](04-spike-evidence.md)) |
| 热换工具中断 | 在途会话期间换表计时 | 在途轮次零中断,新轮次毫秒级见新表 | ✅ 部分(demo 证飞行隔离:新调用得 v2、持旧快照仍得 v1;在途轮次中断的会话级量化待 Agent 切片) |
| HITL 暂停→恢复往返 | suspend→外部信号→resume | 四类 HITL 均可暂停/恢复,状态不丢 | ⏳ 未测 |
| CP→DP 配置收敛/坏配置隔离 | reconcile 测试 + `cp-dp-demo` | 坏配置 NACK 不改 last-good;同版本零 churn(`Arc::ptr_eq`);漏推/乱序自愈 | ✅ 证伪通过(6 测试) |

## 4. 近期待办(Spike 收尾 → Phase 1)

1. **Wasmtime 宿主 + WIT 契约**:为服务器/桌面加 Wasmtime 后端 `ToolHost`(fuel/epoch 配额),工具 ABI 升级为 WIT / Component Model(`wit-bindgen`/`cargo-component`),替代 PoC 的裸 `.wat`。
2. **移动端设备产物**:**双端均已产出** —— Android 经 NDK r30 交叉编译 `aarch64-linux-android`,release **1.5 MB**(stripped,含 SQLite C),`file` 验 ELF ARM aarch64 + Kotlin 包(见 [04 #12](04-spike-evidence.md));iOS 经 full Xcode 交叉编译 `aarch64-apple-ios`(+ `-sim`)、组装 **XCFramework** + Swift 包,并在 **iPhone 17 模拟器实跑**冒烟(摄取/关键词/语义检索全绿,见 [04 #13](04-spike-evidence.md),一键 `scripts/build-ios.sh`);后续接 **真机签名分发** + `cargo-ndk`/CI 固化构建,并补端上向量检索与冷启动量化。
3. **`sqlite-vec` 真向量检索**:替换切片里的玩具 hash-embedding。
4. **Tauri 桌面**:包核心证 PC 外壳。
5. **完整 go/no-go 评分卡**:补齐 §3 未测项。
6. **Agent 核心健壮/编排切片**:在现有 Spike 上加一个最小 ReAct 会话 —— 轮次边界 checkpoint(`AtomicU64` 版本 + 增量写)、崩溃恢复重放、单个 HITL suspend/resume。验证 [06](06-agent-core-design.md) 的健壮/可编排两质量在 native + WASM 两版一致([ADR-0004](../adr/0004-plan-as-append-only-dag.md)/[0005](../adr/0005-round-boundary-checkpoint.md))。**注**:热插拔(ArcSwap 工具换表零中断 + 扩展 enable/disable + shape 分类)已由 `crates/plugin-host` + `hotplug-demo` 单独证伪(见 [04 #9](04-spike-evidence.md)),此切片只需把它接入 ReAct 轮次边界。
7. **可插拔 Harness 切片**:把内置 ReAct 循环抽为 `RuntimeHarness` trait + `HarnessRegistry::select`(`auto` 优先级 + 回退),为后续 CLI-backend/第三方 harness 固化 `PreparedAttempt`/`RuntimePlan` 契约([07 §4](07-plugin-runtime-architecture.md)、[ADR-0008](../adr/0008-agent-runtime-as-pluggable-harness.md))。

## 5. 退出准则

- 全部高风险项有明确结论(通过/变通/阻断)。
- 指标对照 §3 阈值,产出 go/no-go 建议。
- 若 no-go → 退回 Kotlin Multiplatform 同款 Spike,复用本切片与指标表对照。

## 6. 成本现实

~86K LOC 纯核心 + ~321K 基础设施重做,多人季度级工程。**必须绞杀者式增量迁移**(§1),迁移期新旧后端并行,任何阶段都保持可上线。
