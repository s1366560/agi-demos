# 00 · 总览:问题、现状与选型

## 1. 问题与目标(已与用户确认)

将后端用其它语言**完全重写**,使**同一份核心逻辑**编译/打包后:

- 既能跑在**云端服务器**,
- 又能以**包(native library / WASM)**方式内嵌进 **web(WASM)/ PC / 移动端**,
- 在端上**本地运行、可离线(local-first)**。

即:**`可移植核心 + 按平台替换的适配器`**,而不是"把整个后端搬到手机上"。

附加目标(整合插件化调研后明确):MemStack 本质是**智能体平台**,工具/技能/子智能体/MCP 都是扩展点,因此架构必须**同时**解决"可移植"与"可扩展",见 [02-extensibility](02-extensibility.md)。

## 2. 现状评估(本仓库实测)

| 层 | 规模 | 可移植性 |
|---|---|---|
| domain | ~40.7K LOC / 357 文件 | **几乎纯净**:零 sqlalchemy/ray/neo4j/redis/litellm 导入,仅 3 文件碰 pydantic → 可干净抽取为核心 |
| application | ~45.5K LOC / 158 文件 | 多为编排逻辑(use_cases/services),大部分可移植 |
| infrastructure | ~321K LOC / 865 文件 | **服务器侧为主**:FastAPI、SQLAlchemy/Postgres、Neo4j、Redis、Ray Actor、Docker sandbox、LiteLLM → 需按平台重写/替换 |
| configuration | ~3.9K LOC | DI 容器 + 配置 |
| 前端 web | ~327K LOC (TS/TSX) | 现为 React/Vite |

**关键结论:**

- **架构本就是 DDD + 六边形**,`domain/ports` 已定义好接口边界 → 天然契合"核心包 + 平台适配器"。
- 真正的"可移植核心" = domain(~40K)+ application 纯逻辑(~45K)≈ **86K LOC**;其余 321K 基础设施是平台相关的、本就要分平台实现。
- **不是所有东西都能上端**:Ray 分布式、Neo4j、多租户 Postgres、Docker sandbox 天然服务器侧;端上用嵌入式替代(SQLite/libsql + sqlite-vec + 本地 KV)。

## 3. 候选语言/框架对比

| 维度 | **Rust** | **Kotlin Multiplatform** | C#/.NET | Dart/Flutter | TS 全栈 |
|---|---|---|---|---|---|
| 服务器 | 优 (axum/tokio) | 优 (Ktor/JVM) | 优 (ASP.NET) | 中 (Serverpod) | 优 (Node) |
| Web(WASM) | 优 (wasm-bindgen,体积小) | 良(Wasm/JS,渐成熟) | 良 (Blazor,体积大) | 良 (Flutter Web) | 优 (原生 JS) |
| PC 桌面 | 优 (Tauri / 原生) | 良 (Compose Desktop) | 优 (MAUI/WPF) | 优 (Flutter Desktop) | 良 (Tauri/Electron) |
| 移动端 | 优 (UniFFI→Swift/Kotlin) | 优 (原生 iOS/Android) | 良 (MAUI) | 优 (Flutter) | 中 (RN,需 JS 引擎) |
| **作为"包"被原生宿主复用** | **优** (C-ABI/UniFFI/WASM) | **优** (KMP 库) | 良 (NuGet,嵌入原生/RN 弱) | 弱 (难作纯库嵌入) | 弱 (需打包 JS 运行时) |
| 与现有 async/OO 贴近度 | 中(所有权/借用学习成本高) | **优** (协程≈asyncio) | 优 | 良 | 优 |
| 端上 AI/向量 生态 | **优** (Candle/llama.cpp/ort/sqlite-vec) | 中 (经 C 互操作) | 良 (ONNX/ML.NET) | 弱 | 中 (transformers.js/wasm) |
| 性能 / 体积 / 离线 | **优** | 良 | 良 | 良 | 中 |
| 可顺便统一 UI | 否(核心专用,UI 另选) | 可 (Compose MP) | 可 (MAUI/Blazor) | **强**(本就是 UI 框架) | 可 (RN+Web) |
| 从 Python 迁移学习曲线 | 陡 | 平缓 | 平缓 | 中 | 最平缓 |

## 4. 推荐结论

### 首选:Rust 核心 + 平台外壳

**契合"高性能 + 真离线 + 可作原生包嵌入四端"的硬目标。**

- 唯一能让单一核心同时编译为:服务器原生二进制、浏览器 WASM、桌面原生、以及 iOS/Android **原生静态库**(经 UniFFI 自动生成 Swift/Kotlin 绑定)。
- 端上 AI 生态最强:Candle / llama.cpp / ONNX Runtime(ort)做本地推理,sqlite-vec / libsql 做本地向量+关系存储。
- 外壳:PC 用 Tauri,移动端用 UniFFI 绑定 + 原生 UI,Web 用 wasm-bindgen。
- **额外收获**:同一套机制天然支撑插件沙箱(WASM),见 [02-extensibility](02-extensibility.md)。
- 代价:学习曲线最陡;86K LOC 核心重写 + 团队所有权模型适应期。

> 决策记录见 [ADR-0001](../adr/0001-rust-as-portable-core-language.md)。

### 强力替补:Kotlin Multiplatform (+ Compose Multiplatform)

- 为"跨平台共享业务逻辑包"而生:`expect/actual` 几乎 1:1 对应现有六边形 ports。
- 协程语义 ≈ 现有 asyncio,从 Python 迁移心智负担最小;移动端是原生一等公民。
- 可同时用 Compose 统一 web/桌面/Android(iOS 亦支持)UI。
- 代价:WASM 目标仍在成熟;端上 AI 需经 C 互操作。

### 其它情形

- 组织是 .NET 体系 / 想要托管运行时 → **C#/.NET**(ASP.NET + Blazor WASM + MAUI)。
- "统一 UI"是压倒性目标、核心较轻 → **Dart/Flutter (+ Serverpod)**。
- 若可放宽"端上原生包/离线 ML"约束、想最低成本(前端已是 TS)→ **TS 全栈**(Node + RN + Tauri),但端上原生复用与离线推理是其短板。

> 不推荐 Go(移动端弱、WASM 体积大、GC 不利于嵌入)与纯 C/C++(40 万行重写不安全且低效)。

## 5. 与现有 Python 后端的映射

| 现有 (Python) | agi-stack (Rust) |
|---|---|
| `src/domain/model/`、`src/domain/ports/` | 核心 crate `core`(领域 + 端口 trait) |
| `src/application/services`、`use_cases` | 核心 crate `core`(应用编排,纯逻辑) |
| `infrastructure/adapters/secondary/persistence/sql_*` | `adapters-server`(Postgres/sqlx)、`adapters-device`(SQLite) |
| `infrastructure/llm`(LiteLLM) | `LlmPort` + 云/端两套 adapter |
| `infrastructure/agent/tools`(30+ 工具) | 内置 `dyn Trait` 工具 + WASM 第三方工具(`ToolHost`) |
| `infrastructure/mcp`(`MCPSandboxAdapter`/`LocalSandboxAdapter`) | 分层沙箱:WASM-MCP(可上端)+ Subprocess/Docker-MCP(仅服务器) |
| FastAPI routers | `apps/server`(axum) |
| Ray Actor worker | 服务器侧 Actor runner(Kameo),核心保持运行时无关 |

## 6. 三条设计主轴(后续文档导航)

本总览给出"为什么 Rust"。具体设计沿三条主轴展开:

1. **可移植性**(平台轴)—— 一份核心跑四端:[01-portable-core](01-portable-core.md)、[03-platform-adapters](03-platform-adapters.md)。
2. **可扩展性**(信任 × 平台)—— 工具/技能/MCP 插件生态:[02-extensibility](02-extensibility.md)。
3. **核心引擎质量**(健壮 · 可扩展 · 热插拔 · 可编排)—— 学习网关/Flink/Argo 内部设计后的综合:[06-agent-core-design](06-agent-core-design.md);多层插件运行时(能力注册 · 插件形态 · 可插拔 Harness · 热插拔生命周期)学习 OpenClaw 后的综合:[07-plugin-runtime-architecture](07-plugin-runtime-architecture.md);控制流/数据流分离(控制面=SSOT · 声明式 reconcile · xDS 风格分发 · local-first 断连自治)学习 Kubernetes/Istio 后的综合:[08-control-data-plane-separation](08-control-data-plane-separation.md)。证据基见 [`../research/`](../research/README.md)。

落地路径与 go/no-go 见 [05-roadmap](05-roadmap.md);已验证证据见 [04-spike-evidence](04-spike-evidence.md);逐平台出厂矩阵(`Makefile` 一键五端)见 [09-shipping-matrix](09-shipping-matrix.md);生产迁移(Python 后端绞杀替换为 Rust,共享 Postgres strangler + 网关按能力分流,P1 已落地)见 [10-production-migration](10-production-migration.md);关键决策见 [`../adr/`](../adr/)。
