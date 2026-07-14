# Workspace → Conversation UX 与 Python 后端映射

日期：2026-07-13  
范围：桌面客户端左侧树与工作空间概况

## 1. 真实对象层级

桌面端应遵循后端的权威层级：

```text
Tenant
└── Project
    ├── Project knowledge / sandbox / policy
    └── Workspace
        ├── Members
        ├── Agents
        ├── Goal / Plan / Tasks
        └── Conversation
            ├── Runs / execution session
            ├── HITL decisions
            └── Artifacts / verification evidence
```

Settings 继续负责 Tenant → Project 切换。Global rail 在当前 Project 内展示 Workspace → Conversation 树；Project 不是 Conversation 的父级视觉节点，也不与 Workspace 混用名称。

## 2. 左侧树数据

Workspace 根节点显示：名称、会话数、在线/需关注状态。展开后显示 Conversation；行内保留标题、摘要或最近状态、Work/Code/协作模式图标，以及运行、需要输入、待评审、异常状态。

状态优先级：

1. Pending HITL、阻塞任务、等待 Leader adjudication。
2. 活动 execution session 或执行中的 WorkspaceTask。
3. Active Conversation 的最近活动。
4. Archived Conversation。

`parent_conversation_id` 可作为 SubAgent Session 的第三级树节点；`linked_workspace_task_id` 可作为 Task 标签。展开 Workspace 时按 `workspace_id` 加载 Conversation，避免一次拉取全部工作空间历史。

## 3. 工作空间概况

概况页按可行动性组织，而不是堆叠泛化指标：

- Identity：Workspace 名称、描述、在线/归档、当前 Project。
- Root goal：目标、健康度、证据等级、阻塞原因、计划状态。
- Sessions：运行中、需要输入、待评审与最近会话。
- Team：成员角色、Workspace Agents、Presence。
- Execution：Task 状态、Attempt、Conversation 绑定、execution-session health、沙箱。
- Delivery：已验证产物、候选产物、最终交付物。
- Project knowledge：memory、graph node、active node、storage；必须明确是 Project 级共享统计。
- Activity：Plan events、Workspace messages、Task/Agent/Member/Artifact/HITL 事件。

## 4. 会话详情

Conversation 详情以服务端事件时间为唯一排序依据，同时投影为 Narrative Thread 和 Work Canvas：

- `user_message` / `assistant_message`：保留发送者、时间、正文、附件与引用。
- `act` / `observe` / tool events：按同一 Agent turn 聚合为可折叠工具组，显示工具状态、耗时与摘要。
- Plan / Task / execution-session events：作为系统事件插入时间线，不伪装成聊天消息。
- HITL clarification / decision / env_var / permission：显示持久化请求内容和允许动作，并复用现有响应校验。
- Artifact / verification events：显示产物或验证证据的就绪状态，并在 Work Canvas 与 Overview 提供快速入口。

Thread 保留事件叙事；Canvas 根据 `mode` 与 `artifact_type` 映射 Plan、Changes/Artifact、Terminal/Sources、Checks/Verification。`linked_workspace_task_id`、execution session、participants 和 artifacts 进入 Header 或 Overview。

Diff/证据引用由结构化 UI 控件产生，例如 `{type: "code_range", path, start_line, end_line}`、`{type: "artifact_section", artifact_id, anchor}` 或 `{type: "source", source_id}`。客户端不得通过解析用户输入中的文件名或关键词推断引用。进入 Task canvas 是显式动作，不能替换或重建 Conversation。

## 5. 后端接口

- `GET /api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces`
- `GET .../workspaces/{workspace_id}/members`
- `GET .../workspaces/{workspace_id}/agents`
- `GET /api/v1/agent/conversations?project_id=...&workspace_id=...&group_by_workspace=true`
- `GET /api/v1/agent/conversations/{conversation_id}/messages`
- `GET /api/v1/workspaces/{workspace_id}/tasks`
- `GET /api/v1/workspaces/{workspace_id}/tasks/{task_id}/execution-session`
- `GET /api/v1/workspaces/{workspace_id}/plan?include_details=true`
- `GET /api/v1/agent/hitl/projects/{project_id}/pending`
- `GET /api/v1/projects/{project_id}/stats`
- `GET /api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/messages`
- WebSocket `/api/v1/agent/ws` + `subscribe_workspace`

## 6. 源码锚点

- `src/domain/model/workspace/workspace.py`
- `src/domain/model/workspace/workspace_task.py`
- `src/domain/model/workspace/workspace_task_session_attempt.py`
- `src/domain/model/agent/conversation/conversation.py`
- `src/application/services/workspace_task_experience_service.py`
- `src/application/services/task_execution_session_monitor.py`
- `src/application/schemas/project.py`
- `src/infrastructure/adapters/primary/web/routers/workspaces.py`
- `src/infrastructure/adapters/primary/web/routers/workspace_tasks.py`
- `src/infrastructure/adapters/primary/web/routers/workspace_plans.py`
- `src/infrastructure/adapters/primary/web/routers/agent/conversations.py`
- `src/infrastructure/adapters/primary/web/routers/agent/messages.py`
- `src/infrastructure/adapters/primary/web/routers/agent/hitl.py`
- `src/infrastructure/adapters/primary/web/websocket/handlers/workspace_handler.py`

## 7. 原型边界

当前高保真原型使用与上述对象同构的 mock 数据。生产实现必须从服务端读取成员权限、会话状态、HITL 和执行健康；客户端不得根据标题关键词自行判断语义状态，也不得把 Project Artifact 或 Project Memory 总量冒充 Workspace 独占数据。
