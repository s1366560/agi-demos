# Agent Worker 生命周期优化规划

## 概述

将 Agent Worker 改造为类似 MCP Worker 的高效生命周期模式，通过 **Agent Session Pool** 缓存复用组件，避免每次请求重复初始化，预期后续请求延迟降低 95%+。

## 问题分析

### 当前架构瓶颈

每次 `execute_react_agent_activity` 执行时：

| 组件初始化 | 耗时 | 问题 |
|-----------|------|------|
| `_convert_tools()` | 50-200ms | 每次重新创建闭包和提取 schema |
| MCP 工具加载 | 200-500ms | 每次 `refresh=True` 触发 Temporal Workflow |
| `SubAgentRouter` | 10-50ms | 每次重新构建关键词索引 |
| `ReActAgent` 实例 | 50-100ms | 每次完整初始化 |
| **总计** | **~300-800ms** | 首次与后续请求耗时相同 |

### MCP Worker 的成功模式

```python
# MCP Worker 全局客户端缓存
_mcp_clients: Dict[str, MCPClient] = {}

# Workflow 长连接
await workflow.wait_condition(lambda: self._stop_requested)
```

- Workflow 维持长连接，subprocess 常驻
- 全局 `_mcp_clients` 缓存，Activity 间复用
- 首次连接后，工具调用直接使用缓存客户端

## 解决方案：Agent Session Pool

### 架构对比

```
优化前：每次请求 ~300-800ms
┌────────────────────────────────────────┐
│ execute_react_agent_activity           │
│   ├─ _convert_tools()      [50-200ms]  │
│   ├─ load_mcp_tools()      [200-500ms] │
│   ├─ SubAgentRouter()      [10-50ms]   │
│   └─ ReActAgent()          [50-100ms]  │
└────────────────────────────────────────┘

优化后：首次 ~300-800ms，后续 <20ms
┌────────────────────────────────────────┐
│ Agent Session Pool (全局缓存)          │
│   ├─ _agent_session_pool              │
│   ├─ _tool_definitions_cache          │
│   ├─ _mcp_tools_cache (TTL=5min)      │
│   └─ _subagent_router_cache           │
└────────────────────────────────────────┘
                    ↓
┌────────────────────────────────────────┐
│ execute_react_agent_activity           │
│   ├─ get_cached_session()    [<1ms]   │
│   ├─ DoomLoopDetector.reset() [<1ms]  │
│   └─ SessionProcessor()       [5-10ms]│
│                              [<20ms]  │
└────────────────────────────────────────┘
```

### 核心数据结构

```python
@dataclass
class AgentSessionContext:
    """可复用的 Agent 会话上下文"""
    session_key: str  # "{tenant_id}:{project_id}:{agent_mode}"
    
    # 缓存的组件（无状态，可复用）
    tool_definitions: List[ToolDefinition]
    subagent_router: Optional[SubAgentRouter]
    skill_executor: Optional[SkillExecutor]
    system_prompt_manager: SystemPromptManager  # 全局单例
    processor_config: ProcessorConfig
    
    # 缓存有效性检测
    tools_hash: str
    skills_hash: str
    
    # TTL 控制
    created_at: float
    last_used_at: float
    ttl_seconds: int = 1800  # 30分钟
```

## 实施步骤

### Phase 1: 基础缓存层 (1-2天)

1. **创建 `agent_session_pool.py`**
   - `AgentSessionContext` 数据类
   - `get_or_create_session()` 核心逻辑
   - `cleanup_expired_sessions()`

2. **修改 `agent_worker_state.py`**
   - 添加全局缓存字典
   - `get_or_create_tool_definitions()`

### Phase 2: 工具定义缓存 (1天)

1. **修改 `execute_react_agent_activity`**
   - 使用缓存的 `tool_definitions`
   - 添加 `tools_hash` 变更检测

2. **优化 `ReActAgent._convert_tools()`**
   - 添加 `convert_tools_with_cache()` 静态方法

### Phase 3: MCP 工具缓存 (1-2天)

1. **添加 `_mcp_tools_cache` 逻辑**
   - TTL 5分钟
   - 版本号机制

2. **修改 `temporal_tool_loader.py`**
   - `load_all_tools(refresh=False)` 默认使用缓存

### Phase 4: 其他组件缓存 (1天)

1. `SubAgentRouter` 缓存
2. `SystemPromptManager` 全局单例
3. 定时清理任务

### Phase 5: 验证与调优 (1天)

## 关键文件变更

### 新建文件

| 文件 | 用途 |
|------|------|
| `src/infrastructure/adapters/secondary/temporal/agent_session_pool.py` | 核心 Session Pool 实现 |

### 修改文件

| 文件 | 变更 |
|------|------|
| `src/infrastructure/adapters/secondary/temporal/agent_worker_state.py` | 添加全局缓存和访问函数 |
| `src/infrastructure/adapters/secondary/temporal/activities/agent.py` | 重构使用 Session Pool |
| `src/infrastructure/agent/core/react_agent.py` | 优化 `_convert_tools()`，支持外部 `system_prompt_manager` |
| `src/infrastructure/mcp/temporal_tool_loader.py` | MCP 工具 TTL 缓存 |
| `src/agent_worker.py` | 添加定时清理任务 |

## 验证方案

### 单元测试

```bash
# 新增测试文件
uv run pytest src/tests/unit/temporal/test_agent_session_pool.py -v
```

测试用例：
- 缓存命中/未命中
- TTL 过期失效
- 工具变更自动失效
- 并发访问安全

### 性能测试

```bash
# 压力测试脚本
python scripts/benchmark_agent_worker.py
```

预期指标：
- 首次请求：300-800ms（不变）
- 后续请求：<20ms（降低 95%+）
- 缓存命中率：>90%

### 端到端验证

1. 启动 `make dev`
2. 通过 Agent Chat 发送多次请求
3. 观察 Temporal UI 中 Activity 执行时间
4. 检查 Worker 日志中的缓存命中信息

## 风险与应对

| 风险 | 应对措施 |
|------|---------|
| 缓存失效时机不当 | 严格的 hash 检测 + 版本号机制 |
| 内存占用过高 | LRU 淘汰 + 定时清理 + 监控告警 |
| 并发竞争条件 | `asyncio.Lock` + 不可变数据结构 |

## 预期收益

- **性能提升**：后续请求延迟降低 95%+（<20ms）
- **吞吐量提升**：Agent Worker 吞吐量提升 10-20 倍
- **资源优化**：减少 Temporal Workflow 调用和 CPU 消耗
