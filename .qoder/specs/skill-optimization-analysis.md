# 技能系统优化实施计划

## 概述

本文档基于对 `vendor/opencode` 技能系统的深度分析，制定当前项目技能系统的全面优化方案。

**优化范围**：
1. P0: SkillLoaderTool 增强（权限控制 + 结构化返回）
2. P1: 技能权限系统增强（allow/deny/ask 三态）
3. P2: 全局技能目录支持（~/.memstack/skills/）

---

## 一、现状对比分析

### 1.1 OpenCode vs 当前项目

| 特性 | OpenCode | 当前项目 | 差距 |
|------|----------|----------|------|
| 动态描述 | XML 格式列出技能 | 简单文本格式 | 低 |
| 权限控制 | allow/deny/ask + 通配符 | 仅 agent_modes 过滤 | **高** |
| 返回格式 | 结构化 {title, output, metadata} | 纯字符串 | **中** |
| 权限询问 | ctx.ask() 支持用户确认 | 无 | **高** |
| 全局目录 | ~/.claude/skills/ | 无 | 低 |
| Tier 加载 | 无 | ✅ Tier 1/2/3 | 优势 |
| 自动匹配 | 无 | ✅ 关键词/语义匹配 | 优势 |
| 直接执行 | 无 | ✅ 分数>=0.8直接执行 | 优势 |

### 1.2 关键代码文件

**OpenCode 参考**:
- `vendor/opencode/packages/opencode/src/tool/skill.ts` - SkillTool 实现
- `vendor/opencode/packages/opencode/src/permission/next.ts` - 权限系统

**当前项目**:
- `src/infrastructure/agent/tools/skill_loader.py` (254行) - 现有 SkillLoaderTool
- `src/infrastructure/agent/permission/manager.py` - PermissionManager
- `src/domain/model/agent/skill.py` (377行) - Skill 实体

---

## 二、实施计划

### P0: SkillLoaderTool 增强

**目标**: 增加权限询问机制和结构化返回格式

**修改文件**: `src/infrastructure/agent/tools/skill_loader.py`

**变更内容**:

```python
# 1. 构造函数添加 permission_manager 参数
def __init__(
    self,
    skill_service: SkillService,
    permission_manager: Optional[PermissionManager],  # 新增
    tenant_id: str,
    project_id: Optional[str] = None,
    agent_mode: str = "default",
):

# 2. execute() 返回结构化字典
async def execute(self, **kwargs: Any) -> Dict[str, Any]:
    # 权限询问
    if self._permission_manager:
        await self._permission_manager.ask(
            permission="skill",
            patterns=[skill_name],
            metadata={"skill_name": skill_name},
        )
    
    # 返回结构化结果
    return {
        "title": f"Loaded skill: {skill_name}",
        "output": formatted_content,
        "metadata": {
            "name": skill.name,
            "skill_id": skill.id,
            "tools": list(skill.tools),
            "dir": skill.file_path or "",
        },
    }

# 3. 描述格式优化为 XML
def _build_description(self) -> str:
    lines = [
        "Load a skill to get detailed instructions.",
        "<available_skills>",
        *[f"  <skill><name>{s.name}</name><description>{s.description}</description></skill>" 
          for s in self._skills_cache],
        "</available_skills>",
    ]
    return "\n".join(lines)
```

**关联修改**:

| 文件 | 修改内容 |
|------|----------|
| `src/application/services/agent_service.py` | create_tools() 传递 permission_manager |
| `src/infrastructure/agent/core/processor.py` | _execute_tool() 处理字典返回值 |

---

### P1: 技能权限系统增强

**目标**: 支持 allow/deny/ask 三态权限控制

**新增文件**: `src/domain/model/agent/skill_permission.py`

```python
class SkillPermissionAction(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"

@dataclass
class SkillPermissionRule:
    pattern: str  # 支持通配符 "dangerous-*"
    action: SkillPermissionAction

def evaluate_permission(skill_name: str, rules: List[SkillPermissionRule]) -> SkillPermissionAction:
    """评估技能权限，后面的规则优先"""
    for rule in reversed(rules):
        if fnmatch.fnmatch(skill_name, rule.pattern):
            return rule.action
    return SkillPermissionAction.ASK  # 默认询问
```

**修改文件**: `src/domain/model/agent/skill.py`

```python
# 在 Skill 类中添加方法
def check_permission(self, rules: List[SkillPermissionRule]) -> SkillPermissionAction:
    return evaluate_permission(self.name, rules)
```

---

### P2: 全局技能目录支持

**目标**: 支持 `~/.memstack/skills/` 全局技能

**修改文件**: `src/infrastructure/skill/filesystem_scanner.py`

```python
# 在 FileSystemSkillScanner 中添加全局目录扫描
DEFAULT_SKILL_DIRS = [
    ".memstack/skills/",      # 项目级
    "~/.memstack/skills/",    # 全局级（新增）
]

def __init__(self, skill_dirs: Optional[List[str]] = None):
    self._skill_dirs = skill_dirs or DEFAULT_SKILL_DIRS
    # 展开 ~ 为用户主目录
    self._skill_dirs = [os.path.expanduser(d) for d in self._skill_dirs]
```

---

## 三、关键文件清单

### 需要修改的文件

| 优先级 | 文件路径 | 修改类型 |
|--------|----------|----------|
| P0 | `src/infrastructure/agent/tools/skill_loader.py` | 重构 |
| P0 | `src/application/services/agent_service.py` | 小改 |
| P0 | `src/infrastructure/agent/core/processor.py` | 小改 |
| P1 | `src/domain/model/agent/skill_permission.py` | 新建 |
| P1 | `src/domain/model/agent/skill.py` | 小改 |
| P2 | `src/infrastructure/skill/filesystem_scanner.py` | 小改 |

### 参考文件

| 文件路径 | 参考内容 |
|----------|----------|
| `vendor/opencode/packages/opencode/src/tool/skill.ts` | SkillTool 实现 |
| `vendor/opencode/packages/opencode/src/permission/next.ts` | 权限系统 |

---

## 四、验证方案

### 4.1 单元测试

```bash
# 运行技能相关测试
uv run pytest src/tests/unit/test_skill*.py -v
uv run pytest src/tests/unit/infrastructure/agent/tools/test_skill*.py -v
```

### 4.2 集成测试

```bash
# 启动服务
make dev

# 测试 skill_loader 工具调用
curl -X POST http://localhost:8000/api/v1/agent/chat \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "conversation_id": "test-skill",
    "message": "请加载 code-review 技能帮我审查代码",
    "project_id": "1"
  }'
```

### 4.3 验证点

- [ ] LLM 能看到 skill_loader 工具描述中的技能列表
- [ ] LLM 调用 skill_loader 后返回结构化结果
- [ ] 权限询问机制正常工作
- [ ] 全局技能目录能被扫描到

---

## 五、实施顺序

```
Step 1: P0 - SkillLoaderTool 增强
├── 1.1 修改 skill_loader.py（添加 permission_manager + 结构化返回）
├── 1.2 修改 agent_service.py（传递 permission_manager）
├── 1.3 修改 processor.py（处理字典返回）
└── 1.4 编写/更新单元测试

Step 2: P1 - 权限系统增强
├── 2.1 新建 skill_permission.py
├── 2.2 修改 skill.py（添加 check_permission 方法）
└── 2.3 集成到 SkillLoaderTool

Step 3: P2 - 全局目录支持
├── 3.1 修改 filesystem_scanner.py
└── 3.2 验证全局技能加载

Step 4: 集成测试
└── 4.1 端到端测试 Agent 技能调用
```

---

## 六、总结

当前项目技能系统在**自动化执行**方面比 OpenCode 更强大（支持直接执行工具序列），但在**权限控制**和**结构化返回**方面存在差距。

**核心优化**:
1. **P0**: 增强 SkillLoaderTool（权限询问 + 结构化返回）
2. **P1**: 实现 allow/deny/ask 三态权限
3. **P2**: 支持全局技能目录

**预计工作量**: 约 2-3 小时
