# CLAUDE.md

MemStack - 企业级 AI 记忆云平台

## Quick Start

```bash
make init                 # 首次设置: 安装依赖 + 启动基础设施
make dev                  # 启动所有服务 (API + workers + web)
make status               # 检查服务状态
```

**环境重置**:
```bash
make restart              # 快速重启服务
make clean                # 清理缓存和日志
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
| `make dev` | 启动所有服务 (API + workers + web + infra) |
| `make dev-stop` | 停止所有后台服务 |
| `make dev-logs` | 查看所有服务日志 |
| `make dev-backend` | 仅启动 API 服务器 (前台, 端口 8000) |
| `make dev-worker` | 仅启动数据处理 worker |
| `make dev-agent-worker` | 仅启动 Agent worker |
| `make dev-mcp-worker` | 仅启动 MCP worker |
| `make dev-web` | 仅启动 web 前端 (端口 3000) |
| `make dev-infra` | 启动基础设施服务 (Neo4j, Postgres, Redis, MinIO, Temporal) |
| `make status` | 显示所有服务状态 |

### 安装与依赖

| 命令 | 说明 |
|------|------|
| `make install` | 安装所有依赖 |
| `make install-backend` | 安装后端依赖 (uv) |
| `make install-web` | 安装前端依赖 (pnpm) |
| `make update` | 更新所有依赖 |

### 测试

| 命令 | 说明 |
|------|------|
| `make test` | 运行所有测试 |
| `make test-unit` | 仅运行单元测试 |
| `make test-integration` | 仅运行集成测试 |
| `make test-backend` | 运行后端测试 |
| `make test-web` | 运行前端测试 |
| `make test-e2e` | 运行 E2E 测试 (需要服务运行) |
| `make test-coverage` | 运行测试并生成覆盖率报告 (目标 80%+) |

### 代码质量

| 命令 | 说明 |
|------|------|
| `make format` | 格式化所有代码 |
| `make format-backend` | 格式化 Python 代码 |
| `make format-web` | 格式化 TypeScript 代码 |
| `make lint` | 检查所有代码 |
| `make lint-backend` | 检查 Python 代码 (ruff + mypy) |
| `make lint-web` | 检查 TypeScript 代码 |
| `make check` | 运行所有质量检查 (format + lint + test) |

### 数据库

| 命令 | 说明 |
|------|------|
| `make db-init` | 初始化数据库 |
| `make db-reset` | 重置数据库 (警告: 删除所有数据) |
| `make db-shell` | 打开 PostgreSQL shell |
| `make db-schema` | 初始化数据库表结构 |
| `make db-migrate-messages` | 迁移消息表到统一事件时间线 |

### Docker

| 命令 | 说明 |
|------|------|
| `make docker-up` | 启动所有 Docker 服务 |
| `make docker-down` | 停止 Docker 服务 |
| `make docker-logs` | 显示 Docker 日志 |
| `make docker-build` | 构建 Docker 镜像 |
| `make docker-clean` | 清理容器、卷和孤立容器 |

### Sandbox (代码执行环境)

| 命令 | 说明 |
|------|------|
| `make sandbox-build` | 构建 sandbox 镜像 |
| `make sandbox-run` | 启动 sandbox (默认 TigerVNC + XFCE 桌面) |
| `make sandbox-run-x11vnc` | 使用 x11vnc 启动 (稳定回退) |
| `make sandbox-stop` | 停止 sandbox |
| `make sandbox-status` | 显示 sandbox 状态 |
| `make sandbox-logs` | 显示 sandbox 日志 |
| `make sandbox-shell` | 进入 sandbox shell |
| `make sandbox-reset` | 重置 sandbox (clean + rebuild) |

### 工具

| 命令 | 说明 |
|------|------|
| `make clean` | 清理所有生成文件和缓存 |
| `make clean-logs` | 清理日志文件 |
| `make shell` | 打开 Python shell |
| `make test-data` | 生成测试数据 (默认 50 条) |
| `make get-api-key` | 显示 API Key 获取说明 |
| `make hooks-install` | 安装 git hooks |
| `make hooks-uninstall` | 卸载 git hooks |

## 架构概览

MemStack 采用 **DDD + 六边形架构**:

```
src/
├── domain/              # 核心业务逻辑 (无外部依赖)
│   ├── model/          # 领域实体 (agent, auth, memory, project, tenant, task)
│   ├── ports/          # 仓储和服务接口 (依赖倒置)
│   └── llm_providers/  # LLM 提供商抽象
│
├── application/         # 应用编排层
│   ├── services/       # 应用服务 (agent, memory, workflow_learner)
│   ├── use_cases/      # 业务用例
│   ├── schemas/        # DTOs
│   └── tasks/          # 后台任务处理器
│
├── infrastructure/      # 外部实现
│   ├── adapters/
│   │   ├── primary/    # 驱动适配器 (web API)
│   │   └── secondary/  # 被驱动适配器 (数据库, 外部 API)
│   ├── agent/          # ReAct Agent 系统
│   ├── llm/            # LLM 客户端 (LiteLLM)
│   ├── graph/          # 知识图谱引擎
│   └── security/       # 认证授权
│
└── configuration/       # 配置和 DI 容器
    ├── config.py       # Pydantic Settings
    └── di_container.py # 依赖注入
```

### 技术栈

**后端**: Python 3.12+, FastAPI 0.110+, Pydantic 2.5+, SQLAlchemy 2.0+
**数据库**: Neo4j 5.26+ (知识图谱), PostgreSQL 16+ (元数据), Redis 7+ (缓存)
**工作流**: Temporal.io (企业级工作流编排)
**LLM**: LiteLLM (多提供商: Gemini, Qwen, Deepseek, ZhipuAI, OpenAI)

**前端**: React 19.2+, TypeScript 5.9+, Vite 7.3+, Ant Design 6.1+, Zustand 5.0+
**测试**: pytest 9.0+, Vitest 4.0+, Playwright 1.57+ (目标 80%+ 覆盖率)

## 核心概念

- **Episodes**: 包含内容和元数据的离散交互事件
- **Memories**: 从 episodes 中提取的语义记忆
- **Entities**: 具有属性和关系的现实世界对象
- **Projects**: 多租户隔离单元，每个项目有独立的知识图谱
- **API Keys**: SHA256 哈希的认证密钥 (格式: `ms_sk_` + 64 hex)

### ReAct Agent 系统

四层架构:
- **L1**: Tool 层 - 原子能力单元 (10+ 内置工具)
- **L2**: Skill 层 - 声明式工具组合
- **L3**: SubAgent 层 - 专业化代理
- **L4**: Agent 层 - 完整 ReAct 代理

**核心组件**:
- `ReActAgent` - 主代理类
- `SessionProcessor` - 核心 ReAct 推理循环
- `LLMStream` - 流式 LLM 接口
- `PermissionManager` - Allow/Deny/Ask 权限控制
- `DoomLoopDetector` - 代理卡住检测
- `CostTracker` - 实时 token 和成本计算

### 知识图谱系统

**Native Graph Adapter** - 自研知识图谱引擎:
- LLM 驱动的实体提取和关系发现
- 向量相似度实体去重
- 混合搜索 (向量 + 关键词 + RRF)
- Louvain 社区检测

**Neo4j Schema**:
- `(:Episodic)` - Episode 节点
- `(:Entity)` - 实体节点
- `(:Community)` - 社区节点
- `[:MENTIONS]` - Episode → Entity
- `[:RELATES_TO]` - Entity → Entity
- `[:BELONGS_TO]` - Entity → Community

## 重要文件位置

### 后端入口
- API: `src/infrastructure/adapters/primary/web/main.py`
- Worker: `src/worker_temporal.py`
- Config: `src/configuration/config.py`
- DI Container: `src/configuration/di_container.py`

### Agent 系统
- ReAct Agent: `src/infrastructure/agent/core/react_agent.py`
- Session Processor: `src/infrastructure/agent/core/processor.py`
- Agent Tools: `src/infrastructure/agent/tools/`

### 前端
- App: `web/src/App.tsx`
- Agent Chat: `web/src/pages/project/AgentChat.tsx`
- Agent Store: `web/src/stores/agent.ts`
- Agent Service: `web/src/services/agentService.ts`

## API 测试

**获取 API Key**:
```bash
# 检查日志中的自动生成的 API Key
tail -50 logs/api.log | grep "API Key"

# 或通过登录获取 token
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

## 数据库迁移

Alembic 迁移在应用启动时自动运行。

**关键规则**:
1. 永远不要绕过迁移直接修改数据库
2. 始终使用 `--autogenerate` 生成迁移
3. 审查自动生成的迁移文件

**迁移命令**:
```bash
PYTHONPATH=. uv run alembic current          # 显示当前版本
PYTHONPATH=. uv run alembic history          # 显示迁移历史
PYTHONPATH=. uv run alembic upgrade head     # 应用所有迁移
PYTHONPATH=. uv run alembic downgrade -1     # 回退一步
PYTHONPATH=. uv run alembic revision --autogenerate -m "描述"  # 生成迁移
```

## 环境变量

主要配置 (完整列表见 `.env.example`):

| 类别 | 变量 | 说明 |
|------|------|------|
| **API** | `API_HOST`, `API_PORT` | API 服务器配置 |
| **安全** | `SECRET_KEY`, `LLM_ENCRYPTION_KEY` | 加密密钥 |
| **Neo4j** | `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD` | 图数据库连接 |
| **PostgreSQL** | `POSTGRES_HOST`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | 元数据数据库 |
| **Redis** | `REDIS_HOST`, `REDIS_PORT` | 缓存 |
| **Temporal** | `TEMPORAL_HOST`, `TEMPORAL_PORT`, `TEMPORAL_NAMESPACE` | 工作流编排 |
| **LLM** | `LLM_PROVIDER` | 提供商: `gemini`, `qwen`, `openai`, `deepseek`, `zhipu` |
| **LLM Keys** | `GEMINI_API_KEY`, `DASHSCOPE_API_KEY`, `OPENAI_API_KEY`, etc. | LLM API 密钥 |
| **Sandbox** | `SANDBOX_DEFAULT_PROVIDER`, `SANDBOX_TIMEOUT_SECONDS` | 代码执行环境 |
| **MCP** | `MCP_ENABLED`, `MCP_DEFAULT_TIMEOUT` | Model Context Protocol |
| **前端** | `VITE_API_URL` | 前端连接的 API 地址 |

## 测试模式

- `unit` - 单元测试 (mock 外部依赖)
- `integration` - 集成测试 (真实数据库)
- `performance` - 性能测试

**运行特定标记的测试**:
```bash
uv run pytest src/tests/ -m "unit" -v
uv run pytest src/tests/ -m "integration" -v
```

**关键测试 Fixtures**:
- `test_db` / `db_session` - 内存 SQLite 异步会话
- `test_user` - 数据库中的用户记录
- `test_tenant_db` - 租户
- `test_project_db` - 项目
- `mock_graph_service` - Mock GraphServicePort
- `authenticated_client` - 带认证头的 TestClient

## 重要注意事项

- **多租户**: 始终按 `project_id` 或 `tenant_id` 限定查询
- **异步 I/O**: 所有数据库/HTTP 操作必须是异步
- **API Key 格式**: `ms_sk_` + 64 hex 字符, 存储为 SHA256 哈希
- **Neo4j 关键**: 核心知识图谱功能需要 Neo4j 5.26+
- **测试覆盖率**: 必须保持 80%+ 整体覆盖率
- **代码风格**: 100 字符行长度, Ruff 格式化
- **Agent 状态**: Agent 对话是有状态的; 使用 conversation_id 保持连续性
- **SSE 连接**: 前端必须优雅处理 SSE 断开

## 最近更新

- **2026-01-29**: Sandbox 桌面环境集成 (XFCE + VNC + noVNC)
- **2026-01-28**: 前端重构完成 (React 19.2+ 最佳实践)
- **2026-01-17**: Temporal.io 企业级任务调度
- **2026-01-15**: 自研知识图谱引擎
- **2026-01-10**: ReAct Agent 系统
- **2026-01-05**: LiteLLM 多提供商集成
