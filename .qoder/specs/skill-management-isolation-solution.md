# Skill文件系统管理与多租户隔离方案

## 概述

设计一个支持Web UI管理、三层隔离（系统/租户/项目）的Skill管理系统，让用户方便管理文件系统的Skill，同时不影响其他租户或项目加载和使用系统默认提供的基于文件系统的skill。

## 需求分析

- **管理方式**: Web UI管理 - 通过前端界面上传、编辑、删除SKILL.md文件
- **系统Skill保护**: 租户可完全控制 - 可以选择禁用或覆盖任何系统Skill
- **隔离级别**: 系统+租户+项目级 - 三层隔离，优先级：项目 > 租户 > 系统

## 架构设计

### 三层Skill来源

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  系统级Skill  │ ──▶ │  租户级Skill  │ ──▶ │  项目级Skill  │
│ src/builtin/ │     │  PostgreSQL  │     │  PostgreSQL  │
│  (只读共享)   │     │  (租户隔离)   │     │  (项目独享)   │
└──────────────┘     └──────────────┘     └──────────────┘
       │                    │                    │
       │                    │                    │
       └───────────── 加载优先级 ──────────────────┘
                  项目级 > 租户级 > 系统级
```

### 存储方案

| 层级 | 存储位置 | 特点 |
|------|---------|------|
| 系统级 | `src/builtin/skills/` | 代码内置，版本控制，所有租户共享 |
| 租户级 | PostgreSQL `skills` 表 | `scope='tenant'`，租户隔离 |
| 项目级 | PostgreSQL `skills` 表 | `scope='project'`，项目独享 |

## 数据模型变更

### 1. 扩展 `skills` 表

```sql
-- 新增字段
ALTER TABLE skills ADD COLUMN scope VARCHAR(20) DEFAULT 'tenant' NOT NULL;
-- scope: 'system' | 'tenant' | 'project'

ALTER TABLE skills ADD COLUMN is_system_skill BOOLEAN DEFAULT FALSE NOT NULL;
-- 标识是否为系统内置Skill的数据库副本

-- 索引
CREATE INDEX ix_skills_scope ON skills(scope);
CREATE INDEX ix_skills_tenant_scope ON skills(tenant_id, scope);
```

### 2. 新增 `tenant_skill_configs` 表

用于控制租户对系统Skill的禁用/覆盖：

```sql
CREATE TABLE tenant_skill_configs (
    id VARCHAR PRIMARY KEY,
    tenant_id VARCHAR NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    system_skill_name VARCHAR(200) NOT NULL,
    action VARCHAR(20) NOT NULL,  -- 'disable' | 'override'
    override_skill_id VARCHAR REFERENCES skills(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(tenant_id, system_skill_name)
);

CREATE INDEX ix_tenant_skill_configs_tenant ON tenant_skill_configs(tenant_id);
```

### 3. 扩展 Skill 域模型

```python
# src/domain/model/agent/skill.py

class SkillScope(str, Enum):
    SYSTEM = "system"    # 系统级
    TENANT = "tenant"    # 租户级
    PROJECT = "project"  # 项目级

@dataclass
class Skill:
    # ... 现有字段 ...
    scope: SkillScope = SkillScope.TENANT
    is_system_skill: bool = False
```

## 核心逻辑：三层加载与合并

```python
# src/application/services/skill_service.py

async def list_available_skills(
    self,
    tenant_id: str,
    project_id: Optional[str] = None,
) -> List[Skill]:
    skills_map: Dict[str, Skill] = {}
    
    # Step 1: 加载系统级Skill（从builtin目录）
    system_skills = await self._load_system_skills()
    
    # Step 2: 应用租户配置（禁用/覆盖）
    tenant_configs = await self._config_repo.list_by_tenant(tenant_id)
    for skill in system_skills:
        config = tenant_configs.get(skill.name)
        if config and config.action == 'disable':
            continue  # 跳过被禁用的系统Skill
        if config and config.action == 'override':
            continue  # 稍后由租户级Skill覆盖
        skills_map[skill.name] = skill
    
    # Step 3: 加载租户级Skill（覆盖系统级）
    tenant_skills = await self._skill_repo.list_by_tenant(
        tenant_id=tenant_id, scope=SkillScope.TENANT
    )
    for skill in tenant_skills:
        skills_map[skill.name] = skill  # 覆盖
    
    # Step 4: 加载项目级Skill（覆盖租户级）
    if project_id:
        project_skills = await self._skill_repo.list_by_project(
            project_id=project_id, scope=SkillScope.PROJECT
        )
        for skill in project_skills:
            skills_map[skill.name] = skill  # 覆盖
    
    return list(skills_map.values())
```

## API接口设计

### Skill CRUD（扩展现有接口）

```
POST   /api/v1/skills                   # 创建租户/项目级Skill
GET    /api/v1/skills                   # 列出Skill（支持scope过滤）
GET    /api/v1/skills/system            # 获取系统Skill列表（只读）
GET    /api/v1/skills/{id}              # 获取Skill详情
PUT    /api/v1/skills/{id}              # 更新Skill
DELETE /api/v1/skills/{id}              # 删除Skill
GET    /api/v1/skills/{id}/content      # 下载SKILL.md内容
PUT    /api/v1/skills/{id}/content      # 上传SKILL.md内容
```

### 租户Skill配置（新增）

```
GET    /api/v1/tenant/skills/config     # 获取租户Skill配置
POST   /api/v1/tenant/skills/disable    # 禁用系统Skill
POST   /api/v1/tenant/skills/enable     # 启用系统Skill
POST   /api/v1/tenant/skills/override   # 覆盖系统Skill
```

### 请求/响应示例

**创建租户级Skill**:
```json
POST /api/v1/skills
{
  "name": "custom-review",
  "description": "自定义代码审查",
  "scope": "tenant",
  "trigger_type": "keyword",
  "trigger_patterns": [{"pattern": "review code", "weight": 1.0}],
  "tools": ["memory_search", "graph_query"],
  "content": "---\nname: custom-review\n...\n---\n# 正文内容"
}
```

**获取Skill列表**:
```json
GET /api/v1/skills?scope=all

Response:
{
  "skills": [
    {
      "id": "...",
      "name": "code-review",
      "scope": "system",
      "is_system_skill": true,
      "is_disabled": false,
      "is_overridden": false
    },
    {
      "id": "...",
      "name": "custom-review",
      "scope": "tenant",
      "is_system_skill": false
    }
  ]
}
```

## 前端设计

### 页面结构

```
Tenant Settings
└── Skills Management
    ├── System Skills Tab
    │   ├── [只读] code-review       [禁用] [覆盖]
    │   └── [只读] doc-coauthoring   [已禁用] [启用]
    │
    ├── Tenant Skills Tab
    │   ├── [编辑] custom-review     [下载] [删除]
    │   └── [+ 创建新Skill] 按钮
    │
    └── Project Skills Tab (可选)
        └── [编辑] project-specific  [下载] [删除]
```

### 核心组件

1. **SkillManagementPage.tsx** - 主页面，Tab切换三个层级
2. **SystemSkillList.tsx** - 系统Skill列表（只读 + 禁用/覆盖操作）
3. **TenantSkillList.tsx** - 租户Skill CRUD
4. **SkillEditorModal.tsx** - Skill创建/编辑对话框（Markdown编辑器）
5. **SkillUploadModal.tsx** - SKILL.md文件上传

### 状态管理

```typescript
// web/src/stores/skill.ts
interface SkillStore {
  systemSkills: Skill[];
  tenantSkills: Skill[];
  projectSkills: Skill[];
  tenantConfigs: TenantSkillConfig[];
  
  fetchSkills: (scope: 'system'|'tenant'|'project'|'all') => Promise<void>;
  createSkill: (data: SkillCreate) => Promise<Skill>;
  updateSkill: (id: string, data: SkillUpdate) => Promise<Skill>;
  deleteSkill: (id: string) => Promise<void>;
  disableSystemSkill: (skillName: string) => Promise<void>;
  enableSystemSkill: (skillName: string) => Promise<void>;
  overrideSystemSkill: (skillName: string, overrideId: string) => Promise<void>;
}
```

## 实现步骤

### 阶段1: 数据库与领域模型 (2-3天)

1. **创建Alembic迁移**
   - 扩展`skills`表（scope, is_system_skill）
   - 创建`tenant_skill_configs`表
   - 文件: `alembic/versions/xxx_add_skill_scope_and_configs.py`

2. **扩展领域模型**
   - 修改: `src/domain/model/agent/skill.py` - 添加SkillScope枚举和字段
   - 新增: `src/domain/model/agent/tenant_skill_config.py` - TenantSkillConfig实体

3. **扩展仓储层**
   - 修改: `src/domain/ports/repositories/skill_repository.py` - 添加scope参数
   - 修改: `src/infrastructure/adapters/secondary/persistence/sql_skill_repository.py`
   - 新增: `src/domain/ports/repositories/tenant_skill_config_repository.py`
   - 新增: `src/infrastructure/adapters/secondary/persistence/sql_tenant_skill_config_repository.py`

### 阶段2: 系统Skill与服务层 (2-3天)

1. **创建系统Skill目录**
   - 新增: `src/builtin/skills/` 目录
   - 迁移: 将代表性的默认Skill移动到该目录

2. **扩展FileSystemSkillLoader**
   - 修改: `src/infrastructure/skill/filesystem_scanner.py` - 添加builtin路径支持
   - 修改: `src/application/services/filesystem_skill_loader.py` - 添加系统Skill加载

3. **重构SkillService**
   - 修改: `src/application/services/skill_service.py`
   - 实现三层加载逻辑
   - 实现租户配置应用

### 阶段3: API接口 (1-2天)

1. **扩展Skill路由**
   - 修改: `src/infrastructure/adapters/primary/web/routers/skills.py`
   - 添加scope参数支持
   - 添加GET /system端点
   - 添加GET/PUT /{id}/content端点

2. **新增租户配置路由**
   - 新增: `src/infrastructure/adapters/primary/web/routers/tenant_skill_config.py`
   - 实现disable/enable/override端点

### 阶段4: 前端实现 (3-4天)

1. **创建核心组件**
   - 新增: `web/src/pages/tenant/SkillManagement.tsx`
   - 新增: `web/src/components/skill/SystemSkillList.tsx`
   - 新增: `web/src/components/skill/TenantSkillList.tsx`
   - 新增: `web/src/components/skill/SkillEditorModal.tsx`

2. **状态管理与API客户端**
   - 新增: `web/src/stores/skill.ts`
   - 修改: `web/src/services/skillService.ts`

3. **集成到租户设置**
   - 修改租户设置页面，添加Skills Management菜单项

### 阶段5: 测试与文档 (1-2天)

1. **后端测试**
   - 新增: `src/tests/unit/test_skill_multi_tenant.py`
   - 新增: `src/tests/integration/test_skill_scope_isolation.py`

2. **前端测试**
   - 新增: `web/src/test/skill/SkillManagement.test.tsx`

3. **文档更新**
   - 更新AGENTS.md和CLAUDE.md

## 关键文件清单

### 需要修改的文件

| 文件 | 变更内容 |
|------|---------|
| `src/domain/model/agent/skill.py` | 添加SkillScope枚举和scope字段 |
| `src/application/services/skill_service.py` | 实现三层加载逻辑 |
| `src/infrastructure/skill/filesystem_scanner.py` | 添加builtin路径 |
| `src/infrastructure/adapters/primary/web/routers/skills.py` | 扩展API接口 |
| `src/infrastructure/adapters/secondary/persistence/sql_skill_repository.py` | 添加scope查询 |
| `src/infrastructure/adapters/secondary/persistence/models.py` | 扩展Skill模型 |

### 需要新建的文件

| 文件 | 用途 |
|------|-----|
| `alembic/versions/xxx_add_skill_scope_and_configs.py` | 数据库迁移 |
| `src/domain/model/agent/tenant_skill_config.py` | 租户配置实体 |
| `src/domain/ports/repositories/tenant_skill_config_repository.py` | 配置仓储接口 |
| `src/infrastructure/adapters/secondary/persistence/sql_tenant_skill_config_repository.py` | 配置仓储实现 |
| `src/infrastructure/adapters/primary/web/routers/tenant_skill_config.py` | 配置API路由 |
| `src/builtin/skills/` | 系统Skill目录 |
| `web/src/pages/tenant/SkillManagement.tsx` | 主管理页面 |
| `web/src/stores/skill.ts` | Zustand状态管理 |
| `web/src/components/skill/*.tsx` | UI组件 |

## 验证方案

1. **后端验证**
   - 运行 `make test-unit` 和 `make test-integration`
   - 使用curl测试API端点
   - 验证三层Skill加载和覆盖逻辑

2. **前端验证**
   - 启动 `make dev-web`
   - 访问租户设置 > Skills Management
   - 测试：查看系统Skill、禁用/启用、创建租户Skill、覆盖系统Skill

3. **端到端验证**
   - 创建两个租户
   - 租户A禁用某系统Skill，验证租户B不受影响
   - 租户A创建同名Skill覆盖系统Skill，验证覆盖生效
   - 验证项目级Skill可以覆盖租户级Skill

## 安全考虑

- 系统Skill只读，不可通过API修改
- 租户级Skill只能由Tenant Admin管理
- 项目级Skill只能由Project Admin管理
- Skill内容上传限制文件类型（仅.md）和大小（5MB）
