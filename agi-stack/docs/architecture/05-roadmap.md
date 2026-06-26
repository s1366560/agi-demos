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
| **1 · 抽取可移植核心** | domain(已纯净)+ application 纯逻辑迁入核心包;ports 落为跨平台 trait | ⏭️ 下一步 |
| **2 · 平台适配器** | 每个端口两套实现(server 重型栈 / device 嵌入式栈) | 🎯 |
| **2.5 · 扩展性/插件宿主** | 落 `ToolHost`/`PluginRuntime` 端口 + WIT 工具契约;内置工具走 `dyn Trait`;第三方/MCP 走 WASM 沙箱;Skill 落为数据 + Rhai;**热插拔生命周期**(ArcSwap 原子换表 + CP/DP 配置推送 + proxy-wasm 风格 ABI,见 [06 §2](06-agent-core-design.md))。**绞杀点:现有 30+ 工具与 MCP 沙箱在此分批迁移到统一插件契约** | 🎯(PoC 已验证,见 [02](02-extensibility.md)) |
| **3 · AI/LLM 抽象** | LLM、embedding、向量检索的 cloud↔on-device 双适配 | 🎯 |
| **4 · 同步层** | local-first 同步、冲突解决、离线优先 | 🎯 |
| **5 · 逐平台上线** | 先服务器对齐现有功能(绞杀替换旧 Python),再 PC → 移动端 → web-WASM | 🎯 |

> **核心引擎质量(健壮 · 可编排)横跨多阶段**:会话 checkpoint/崩溃恢复(健壮)落在 Phase 1 核心 + 服务器/端上 runner;Plan append-only DAG 编排、HITL suspend/resume、retry/memoization(可编排)落在核心编排层。机制来源与综合设计见 [06-agent-core-design](06-agent-core-design.md),决策见 [ADR-0004](../adr/0004-plan-as-append-only-dag.md)/[0005](../adr/0005-round-boundary-checkpoint.md)/[0006](../adr/0006-hot-plug-via-arcswap-and-proxy-wasm-abi.md)。

## 2. 必须证伪的高风险项(按优先级)

| # | 风险 | 状态 |
|---|---|---|
| 1 | **运行时无关 async**:core 不绑 tokio 却能在 native/WASM/UniFFI 三处都跑 | ✅ 证伪通过 |
| 2 | **WASM + 本地存储/向量**:wa-sqlite/sqlite-vec 是否可用?否则降级 IndexedDB + 内存 hnsw | ⏳ 部分(内存路径已通,wa-sqlite 待接) |
| 3 | **端上向量检索**:sqlite-vec / usearch / hnsw-rs 在 iOS/Android 交叉编译 | ⏳ 待办 |
| 4 | **UniFFI 复杂类型 + async + 回调**:`Memory`(嵌套 list)能否干净导出?宿主端口能否回注? | ✅ codegen 验证 / ⏳ 设备运行待 SDK |
| 5 | **图依赖**:端上无 Neo4j,entities/relationships 用 SQLite 关系表或内存 petgraph 近似 | 🎯 待验证 |
| 6 | **端上 LLM**(可选):llama.cpp/Candle 移动端体积与可行性 | 🎯 后续 |
| 7 | **可移植插件宿主**:核心能否在不破坏"运行时无关+四端可移植"前提下宿主沙箱工具?WASM-in-WASM(浏览器,Wasmi)成立? | ✅ 证伪通过(见 [04 #8](04-spike-evidence.md)) |
| 8 | **会话 checkpoint 崩溃恢复**:轮次边界快照能否在不重复已完成工具的前提下恢复长会话?端上(无 tokio,WASM 无 FS)增量持久化是否成立? | 🎯 待验证([06 §4](06-agent-core-design.md)、[ADR-0005](../adr/0005-round-boundary-checkpoint.md)) |
| 9 | **热换工具零中断**:ArcSwap 换表 + CP/DP 推送能否在不打断在途会话的前提下启用/禁用/升级工具? | 🎯 待验证([06 §2](06-agent-core-design.md)、[ADR-0006](../adr/0006-hot-plug-via-arcswap-and-proxy-wasm-abi.md)) |
| 10 | **Plan 动态 DAG + HITL**:append-only DAG 的 reconcile 幂等、suspend/resume(四类 HITL)在重型(Kameo)与轻量(`MiniOrchestrator`)两版是否一致? | 🎯 待验证([06 §5](06-agent-core-design.md)、[ADR-0004](../adr/0004-plan-as-append-only-dag.md)) |

## 3. 量化指标与 go/no-go 阈值(示例,需团队定档)

| 指标 | 采集方式 | 建议 go 阈值 | 当前 |
|---|---|---|---|
| WASM 体积(gzip) | `wasm-opt -Oz` 后测 | ≤ 2.5 MB(切片) | ✅ ~49 KB |
| iOS lib / Android .so | 链接产物 | ≤ 8 MB/arch(不含本地模型) | ⏳ 未测 |
| 单步提取延迟(剔 LLM 网络) | 核心打点 | ≤ 50 ms | ✅ ~0.49 ms |
| 端上向量检索(N=10k, dim=768) | sqlite-vec/hnsw 计时 | P50 ≤ 20 ms | ⏳ 未测 |
| 移动端冷启动首调 | app 内打点 | ≤ 300 ms | ⏳ 未测 |
| 跨 FFI 复杂类型往返 | 微基准 | 无频繁拷贝瓶颈 | ⏳ 未测 |
| 每端口平台胶水 LOC | 统计 | 低且可复制 | ✅ ≈ 一个文件 |
| async 跨 UniFFI/WASM | 是否需 hack | 原生支持、不阻塞主线程 | ✅ 原生支持 |
| 会话崩溃恢复正确性 | 杀进程→恢复→比对 | 不丢轮次、不重复已完成工具 | ⏳ 未测 |
| 热换工具中断 | 在途会话期间换表计时 | 在途轮次零中断,新轮次毫秒级见新表 | ⏳ 未测 |
| HITL 暂停→恢复往返 | suspend→外部信号→resume | 四类 HITL 均可暂停/恢复,状态不丢 | ⏳ 未测 |

## 4. 近期待办(Spike 收尾 → Phase 1)

1. **Wasmtime 宿主 + WIT 契约**:为服务器/桌面加 Wasmtime 后端 `ToolHost`(fuel/epoch 配额),工具 ABI 升级为 WIT / Component Model(`wit-bindgen`/`cargo-component`),替代 PoC 的裸 `.wat`。
2. **移动端设备产物**:装 full Xcode(iOS SDK)+ Android NDK,产出 `.a`/`.so`,模拟器/真机跑通。
3. **`sqlite-vec` 真向量检索**:替换切片里的玩具 hash-embedding。
4. **Tauri 桌面**:包核心证 PC 外壳。
5. **完整 go/no-go 评分卡**:补齐 §3 未测项。
6. **Agent 核心健壮/编排切片**:在现有 Spike 上加一个最小 ReAct 会话 —— 轮次边界 checkpoint(`AtomicU64` 版本 + 增量写)、崩溃恢复重放、ArcSwap 工具换表零中断、单个 HITL suspend/resume。验证 [06](06-agent-core-design.md) 的健壮/可编排/热插拔三质量在 native + WASM 两版一致([ADR-0004](../adr/0004-plan-as-append-only-dag.md)/[0005](../adr/0005-round-boundary-checkpoint.md)/[0006](../adr/0006-hot-plug-via-arcswap-and-proxy-wasm-abi.md))。

## 5. 退出准则

- 全部高风险项有明确结论(通过/变通/阻断)。
- 指标对照 §3 阈值,产出 go/no-go 建议。
- 若 no-go → 退回 Kotlin Multiplatform 同款 Spike,复用本切片与指标表对照。

## 6. 成本现实

~86K LOC 纯核心 + ~321K 基础设施重做,多人季度级工程。**必须绞杀者式增量迁移**(§1),迁移期新旧后端并行,任何阶段都保持可上线。
