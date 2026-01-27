# 重构方案：对齐事件体系与清理遗留代码

## 1. 现状分析

在之前的重构中，我们建立了基于 `AgentDomainEvent` 的强类型领域事件体系，并更新了核心 Agent 逻辑（Processor, SkillExecutor）。然而，目前的搜索结果显示仍有部分代码处于“脱离”状态：

1.  **CUA (Computer Use Agent) 桥接 (`sse_bridge.py`)**: 仍然直接依赖并实例化旧的 `SSEEvent`，需要更新为生成 `AgentDomainEvent`，然后使用适配器转换为 SSE。
2.  **应用服务 (`agent_service.py`)**: 直接实例化 `AgentExecutionEvent` (领域实体) 并调用 `to_sse_format()`，这部分逻辑应改为使用 `AgentDomainEvent`，利用其作为统一的数据源。
3.  **Temporal Activities**: 直接操作数据库模型 `AgentExecutionEvent` (SQLAlchemy model)，虽然这属于基础设施层的直接数据访问，但应确保其数据结构与领域事件保持一致（目前通过 Repository 转换，风险较低，但需检查）。

## 2. 重构目标

确保系统中的所有事件源头（无论是 Agent 核心、CUA 插件还是 Service 层手动创建）都统一生成 `AgentDomainEvent`，然后通过适配器转换为传输格式 (SSE) 或持久化格式 (DB Entity)。

## 3. 详细实施步骤

### 3.1 重构 CUA SSE Bridge
*   **文件**: `src/infrastructure/agent/cua/callbacks/sse_bridge.py`
*   **任务**:
    *   修改 `convert_event` 方法，使其返回 `AgentDomainEvent` 而非 `SSEEvent`。
    *   更新调用方（如果有），确保它们能处理 Domain Event 或使用 `SSEEvent.from_domain_event()` 进行转换。

### 3.2 重构 Agent Service
*   **文件**: `src/application/services/agent_service.py`
*   **任务**:
    *   检查 `stream_chat_v2` 和其他方法中手动创建事件的地方（如 `user_msg_event`）。
    *   改为实例化 `AgentMessageEvent` (Domain Event)。
    *   使用 `AgentExecutionEvent.from_domain_event()` 创建持久化实体。
    *   使用 `SSEEvent.from_domain_event()` 创建流式响应。

### 3.3 验证与清理
*   **文件**: `src/infrastructure/agent/core/events.py`
*   **任务**: 检查旧的 `SSEEvent` 工厂方法（如 `thought()`, `act()`）是否仍有被引用的地方。如果在上述重构后不再使用，标记为 `Deprecated` 或移除，以强制统一使用 `from_domain_event`。

## 4. 预期收益
*   **统一数据流**: 所有事件流都源自强类型的 `AgentDomainEvent`。
*   **消除歧义**: 明确区分“事件发生”（Domain）与“事件传输”（Infrastructure）。
*   **减少维护成本**: 修改事件结构时只需调整 Domain Event 定义，适配器会自动处理格式转换。
