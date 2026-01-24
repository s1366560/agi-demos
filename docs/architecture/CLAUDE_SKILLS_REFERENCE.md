# Claude Skills 架构技术参考

> **版本**: 1.1.0
> **创建日期**: 2026-01-16
> **最后更新**: 2026-01-16
> **状态**: 技术参考 + 集成方案
> **来源**: [Claude Skills Architecture](https://claudecn.com/blog/claude-skills-architecture/)

---

## 目录

1. [概述](#1-概述)
2. [渐进式披露机制](#2-渐进式披露机制)
3. [三级加载架构](#3-三级加载架构)
4. [Skill 文件格式规范](#4-skill-文件格式规范)
5. [运行时架构](#5-运行时架构)
6. [安全模型](#6-安全模型)
7. [与 MCP 协同](#7-与-mcp-协同)
8. [高级模式](#8-高级模式)
9. [对 MemStack 的启示](#9-对-memstack-的启示)
10. [OpenCode 实现分析](#10-opencode-实现分析)
11. [MemStack 集成方案](#11-memstack-集成方案)
12. [实施路线图](#12-实施路线图)

---

## 1. 概述

### 1.1 从提示词工程到上下文工程

Claude Skills 代表了一种范式转移：从传统的"提示词工程"转向"上下文工程"。核心理念是**渐进式披露（Progressive Disclosure）**——仅在需要时注入知识，最大限度减少上下文窗口消耗。

### 1.2 核心价值

| 价值 | 描述 |
|------|------|
| **Token 效率** | 通过延迟加载，单个 Skill 初始仅消耗 ~100 tokens |
| **模块化** | 知识封装为独立 Skill，可复用、可版本管理 |
| **零上下文执行** | 脚本执行不占用上下文窗口 |
| **安全隔离** | 系统级沙箱隔离文件和网络访问 |

---

## 2. 渐进式披露机制

### 2.1 设计哲学

传统方法将所有指令预加载到系统提示中，导致：
- 上下文窗口快速耗尽
- 不相关知识干扰模型推理
- 难以扩展到大量技能

渐进式披露采用"按需加载"策略：
- **元认知索引**：模型仅知道技能存在及其用途
- **语义匹配**：根据用户请求动态激活相关技能
- **延迟注入**：完整指令仅在需要时加载

### 2.2 工作流程

```
用户请求
    ↓
语义匹配（基于 Tier 1 元数据）
    ↓
动态注入（Tier 2 完整指令）
    ↓
脚本执行（Tier 3 零上下文）
    ↓
结果返回
```

---

## 3. 三级加载架构

### 3.1 架构概览

| 层级 | 加载时机 | 加载内容 | Token 消耗 |
|------|----------|----------|------------|
| **Tier 1** | 会话启动 | YAML Frontmatter（name, description） | ~100 tokens/skill |
| **Tier 2** | 语义匹配后 | 完整 SKILL.md 正文 | 按需加载 |
| **Tier 3** | 执行中 | scripts/ 脚本执行结果 | 零上下文 |

### 3.2 Tier 1: 元认知索引

会话初始化时，系统扫描 `.claude/skills/` 目录，仅提取每个 Skill 的元数据：

```yaml
# 仅加载这部分（~100 tokens）
name: data-analysis-pro
description: "Analyzes CSV/Excel datasets, generates visualizations, 
              when user asks for trends, forecasts, or data insights"
```

模型建立"技能清单"，知道有哪些能力可用，但不加载具体实现。

### 3.3 Tier 2: 动态指令注入

当用户请求与某个 Skill 语义匹配时，系统动态注入该 Skill 的完整 Markdown 正文：

```markdown
## Instructions

1. Always validate data format before analysis
2. Use pandas for data manipulation
3. Generate visualizations with matplotlib
4. Run `python scripts/verify_format.py` for validation

## Output Format

- Summary statistics in table format
- Key insights as bullet points
- Visualization saved to output/
```

### 3.4 Tier 3: 零上下文执行

脚本执行采用"输出返回"模式：
- 脚本代码本身不进入上下文
- 仅执行结果（stdout/stderr）返回给模型
- 大幅降低上下文消耗

```
模型指令: "运行 python scripts/clean_data.py input.csv"
    ↓
系统执行脚本（脚本代码不占上下文）
    ↓
返回输出: "Cleaned 1500 rows, removed 23 duplicates"
```

---

## 4. Skill 文件格式规范

### 4.1 目录结构

```
.claude/skills/
└── skill-id/
    ├── SKILL.md           # 核心定义文件（必需）
    ├── scripts/           # 可执行脚本（可选）
    │   ├── analyze.py
    │   └── validate.sh
    └── resources/         # 静态资源（可选）
        ├── templates/
        └── glossary.csv
```

### 4.2 SKILL.md 格式

```markdown
---
# YAML Frontmatter（Tier 1 加载）
name: data-analysis-pro
description: "Analyzes CSV/Excel datasets with statistical methods"

# 可选配置
allowed-tools:              # 允许使用的工具
  - Read
  - Write
  - Bash
user-invocable: true        # 用户可直接调用
context: fork               # 上下文模式：shared | fork
agent: plan                 # 代理模式：default | plan
---

# Markdown 正文（Tier 2 加载）

## Overview

This skill provides advanced data analysis capabilities...

## Instructions

1. Validate input data format
2. Load data using pandas
3. Perform requested analysis
4. Generate visualizations

## Scripts

- `scripts/validate.py` - Validates data format
- `scripts/analyze.py` - Performs statistical analysis

## Output Format

Results should include:
- Summary statistics table
- Key findings (3-5 bullet points)
- Visualizations (saved to output/)
```

### 4.3 Frontmatter 字段说明

| 字段 | 类型 | 必需 | 描述 |
|------|------|------|------|
| `name` | string | 是 | Skill 唯一标识符 |
| `description` | string | 是 | 触发条件和功能描述（用于语义匹配） |
| `allowed-tools` | array | 否 | 允许使用的工具列表 |
| `user-invocable` | bool | 否 | 用户是否可直接调用（默认 true） |
| `context` | string | 否 | 上下文模式：`shared`（共享）或 `fork`（分叉） |
| `agent` | string | 否 | 代理模式：`default` 或 `plan` |

---

## 5. 运行时架构

### 5.1 监督者-执行者模式

```
┌─────────────────────────────────────────┐
│           Claude Desktop (监督者)        │
│  - 对话管理                              │
│  - 任务规划                              │
│  - Skill 选择与编排                      │
└─────────────────┬───────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────┐
│           Claude Code CLI (执行者)       │
│  - 脚本执行                              │
│  - 文件操作                              │
│  - 沙箱隔离                              │
└─────────────────────────────────────────┘
```

### 5.2 优先级规则

Skills 按以下优先级解析：

1. **项目级**：`.claude/skills/`（当前项目目录）
2. **用户级**：`~/.claude/skills/`（用户主目录）
3. **全局级**：系统安装的 Skills

项目级配置覆盖用户级和全局级，支持项目特定的定制。

---

## 6. 安全模型

### 6.1 双重隔离

| 隔离层 | 机制 | 限制 |
|--------|------|------|
| **文件系统** | 沙箱限制 | 仅访问当前目录及子目录 |
| **网络访问** | 代理白名单 | 需显式授权的 URL 列表 |

### 6.2 沙箱技术

- **Linux**: Bubblewrap (bwrap) 容器化
- **macOS**: Seatbelt 沙箱框架
- **Windows**: AppContainer 隔离

### 6.3 权限控制

```yaml
# 权限配置示例
permissions:
  file-read: allow          # 允许读取文件
  file-write: ask           # 写入需确认
  network: deny             # 禁止网络访问
  execute: ask              # 执行需确认
```

权限级别：
- `allow`: 自动授权
- `ask`: 每次需用户确认
- `deny`: 禁止操作

---

## 7. 与 MCP 协同

### 7.1 职责分离

| 组件 | 职责 |
|------|------|
| **Skills** | 定义流程逻辑、编排工具调用 |
| **MCP** | 提供连接能力、外部服务集成 |

**核心理念**：Skills 编排流程，MCP 提供连接。

### 7.2 协同示例

```markdown
# incident-response Skill

## Instructions

When handling incidents:
1. Query Prometheus MCP for current metrics
2. Check Kubernetes MCP for pod status
3. Analyze logs using log-analysis MCP
4. Generate incident report

## MCP Integrations

- prometheus-mcp: Metrics queries
- kubernetes-mcp: Cluster operations
- log-analysis-mcp: Log processing
```

### 7.3 工具组合

Skills 可以组合多个 MCP 工具形成工作流：

```
用户请求: "分析生产环境性能问题"
    ↓
incident-response Skill 激活
    ↓
├── prometheus-mcp.query_metrics()
├── kubernetes-mcp.get_pod_status()
└── log-analysis-mcp.search_errors()
    ↓
综合分析并生成报告
```

---

## 8. 高级模式

### 8.1 上下文分叉 (context: fork)

```yaml
context: fork
```

- 创建独立的上下文副本
- Skill 执行不影响主对话上下文
- 适用于复杂分析或长时间运行的任务

### 8.2 递归组合

Skills 可以调用其他 Skills，形成能力层叠：

```markdown
# meta-analysis Skill

## Instructions

1. Invoke data-cleaning skill for preprocessing
2. Invoke statistical-analysis skill for core analysis
3. Invoke report-generation skill for output
```

### 8.3 自进化技能

基于执行历史优化 Skill 行为：
- 记录成功/失败模式
- 调整触发条件
- 优化指令顺序

---

## 9. 对 MemStack 的启示

### 9.1 当前架构对比

| 方面 | Claude Skills | MemStack Agent |
|------|---------------|----------------|
| 工具定义 | SKILL.md + YAML | Python Tools (tools/) |
| 加载策略 | 三级渐进式 | 全量加载 |
| 上下文管理 | 分叉/隔离 | 共享会话 |
| 脚本执行 | 零上下文 | 工具调用返回结果 |
| 安全隔离 | 系统沙箱 | 应用层权限 |

### 9.2 可借鉴的设计

1. **元数据索引**
   - 仅加载技能摘要，建立"能力清单"
   - 减少初始上下文消耗

2. **语义匹配激活**
   - 基于用户请求动态激活相关技能
   - 避免加载不相关的指令

3. **声明式定义**
   - 使用 Markdown + YAML 定义技能
   - 支持版本管理和模板化

4. **上下文分叉**
   - 复杂任务使用独立上下文
   - 避免污染主对话

### 9.3 实施建议

参考 `docs/architecture/ARCHITECTURE.md` 第8节"技能系统"，可考虑：

1. 为现有 Skill 定义添加元数据层（name, description, triggers）
2. 实现基于语义的 Skill 匹配机制
3. 支持 `context: fork` 模式用于复杂分析任务
4. 增强与 MCP 工具的编排能力

---

## 10. OpenCode 实现分析

> 参考: `vendor/opencode/packages/opencode/src/`

### 10.1 Skill 加载机制

**文件**: `vendor/opencode/packages/opencode/src/skill/skill.ts`

```typescript
// 扫描两种目录格式
const OPENCODE_SKILL_GLOB = new Bun.Glob("{skill,skills}/**/SKILL.md")
const CLAUDE_SKILL_GLOB = new Bun.Glob("skills/**/SKILL.md")

// 单例缓存 + 懒加载
export const state = Instance.state(async () => {
  const skills: Record<string, Info> = {}
  
  // 1. 扫描 .claude/skills/ (项目级 + 全局 ~/.claude/)
  // 2. 扫描 .opencode/skill/
  // 3. 仅提取元数据 (name, description, location)
  
  return skills
})
```

**关键特性**：
- 递归扫描目录查找 `SKILL.md` 文件
- 仅加载 YAML Frontmatter（Tier 1）
- 使用 `Instance.state()` 实现单例缓存
- 支持项目级和全局级 Skills

### 10.2 SkillTool 实现

**文件**: `vendor/opencode/packages/opencode/src/tool/skill.ts`

```typescript
export const SkillTool = Tool.define("skill", async (ctx) => {
  const skills = await Skill.all()
  
  // 构建 available_skills 列表注入到 description
  const description = [
    "Load a skill to get detailed instructions...",
    "<available_skills>",
    ...skills.map(s => `<skill><name>${s.name}</name>...</skill>`),
    "</available_skills>",
  ].join(" ")

  return {
    description,  // 包含技能清单的工具描述
    parameters: z.object({ name: z.string() }),
    async execute(params) {
      // Tier 2: 按需加载完整内容
      const skill = await Skill.get(params.name)
      const parsed = await ConfigMarkdown.parse(skill.location)
      return {
        title: `Loaded skill: ${skill.name}`,
        output: parsed.content,  // 完整 Markdown 正文
        metadata: { name: skill.name, dir: path.dirname(skill.location) }
      }
    }
  }
})
```

**渐进式加载实现**：
1. **Tier 1**: 技能清单嵌入工具描述（~100 tokens/skill）
2. **Tier 2**: 调用 `skill` 工具时加载完整内容
3. **Tier 3**: 脚本通过 `Bash` 工具执行

### 10.3 权限检查

```typescript
// 按 Agent 权限过滤可访问的 Skills
const accessibleSkills = agent
  ? skills.filter((skill) => {
      const rule = PermissionNext.evaluate("skill", skill.name, agent.permission)
      return rule.action !== "deny"
    })
  : skills
```

---

## 11. MemStack 集成方案

### 11.1 架构对比

| 维度 | OpenCode | MemStack 现有 | 建议方案 |
|------|----------|--------------|----------|
| **Skill 定义** | SKILL.md 文件 | Python dataclass + DB | **混合**: 文件 + 数据库 |
| **存储位置** | 文件系统 | PostgreSQL | **双源**: FS 静态 + DB 动态 |
| **加载策略** | 懒加载单例 | 全量加载 | **渐进式**: Tier 1/2/3 |
| **触发机制** | 工具调用 | 关键词/语义 | **增强**: 嵌入匹配 + 工具触发 |
| **租户隔离** | 无 | tenant_id | **保留**: 多租户支持 |

### 11.2 建议实现

#### 阶段一：文件系统 Skill 加载器

新增 `src/infrastructure/agent/skill/loader.py`:

```python
from pathlib import Path
from typing import Dict, Optional
import yaml
import frontmatter

class SkillLoader:
    """
    从文件系统加载 SKILL.md 格式的技能定义。
    支持 .memstack/skills/ 和 .claude/skills/ 目录。
    """
    
    SKILL_DIRS = [".memstack/skills", ".claude/skills"]
    
    def __init__(self, project_root: Path):
        self._project_root = project_root
        self._cache: Dict[str, SkillInfo] = {}
        self._loaded = False
    
    async def scan(self) -> Dict[str, SkillInfo]:
        """扫描并缓存所有技能元数据 (Tier 1)"""
        if self._loaded:
            return self._cache
            
        for skill_dir in self.SKILL_DIRS:
            dir_path = self._project_root / skill_dir
            if not dir_path.exists():
                continue
            for skill_md in dir_path.rglob("SKILL.md"):
                info = await self._parse_metadata(skill_md)
                if info:
                    self._cache[info.name] = info
        
        self._loaded = True
        return self._cache
    
    async def _parse_metadata(self, path: Path) -> Optional[SkillInfo]:
        """仅解析 YAML Frontmatter"""
        content = path.read_text()
        post = frontmatter.loads(content)
        return SkillInfo(
            name=post.get("name"),
            description=post.get("description"),
            location=str(path),
            allowed_tools=post.get("allowed-tools", []),
        )
    
    async def load_full(self, name: str) -> Optional[SkillContent]:
        """按需加载完整内容 (Tier 2)"""
        info = self._cache.get(name)
        if not info:
            return None
        
        content = Path(info.location).read_text()
        post = frontmatter.loads(content)
        return SkillContent(
            info=info,
            instructions=post.content,  # Markdown 正文
            scripts_dir=Path(info.location).parent / "scripts",
        )
```

#### 阶段二：统一 Skill 服务

修改 `src/application/services/skill_service.py`:

```python
class SkillService:
    """统一管理文件系统和数据库中的技能"""
    
    def __init__(
        self,
        skill_repository: SkillRepository,  # 数据库
        skill_loader: SkillLoader,           # 文件系统
    ):
        self._db_repo = skill_repository
        self._fs_loader = skill_loader
    
    async def get_all_metadata(
        self, 
        tenant_id: str, 
        project_id: Optional[str] = None
    ) -> List[SkillMetadata]:
        """获取所有技能元数据 (Tier 1)"""
        # 1. 文件系统技能（项目级）
        fs_skills = await self._fs_loader.scan()
        
        # 2. 数据库技能（租户级 + 项目级）
        db_skills = await self._db_repo.find_by_tenant(
            tenant_id, project_id
        )
        
        # 3. 合并，文件系统优先
        return self._merge_skills(fs_skills, db_skills)
    
    async def load_skill(self, name: str) -> Optional[Skill]:
        """按需加载完整技能 (Tier 2)"""
        # 优先从文件系统加载
        fs_content = await self._fs_loader.load_full(name)
        if fs_content:
            return self._convert_to_skill(fs_content)
        
        # 回退到数据库
        return await self._db_repo.get_by_name(name)
```

#### 阶段三：SkillTool 实现

新增 `src/infrastructure/agent/tools/skill_loader.py`:

```python
class SkillLoaderTool(AgentTool):
    """
    技能加载工具 - 实现渐进式披露。
    
    在工具描述中注入可用技能清单 (Tier 1)，
    执行时加载完整指令 (Tier 2)。
    """
    
    def __init__(self, skill_service: SkillService):
        self._skill_service = skill_service
        self._cached_description: Optional[str] = None
    
    async def get_description(self) -> str:
        """动态生成包含技能清单的描述"""
        if self._cached_description:
            return self._cached_description
        
        skills = await self._skill_service.get_all_metadata()
        
        self._cached_description = "\n".join([
            "Load a skill to get detailed instructions.",
            "<available_skills>",
            *[f"  <skill name='{s.name}'>{s.description}</skill>" 
              for s in skills],
            "</available_skills>",
        ])
        return self._cached_description
    
    async def execute(self, name: str, **kwargs) -> str:
        """加载技能完整内容"""
        skill = await self._skill_service.load_skill(name)
        if not skill:
            return f"Skill '{name}' not found"
        
        return f"""## Skill: {skill.name}

**Tools**: {', '.join(skill.tools)}

{skill.prompt_template or skill.description}
"""
```

### 11.3 SKILL.md 格式扩展

为兼容 MemStack 的多租户和触发机制，扩展 Frontmatter：

```yaml
---
name: knowledge-search
description: "Search and analyze knowledge graph when user asks about entities, relationships"

# Claude/OpenCode 兼容字段
allowed-tools:
  - memory_search
  - entity_lookup
  - graph_query
user-invocable: true
context: shared

# MemStack 扩展字段
trigger:
  type: hybrid              # keyword | semantic | hybrid
  patterns:
    - pattern: "search knowledge"
      weight: 1.0
    - pattern: "find entity"
      weight: 0.8
    - pattern: "graph query"
      weight: 0.9
      
# 多租户支持（可选，默认项目级）
scope: project              # project | tenant | global
---

## Instructions

1. First use `memory_search` to find relevant memories
2. Use `entity_lookup` to get entity details
3. Use `graph_query` for relationship analysis

## Output Format

Provide results in structured format with:
- Entity summaries
- Relationship descriptions  
- Confidence scores
```

### 11.4 集成点

**1. ReActAgent 初始化**:
```python
# 在 _build_react_agent 中
skill_loader_tool = SkillLoaderTool(skill_service)
tools["load_skill"] = skill_loader_tool
```

**2. 系统提示增强**:
```python
# 在构建系统提示时
skill_metadata = await skill_service.get_all_metadata()
system_prompt += f"""
## Available Skills

You can load detailed instructions using the `load_skill` tool:
{format_skill_list(skill_metadata)}
"""
```

**3. SSE 事件扩展**:
```python
class SSEEventType(Enum):
    SKILL_LOADED = "skill_loaded"  # 新增
```

### 11.5 目录结构建议

```
.memstack/
└── skills/
    ├── knowledge-search/
    │   ├── SKILL.md
    │   ├── scripts/
    │   │   └── format_results.py
    │   └── resources/
    │       └── query_templates.yaml
    │
    └── data-analysis/
        ├── SKILL.md
        └── scripts/
            ├── analyze.py
            └── visualize.py
```

---

## 12. 实施路线图

### Phase 1: 基础设施（1-2 周）

- [ ] 实现 `SkillLoader` 文件扫描器
- [ ] 实现 `SkillLoaderTool` 工具
- [ ] 扩展 `SkillService` 支持双数据源
- [ ] 添加 SKILL.md 解析器

### Phase 2: 渐进式加载（1 周）

- [ ] 优化工具描述动态生成
- [ ] 实现元数据缓存机制
- [ ] 添加技能热重载支持

### Phase 3: 高级特性（2 周）

- [ ] 实现 `context: fork` 上下文分叉
- [ ] 增强语义匹配（嵌入向量）
- [ ] 添加技能版本管理
- [ ] 实现跨租户技能市场

---

## 参考资料

- [Claude Skills Architecture 原文](https://claudecn.com/blog/claude-skills-architecture/)
- [MemStack ARCHITECTURE.md](./ARCHITECTURE.md) - 第8节技能系统
- [Model Context Protocol (MCP)](https://modelcontextprotocol.io/)
- [OpenCode 源码](../../../vendor/opencode/) - Skills 实现参考
