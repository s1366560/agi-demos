# ADR-0001 · 选 Rust 作为可移植核心语言

- 状态:**已接受**(决策 Spike 证伪通过)
- 日期:2026-06
- 关联:[00-overview §4](../architecture/00-overview.md)、[04-spike-evidence](../architecture/04-spike-evidence.md)

## 背景

MemStack 后端需完全重写,使**同一份核心逻辑**同时跑云端服务器与端侧(浏览器 WASM / PC / 移动端),本地优先、可离线,并能以**原生包**被各平台宿主复用。候选:Rust、Kotlin Multiplatform、C#/.NET、Dart/Flutter、TS 全栈。

## 决策

选 **Rust 核心 + 平台外壳**。

理由:

1. **唯一**能让单一核心同时编为:服务器原生二进制、浏览器 WASM、桌面原生、iOS/Android **原生静态库**(UniFFI 自动生成 Swift/Kotlin)。
2. 端上 AI/向量生态最强(Candle / llama.cpp / ort / sqlite-vec)—— 离线推理的硬需求。
3. 体积/性能/无 GC,利于嵌入(Spike 实测:640 KB server 二进制、~49 KB gzip wasm)。
4. **副产物**:WASM 沙箱同时是不可信插件的隔离机制(见 [ADR-0002](0002-untrusted-plugins-wasm-only.md)),一套技术栈解决可移植 + 可扩展两条轴。

替补:**Kotlin Multiplatform**(若更看重迁移速度/团队上手且想统一 UI)。退出准则触发时回退到 KMP 同款 Spike 对照。

## 后果

- ➕ 一份核心覆盖四端;最小体积与最佳离线能力;插件沙箱天然。
- ➖ 学习曲线最陡(所有权/借用);~86K LOC 核心重写 + 团队适应期。
- ⚠️ 须严守"核心运行时无关"纪律(见 [01-portable-core](../architecture/01-portable-core.md)),否则丧失可移植性。
