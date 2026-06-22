# SKILL 资源与远程 Sandbox 集成架构设计

## 一、问题背景

**生产环境部署架构**：
- Agent 服务和 Sandbox 容器分别独立部署
- 通过 WebSocket/MCP 协议通信
- SKILL 文件存储在 Agent 宿主机
- Sandbox 容器只能访问挂载的项目目录

**核心问题**：SKILL 需要访问本地资源（`scripts/`、`references/`），但远程 Sandbox 容器看不到这些文件。

## 二、设计原则

1. **SKILL 零修改**：完全兼容 Agent Skills 规范
2. **自动透明**：Agent 自动处理资源可用性
3. **向后兼容**：不使用资源的 SKILL 不受影响
4. **网络透明**：支持远程 Sandbox 部署

## 三、架构设计

### 3.1 整体架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                       Agent 服务                                 │
│                                                                 │
│  SKILL 文件 (标准格式)                                          │
│  .memstack/skills/code-analyzer/SKILL.md                         │
│      ├── scripts/analyze.py                                      │
│      └── references/guide.md                                     │
│      │                                                          │
│      ▼                                                          │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  SkillResourceLoader (新增)                                │    │
│  │  - 扫描 SKILL 资源目录                                     │    │
│  │  - 检测 SKILL.md 中引用的资源                               │    │
│  └─────────────────────────────────────────────────────────┘    │
│      │                                                          │
│      ▼                                                          │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  SkillResourceInjector (新增)                              │    │
│  │  - 批量注入资源到 Sandbox                                  │    │
│  │  - 设置环境变量                                            │    │
│  └─────────────────────────────────────────────────────────┘    │
│      │                                                          │
│      ▼                                                          │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  SkillExecutor (修改)                                     │    │
│  │  - 执行前注入资源                                         │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
                                │
                                │ MCP WebSocket
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Sandbox 容器                                │
│  /workspace/                                                    │
│    ├── .skills/          ← SKILL 资源注入目录                    │
│    │   └── code-analyzer/                                      │
│    │       ├── scripts/analyze.py  ◄─── 自动注入               │
│    │       └── references/guide.md  ◄─── 自动注入               │
│    └── project/              ◄─── 项目代码                       │
│                                                                 │
│  环境变量: SKILL_ROOT=/workspace/.skills/code-analyzer           │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 核心组件

#### SkillResourceLoader
- 扫描 SKILL 资源目录（scripts/、references/、assets/）
- 从 SKILL.md 内容中检测引用的资源
- 返回需要注入的资源列表

#### SkillResourceInjector
- 读取本地资源文件
- 通过 MCP write 工具注入到 Sandbox
- 设置 SKILL_ROOT 环境变量

#### SkillExecutor 增强
- 执行 SKILL 前自动注入资源
- 设置环境变量使相对路径可用

### 3.3 SKILL 使用示例（标准格式）

```markdown
---
name: code-analyzer
description: Analyze code quality
tools: [sandbox:bash]
---

# Code Analyzer

Run the analyzer:
```bash
python3 scripts/analyze.py /workspace/src
```

See references/guide.md for details.
```

### 3.4 执行流程

1. Agent 匹配到 SKILL: code-analyzer
2. SkillExecutor.execute(skill, sandbox_id="xxx")
3. 自动扫描 SKILL 资源目录
4. 批量注入资源到 Sandbox 的 `/workspace/.skills/code-analyzer/`
5. 设置环境变量 `SKILL_ROOT=/workspace/.skills/code-analyzer`
6. 执行 bash 命令时自动加入环境变量
7. Sandbox 中的相对路径 `scripts/analyze.py` 通过环境变量解析

## 四、实现阶段

> 落地说明（对照代码，截至 2026-06-22）：架构在实现时偏离了原始设计。
> 实际未引入独立的 `SkillResourceInjector` / `skill_path_resolver.py` / `skill_executor.py`，
> 而是改用「`SkillResourceLoader` + `SkillResourceSyncService`（应用层统一同步入口）+
> `SandboxSkillResourceAdapter` / `LocalSkillResourceAdapter`（二级适配器）」的组合，
> 同步入口被 `skill_loader` 工具、`react_agent_stream_mixin` 的 INJECT 模式、`agent_session_pool`
> 三处调用。容器内资源根目录为 `/workspace/.memstack/skills/`（非设计稿的 `/workspace/.skills/`）。

### Phase 1: 资源扫描 — Done
- [x] 创建 `SkillResourceLoader`（`src/infrastructure/agent/skill/skill_resource_loader.py`）
- [x] 实现 SKILL 目录扫描（`get_skill_resources()`，委托 `FileSystemSkillScanner`）
- [x] 实现内容引用检测（`detect_referred_resources()`）
- [x] 单元测试（`src/tests/unit/infrastructure/agent/skill/test_skill_resource_loader.py`）

### Phase 2: 资源注入 — Done（实现方式与设计稿不同）
- [x] ~~创建 `SkillResourceInjector`~~ 改为 `SkillResourceSyncService`（`src/application/services/skill_resource_sync_service.py`）+ `SandboxSkillResourceAdapter`（`src/infrastructure/adapters/secondary/skill/sandbox_skill_resource_adapter.py`）
- [x] 实现批量资源注入（`SkillResourceSyncService.sync_for_skill()` + 适配器版本缓存幂等同步）
- [x] 实现环境设置（`SkillResourcePort.setup_environment()`，设置 `SKILL_ROOT`、`SKILL_NAME`、`PATH`）
- [x] 单元测试（`src/tests/unit/test_skill_resource_sync_service.py`）

### Phase 3: 执行器集成 — Done（无独立 SkillExecutor，集成进多处）
- [x] ~~修改 `SkillExecutor` 添加资源注入~~ 同步逻辑已挂入：`skill_loader` 工具（`src/infrastructure/agent/tools/skill_loader.py`）、ReActAgent INJECT 模式（`src/infrastructure/agent/core/react_agent_stream_mixin.py` 的 `_stream_sync_skill_resources`）、`agent_session_pool`（`src/infrastructure/agent/state/agent_session_pool.py` 装配 `SkillResourceSyncService`）
- [x] 集成测试（随各调用点的单元测试覆盖）

### Phase 4: E2E 测试 — Pending
- [ ] 创建测试 SKILL
- [ ] 端到端测试
- [x] 文档更新（本次对照代码修订）

## 五、文件清单

> 实际落地结构（对照代码，截至 2026-06-22）：未采用设计稿中的
> `skill_resource_injector.py` / `skill_path_resolver.py` / `skill_executor.py`。

```
src/infrastructure/agent/skill/
├── __init__.py
└── skill_resource_loader.py      # 已落地（路径解析内建于此）

src/application/services/
└── skill_resource_sync_service.py     # 实际的统一同步入口（替代设计稿的 SkillResourceInjector）

src/infrastructure/adapters/secondary/skill/
├── sandbox_skill_resource_adapter.py  # 远程 Sandbox 注入适配器
└── local_skill_resource_adapter.py    # 本地环境适配器

# 同步逻辑的调用点（设计稿称 "SkillExecutor 增强"，实际分散在以下三处）
src/infrastructure/agent/tools/skill_loader.py          # skill_loader 工具
src/infrastructure/agent/core/react_agent_stream_mixin.py  # INJECT 模式（_stream_sync_skill_resources）
src/infrastructure/agent/state/agent_session_pool.py    # 装配 SkillResourceSyncService

# 测试
src/tests/unit/infrastructure/agent/skill/test_skill_resource_loader.py
src/tests/unit/test_skill_resource_sync_service.py
```

## 六、复杂度评估

- **后端开发**: 4-6 小时
- **测试**: 2-3 小时
- **总计**: 6-9 小时 | **复杂度**: LOW-MEDIUM
