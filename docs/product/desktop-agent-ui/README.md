# MemStack 桌面 Agent 客户端设计交付包

更新日期：2026-07-10

本交付包定义 MemStack 桌面客户端的完整产品方向：以同一套项目、任务、线程、记忆、权限、运行状态和产物模型，支持“通用 Agent（Work）”与“编程 Agent（Code）”两类核心场景，并在 Settings 内提供 Models、Skills、Plugins、Agents 的统一治理工作台与中英文切换。

## 交付物

- [竞品与用户问题研究](01-competitive-research.md)
- [产品 PRD](02-product-prd.md)
- [产品 PRD（PDF）](MemStack-Desktop-Agent-Client-PRD.pdf)
- [产品 PRD（Word）](MemStack-Desktop-Agent-Client-PRD.docx)
- [UI/UX 设计规范](03-ui-ux-spec.md)
- [LLM Provider 配置 UX 研究](04-llm-provider-ux-research.md)
- [可交互高保真原型](../../../design-prototype/memstack-desktop-agent-mission-control/)
- [视觉方向 1：Adaptive Task Canvas](visual-directions/01-adaptive-task-canvas.png)
- [视觉方向 2：My Work Mission Control（已选主方向）](visual-directions/02-my-work-mission-control.png)
- [视觉方向 3：Shared Workspace Deck](visual-directions/03-shared-workspace-deck.png)

## 当前设计决策

产品不采用两套彼此割裂的“通用助手”和“代码工具”。两种场景共享同一个任务内核，在任务级别切换 Work / Code 能力集；共享的项目上下文、企业记忆、运行历史、通知、权限与审批不会因模式切换而丢失。

视觉主方向已锁定为 **My Work Mission Control**。配套原型已实现 Work / Code 双模式、任务状态分组、审批输入、来源查看、代码变更与终端标签、暂停/恢复、Review 和 Steer；Settings → Models 已采用 Provider-first 配置，覆盖认证、Endpoint、连接验证、模型发现、模型启用与工作区路由，Skills、Plugins、Agents 继续共享统一治理工作台，并支持 English / 简体中文即时切换与本地持久化。
