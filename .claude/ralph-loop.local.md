---
active: true
iteration: 4
max_iterations: 0
completion_promise: null
started_at: "2026-01-22T15:07:29Z"
---

你现在以 **Ralph Loop 机制** 工作，目标是：

> 对照 `vendor/opencode` 的实现，完整补齐本项目（MemStack）的 Agent 能力与工具系统，在不擅自改动架构前提下，完成后端 + 前端功能开发、文档更新和测试，通过多轮迭代逐步收敛。

---

## 一、项目与约束

1. 本项目是 **前后端分离的 Web 应用**：
   - 后端：Python + FastAPI，采用 **DDD + 六边形架构**
     - 代码根目录：`src/`
   - 前端：React + TypeScript + Ant Design + Zustand
     - 代码根目录：`web/src/`

2. 架构约束（非常重要）：
   - 严格遵守现有 DDD / 六边形架构分层与目录结构
   - **禁止擅自修改系统架构**（如领域划分、大型模块拆并、跨层直接依赖）
   - 如确有架构调整需要，只能先在回复中提出“变更方案”，等待用户确认后再实施

3. 参考代码：
   - OpenCode（参考实现，仅作设计/模式对照，非逐行复制）
     - Agent 核心 & 会话处理：`vendor/opencode/packages/opencode/src/agent/`, `session/`
     - 工具系统：`vendor/opencode/packages/opencode/src/tool/`
     - MCP & OAuth：`vendor/opencode/packages/opencode/src/mcp/`
     - 插件系统：`vendor/opencode/packages/plugin/`

4. 文档文件（只编辑，不新建新的 .md）：
   - 架构设计文档：`docs/architecture/ARCHITECTURE.md`
   - 设计差距与进度：`docs/architecture/DESIGN_GAP_ANALYSIS.md`
   - 工具系统设计（如需细节）：`docs/design/tools.md`

---

## 二、Ralph Loop 每轮迭代任务

每一轮 Loop，请按以下顺序操作，并在结束时给出简要总结：

1. **对照分析**
   - 选定一个具体能力/模块（例如：文件编辑工具、代码搜索工具、上下文压缩、MCP OAuth、插件系统等）
   - 查阅 `vendor/opencode` 中对应实现（agent/session/tool/mcp/plugin 等）
   - 对照本项目当前实现（后端 + 前端），明确：
     - 已对齐的部分
     - 功能/安全性/可观测性仍有差距的部分
     - 完全缺失的部分

2. **功能实现 / 补齐**
   - 在后端：只在合适的层修改代码（domain/application/infrastructure/agent），保持依赖方向正确
   - 在前端：遵循现有结构（`pages/` + `components/` + `stores/` + `services/`），使用 AntD + Zustand
   - 遵循既有命名/风格规范（Python: snake_case + dataclass；TSX: PascalCase 组件、camelCase 函数）

3. **测试补齐与执行**
   - 为本轮新功能补充/完善测试：
     - 后端：`src/tests/unit/` 和/或 `src/tests/integration/`
     - 前端：Vitest 单测（`*.test.ts(x)`）和必要的 Playwright E2E（`web/e2e/*.spec.ts`）
   - 运行至少以下命令（可根据粒度选择）：
     - 后端：`make test` 或有针对性的 `uv run pytest ...`
     - 前端：`cd web && pnpm test`（必要时加 E2E：`pnpm test:e2e`）
   - 在总结中明确写出执行了哪些测试，是否全部通过

4. **更新文档（非常关键）**
   - `ARCHITECTURE.md`：
     - 更新 **版本历史表**，增加一行本轮迭代（日期 + 简短变更摘要）
     - 如架构能力有实质补齐（例如新增工具类别、MCP/OAuth 完善），更新对应章节的描述和组件列表
   - `DESIGN_GAP_ANALYSIS.md`：
     - 在“执行摘要 / 完成度 / Sprint 进度”中更新本轮完成项
     - 在“与 vendor/opencode 对比”部分，标记已对齐的能力（例如某类工具或某个系统模块从“缺失”变为“已实现”）
   - `.claude/ralph-loop.local.md`：
     - 输出本轮总结（给用户 + 作为下一轮上下文）**
     - 用简洁要点列出：
     - ✅ 本轮对齐/新实现的功能点（按模块/文件列出）
     - 🧪 运行的测试命令 & 关键测试文件 & 是否通过
     - 📄 修改的文档章节（文件名 + 章节标题）
     - ⏭️ 下一轮推荐关注的模块（基于与 `vendor/opencode` 的差距）

---

## 三、功能优先级参考（对齐 vendor/opencode）

在安排每轮 Loop 时，优先关注下列方向：

1. **P0：Agent 核心能力与工具系统**
   - 已有：SessionProcessor、PermissionManager、DoomLoopDetector、CostTracker、ContextCompaction、FileEdit/CodeSearch/Bash/MultiEdit/Patch 等
   - 重点确认：这些实现是否已达到生产级健壮性（错误处理、边界情况、日志与可观测性等）

2. **P1：MCP 与外部集成**
   - MCP 传输（stdio/HTTP/SSE/WebSocket）与 OAuth
   - 工具统一注册与命名空间策略（例如 `mcp_{server}_{tool}`）
   - 前端 MCP 管理页面功能完备性

3. **P2：插件系统 **
   - 参考 `vendor/opencode/packages/plugin/` 的 Hook 体系
   - 如涉及架构级改造，先仅做设计和文档更新，等待用户确认再落地实现

---

## 四、上下文与资源使用约束

- 避免在回复中粘贴大量、重复的长代码；优先给出：
  - 精选的关键片段
  - 清晰的“修改点路径 + 修改意图”说明
- 尽量减少冗长解释，把重点放在：
  - 对照差距 → 实施改动 → 测试验证 → 文档更新 → 下一步建议
- 严禁擅自新增新的 .md / README 等文档文件；如需文档扩展，优先编辑已有文档中的相关章节。

---
