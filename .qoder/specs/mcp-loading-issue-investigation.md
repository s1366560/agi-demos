# MCP 工具未加载到 Agent 上下文问题调查

## 问题描述

MCP (Model Context Protocol) 工具没有被正确加载到 Agent 上下文中，导致 Agent 无法使用通过 MCP 服务器提供的工具。

---

## 方案对比：MemStack vs OpenCode

### 架构对比

| 维度 | MemStack (当前方案) | OpenCode (vendor/opencode) |
|------|---------------------|---------------------------|
| **语言** | Python + Temporal | TypeScript + Instance.state |
| **MCP 客户端管理** | MCPTemporalAdapter (通过 Temporal 工作流) | 直接内存管理 (Record<string, MCPClient>) |
| **工具加载时机** | Worker 启动时 + Activity 执行时 | 每次 Agent 循环时按需加载 |
| **缓存级别** | tenant_id 级别 | 无持久缓存，每次循环重新获取 |
| **工具命名** | `mcp__{server}__{tool}` | `{server}_{tool}` |
| **OAuth 支持** | 通过配置支持 | 完整 OAuth 2.0 流程 (内置 Provider) |
| **传输协议** | stdio / HTTP / SSE | stdio / StreamableHTTP / SSE (自动降级) |

### 关键差异分析

#### 1. **工具加载流程**

**OpenCode 方式** (`session/prompt.ts:643-819`):
```typescript
// 每次 Agent 循环时合并工具
async function resolveTools(input) {
  const tools = {}
  
  // 第一层：内置工具
  for (const item of await ToolRegistry.tools()) {
    tools[item.id] = tool({...})
  }
  
  // 第二层：MCP 工具（实时获取）
  for (const [key, item] of Object.entries(await MCP.tools())) {
    tools[key] = item
  }
  
  return tools
}
```

**MemStack 方式** (当前问题代码):
```python
# 工具在 Worker 启动时创建，MCP 工具被遗漏
tools = await get_or_create_tools(project_id, graph_service, redis_client, llm)
# 没有调用 MCPTemporalToolLoader
```

#### 2. **优劣势对比**

| 方面 | MemStack 方案 | OpenCode 方案 |
|------|--------------|--------------|
| **性能** | ✅ 缓存减少重复加载 | ⚠️ 每次循环都重新获取工具列表 |
| **实时性** | ⚠️ 新增 MCP 服务器需要清缓存 | ✅ 自动获取最新工具 |
| **复杂度** | ⚠️ Temporal 工作流增加复杂度 | ✅ 简单直接的内存管理 |
| **可扩展性** | ✅ 可独立扩展 MCP Worker | ⚠️ 单进程限制 |
| **故障隔离** | ✅ MCP 故障不影响 Agent Worker | ⚠️ 同进程，需要 try-catch |
| **OAuth** | ⚠️ 基础支持 | ✅ 完整 OAuth 流程 + UI 提示 |

#### 3. **OpenCode 的优秀设计**

1. **自动传输降级** (`mcp/index.ts:304-406`):
```typescript
// 尝试多个 Transport，自动降级
const transports = [
  { name: "StreamableHTTP", transport: new StreamableHTTPClientTransport(...) },
  { name: "SSE", transport: new SSEClientTransport(...) },
]
for (const { name, transport } of transports) {
  try {
    await client.connect(transport)
    break  // 成功即停止
  } catch (error) {
    // 继续尝试下一个
  }
}
```

2. **并行初始化** (`mcp/index.ts:163-210`):
```typescript
await Promise.all(
  Object.entries(config).map(async ([key, mcp]) => {
    const result = await create(key, mcp)
    // ...
  }),
)
```

3. **完整的错误状态** (`mcp/index.ts:87-117`):
```typescript
type Status =
  | { status: "connected" }
  | { status: "failed"; error: string }
  | { status: "needs_auth" }
  | { status: "needs_client_registration"; error: string }
  | { status: "disabled" }
```

---

## 推荐方案：借鉴 OpenCode 优化 MemStack

### 改进点

1. **简化 MCP 工具加载** - 不再依赖 Temporal 工作流缓存，改为 Activity 执行时直接加载
2. **添加传输自动降级** - 支持 StreamableHTTP → SSE 自动降级
3. **增强错误状态** - 区分 connected / failed / needs_auth / disabled
4. **保持缓存优势** - 按 tenant_id 缓存 MCP 客户端连接（不是工具列表）

### 架构改进图

```
原方案:
Agent Worker 启动
  → set_mcp_temporal_adapter()
    → Activity 执行时 get_or_create_tools()
      → MCPTemporalToolLoader.load_all_tools() [缓存工具列表]
        → MCPTemporalAdapter.list_all_tools()
          → Temporal Workflow (call MCP server)

优化方案 (借鉴 OpenCode):
Agent Worker 启动
  → 初始化 MCP 客户端池 (按 tenant_id)
    → Activity 执行时 get_or_create_tools()
      → 获取内置工具
      → 获取 MCP 工具 (直接从客户端池获取，实时 list_tools)
        → 合并返回
```

---

## 根因分析

### 发现的问题

**核心问题：`MCPTemporalToolLoader` 已实现但从未被调用**

虽然系统中已经实现了完整的 MCP 工具加载机制（`MCPTemporalToolLoader`），但在 Agent 工具加载流程中**从未被使用**。

### 问题代码路径

#### 1. Temporal Activity 中的工具加载 (agent.py:1114-1120)

```python
# 当前代码 - 只加载内置工具，没有 MCP 工具
tools = await get_or_create_tools(
    project_id=project_id,
    graph_service=graph_service,
    redis_client=redis_client,
    llm=llm_client,
)
```

#### 2. 工具缓存函数 (agent_worker_state.py:157-206)

```python
# 只创建 8 个内置工具，没有 MCP 工具
_tools_cache[project_id] = {
    "memory_search": MemorySearchTool(graph_service),
    "entity_lookup": EntityLookupTool(neo4j_client),
    "graph_query": GraphQueryTool(neo4j_client),
    "memory_create": MemoryCreateTool(graph_service),
    "episode_retrieval": EpisodeRetrievalTool(neo4j_client),
    "web_search": WebSearchTool(redis_client),
    "web_scrape": WebScrapeTool(),
    "summary": SummaryTool(llm) if llm else None,
}
```

#### 3. AgentService 中的工具定义 (agent_service.py:803-883)

```python
# _mcp_temporal_adapter 虽然被保存，但从未在 get_available_tools() 中使用
self._mcp_temporal_adapter = mcp_temporal_adapter  # 行151 - 保存了

# get_available_tools() 只返回静态工具，没有 MCP 工具
async def get_available_tools(self, project_id: str, tenant_id: str):
    # ... 只返回 _build_base_tool_definitions() + skill_loader
    # 完全没有使用 _mcp_temporal_adapter
```

### 已实现但未使用的代码

**`src/infrastructure/mcp/temporal_tool_loader.py`** - 完整的 MCP 工具加载器

```python
class MCPTemporalToolLoader:
    async def load_all_tools(self, refresh: bool = False) -> Dict[str, AgentTool]:
        """从所有连接的 Temporal MCP 服务器加载工具"""
        all_tools = await self.mcp_temporal_adapter.list_all_tools(self.tenant_id)
        for tool_info in all_tools:
            adapter = MCPTemporalToolAdapter(...)
            tools[adapter.name] = adapter
        return tools
```

## 关键文件

| 文件 | 作用 | 问题 |
|------|------|------|
| `src/infrastructure/adapters/secondary/temporal/activities/agent.py` | Agent 执行 Activity | 行1114-1120: 只调用 `get_or_create_tools()`，不加载 MCP |
| `src/infrastructure/adapters/secondary/temporal/agent_worker_state.py` | 工具缓存管理 | 行157-206: `get_or_create_tools()` 只创建内置工具 |
| `src/application/services/agent_service.py` | Agent 服务 | 行803-883: `get_available_tools()` 不使用 `_mcp_temporal_adapter` |
| `src/infrastructure/mcp/temporal_tool_loader.py` | MCP 工具加载器 | **已实现但从未被调用** |
| `src/infrastructure/mcp/temporal_tool_adapter.py` | MCP 工具适配器 | 已实现，用于将 MCP 工具转为 AgentTool |
| `src/configuration/di_container.py` | 依赖注入 | 行411: `mcp_temporal_adapter` 已传递给 AgentService |

## 修复方案

### 方案：在 `agent_worker_state.py` 中集成 MCP 工具加载

修改 `get_or_create_tools()` 函数，添加 MCP 工具加载逻辑：

```python
async def get_or_create_tools(
    project_id: str,
    tenant_id: str,  # 新增参数
    graph_service: Any,
    redis_client: Any,
    llm: Any = None,
    mcp_temporal_adapter: Any = None,  # 新增参数
) -> Dict[str, Any]:
    """Get or create a cached tool set for a project, including MCP tools."""
    
    async with _tools_cache_lock:
        if project_id not in _tools_cache:
            # 1. 创建内置工具
            neo4j_client = getattr(graph_service, "neo4j_client", None)
            tools = {
                "memory_search": MemorySearchTool(graph_service),
                "entity_lookup": EntityLookupTool(neo4j_client),
                # ... 其他内置工具
            }
            
            # 2. 加载 MCP 工具 (新增)
            if mcp_temporal_adapter:
                from src.infrastructure.mcp.temporal_tool_loader import MCPTemporalToolLoader
                
                mcp_loader = MCPTemporalToolLoader(
                    mcp_temporal_adapter=mcp_temporal_adapter,
                    tenant_id=tenant_id,
                )
                try:
                    mcp_tools = await mcp_loader.load_all_tools()
                    tools.update(mcp_tools)
                    logger.info(f"Loaded {len(mcp_tools)} MCP tools for project {project_id}")
                except Exception as e:
                    logger.warning(f"Failed to load MCP tools: {e}")
            
            _tools_cache[project_id] = tools
        
        return _tools_cache[project_id]
```

### 需要修改的文件

1. **`src/infrastructure/adapters/secondary/temporal/agent_worker_state.py`**
   - 修改 `get_or_create_tools()` 添加 `tenant_id` 和 `mcp_temporal_adapter` 参数
   - 添加 MCP 工具加载逻辑

2. **`src/infrastructure/adapters/secondary/temporal/activities/agent.py`**
   - 修改 `execute_react_step_activity()` 传递 `tenant_id` 和 `mcp_temporal_adapter`
   - 需要获取或创建 `MCPTemporalAdapter` 实例

3. **`src/worker_agent.py`** (如果需要)
   - 在 Agent Worker 启动时初始化 `MCPTemporalAdapter`

## 验证步骤

1. **启动 MCP Worker**
   ```bash
   uv run python src/worker_mcp.py
   ```

2. **配置 MCP 服务器**
   - 通过 API 创建 MCP 服务器配置: `POST /api/v1/mcp`

3. **测试 Agent Chat**
   - 发送消息到 Agent: `POST /api/v1/agent/chat`
   - 检查返回的工具列表是否包含 `mcp__*` 前缀的工具

4. **日志验证**
   - 检查 `logs/api.log` 中是否有 "Loaded X MCP tools" 日志

5. **运行测试**
   ```bash
   make test-unit
   ```

## 实现方案（优化版 - 借鉴 OpenCode）

### 设计决策

1. **MCP 客户端连接缓存**: 按 `tenant_id` 缓存 MCP 客户端连接（不是工具列表）
2. **工具列表实时获取**: 每次 Activity 执行时调用 `list_tools()`，确保工具最新
3. **MCPTemporalAdapter 初始化**: 在 Worker 启动时初始化
4. **传输自动降级**: 支持 HTTP → SSE 自动降级（借鉴 OpenCode）

### 修改文件清单

#### 1. `src/infrastructure/adapters/secondary/temporal/agent_worker_state.py`

**新增**:
- `_mcp_temporal_adapter` 全局变量
- `set_mcp_temporal_adapter()` / `get_mcp_temporal_adapter()` 函数
- 修改 `get_or_create_tools()` 添加 `tenant_id` 参数，实时加载 MCP 工具

```python
# === 新增 MCP 支持 ===
_mcp_temporal_adapter: Optional[Any] = None

def set_mcp_temporal_adapter(adapter: Any) -> None:
    global _mcp_temporal_adapter
    _mcp_temporal_adapter = adapter
    logger.info("Agent Worker: MCP Temporal Adapter registered")

def get_mcp_temporal_adapter() -> Optional[Any]:
    return _mcp_temporal_adapter

async def get_or_create_tools(
    project_id: str,
    tenant_id: str,  # 新增
    graph_service: Any,
    redis_client: Any,
    llm: Any = None,
) -> Dict[str, Any]:
    """Get tool set for a project, including real-time MCP tools."""
    # 1. 获取缓存的内置工具
    async with _tools_cache_lock:
        if project_id not in _tools_cache:
            # ... 创建内置工具 (同原代码)
            _tools_cache[project_id] = {...}
    
    # 2. 复制内置工具（避免污染缓存）
    tools = dict(_tools_cache[project_id])
    
    # 3. 实时加载 MCP 工具（借鉴 OpenCode 的做法）
    if _mcp_temporal_adapter is not None:
        try:
            from src.infrastructure.mcp.temporal_tool_loader import MCPTemporalToolLoader
            
            loader = MCPTemporalToolLoader(
                mcp_temporal_adapter=_mcp_temporal_adapter,
                tenant_id=tenant_id,
            )
            # 不缓存工具列表，每次实时获取
            mcp_tools = await loader.load_all_tools(refresh=True)
            tools.update(mcp_tools)
            logger.info(f"Loaded {len(mcp_tools)} MCP tools for tenant {tenant_id}")
        except Exception as e:
            logger.warning(f"Failed to load MCP tools: {e}")
    
    return tools
```

#### 2. `src/agent_worker.py`

**新增**:
- 导入 `MCPTemporalAdapter`
- 在 `main()` 中初始化并注册 MCPTemporalAdapter

```python
# 新增导入
from src.infrastructure.adapters.secondary.temporal.mcp.adapter import MCPTemporalAdapter
from src.infrastructure.adapters.secondary.temporal.agent_worker_state import (
    set_mcp_temporal_adapter,
)

# 在 main() 中 graph_service 初始化之后添加:
# Initialize MCP Temporal Adapter
try:
    mcp_temporal_adapter = MCPTemporalAdapter(temporal_client)
    set_mcp_temporal_adapter(mcp_temporal_adapter)
    logger.info("Agent Worker: MCP Temporal Adapter initialized")
except Exception as e:
    logger.warning(f"Agent Worker: Failed to initialize MCP adapter (MCP tools disabled): {e}")
```

#### 3. `src/infrastructure/adapters/secondary/temporal/activities/agent.py`

**修改**:
- 修改 `execute_react_step_activity()` 传递 `tenant_id`

```python
# 修改第 1115 行
tools = await get_or_create_tools(
    project_id=project_id,
    tenant_id=tenant_id,  # 新增
    graph_service=graph_service,
    redis_client=redis_client,
    llm=llm_client,
)
```

### 与原方案的区别

| 方面 | 原方案 | 优化方案 |
|------|--------|---------|
| **工具缓存** | 按 tenant_id 缓存工具列表 | 只缓存内置工具，MCP 实时获取 |
| **实时性** | 需要手动刷新缓存 | 自动获取最新工具 |
| **代码量** | 需要新增缓存管理函数 | 更少代码，复用现有 Loader |
| **性能** | 更快（缓存命中） | 略慢（每次 list_tools） |
| **可靠性** | MCP 服务器状态可能过时 | 总是最新状态 |

### 为什么选择优化方案

1. **更符合 OpenCode 的设计哲学** - 工具列表实时获取，不缓存
2. **更简单** - 减少缓存管理复杂度
3. **更可靠** - 避免缓存不一致问题
4. **性能可接受** - `list_tools()` 调用开销小，且 MCP 客户端连接已复用

## 验证步骤

### 1. 启动服务

```bash
# 终端 1: 启动基础设施
make dev-infra

# 终端 2: 启动 MCP Worker (管理 MCP 服务器连接)
uv run python src/worker_mcp.py

# 终端 3: 启动 Agent Worker (现在会初始化 MCPTemporalAdapter)
uv run python src/agent_worker.py

# 终端 4: 启动 API 服务
make dev-backend
```

### 2. 配置 MCP 服务器

```bash
# 获取 API Key
export API_KEY="ms_sk_your_key_here"

# 创建 MCP 服务器配置 (例如 filesystem)
curl -X POST http://localhost:8000/api/v1/mcp \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "filesystem",
    "description": "File system access",
    "server_type": "stdio",
    "transport_config": {
      "command": ["npx", "-y", "@anthropics/mcp-filesystem"],
      "environment": {},
      "timeout": 30000
    },
    "enabled": true
  }'
```

### 3. 测试 Agent Chat

```bash
# 发送消息到 Agent，使用 MCP 工具
curl -X POST http://localhost:8000/api/v1/agent/chat \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "conversation_id": "test-conv-1",
    "message": "请使用文件系统工具列出当前目录",
    "project_id": "1"
  }'
```

### 4. 验证日志

**Agent Worker 日志检查点**:
```
Agent Worker: MCP Temporal Adapter initialized       # Worker 启动时
Loaded X MCP tools for tenant xxx                    # Activity 执行时
```

**预期结果**:
- Agent 返回的响应中使用了 `mcp__filesystem__*` 工具
- 日志显示 MCP 工具成功加载

### 5. 运行测试

```bash
make test-unit
```

---

## 风险评估

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| MCP Worker 未启动 | MCP 工具加载失败 | warning 日志，不影响内置工具 |
| MCP 服务器连接超时 | 单个工具不可用 | 30s 超时，跳过失败的工具 |
| tenant 无 MCP 配置 | 返回空 MCP 工具列表 | 正常行为，只使用内置工具 |
| 每次实时获取性能 | 略增加延迟 | list_tools() 调用轻量，可接受 |

---

## 后续优化（可选）

1. **添加 MCP 服务器状态 API** - 让前端显示 MCP 连接状态
2. **支持传输自动降级** - HTTP → SSE 自动切换（借鉴 OpenCode）
3. **OAuth 流程优化** - 添加 UI 提示和自动认证流程
4. **MCP 工具权限控制** - 按 SubAgent 配置允许的 MCP 工具
