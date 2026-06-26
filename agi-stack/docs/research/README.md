# 调研沉淀 · research/

本目录是 [06-agent-core-design](../architecture/06-agent-core-design.md) 的**证据基**。三篇笔记是对网关 / Flink / Argo **内部设计**的源码级调研提炼,目的不是集成这些系统,而是**学习其机制**并映射到 Rust AI Agent 核心的四个质量目标:**健壮 · 可扩展 · 热插拔 · 可编排**。

| 笔记 | 调研对象 | 贡献的质量目标 |
|---|---|---|
| [gateways-internals.md](gateways-internals.md) | Apache ShenYu · Kong · Higress + Envoy(proxy-wasm) | **热插拔 · 可扩展** |
| [flink-internals.md](flink-internals.md) | Apache Flink | **健壮** |
| [argo-internals.md](argo-internals.md) | Argo Workflows | **可编排 · 健壮** |

## 约定

- 引用格式 `owner/repo:path[:line]`,指向上游开源仓库,便于回溯。
- 每篇含:架构概览 → 核心机制(带源码引用)→ **机制 → AI Agent 映射表** → 关键引用汇总。
- 综合设计与取舍结论见 [06-agent-core-design](../architecture/06-agent-core-design.md);本目录仅存"机制本身"。
- 调研在源码抓取时点完成;上游可能演进,引用行号为当时近似。
