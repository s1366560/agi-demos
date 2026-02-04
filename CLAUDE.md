# CLAUDE.md

MemStack - 企业级 AI 记忆云平台

## Quick Start

```bash
make init                 # 首次设置: 安装依赖 + 启动基础设施 + 初始化数据库
make dev                  # 启动所有服务 (API + workers + infra)
make dev-web              # 启动前端 (另开终端)
make status               # 检查服务状态
```

**环境重置**:
```bash
make restart              # 快速重启服务
make reset                # 完整重置 (停止 + 清理 Docker + 清理缓存)
make fresh                # 从零开始 (reset + init + dev)
```

**默认凭据** (首次 `make dev` 后自动创建):
- Admin: `admin@memstack.ai` / `adminpassword`
- User: `user@memstack.ai` / `userpassword`

## 常用命令

### 开发服务

| 命令 | 说明 |
|------|------|
| `make dev` | 启动所有后端服务 (API + workers + infra) |
| `make dev-stop` | 停止所有后台服务 |
| `make dev-logs` | 查看所有服务日志 |
| `make dev-backend` | 仅启动 API 服务器 (前台, 端口 8000) |
| `make dev-worker` | 仅启动数据处理 worker |
| `make dev-agent-worker` | 仅启动 Agent worker |
| `make dev-mcp-worker` | 仅启动 MCP worker |
| `make dev-web` | 仅启动 web 前端 (端口 3000) |
| `make dev-infra` | 启动基础设施 (Neo4j, Postgres, Redis, MinIO, Temporal) |
| `make status` | 显示所有服务状态 |

### 测试

| 命令 | 说明 |
|------|------|
| `make test` | 运行所有测试 |
| `make test-unit` | 仅运行单元测试 |
| `make test-integration` | 仅运行集成测试 |
| `make test-coverage` | 运行测试并生成覆盖率报告 (目标 80%+) |
| `make test-watch` | 监听模式运行测试 |

```bash
# 运行单个测试文件
uv run pytest src/tests/unit/test_memory_service.py -v

# 运行单个测试函数
uv run pytest src/tests/unit/test_memory_service.py::TestMemoryService::test_create -v

# 按标记运行
uv run pytest src/tests/ -m "unit" -v
uv run pytest src/tests/ -m "integration" -v
```

### 代码质量

| 命令 | 说明 |
|------|------|
| `make format` | 格式化所有代码 (ruff + eslint) |
| `make lint` | 检查所有代码 |
| `make check` | 运行所有质量检查 (format + lint + test) |

### 数据库

| 命令 | 说明 |
|------|------|
| `make db-init` | 初始化数据库 |
| `make db-reset` | 重置数据库 (警告: 删除所有数据) |
| `make db-migrate` | 运行 Alembic 迁移 |
| `make db-migrate-new` | 生成新的迁移文件 |
| `make db-status` | 显示迁移状态 |

```bash
# Alembic 命令
PYTHONPATH=. uv run alembic current          # 显示当前版本
PYTHONPATH=. uv run alembic history          # 显示迁移历史
PYTHONPATH=. uv run alembic upgrade head     # 应用所有迁移
PYTHONPATH=. uv run alembic downgrade -1     # 回退一步
PYTHONPATH=. uv run alembic revision --autogenerate -m "描述"  # 生成迁移
```

### Docker & 基础设施

| 命令 | 说明 |
|------|------|
| `make docker-up` | 启动所有 Docker 服务 |
| `make docker-down` | 停止 Docker 服务 |
| `make docker-logs` | 显示 Docker 日志 |
| `make docker-clean` | 清理容器、卷和孤立容器 |

### Sandbox (代码执行环境)

| 命令 | 说明 |
|------|------|
| `make sandbox-build` | 构建 sandbox 镜像 (含桌面环境) |
| `make sandbox-build-lite` | 构建轻量版镜像 (无桌面) |
| `make sandbox-run` | 启动 sandbox (XFCE + TigerVNC) |
| `make sandbox-run-lite` | 启动轻量版 sandbox |
| `make sandbox-stop` | 停止 sandbox |
| `make sandbox-status` | 显示 sandbox 状态 |
| `make sandbox-shell` | 进入 sandbox shell |
| `make sandbox-reset` | 重置 sandbox (clean + rebuild) |

### 可观测性

| 命令 | 说明 |
|------|------|
| `make obs-start` | 启动可观测性服务 (Jaeger, OTel, Prometheus, Grafana) |
| `make obs-stop` | 停止可观测性服务 |
| `make obs-ui` | 显示可观测性 UI URLs |

## 架构概览

MemStack 采用 **DDD + 六边形架构**:

```
src/
├── domain/              # 核心业务逻辑 (无外部依赖)
│   ├── model/          # 领域实体 (8 个模块)
│   │   ├── agent/      # Conversation, Plan, Skill, SubAgent, WorkPlan, Message
│   │   ├── memory/     # Memory, Entity, Episode, Community
│   │   ├── project/    # Project, SandboxConfig
│   │   ├── sandbox/    # ProjectSandbox, ResourcePool
│   │   ├── artifact/   # Artifact (文件输出)
│   │   ├── mcp/        # MCPServer, MCPTool
│   │   ├── auth/       # User, ApiKey
│   │   └── tenant/     # Tenant
│   ├── ports/          # 仓储和服务接口 (依赖倒置)
│   └── exceptions/     # 领域异常
│
├── application/         # 应用编排层
│   ├── services/       # 应用服务
│   ├── use_cases/      # 业务用例
│   └── schemas/        # DTOs
│
├── infrastructure/      # 外部实现
│   ├── adapters/
│   │   ├── primary/    # 驱动适配器 (FastAPI 路由, 31 个模块)
│   │   └── secondary/  # 被驱动适配器 (数据库, Temporal, 外部 API)
│   ├── agent/          # ReAct Agent 系统 (4 层架构)
│   ├── llm/            # LLM 统一客户端 (LiteLLM)
│   ├── graph/          # 知识图谱引擎 (Neo4j)
│   ├── mcp/            # Model Context Protocol
│   └── security/       # 认证授权
│
└── configuration/       # 配置和 DI 容器
    ├── config.py       # Pydantic Settings
    └── di_container.py # 依赖注入
```

## Agent 四层架构

```
┌─────────────────────────────────────────────────────────┐
│  L4: Agent (ReAct 推理循环)                              │
│  ├─ SessionProcessor: Think → Act → Observe 循环        │
│  ├─ DoomLoopDetector: 卡住检测                          │
│  └─ CostTracker: Token/成本追踪                         │
├─────────────────────────────────────────────────────────┤
│  L3: SubAgent (专业化代理)                               │
│  ├─ SubAgentOrchestrator: 路由到专业代理                 │
│  ├─ SubAgentRouter: 语义匹配                            │
│  └─ SubAgentExecutor: 子代理执行                        │
├─────────────────────────────────────────────────────────┤
│  L2: Skill (声明式工具组合)                              │
│  ├─ SkillOrchestrator: 技能匹配和路由                    │
│  ├─ SkillExecutor: 技能执行                             │
│  └─ 触发模式: keyword / semantic / hybrid               │
├─────────────────────────────────────────────────────────┤
│  L1: Tool (原子能力)                                     │
│  ├─ TerminalTool: Shell 命令执行                        │
│  ├─ DesktopTool: 桌面/UI 交互                           │
│  ├─ WebSearchTool / WebScrapeTool: 网络搜索和抓取        │
│  ├─ PlanEnterTool / PlanUpdateTool / PlanExitTool       │
│  ├─ ClarificationTool / DecisionTool: 用户交互          │
│  ├─ GetEnvVarTool / RequestEnvVarTool: 环境变量         │
│  └─ SandboxMCPToolWrapper: MCP 工具包装                 │
└─────────────────────────────────────────────────────────┘
```

## Sandbox & MCP 系统

### 两种 Sandbox 适配器

| 适配器 | 场景 | 通信方式 |
|--------|------|----------|
| `MCPSandboxAdapter` | 云端 Docker 容器 | WebSocket |
| `LocalSandboxAdapter` | 本地机器 (ngrok/Cloudflare 隧道) | WebSocket + Token |

### MCP 工具 (30+)

**文件操作**: `read`, `write`, `edit`, `glob`, `grep`, `list`, `patch`
**代码智能**: `ast_parse`, `ast_find_symbols`, `find_definition`, `find_references`, `call_graph`
**编辑**: `edit_by_ast`, `batch_edit`, `preview_edit`
**测试**: `generate_tests`, `run_tests`, `analyze_coverage`
**Git**: `git_diff`, `git_log`, `generate_commit`
**终端/桌面**: `start_terminal`, `start_desktop` (ttyd + noVNC)

## Temporal 工作流

| 工作流 | 用途 |
|--------|------|
| `ProjectAgentWorkflow` | 持久化 Agent 会话 (支持 HITL) |
| `EpisodeProcessingWorkflow` | 知识图谱 Episode 处理 |
| `DeduplicateEntitiesWorkflow` | 实体去重 |
| `RebuildCommunitiesWorkflow` | 社区检测和重建 |

**HITL (Human-in-the-Loop) 模式**:
- `clarification`: 请求用户澄清
- `decision`: 请求用户决策
- `env_var`: 请求环境变量
- `permission`: 请求工具权限

## 编码规范

### Python 后端

**格式化 & 检查**:
- 行长度: 100 字符
- 格式化: `ruff format`
- 检查: `ruff check`
- 类型检查: `mypy` (宽松模式)

**命名规范**:
| 类型 | 规范 | 示例 |
|------|------|------|
| 类 | PascalCase | `UserService`, `SqlUserRepository` |
| 函数/变量 | snake_case | `create_user`, `user_id` |
| 常量 | UPPER_SNAKE_CASE | `MAX_RETRIES`, `DEFAULT_TIMEOUT` |
| 私有 | _前缀 | `_internal_method`, `_session` |

**DDD 模式**:
```python
# Entity - 可变, 有唯一标识
@dataclass(kw_only=True)
class User:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    email: str
    name: str
    
    def change_email(self, new_email: str) -> None:
        # 业务逻辑在实体内部
        self.email = new_email

# Value Object - 不可变
@dataclass(frozen=True)
class Email:
    value: str
    
    def __post_init__(self):
        if '@' not in self.value:
            raise ValueError("Invalid email")

# Repository 接口 - 定义在 domain/ports/
class UserRepository(ABC):
    @abstractmethod
    async def save(self, user: User) -> None: ...
    
    @abstractmethod
    async def find_by_id(self, user_id: str) -> User | None: ...
```

**Import 顺序**:
```python
# 1. 标准库
import uuid
from datetime import datetime
from typing import Optional

# 2. 第三方库
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

# 3. 应用模块
from src.domain.model.auth import User
from src.application.services import UserService

# 4. 相对导入
from .models import UserModel
from ..ports import UserRepository
```

### TypeScript/React 前端

**命名规范**:
| 类型 | 规范 | 示例 |
|------|------|------|
| 组件 | PascalCase | `MessageBubble.tsx` |
| Hooks | use 前缀 | `useAgentStore` |
| Services | camelCase | `agentService.ts` |
| Stores | Store 后缀 | `agentStore.ts` |

**⚠️ Zustand 关键模式** (必须遵守):
```tsx
// ✅ 正确 - 对象选择器必须使用 useShallow
import { useShallow } from 'zustand/react/shallow';

const { messages, isLoading } = useAgentStore(
  useShallow((state) => ({
    messages: state.messages,
    isLoading: state.isLoading,
  }))
);

// ❌ 错误 - 会导致无限重渲染
const { messages, isLoading } = useAgentStore(
  (state) => ({ messages: state.messages, isLoading: state.isLoading })
);

// ✅ 单个值不需要 useShallow
const messages = useAgentStore((state) => state.messages);
```

**禁止 Barrel Import**:
```tsx
// ❌ 避免从 index.ts 导入
import { Button } from '@/components';

// ✅ 直接导入
import { Button } from '@/components/ui/Button';
```

### 测试规范

**Python**:
```python
# 文件命名: test_{module}.py
# 类命名: Test{Component}
# 方法命名: test_{scenario}_{expected}

@pytest.mark.unit
class TestUserService:
    async def test_create_user_success(self, db_session):
        # Arrange
        service = UserService(db_session)
        
        # Act
        user = await service.create("test@example.com")
        
        # Assert
        assert user.email == "test@example.com"

@pytest.mark.integration
class TestUserRepository:
    async def test_save_and_find(self, db_session):
        ...
```

**TypeScript**:
```tsx
// 单元测试: {Component}.test.tsx
// E2E 测试: {feature}.spec.ts

describe('MessageBubble', () => {
  it('should render assistant message correctly', () => {
    // ...
  });
});
```

## 关键文件位置

### 后端入口
- API: `src/infrastructure/adapters/primary/web/main.py`
- Worker: `src/worker_temporal.py`
- Config: `src/configuration/config.py`
- DI Container: `src/configuration/di_container.py`

### Agent 系统
- ReAct Agent: `src/infrastructure/agent/core/react_agent.py`
- Session Processor: `src/infrastructure/agent/processor/processor.py`
- Agent Tools: `src/infrastructure/agent/tools/`
- Skill Orchestrator: `src/infrastructure/agent/skill/orchestrator.py`
- SubAgent Router: `src/infrastructure/agent/routing/router.py`

### 前端
- App: `web/src/App.tsx`
- Agent Chat: `web/src/pages/tenant/AgentWorkspace.tsx`
- Agent Store: `web/src/stores/agentV3.ts`
- Agent Service: `web/src/services/agentService.ts`

## API 测试

**获取 API Key**:
```bash
# 检查日志中的自动生成的 API Key
tail -50 logs/api.log | grep "API Key"

# 或通过登录获取
curl -X POST http://localhost:8000/api/v1/auth/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin@memstack.ai&password=adminpassword"
```

**API 测试**:
```bash
export API_KEY="ms_sk_your_key_here"

# 列出项目
curl -H "Authorization: Bearer $API_KEY" http://localhost:8000/api/v1/projects

# 创建 episode
curl -X POST http://localhost:8000/api/v1/episodes \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"project_id": "1", "content": "Test content"}'

# Agent chat (SSE 流式)
curl -N http://localhost:8000/api/v1/agent/chat \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"conversation_id": "conv-id", "message": "Hello", "project_id": "1"}'
```

**服务端点**:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc
- Temporal UI: http://localhost:8080/namespaces/default
- Web Frontend: http://localhost:3000

## 环境变量

| 类别 | 变量 | 说明 |
|------|------|------|
| **API** | `API_HOST`, `API_PORT` | API 服务器配置 |
| **安全** | `SECRET_KEY`, `LLM_ENCRYPTION_KEY` | 加密密钥 |
| **Neo4j** | `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD` | 图数据库 |
| **PostgreSQL** | `POSTGRES_HOST`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | 元数据库 |
| **Redis** | `REDIS_HOST`, `REDIS_PORT` | 缓存 |
| **Temporal** | `TEMPORAL_HOST`, `TEMPORAL_PORT`, `TEMPORAL_NAMESPACE` | 工作流 |
| **LLM** | `LLM_PROVIDER` | 提供商: `gemini`, `qwen`, `openai`, `deepseek` |
| **LLM Keys** | `GEMINI_API_KEY`, `DASHSCOPE_API_KEY`, `OPENAI_API_KEY` | API 密钥 |
| **Sandbox** | `SANDBOX_DEFAULT_PROVIDER`, `SANDBOX_TIMEOUT_SECONDS` | 代码执行 |
| **MCP** | `MCP_ENABLED`, `MCP_DEFAULT_TIMEOUT` | MCP 协议 |

## 技术栈

**后端**: Python 3.12+, FastAPI 0.104+, SQLAlchemy 2.0+, PostgreSQL 16+, Redis 7+, Neo4j 5.26+
**工作流**: Temporal.io
**LLM**: LiteLLM (Gemini, Qwen, Deepseek, OpenAI, Anthropic)
**前端**: React 19.2+, TypeScript 5.9+, Vite 7.3+, Ant Design 6.1+, Zustand 5.0+
**测试**: pytest 7.4+, Vitest, Playwright

## 重要注意事项

- **多租户**: 始终按 `project_id` 或 `tenant_id` 限定查询
- **异步 I/O**: 所有数据库/HTTP 操作必须是异步
- **API Key 格式**: `ms_sk_` + 64 hex 字符, 存储为 SHA256 哈希
- **Neo4j 关键**: 核心知识图谱功能需要 Neo4j 5.26+
- **测试覆盖率**: 必须保持 80%+ 整体覆盖率
- **Agent 状态**: Agent 对话是有状态的; 使用 conversation_id 保持连续性
- **Zustand useShallow**: 对象选择器必须使用 `useShallow` 防止无限重渲染
