# 架构文档

`agi-stack` 新架构的权威设计文档。按从「为什么」到「怎么落地」的顺序阅读。

## 阅读顺序

1. **[00-overview.md](00-overview.md)** —— 问题与目标、现状评估、语言选型对比与推荐结论。先读这篇建立全局。
2. **[01-portable-core.md](01-portable-core.md)** —— 架构主脊:运行时无关核心、六边形端口、能力分层(什么上端、什么留服务器)。
3. **[02-extensibility.md](02-extensibility.md)** —— 第二条主轴:信任 × 平台两轴插件模型、`ToolHost` 端口、MCP 分层沙箱、Skill=数据+Rhai、L4 Actor 监督。
4. **[03-platform-adapters.md](03-platform-adapters.md)** —— 端口的按平台实现矩阵:存储、LLM/embedding、向量检索、插件宿主运行时。
5. **[04-spike-evidence.md](04-spike-evidence.md)** —— 决策 Spike 已验证的结论与实测指标(证据,非空想)。
6. **[05-roadmap.md](05-roadmap.md)** —— 绞杀者式增量迁移路径、风险清单、go/no-go 评分卡。
7. **[06-agent-core-design.md](06-agent-core-design.md)** —— 第三条主轴:健壮 · 可扩展 · 热插拔 · 可编排的 Agent 核心(学习网关/Flink/Argo 内部设计后的综合)。
8. **[07-plugin-runtime-architecture.md](07-plugin-runtime-architecture.md)** —— 多层插件运行时:能力注册模型、插件形态分类、可插拔 Harness(embedded vs CLI-backend)、热插拔生命周期状态机(学习 OpenClaw 多端运行时后的综合)。

## 调研沉淀(证据基)

[06](06-agent-core-design.md) 的源码级证据沉淀于 [`../research/`](../research/README.md):网关([gateways-internals](../research/gateways-internals.md))、Flink([flink-internals](../research/flink-internals.md))、Argo([argo-internals](../research/argo-internals.md)),各含机制详解 + 映射表 + 引用汇总。[07](07-plugin-runtime-architecture.md) 的证据沉淀于 [openclaw-runtime-internals](../research/openclaw-runtime-internals.md)(运行时分层 / 能力注册 / 热插拔生命周期三节)。

## 决策记录(ADR)

关键且不易逆转的决策单独沉淀为 ADR,见 [`../adr/`](../adr/):

| ADR | 决策 |
|---|---|
| [0001](../adr/0001-rust-as-portable-core-language.md) | 选 Rust 作为可移植核心语言 |
| [0002](../adr/0002-untrusted-plugins-wasm-only.md) | 不可信插件**只走 WASM**,绝不进 cdylib |
| [0003](../adr/0003-plugin-host-as-hexagonal-port.md) | 把插件宿主抽象为六边形端口 `ToolHost` |
| [0004](../adr/0004-plan-as-append-only-dag.md) | Plan 编排选 append-only DAG |
| [0005](../adr/0005-round-boundary-checkpoint.md) | 以轮次边界 checkpoint 为健壮性原语 |
| [0006](../adr/0006-hot-plug-via-arcswap-and-proxy-wasm-abi.md) | 热插拔 = ArcSwap 换表 + proxy-wasm ABI + CP/DP |
| [0007](../adr/0007-capability-registration-plugin-model.md) | 能力注册模型 + 插件形态分类(优先于 ad-hoc hooks) |
| [0008](../adr/0008-agent-runtime-as-pluggable-harness.md) | Agent Runtime 即可插拔 Harness(embedded vs CLI-backend) |

## 文档约定

- 正文中文;代码标识符、命令、crate 名用英文原文。
- `✅` 已验证(有 Spike 证据)、`⏳` 待办/环境阻塞、`🎯` 设计目标(未实现)。
- 涉及实测数字均注明"切片/数量级"口径,避免被当作最终性能承诺。
