## [0.2.2] - 2026-02-03

### Changed
- **LiteLLM 升级至 1.81.6**: 支持 Z.AI (ZhipuAI) 原生 provider
  - 升级 `litellm>=1.81.0` (从 1.80.0)
  - 升级 `openai>=2.8.0` (从 1.77.0)
  - 新增 `zai/` provider 前缀支持
  
- **ZhipuAI Provider 前缀标准化**
  - 模型前缀: `zhipu/` → `zai/` (符合 LiteLLM 官方标准)
  - 环境变量: `ZHIPU_API_KEY` → `ZAI_API_KEY` (保留向后兼容)
  - 模型示例: `zai/glm-4.7`, `zai/glm-4.5-flash`

### Fixed
- 修复 ZhipuAI 模型调用时 "LLM Provider NOT provided" 错误

### Documentation
- 更新 `.env.example` 使用 `ZAI_*` 配置
- 更新 `CLAUDE.md` 添加 LiteLLM Provider 前缀映射表

---

## [0.2.1] - 2026-02-03

### Changed
- **LLM Provider 架构统一**: 全面迁移至 LiteLLM
  - 移除所有原生 LLM 客户端 (Qwen/Gemini/Deepseek/OpenAI/ZAI)
  - 统一使用 LiteLLM adapter 支持所有 provider
  - 增强 LiteLLMEmbedder 支持自动 embedding 维度检测
  - 增强 LiteLLMReranker 支持 Cohere 原生 rerank API 及 LLM-based fallback

### Added
- Provider 管理 UI 重构
  - `ProviderCard.tsx`: 现代卡片式 Provider 显示
  - `ProviderHealthPanel.tsx`: 健康监控仪表板
  - 卡片/表格视图切换
  - 实时健康状态、熔断器状态、响应时间显示

### Removed
- 原生 LLM 客户端目录
  - `src/infrastructure/llm/qwen/`
  - `src/infrastructure/llm/gemini/`
  - `src/infrastructure/llm/deepseek/`
  - `src/infrastructure/llm/openai/`
  - `src/infrastructure/llm/zai/`
- 对应的测试文件

### Migration
- 所有 provider 现在通过 LiteLLM 统一接口访问
- 无需更改环境变量配置，现有 API key 继续有效
- Provider 管理 UI 自动升级，无需额外操作

---

## [0.2.0] - 2026-02-03

### Changed
- **Agent Worker 架构重构**: 统一为 ProjectAgentWorkflow
  - 删除 AgentExecutionWorkflow (~328 行)
  - 删除 AgentSessionWorkflow (~655 行)
  - 删除 agent_session.py activities (~1860 行)
  - 精简 agent.py (~1650 行删减)
  - 总计删除约 5000+ 行冗余代码

### Added
- `activities/_shared/` 共享模块
  - `artifact_handlers.py`: Artifact 存储处理
  - `event_persistence.py`: 事件持久化
- ProjectAgentWorkflow 新增 `restart` 信号
- OpenTelemetry metrics 集成
  - `project_agent.init_latency_ms` (Histogram)
  - `project_agent.chat_total` (Counter)
  - `project_agent.chat_latency_ms` (Histogram)
  - `project_agent.chat_errors` (Counter)
  - `project_agent.active_count` (Gauge)

### Migration
- WebSocket 端点已迁移至 ProjectAgentWorkflow
- AgentService 已迁移至 ProjectAgentWorkflow
- 环境变量 `USE_AGENT_SESSION_WORKFLOW` 不再需要

---

## [0.1.1] - 2026-01-20

### Added
- Agent Temporal工作流集成
  - AgentExecutionWorkflow: 完整的ReAct代理生命周期管理 (已在 0.2.0 删除)
  - Agent执行活动: execute_react_step_activity, save_event_activity, save_checkpoint_activity
  - Agent执行事件持久化 (AgentExecutionEvent)
  - 执行检查点机制 (ExecutionCheckpoint) 用于故障恢复
  - 工具执行记录 (ToolExecutionRecord)
- Agent事件回放API
  - GET /api/v1/agent/conversations/{id}/events - 获取历史事件
  - GET /api/v1/agent/conversations/{id}/execution-status - 获取执行状态
  - POST /api/v1/agent/conversations/{id}/resume - 从检查点恢复
  - GET /api/v1/agent/conversations/{id}/tool-executions - 工具执行历史

### Changed
- 更新架构文档 (docs/architecture/ARCHITECTURE.md) 添加Agent Temporal组件说明
- 扩展数据库架构文档包含agent_execution_events, execution_checkpoints表
- 架构文档版本升级至 0.0.6

### Fixed
- LiteLLMClient导入路径错误 (activities/agent.py)
  - 修正: from src.infrastructure.llm.litellm.litellm_client import LiteLLMClient
- WorkflowStatusResponse缺少datetime导入 (routers/agent.py)

## [0.0.2] - 2026-01-17

### Added
- Temporal.io企业级任务调度系统集成
  - Episode、Entity、Community处理工作流实现
  - Temporal Worker和Activity定义
  - Docker Compose Temporal服务配置

### Fixed
- **Agent工具修复**:
  - `graph_query.py`: 修复Neo4j EagerResult解析错误 (`'list' object has no attribute 'items'`)
  - `agent_service.py`: 统一参数命名 (`graphiti_client` → `neo4j_client`)
  - `agent.py`: 移除无效的`graphiti_client`引用
- **知识图谱提取修复**:
  - `entity_extractor.py`: 添加LangChain ChatOpenAI的`ainvoke()`支持
  - `relationship_extractor.py`: 添加LangChain `ainvoke()`支持
  - `reflexion.py`: 修复EntityNode对象类型兼容性问题
  - `prompts.py`: 修复Pydantic模型字段访问
  - `schemas.py`: 修复Neo4j属性序列化（JSON序列化Map类型）
  - `neo4j_client.py`: 修复uuid参数重复传递问题
  - `episode.py`: 修正字段名 (`entities/relationships` → `nodes/edges`)
- **前端API路径修复**:
  - `graphService.ts`: 修正实体和社区API路径（添加`/graph/`前缀）

### Tested
- 记忆添加/更新功能
- Schema提取 (16实体, 4关系)
- Agent对话 + SSE流式响应
- Agent工具执行验证:
  - memory_search工具 (629ms)
  - entity_lookup工具 (248ms)
  - graph_query工具 (38ms)

## [0.0.1] - 2026-01-15

### Added
- React Agent multi-level thinking implementation
- Zai LLM provider integration
- Multi-language internationalization support (i18n)
- Tenant configuration UI for enhanced customization

### Changed
- Improved memory management with better graph cleanup and error handling
- Enhanced system stability with improved error handling and caching
- Streamlined test code structure for better maintainability

### Fixed
- Agent chat interface issues resolved
- Simplified agent routing integration tests for improved reliability
- Fixed frontend test compatibility with component implementations
- Resolved CI compatibility issues with Aliyun mirror
- Improved frontend SSE handling stability
- Fixed inconsistent mock response formats in tests