# Langfuse 集成架构方案

## 概述

在 MemStack 项目中集成 Langfuse 可观测性平台，追踪所有 LLM 调用（Agent 对话、Entity 提取、Embedding、Reranker），支持自托管部署，并在前端对话界面显示 trace 链接。

## 集成架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Application Layer                           │
│  AgentService / EntityExtractor / EmbeddingService / Reranker      │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────────┐
│                      Infrastructure Layer                           │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────┐ │
│  │   LLMStream     │  │  LiteLLMClient  │  │  LiteLLMEmbedder   │ │
│  │   (Agent)       │  │  (知识图谱)      │  │  LiteLLMReranker   │ │
│  └────────┬────────┘  └────────┬────────┘  └──────────┬──────────┘ │
│           │                    │                      │            │
│           └────────────────────┼──────────────────────┘            │
│                                │                                    │
│                    ┌───────────▼────────────┐                      │
│                    │  litellm.acompletion() │                      │
│                    │  + Langfuse Callback   │                      │
│                    └───────────┬────────────┘                      │
└────────────────────────────────┼────────────────────────────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │   Langfuse 自托管实例    │
                    │   (Docker Compose)      │
                    └─────────────────────────┘
```

## 核心修改文件

### 1. 配置层

**文件**: `src/configuration/config.py`

新增配置项：
```python
# Langfuse 配置
langfuse_enabled: bool = False
langfuse_public_key: Optional[str] = None
langfuse_secret_key: Optional[str] = None
langfuse_host: str = "http://localhost:3000"  # 自托管默认地址
langfuse_sample_rate: float = 1.0  # 采样率
```

### 2. LiteLLM Callback 初始化

**文件**: `src/infrastructure/adapters/primary/web/main.py`

在 lifespan 中初始化 Langfuse callback：
```python
if settings.langfuse_enabled:
    import litellm
    os.environ["LANGFUSE_PUBLIC_KEY"] = settings.langfuse_public_key
    os.environ["LANGFUSE_SECRET_KEY"] = settings.langfuse_secret_key
    os.environ["LANGFUSE_HOST"] = settings.langfuse_host
    litellm.success_callback = ["langfuse"]
    litellm.failure_callback = ["langfuse"]
```

### 3. Agent 系统 - Metadata 注入

**文件**: `src/infrastructure/agent/core/llm_stream.py`

修改 `generate()` 方法，支持传递 Langfuse metadata：
```python
async def generate(
    self,
    messages: List[Dict[str, Any]],
    request_id: Optional[str] = None,
    langfuse_context: Optional[Dict[str, Any]] = None,  # 新增
) -> AsyncIterator[StreamEvent]:
    kwargs = self.config.to_litellm_kwargs()
    kwargs["messages"] = messages
    
    # 注入 Langfuse metadata
    if langfuse_context:
        kwargs["metadata"] = {
            "trace_id": langfuse_context.get("conversation_id"),
            "session_id": langfuse_context.get("conversation_id"),
            "trace_user_id": langfuse_context.get("user_id"),
            "tags": [langfuse_context.get("tenant_id", "default")],
            "trace_name": "agent_chat",
            **langfuse_context.get("extra", {}),
        }
```

**文件**: `src/infrastructure/agent/core/processor.py`

在 `_process_step()` 中构建并传递 langfuse_context：
```python
langfuse_context = {
    "conversation_id": session_id,
    "user_id": self._user_id,
    "tenant_id": self._tenant_id,
    "project_id": self._project_id,
    "extra": {
        "step_number": self._step_count,
        "model": self.config.model,
    }
}
```

### 4. 知识图谱 - Metadata 注入

**文件**: `src/infrastructure/llm/litellm/litellm_client.py`

修改 `_generate_response()` 和 `generate_stream()` 支持 metadata：
```python
async def _generate_response(
    self,
    messages: List[Message],
    response_model: Type[T] | None = None,
    langfuse_context: Optional[Dict[str, Any]] = None,  # 新增
) -> T | str:
    # 构建 metadata
    metadata = {}
    if langfuse_context:
        metadata = {
            "trace_name": langfuse_context.get("trace_name", "llm_call"),
            "trace_id": langfuse_context.get("trace_id"),
            "tags": langfuse_context.get("tags", []),
            **langfuse_context.get("extra", {}),
        }
    
    response = await litellm.acompletion(
        **completion_kwargs,
        metadata=metadata if metadata else None,
    )
```

**文件**: `src/infrastructure/graph/extraction/entity_extractor.py`

传递追踪上下文：
```python
langfuse_context = {
    "trace_name": "entity_extraction",
    "trace_id": episode_id,
    "tags": [project_id],
    "extra": {"episode_id": episode_id},
}
```

### 5. Embedding & Reranker

**文件**: `src/infrastructure/llm/litellm/litellm_embedder.py`
**文件**: `src/infrastructure/llm/litellm/litellm_reranker.py`

类似修改，支持 metadata 传递。

### 6. 前端 - 显示 Trace 链接

**文件**: `src/infrastructure/agent/core/processor.py`

在 SSE 事件中返回 trace_url：
```python
# 在 step_finish 或 complete 事件中返回 trace_url
trace_url = f"{settings.langfuse_host}/trace/{session_id}"
yield SSEEvent.complete(content=final_content, trace_url=trace_url)
```

**文件**: `src/infrastructure/agent/core/events.py`

扩展 SSEEvent 支持 trace_url：
```python
@classmethod
def complete(cls, content: str, trace_url: Optional[str] = None) -> "SSEEvent":
    data = {"content": content}
    if trace_url:
        data["trace_url"] = trace_url
    return cls(SSEEventType.COMPLETE, data)
```

**文件**: `web/src/components/agent/ChatInterface.tsx`

显示 trace 链接：
```tsx
{message.trace_url && (
    <a href={message.trace_url} target="_blank" rel="noopener">
        View Trace
    </a>
)}
```

### 7. Docker Compose - Langfuse 自托管

**文件**: `docker-compose.yml`

添加 Langfuse 服务：
```yaml
services:
  langfuse-server:
    image: langfuse/langfuse:latest
    ports:
      - "3001:3000"
    environment:
      DATABASE_URL: postgresql://postgres:postgres@langfuse-db:5432/langfuse
      NEXTAUTH_URL: http://localhost:3001
      NEXTAUTH_SECRET: ${LANGFUSE_NEXTAUTH_SECRET:-mysecret}
      SALT: ${LANGFUSE_SALT:-mysalt}
    depends_on:
      - langfuse-db

  langfuse-db:
    image: postgres:16
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: langfuse
    volumes:
      - langfuse_postgres_data:/var/lib/postgresql/data

volumes:
  langfuse_postgres_data:
```

## 环境变量配置

**.env.example** 新增：
```env
# Langfuse Observability
LANGFUSE_ENABLED=true
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=http://localhost:3001
LANGFUSE_SAMPLE_RATE=1.0

# Langfuse 自托管配置
LANGFUSE_NEXTAUTH_SECRET=your-secret-key
LANGFUSE_SALT=your-salt
```

## 实施步骤

### Phase 1: 基础框架（预计 4 小时）

1. [ ] `src/configuration/config.py` - 添加 Langfuse 配置项
2. [ ] `src/infrastructure/adapters/primary/web/main.py` - 初始化 LiteLLM callback
3. [ ] `.env.example` - 添加配置示例
4. [ ] `docker-compose.yml` - 添加 Langfuse 服务

### Phase 2: Agent 系统集成（预计 3 小时）

5. [ ] `src/infrastructure/agent/core/llm_stream.py` - 添加 langfuse_context 参数
6. [ ] `src/infrastructure/agent/core/processor.py` - 构建并传递上下文
7. [ ] `src/infrastructure/agent/core/events.py` - SSEEvent 支持 trace_url

### Phase 3: 知识图谱集成（预计 2 小时）

8. [ ] `src/infrastructure/llm/litellm/litellm_client.py` - 支持 metadata
9. [ ] `src/infrastructure/graph/extraction/entity_extractor.py` - 传递上下文
10. [ ] `src/infrastructure/graph/extraction/relationship_extractor.py` - 传递上下文

### Phase 4: Embedding & Reranker（预计 1 小时）

11. [ ] `src/infrastructure/llm/litellm/litellm_embedder.py` - 支持 metadata
12. [ ] `src/infrastructure/llm/litellm/litellm_reranker.py` - 支持 metadata

### Phase 5: 前端集成（预计 2 小时）

13. [ ] `web/src/stores/agent.ts` - 存储 trace_url
14. [ ] `web/src/components/agent/MessageBubble.tsx` - 显示 trace 链接

### Phase 6: 测试验证（预计 2 小时）

15. [ ] 单元测试：metadata 构建逻辑
16. [ ] 集成测试：端到端验证
17. [ ] 手动验证：Langfuse Dashboard 查看

## 验证步骤

1. **启动 Langfuse 服务**：
   ```bash
   docker-compose up -d langfuse-server langfuse-db
   ```

2. **配置环境变量**：
   ```bash
   # 在 Langfuse UI (http://localhost:3001) 创建 project 获取 key
   export LANGFUSE_ENABLED=true
   export LANGFUSE_PUBLIC_KEY=pk-lf-xxx
   export LANGFUSE_SECRET_KEY=sk-lf-xxx
   export LANGFUSE_HOST=http://localhost:3001
   ```

3. **启动后端服务**：
   ```bash
   make dev
   ```

4. **发起 Agent 对话**：
   - 通过 Web UI 或 curl 发起对话请求
   - 确认响应中包含 trace_url

5. **验证 Langfuse Dashboard**：
   - 访问 http://localhost:3001
   - 检查 trace 是否创建
   - 验证 metadata（conversation_id, user_id, tenant_id）
   - 验证 tokens 和 cost 数据

6. **验证前端链接**：
   - 点击对话消息中的 "View Trace" 链接
   - 确认跳转到正确的 trace 页面

## 降级策略

当 Langfuse 不可用时：
```python
try:
    litellm.success_callback = ["langfuse"]
except Exception as e:
    logger.warning(f"Langfuse unavailable, tracing disabled: {e}")
    litellm.success_callback = []
```

## 关键技术点

1. **LiteLLM 原生支持**：利用 LiteLLM 的 Langfuse callback，无需额外 HTTP 调用
2. **流式响应**：LiteLLM callback 自动处理 SSE 流式响应的 trace
3. **成本追踪**：LiteLLM 自动计算 tokens 和 cost，同步到 Langfuse
4. **多租户隔离**：使用 tags 字段实现租户级别的数据过滤
