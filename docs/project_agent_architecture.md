# Project-Level ReActAgent Architecture (Ray Actors)

本架构基于 Ray Actor 实现项目级常驻 Agent。

## Overview

每个项目对应一个 Ray Actor，负责持久化的 ProjectReActAgent 执行。

## 核心组件

### ProjectReActAgent

`src/infrastructure/agent/core/project_react_agent.py`

```python
class ProjectReActAgent:
    def __init__(self, config: ProjectAgentConfig)
    async def initialize(self, force_refresh: bool = False) -> bool
    async def execute_chat(...) -> AsyncIterator[Dict[str, Any]]
    def get_status(self) -> ProjectAgentStatus
```

### ProjectAgentActor

`src/infrastructure/agent/actor/project_agent_actor.py`

```python
class ProjectAgentActor:
    async def initialize(self, config, force_refresh: bool = False) -> None
    async def chat(self, request: ProjectChatRequest) -> ProjectChatResult
    async def continue_chat(self, request_id: str, response_data: Dict[str, Any]) -> ProjectChatResult
    async def cancel(self, conversation_id: str) -> bool
    async def status(self) -> ProjectAgentStatus
```

### Actor Manager

`src/infrastructure/agent/actor/actor_manager.py`

```python
async def get_or_create_actor(tenant_id, project_id, agent_mode, config):
    ...
```

## Application Service

`src/application/services/agent_service.py` 通过 Ray 获取 Actor 并调用 `chat`/`continue_chat`。

## 配置

- `RAY_ADDRESS` 控制 Ray Client 地址
- `RAY_NAMESPACE` 控制命名空间
