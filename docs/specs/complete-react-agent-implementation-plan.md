# ReAct Agent 系统完整实施开发计划

## 执行摘要

基于对代码库的全面分析，当前 ReAct Agent 核心系统（`ReActAgent`、`SessionProcessor`、`LLMStream`）已完成 **95%**，SSE 流式传输管道已全面验证。本计划将系统化补全剩余的高级特性，实现完整的四层能力架构（Tool → Skill → SubAgent → Agent）。

---

## 一、架构现状评估

### 已完成部分 ✅

| 组件 | 完成度 | 关键文件 |
|------|--------|----------|
| **ReAct 核心引擎** | 95% | `react_agent.py`, `processor.py`, `llm_stream.py` |
| **多层思考** | 90% | `plan_work.py`, `execute_step.py`, `work_plan.py` |
| **SSE 流式传输** | 95% | `events.py`, `agent.py` (router) |
| **基础工具系统** | 90% | `tools/` 目录 (8个工具) |
| **工作流模式** | 85% | `workflow_pattern.py`, `learn_pattern.py` |
| **权限&成本&循环检测** | 95% | `permission/`, `cost/`, `doom_loop/` |
| **前端聊天界面** | 90% | `AgentChat.tsx`, `MessageBubble.tsx`, `ChatInterface.tsx` |

### 缺失部分 ❌

| 功能模块 | 优先级 | 依赖关系 |
|---------|--------|----------|
| **SubAgent 系统** | P0 | 独立 |
| **Skill 注册表** | P0 | 独立 |
| **MCP 集成** | P1 | 依赖 Skill |
| **Tool Composition 执行** | P1 | 依赖基础工具 |
| **Context Compression** | P2 | 依赖核心引擎 |
| **SubAgent 管理 UI** | P1 | 依赖后端 API |
| **Activity Log 可视化** | P2 | 依赖 SSE 事件 |

---

## 二、分阶段实施计划

### **Phase 1: 核心能力扩展（P0 - 关键路径）**

**目标**: 完成四层架构的 L2 (Skill) 和 L3 (SubAgent) 层

#### 任务 1.1: Skill System（技能系统）
**优先级**: P0

##### 后端实现

**新增文件**:

1. **`src/domain/model/agent/skill.py`** - Skill 实体
   ```python
   @dataclass
   class Skill:
       id: str
       tenant_id: str
       project_id: Optional[str]
       name: str
       description: str
       trigger_type: TriggerType  # keyword, semantic, hybrid
       trigger_patterns: List[TriggerPattern]
       tools: List[str]
       prompt_template: Optional[str]
       status: SkillStatus  # active, disabled, deprecated
       success_count: int = 0
       failure_count: int = 0
   ```

2. **`src/domain/ports/repositories/skill_repository.py`** - Skill 仓储接口
   ```python
   class SkillRepository(Protocol):
       async def find_by_trigger(self, query: str, tenant_id: str) -> List[Skill]
       async def find_by_tenant(self, tenant_id: str) -> List[Skill]
       async def save(self, skill: Skill) -> None
       async def update(self, skill: Skill) -> None
   ```

3. **`src/infrastructure/agent/skill/registry.py`** - Skill 注册表
   ```python
   class SkillRegistry:
       def load_from_yaml(self, path: str) -> List[Skill]
       def register(self, skill: Skill) -> None
       def match_trigger(self, query: str, context: dict) -> List[Skill]
       def get_skill_tools(self, skill_id: str) -> List[ToolDefinition]
   ```

4. **`src/infrastructure/agent/skill/parser.py`** - SKILL.md 解析器
   ```python
   def parse_skill_markdown(content: str) -> Skill
   def extract_metadata(content: str) -> dict
   def extract_trigger_patterns(content: str) -> list
   def extract_tool_definitions(content: str) -> list
   ```

5. **`src/application/use_cases/agent/match_skills.py`** - Skill 匹配用例

**数据库迁移**:

```sql
-- alembic/versions/agent_005_add_skills_table.py
CREATE TABLE skills (
    id VARCHAR PRIMARY KEY,
    tenant_id VARCHAR NOT NULL,
    project_id VARCHAR,
    name VARCHAR NOT NULL,
    description TEXT,
    trigger_type VARCHAR NOT NULL,
    trigger_patterns JSON,
    tools JSON NOT NULL,
    prompt_template TEXT,
    status VARCHAR DEFAULT 'active',
    success_count INTEGER DEFAULT 0,
    failure_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP
);
CREATE INDEX ix_skills_tenant ON skills(tenant_id);
CREATE INDEX ix_skills_trigger ON skills(trigger_type);
```

**API 端点** (`src/infrastructure/adapters/primary/web/routers/skill.py`):

| 方法 | 端点 | 描述 |
|------|------|------|
| POST | `/api/v1/skills` | 创建 Skill |
| GET | `/api/v1/skills` | 列出 Skills（租户级） |
| GET | `/api/v1/skills/{skill_id}` | 获取 Skill 详情 |
| PUT | `/api/v1/skills/{skill_id}` | 更新 Skill |
| DELETE | `/api/v1/skills/{skill_id}` | 删除 Skill |
| POST | `/api/v1/skills/match` | 匹配 Skill |
| POST | `/api/v1/skills/upload` | 上传 SKILL.md 文件 |

---

#### 任务 1.2: SubAgent System（子智能体系统）
**优先级**: P0

##### 后端实现

**新增文件**:

1. **`src/domain/model/agent/subagent.py`** - SubAgent 实体
   ```python
   @dataclass
   class SubAgent:
       id: str
       tenant_id: str
       name: str  # unique identifier
       display_name: str
       system_prompt: str
       trigger: AgentTrigger
       model: AgentModel  # INHERIT, QWEN, GPT4, CLAUDE
       allowed_tools: List[str]
       allowed_skills: List[str]
       allowed_mcp_servers: List[str]
       max_tokens: int = 4096
       temperature: float = 0.7
       max_iterations: int = 10
       enabled: bool = True
       # Statistics
       total_invocations: int = 0
       avg_execution_time_ms: float = 0.0
       success_rate: float = 1.0
   ```

2. **`src/domain/ports/repositories/subagent_repository.py`** - SubAgent 仓储接口

3. **`src/infrastructure/agent/subagent/registry.py`** - SubAgent 注册表
   ```python
   class SubAgentRegistry:
       def register(self, subagent: SubAgent) -> None
       def get(self, name: str) -> Optional[SubAgent]
       def list_all(self) -> List[SubAgent]
       def match_capability(self, task_description: str) -> Optional[SubAgent]
   ```

4. **`src/infrastructure/agent/subagent/executor.py`** - SubAgent 执行器
   ```python
   class SubAgentExecutor:
       async def execute_step(self, subagent: SubAgent, step: PlanStep) -> dict
       # 创建独立 ReActAgent 实例（隔离工具集、system prompt）
   ```

5. **`src/application/use_cases/agent/route_to_subagent.py`** - SubAgent 路由用例

**数据库迁移**:

```sql
-- alembic/versions/agent_006_add_subagents_table.py
CREATE TABLE subagents (
    id VARCHAR PRIMARY KEY,
    tenant_id VARCHAR NOT NULL,
    project_id VARCHAR,
    name VARCHAR NOT NULL UNIQUE,
    display_name VARCHAR NOT NULL,
    system_prompt TEXT NOT NULL,
    trigger_description TEXT,
    trigger_examples JSON,
    model VARCHAR DEFAULT 'inherit',
    color VARCHAR DEFAULT 'blue',
    allowed_tools JSON,
    allowed_skills JSON,
    allowed_mcp_servers JSON,
    max_tokens INTEGER DEFAULT 4096,
    temperature FLOAT DEFAULT 0.7,
    max_iterations INTEGER DEFAULT 10,
    enabled BOOLEAN DEFAULT true,
    total_invocations INTEGER DEFAULT 0,
    avg_execution_time_ms FLOAT DEFAULT 0.0,
    success_rate FLOAT DEFAULT 1.0,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP
);
CREATE INDEX ix_subagents_tenant ON subagents(tenant_id);
```

**API 端点** (`src/infrastructure/adapters/primary/web/routers/subagent.py`):

| 方法 | 端点 | 描述 |
|------|------|------|
| POST | `/api/v1/subagents` | 创建 SubAgent |
| GET | `/api/v1/subagents` | 列出 SubAgents |
| GET | `/api/v1/subagents/{id}` | 获取 SubAgent 详情 |
| PUT | `/api/v1/subagents/{id}` | 更新 SubAgent |
| DELETE | `/api/v1/subagents/{id}` | 删除 SubAgent |
| PATCH | `/api/v1/subagents/{id}/enable` | 启用/禁用 |
| GET | `/api/v1/subagents/{id}/stats` | 获取统计信息 |
| POST | `/api/v1/subagents/match` | 匹配 SubAgent |

**集成到现有流程**:

修改 `src/application/use_cases/agent/execute_step.py`:
- 检查 `step.assigned_agent` 字段
- 从 SubAgentRegistry 获取 SubAgent
- 使用 SubAgentExecutor 执行步骤

修改 `src/application/use_cases/agent/plan_work.py`:
- 生成 WorkPlan 时为每个 step 分配 SubAgent
- 在 WorkPlan SSE 事件中包含 assigned_agent 信息

---

#### 任务 1.3: 集成 Skill 和 SubAgent
**优先级**: P0

**关键修改**:

1. **更新 `PlanStep` 实体**:
   ```python
   @dataclass
   class PlanStep:
       ...
       assigned_agent: Optional[str] = None  # SubAgent name
       required_skills: List[str] = field(default_factory=list)
   ```

2. **增强 `SessionProcessor`**:
   - 集成 SkillRegistry
   - 根据匹配的 Skill 调整 system_prompt
   - 动态加载工具

3. **更新 SSE 事件**:
   ```python
   # 新增事件类型
   SKILL_ACTIVATED = "skill_activated"
   SUBAGENT_ASSIGNED = "subagent_assigned"
   SUBAGENT_STARTED = "subagent_started"
   SUBAGENT_COMPLETED = "subagent_completed"
   ```

---

### **Phase 2: 生态集成扩展（P1 - 重要特性）**

#### 任务 2.1: MCP Integration（模型上下文协议集成）
**优先级**: P1

**新增文件**:

1. **`src/infrastructure/agent/mcp/client.py`** - MCP 客户端
   - 支持 stdio, SSE, HTTP, WebSocket 传输协议

2. **`src/infrastructure/agent/mcp/registry.py`** - MCP 服务器注册表

3. **`src/infrastructure/agent/mcp/adapter.py`** - MCP 工具适配器

**API 端点** (`src/infrastructure/adapters/primary/web/routers/mcp.py`):

| 方法 | 端点 | 描述 |
|------|------|------|
| GET | `/api/v1/mcp/servers` | 列出 MCP 服务器 |
| POST | `/api/v1/mcp/servers` | 注册 MCP 服务器 |
| GET | `/api/v1/mcp/servers/{name}/tools` | 获取工具列表 |
| POST | `/api/v1/mcp/servers/{name}/test` | 测试连接 |
| DELETE | `/api/v1/mcp/servers/{name}` | 删除服务器 |

---

#### 任务 2.2: Tool Composition Execution（工具组合执行）
**优先级**: P1

**新增文件**:

1. **`src/infrastructure/agent/composition/executor.py`** - 组合执行器
   - Sequential execution (顺序执行)
   - Parallel execution (并行执行)
   - Conditional execution (条件执行)

2. **`src/infrastructure/agent/composition/optimizer.py`** - 组合优化器

**数据库迁移**:

```sql
CREATE TABLE tool_compositions (
    id VARCHAR PRIMARY KEY,
    tenant_id VARCHAR NOT NULL,
    name VARCHAR NOT NULL,
    description TEXT,
    tools JSON NOT NULL,
    execution_template JSON NOT NULL,
    success_count INTEGER DEFAULT 0,
    failure_count INTEGER DEFAULT 0,
    avg_execution_time_ms FLOAT DEFAULT 0.0,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP
);
```

---

#### 任务 2.3: Context Compression（上下文压缩）
**优先级**: P2

**新增文件**:

1. **`src/infrastructure/agent/compression/compressor.py`** - 压缩器

2. **`src/infrastructure/agent/compression/strategy.py`** - 压缩策略
   - SlidingWindowStrategy
   - SummarizationStrategy
   - HybridStrategy

---

### **Phase 3: 前端增强（P1-P2）**

#### 任务 3.1: SubAgent Management UI
**优先级**: P1

**新增组件**:

1. **`web/src/pages/tenant/SubAgentList.tsx`** - SubAgent 列表页
2. **`web/src/pages/tenant/SubAgentDetail.tsx`** - SubAgent 详情页
3. **`web/src/components/agent/SubAgentCard.tsx`** - SubAgent 卡片组件
4. **`web/src/components/agent/SubAgentConfigEditor.tsx`** - 配置编辑器
5. **`web/src/components/agent/RouterFlowDiagram.tsx`** - 路由流程图

**状态管理** (`web/src/stores/subagent.ts`)

**API 服务** (`web/src/services/subagentService.ts`)

---

#### 任务 3.2: Skill Registry UI
**优先级**: P1

**新增组件**:

1. **`web/src/pages/tenant/SkillRegistry.tsx`** - 技能注册表页
2. **`web/src/components/agent/SkillEditor.tsx`** - 技能编辑器
3. **`web/src/components/agent/SkillCard.tsx`** - 技能卡片

---

#### 任务 3.3: Activity Log Visualization
**优先级**: P2

**新增组件**:

1. **`web/src/components/agent/ActivityTimeline.tsx`** - 活动时间线
2. **`web/src/components/agent/TokenUsageChart.tsx`** - Token 使用图表
3. **`web/src/components/agent/ToolCallVisualization.tsx`** - 工具调用图

---

### **Phase 4: 端点整合与优化（P2）**

#### 任务 4.1: Endpoint Consolidation
**优先级**: P2

**目标**: 合并 `/api/v1/agent/chat` 和 `/api/v1/agent/chat-v2`

**策略**:
1. 保留 `/chat-v2` 作为主端点
2. `/chat` 添加 `@deprecated` 标记
3. 添加版本协商机制
4. 更新前端调用
5. 保留 `/chat` 端点 3 个月（宽限期）

---

#### 任务 4.2: Performance Optimization
**优先级**: P2

**优化项**:
1. 数据库查询优化
2. 缓存策略（SubAgent/Skill 配置缓存）
3. SSE 性能优化

---

## 三、数据库 Schema 设计总结

### 新增表

| 表名 | 描述 |
|------|------|
| `skills` | 技能定义和配置 |
| `subagents` | 子智能体定义和配置 |
| `tool_compositions` | 工具组合定义 |
| `mcp_servers` | MCP 服务器配置 |

### 修改表

```sql
-- 更新 plan_steps 表
ALTER TABLE plan_steps ADD COLUMN assigned_agent VARCHAR;
ALTER TABLE plan_steps ADD COLUMN required_skills JSON;
```

---

## 四、依赖关系图

```
Phase 1 (P0):
  Skill System ─────┐
                    ├──► Skill + SubAgent Integration
  SubAgent System ──┘

Phase 2 (P1):
  MCP Integration ◄─── depends on ─── Skill System
  Tool Composition ◄── depends on ─── Basic Tools

Phase 3 (P1-P2):
  SubAgent UI ◄──── depends on ────── SubAgent API
  Skill UI ◄─────── depends on ────── Skill API
  Activity Log UI ◄─ depends on ────── SSE Events

Phase 4 (P2):
  Endpoint Consolidation
  Performance Optimization
```

**关键路径**: Skill System → SubAgent System → SubAgent UI

---

## 五、测试策略

### 单元测试覆盖率目标

| 模块 | 目标覆盖率 |
|------|-----------|
| Domain Models | 90%+ |
| Use Cases | 80%+ |
| Infrastructure | 70%+ |
| API Endpoints | 80%+ |

### 集成测试关键场景

1. **SubAgent 路由测试**: 验证正确路由到对应 SubAgent
2. **Skill 匹配测试**: 验证关键词/语义/混合匹配
3. **MCP 集成测试**: 工具发现和执行
4. **Tool Composition 测试**: 顺序/并行/条件执行

### 前端测试

- **单元测试** (Vitest): 组件测试
- **E2E 测试** (Playwright): 完整流程测试

---

## 六、风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| MCP 生态不成熟 | 高 | MCP 作为可选扩展 |
| LLM 成本过高 | 中 | 实施缓存策略 |
| SubAgent 路由不准确 | 中 | 提供手动指定选项 |
| 数据库性能瓶颈 | 中 | 添加索引，实施缓存 |

---

## 七、关键文件清单

### 后端新增文件

```
src/domain/model/agent/
├── skill.py                    # Skill 实体
└── subagent.py                 # SubAgent 实体

src/domain/ports/repositories/
├── skill_repository.py         # Skill 仓储接口
└── subagent_repository.py      # SubAgent 仓储接口

src/infrastructure/agent/
├── skill/
│   ├── registry.py             # Skill 注册表
│   └── parser.py               # SKILL.md 解析器
├── subagent/
│   ├── registry.py             # SubAgent 注册表
│   └── executor.py             # SubAgent 执行器
├── mcp/
│   ├── client.py               # MCP 客户端
│   ├── registry.py             # MCP 服务器注册表
│   └── adapter.py              # MCP 工具适配器
└── compression/
    ├── compressor.py           # 压缩器
    └── strategy.py             # 压缩策略

src/application/use_cases/agent/
├── match_skills.py             # Skill 匹配用例
└── route_to_subagent.py        # SubAgent 路由用例

src/infrastructure/adapters/primary/web/routers/
├── skill.py                    # Skill API
├── subagent.py                 # SubAgent API
└── mcp.py                      # MCP API
```

### 前端新增文件

```
web/src/pages/tenant/
├── SubAgentList.tsx            # SubAgent 列表页
├── SubAgentDetail.tsx          # SubAgent 详情页
└── SkillRegistry.tsx           # 技能注册表页

web/src/components/agent/
├── SubAgentCard.tsx            # SubAgent 卡片
├── SubAgentConfigEditor.tsx    # SubAgent 配置编辑器
├── RouterFlowDiagram.tsx       # 路由流程图
├── SkillEditor.tsx             # 技能编辑器
├── SkillCard.tsx               # 技能卡片
├── ActivityTimeline.tsx        # 活动时间线
├── TokenUsageChart.tsx         # Token 使用图表
└── ToolCallVisualization.tsx   # 工具调用图

web/src/stores/
├── subagent.ts                 # SubAgent 状态管理
└── skill.ts                    # Skill 状态管理

web/src/services/
├── subagentService.ts          # SubAgent API 服务
├── skillService.ts             # Skill API 服务
└── mcpService.ts               # MCP API 服务
```

### 数据库迁移文件

```
alembic/versions/
├── agent_005_add_skills_table.py
├── agent_006_add_subagents_table.py
├── agent_007_add_compositions_table.py
└── agent_008_add_mcp_servers_table.py
```

---

## 八、实施顺序建议

1. **Phase 1** (P0 - 关键路径)
   - 1.1 Skill System
   - 1.2 SubAgent System
   - 1.3 集成 Skill 和 SubAgent

2. **Phase 2** (P1 - 重要特性)
   - 2.1 MCP Integration
   - 2.2 Tool Composition Execution
   - 2.3 Context Compression

3. **Phase 3** (P1-P2 - 前端增强)
   - 3.1 SubAgent Management UI
   - 3.2 Skill Registry UI
   - 3.3 Activity Log Visualization

4. **Phase 4** (P2 - 优化)
   - 4.1 Endpoint Consolidation
   - 4.2 Performance Optimization
