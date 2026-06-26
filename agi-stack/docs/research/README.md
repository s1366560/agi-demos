# 调研沉淀 · research/

本目录是 [06-agent-core-design](../architecture/06-agent-core-design.md)、[07-plugin-runtime-architecture](../architecture/07-plugin-runtime-architecture.md) 与 [08-control-data-plane-separation](../architecture/08-control-data-plane-separation.md) 的**证据基**。各篇笔记是对开源系统**内部设计**的源码级调研提炼,目的不是集成这些系统,而是**学习其机制**并映射到 Rust AI Agent 核心。前三篇服务四个质量目标(**健壮 · 可扩展 · 热插拔 · 可编排**),第四篇服务多层插件运行时(**能力注册 · 插件形态 · 可插拔 Harness · 热插拔生命周期**),第五篇服务控制流/数据流分离(**控制面=SSOT · 声明式 reconcile · xDS 风格分发 · local-first 断连自治**)。

| 笔记 | 调研对象 | 贡献 |
|---|---|---|
| [gateways-internals.md](gateways-internals.md) | Apache ShenYu · Kong · Higress + Envoy(proxy-wasm) | **热插拔 · 可扩展** |
| [flink-internals.md](flink-internals.md) | Apache Flink | **健壮** |
| [argo-internals.md](argo-internals.md) | Argo Workflows | **可编排 · 健壮** |
| [openclaw-runtime-internals.md](openclaw-runtime-internals.md) | OpenClaw(`openclaw/openclaw`,380K★ 多端 Agent 运行时) | **多层插件运行时 · 可插拔 Harness · 热插拔生命周期** |
| [istio-k8s-control-data-plane.md](istio-k8s-control-data-plane.md) | Kubernetes · Istio + Envoy/ztunnel(xDS) | **控制面/数据面分离 · 声明式 reconcile · 版本化分发** |

## 约定

- 引用格式 `owner/repo:path[:line]`,指向上游开源仓库,便于回溯。
- 每篇含:架构概览 → 核心机制(带源码引用)→ **机制 → AI Agent / Rust 映射表** → 关键引用汇总。
- 综合设计与取舍结论见 [06-agent-core-design](../architecture/06-agent-core-design.md) 与 [07-plugin-runtime-architecture](../architecture/07-plugin-runtime-architecture.md);本目录仅存"机制本身"。
- 调研在源码抓取时点完成;上游可能演进,引用行号为当时近似。
