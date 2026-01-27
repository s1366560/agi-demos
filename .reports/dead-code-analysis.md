# AgentV2 相关代码死代码分析报告

生成时间: 2026-01-27

## 执行摘要

**结论**: 没有发现可以安全删除的死代码。

所有 AgentV2 相关代码都是活跃使用的：
- `AgentChatV2` 页面在路由 `/project/:projectId/agent-v2` 上可用
- `agentV2.ts` store 被 `AgentChatV2` 页面使用
- `agentV2Service.ts` 被 `agentV2.ts` store 使用
- 后端的 `stream_chat_v2` 是当前唯一的 Agent 聊天实现

## 发现的文件及其状态

### 后端文件

| 文件 | 状态 | 说明 |
|------|------|------|
| `src/application/services/agent_service.py:stream_chat_v2` | **活跃** | 当前唯一的 Agent 聊天实现 |
| `src/application/use_cases/agent/chat.py` | **活跃** | 使用 `stream_chat_v2` |
| `src/infrastructure/adapters/primary/web/routers/agent_websocket.py` | **活跃** | 使用 `stream_chat_v2` |
| `src/domain/ports/services/agent_service_port.py` | **活跃** | 定义 `stream_chat_v2` 接口 |

### 前端文件

| 文件 | 状态 | 说明 |
|------|------|------|
| `web/src/stores/agentV2.ts` | **活跃** | 被 `AgentChatV2` 页面使用 |
| `web/src/services/agentV2Service.ts` | **活跃** | 被 `agentV2.ts` store 使用 |
| `web/src/pages/project/AgentChatV2.tsx` | **活跃** | 路由 `/project/:projectId/agent-v2` |
| `web/src/components/agentV2/` | **活跃** | AgentChatV2 页面使用的组件 |
| `web/src/stores/agentV2/` | **空目录** | 可以删除（只有 `.` 和 `..`） |

### 前端版本对比

| 版本 | 文件 | 使用状态 | 路由 |
|------|------|----------|------|
| V1 | `agent.ts` | 被其他组件使用 | - |
| V2 | `agentV2.ts` | 被 `AgentChatV2` 使用 | `/project/:projectId/agent-v2` |
| V3 | `agentV3.ts` | 被 `AgentChatV3` 使用 | `/project/:projectId/agent` (默认) |

## 当前架构说明

前端使用 **版本策略** 来管理不同的 Agent 实现：

1. **V3 (`AgentChatV3`)**: 当前默认版本，路由 `/project/:projectId/agent`
2. **V2 (`AgentChatV2`)**: 备用/实验版本，路由 `/project/:projectId/agent-v2`
3. **V1 (`agent.ts` store)**: 基础 store，被其他组件复用

后端只有一个实现 `stream_chat_v2`，所有前端版本都调用同一个后端接口。

## 可安全删除的文件

### 1. 空目录（可删除）

```bash
web/src/stores/agentV2/
```

这是一个空目录，可以安全删除。

## 不能删除的代码

以下代码虽然名为 "V2"，但是活跃使用的核心功能：

### 后端
- `stream_chat_v2` 方法 - 这是当前唯一的 Agent 聊天实现

### 前端
- `AgentChatV2` 页面 - 提供独立的 `/project/:projectId/agent-v2` 路由
- `agentV2.ts` store - AgentChatV2 页面的状态管理
- `agentV2Service.ts` - AgentChatV2 的 API 服务层

## 建议

1. **重命名**: 考虑将 `stream_chat_v2` 重命名为 `stream_chat`，因为它已经是唯一的实现
2. **清理空目录**: 删除 `web/src/stores/agentV2/` 空目录
3. **文档更新**: 如果 V2 版本不再需要维护，应该更新文档说明

## 清理命令

如果要删除空目录（唯一可安全删除的项目）：

```bash
rmdir web/src/stores/agentV2/
```

