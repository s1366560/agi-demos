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

### Phase 1: 资源扫描
- [ ] 创建 `SkillResourceLoader`
- [ ] 实现 SKILL 目录扫描
- [ ] 实现内容引用检测
- [ ] 单元测试

### Phase 2: 资源注入
- [ ] 创建 `SkillResourceInjector`
- [ ] 实现批量资源注入
- [ ] 实现环境设置
- [ ] 单元测试

### Phase 3: 执行器集成
- [ ] 修改 `SkillExecutor` 添加资源注入
- [ ] 集成测试

### Phase 4: E2E 测试
- [ ] 创建测试 SKILL
- [ ] 端到端测试
- [ ] 文档更新

## 五、文件清单

```
src/infrastructure/agent/skill/
├── __init__.py
├── skill_resource_loader.py      # 新增
├── skill_resource_injector.py    # 新增
└── skill_path_resolver.py        # 新增

src/infrastructure/agent/core/
└── skill_executor.py             # 修改

tests/unit/agent/skill/
├── test_skill_resource_loader.py     # 新增
├── test_skill_resource_injector.py   # 新增
└── test_skill_path_resolver.py       # 新增

tests/integration/agent/
└── test_skill_execution_with_resources.py  # 新增
```

## 六、复杂度评估

- **后端开发**: 4-6 小时
- **测试**: 2-3 小时
- **总计**: 6-9 小时 | **复杂度**: LOW-MEDIUM
