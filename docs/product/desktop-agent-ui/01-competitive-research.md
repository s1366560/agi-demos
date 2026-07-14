# 桌面 Agent 客户端竞品与用户问题研究

研究对象：GitHub Copilot App、Codex / ChatGPT Desktop、MemStack 当前桌面实现
目标用户：知识工作者、产品/运营人员、软件工程师、技术负责人、企业管理员
时间范围：重点覆盖 2026 年 2 月至 2026 年 7 月的公开资料
研究日期：2026-07-10

## 1. Executive Read

Agent 桌面产品的核心竞争已经从“模型能否完成任务”转向“用户能否同时指挥、观察、审阅和接管多个长任务”。GitHub Copilot App 的优势是把 Issue、会话、Worktree、PR、CI 与合并闭环放进同一产品；Codex / ChatGPT Desktop 的优势是把通用知识工作、文件产物、浏览器、计算机操作和本地编程环境放入同一任务系统。两者共同证明，聊天不是最终的信息架构：聊天适合表达意图和消除歧义，真正的工作需要可检查的画布、产物和决策点。

公开用户反馈集中在四类高风险问题：运行状态不可相信、Worktree/分支语义不清、长任务恢复与历史列表不可靠、客户端在大型工作区或多任务下性能下降。对 MemStack 来说，机会不是简单复制两者，而是把企业记忆和可审计决策链作为共享内核，让通用工作与编程任务在一个任务对象中连续流转。

结论：MemStack 应采用“统一任务内核 + 双能力模式 + 自适应工作画布”。主导航围绕 Home、My Work、Automations、Search 和 Projects；任务页围绕状态、计划、产物、环境、审批和可恢复性，而不是围绕聊天消息数量。

## 2. 竞品产品模型

### 2.1 GitHub Copilot App

观察证据：

- GitHub 将 Copilot App 定义为面向 Agent 驱动开发的桌面应用，核心能力包含并行工作区、GitHub 原生 Issue/PR 上下文、会话模式、自动化、Quick chats 和 Canvas。[GitHub Copilot App 概念文档](https://docs.github.com/en/copilot/concepts/agents/github-copilot-app)
- 每个会话可运行在新 Worktree、本地仓库或云沙箱中，并提供 Interactive、Plan、Autopilot 三种自主程度。[Agent sessions 文档](https://docs.github.com/en/copilot/how-tos/github-copilot-app/agent-sessions)
- My Work 将 Issue、PR 和活跃工作集中展示，Issue 可以预加载上下文并默认进入 Plan；PR 可查看概览、CI、Review activity、Files changed，并发起修复或 Agent Merge。[Issue 与 PR 工作流](https://docs.github.com/en/copilot/how-tos/github-copilot-app/managing-issues-and-pull-requests)
- Canvas 被定位为“人与 Agent 共同操作的工作表面”，可承载计划、浏览器、终端、部署、仪表盘和流程状态。[Canvas 文档](https://docs.github.com/en/enterprise-cloud%40latest/copilot/how-tos/github-copilot-app/working-with-canvas-extensions)
- Automations 支持本地或云端运行、手动/定时/Issue 触发，并在创建时限定可用工具。[Automations 文档](https://docs.github.com/en/copilot/how-tos/github-copilot-app/using-automations)

设计优点：

- 用 My Work 解决“我现在应该处理什么”，而不是把用户直接扔进空聊天。
- GitHub 对象天然成为上下文和交付物，Issue 到 PR 的闭环非常短。
- Quick chat 与正式 Session 分开，降低无意义 Worktree 的创建成本。
- Canvas 明确承认聊天不足以承载复杂工作的事实。

局限与推断：

- 产品价值高度绑定 GitHub 对象模型；跨文档、数据、内部业务系统的通用工作不是主路径。
- 2026 年 6 月后公开上线时间较短，社区问题样本仍偏少；当前不能从少量讨论推断普遍满意度。
- 功能持续扩张后，My Work、Sessions、Automations、Canvas、PR Review 之间可能出现入口竞争，需要严格的任务模型约束。

### 2.2 Codex / ChatGPT Desktop

观察证据：

- Codex App 最初被定义为“Agent 的指挥中心”，强调项目分组线程、并行 Agent、Worktree、Diff 审阅、Skills 与 Automations。[Codex App 发布说明](https://openai.com/index/introducing-the-codex-app/)
- 2026 年 4 月更新将能力扩展到计算机操作、插件、图像、PR 审阅、多文件、多终端、SSH Devbox 和内置浏览器，方向从纯代码工具走向通用工作平台。[Codex for (almost) everything](https://openai.com/index/codex-for-almost-everything/)
- 当前桌面产品将 Project、Chat、Work 和 Codex 放入同一应用。Project 统一组织聊天、任务、文件和来源；Chat / Work 改变处理方式，而不是改变会话归属。[Projects, chats, and tasks](https://learn.chatgpt.com/docs/projects)
- Codex 任务可选择 Local、Worktree 或 Cloud；Worktree 支持并行任务和 Local/Worktree Handoff。[环境模式](https://learn.chatgpt.com/docs/environments/modes)、[Worktree 文档](https://learn.chatgpt.com/docs/environments/git-worktrees)
- 每个任务有项目/Worktree 作用域终端，Agent 可读取当前终端输出；审阅面板支持行级反馈、Stage、Revert、Commit、Push。[集成终端](https://learn.chatgpt.com/docs/integrated-terminal)、[Code review](https://learn.chatgpt.com/docs/code-review)
- 内置浏览器为人与 Agent 提供共享网页和本地应用视图，但与日常浏览器 Profile 隔离。[Browser 文档](https://learn.chatgpt.com/docs/browser)

设计优点：

- 通用工作、文件产物与编程环境共享项目和任务概念，跨场景连续性强。
- Local / Worktree / Cloud 是任务启动时的一等选择。
- Terminal、Browser、Review pane 均是工作表面，而不是日志附件。
- Skills / Plugins 让产品能扩展到企业工作流，而不把全部能力硬编码在主界面。

局限与公开反馈：

- 有用户报告活跃任务实际仍在运行，但 UI 停留在 Thinking、Stop 无效或重启后任务不可见；这直接伤害“Agent 指挥中心”的安全基础。[openai/codex#24287](https://github.com/openai/codex/issues/24287)
- Worktree 入口、Detached HEAD 下可用操作和 Diff 范围曾产生明显困惑。[openai/codex#11181](https://github.com/openai/codex/issues/11181)、[openai/codex#10704](https://github.com/openai/codex/issues/10704)
- 大型工作区扫描可能引发卡顿或崩溃，用户需要可见的索引范围和排除规则。[openai/codex#10996](https://github.com/openai/codex/issues/10996)
- 本地数据库仍有会话但侧栏未显示的反馈，说明历史与恢复必须作为产品状态而不是仅作为列表渲染。[openai/codex#21076](https://github.com/openai/codex/issues/21076)
- Reddit 上关于并行 Worktree 的反馈同时包含高价值与高困惑信号，适合用来发现问题，不足以估计发生率。[规模化使用讨论](https://www.reddit.com/r/codex/comments/1sc7g2x/how_are_you_actually_running_codex_at_scale/)

## 3. MemStack 当前桌面实现

仓库证据：

- 已存在 Tauri + React 桌面应用：`agi-stack/apps/desktop`。
- 已实现 Session 侧栏、Runs、Agents、Memory、Artifacts、Runtime、Chat、Board、Workspace Dock、Terminal、Changes、Pull request、Plan、Tool events 和 Artifacts 等大量表面。
- 当前视觉采用深色基础色 `#080C12`，面板 `#0F141D / #151A24`，状态色 Cyan/Green/Amber/Red，适合延续。
- 当前 `App` 主函数覆盖约 3,000 行并直接协调大量状态和表面。后续大规模 UX 实现前，应将 Shell、Task State、Navigation、Workspace Canvas 和 Approval 分离，否则设计迭代成本会持续上升。

当前体验问题（基于本地实现与页面检查）：

- Quick links 同时包含 Runs、Agents、Memory、Artifacts、Runtime，而 Session/Workspace 又拥有 Changes、PR、Plan、Terminal、Tool events、Artifacts，存在全局对象与任务内对象的层级重复。
- 登录前主界面已经暴露大量编程概念，通用用户难以理解第一步。
- “Runs、Sessions、Workspaces、Conversations、Tasks”在界面和后端中同时存在，需要统一用户语言。
- 右侧 Workspace Dock 已具备演进为自适应画布的基础，但当前更像多 Tab 工具箱，尚未围绕当前决策组织。

## 4. 排名后的 UX 问题

### P0：运行状态不可信

- 用户目标：明确知道 Agent 是否仍在运行、等待、暂停、断开、失败或已经完成。
- 破坏点：UI 与真实执行脱节时，用户可能重复发起任务、无法停止副作用，或误以为工作丢失。
- 严重度：Critical。
- 频率信号：多个公开 Issue；无法从公开样本量估计整体比例。
- 置信度：高（问题存在），中（普遍性）。
- 产品动作：服务端权威状态 + monotonic revision；每个任务显示最后心跳、环境、执行 ID、可恢复动作；UI 不得用模糊 “Thinking” 覆盖所有状态。

### P0：环境、Worktree 与分支语义不清

- 用户目标：知道 Agent 在哪里改了什么，以及这些改动如何进入本地或 PR。
- 破坏点：入口消失、Detached HEAD、Local/Worktree Handoff 和 Diff 范围不一致会让用户无法预测结果。
- 严重度：High。
- 频率信号：多个 Codex Issue 与社区讨论。
- 置信度：高。
- 产品动作：任务 Header 永久显示 Environment + Checkout + Branch；危险/不可用动作解释原因；Handoff 使用可预览步骤而不是单一动词。

### P0：审批脱离工作上下文

- 用户目标：在看到风险、变更、来源和影响范围的同一处做决定。
- 破坏点：如果审批只出现在聊天卡片或全局通知，用户需要在多个表面拼接证据。
- 严重度：High。
- 频率信号：GitHub 对审阅负担的官方问题陈述，且多 Agent 输出会放大该问题。[GitHub Copilot App 发布文章](https://github.blog/news-insights/product-news/github-copilot-app-the-agent-native-desktop-experience/)
- 置信度：高。
- 产品动作：审批卡固定在受影响的 Canvas 旁边；显示动作、目标、数据、风险、可逆性与适用范围。

### P1：聊天滚动无法承载真实工作

- 用户目标：直接检查计划、文档、表格、网页、Diff、终端和最终产物。
- 破坏点：日志和工具调用淹没意图，最终产物难以发现或继续编辑。
- 严重度：High。
- 频率信号：GitHub Canvas 与 Codex 多工作表面方向一致。
- 置信度：高。
- 产品动作：Canvas 为主、Timeline 为辅；工具活动默认折叠；产物有版本和生命周期。

### P1：任务队列不能表达“现在需要我做什么”

- 用户目标：在多个项目和 Agent 中迅速找到 Needs input、Needs approval、Ready to review。
- 破坏点：仅按最近时间列 Session，会把重要决策淹没在活跃日志中。
- 严重度：Medium-High。
- 频率信号：GitHub My Work 的产品结构直接回应此问题。
- 置信度：高。
- 产品动作：My Work 使用语义分组，不默认按聊天最近活动排序。

### P1：长任务恢复与历史缺少可验证性

- 用户目标：重启、断网、跨设备或切换项目后继续工作。
- 破坏点：侧栏丢失条目、缓存与服务端状态不一致、重新发送造成重复执行。
- 严重度：High。
- 频率信号：公开 Issue 与多窗口反馈。
- 置信度：中高。
- 产品动作：独立的恢复页、重复执行保护、运行 revision、最近同步时间、显式 “Reconnect / Resume / Fork recovery”。

### P2：大型项目扫描与多任务性能缺少边界

- 用户目标：知道索引什么、为什么变慢、如何排除大目录。
- 破坏点：应用卡顿或崩溃，但用户只能通过移走目录规避。
- 严重度：Medium-High。
- 频率信号：少量但高影响的公开 Issue。
- 置信度：中。
- 产品动作：索引状态与排除规则可见；默认尊重 `.gitignore`；大目录预警；后台索引资源预算。

## 5. 机会地图

### 本周可做

- 统一状态词：Running、Paused、Needs input、Needs approval、Ready to review、Failed、Disconnected。
- 在任务 Header 永久显示 Environment、Branch、Execution ID 和 Last update。
- 将通用任务与代码任务放进同一 My Work 语义队列。
- 将 Tool events 默认折叠，保留当前动作和验证结果。

### 本季度可做

- 自适应 Canvas：Work 模式的 Sources/Browser/Document/Data/Artifact；Code 模式的 Plan/Browser/Changes/Terminal/Artifact。
- 上下文审批：每个审批带风险、范围、可逆性和证据。
- 任务恢复协议与跨窗口唯一运行状态。
- 统一 Project / Task / Thread / Run / Artifact 用户模型。

### 需要进一步验证

- 非开发者是否理解 Work / Code，或更适合“能力标签 + 自动建议”。
- 多任务用户更偏好 My Work 队列还是项目树作为默认首页。
- 右侧审批 Rail 与 Canvas 内嵌审批的可发现性差异。
- 企业管理员对本地、云端和连接器数据边界的理解成本。

## 6. 产品差异化

MemStack 不应定位为 GitHub Copilot App 的替代 IDE，也不应只做 Codex App 的外观复制。其差异化是：

- 企业记忆原生：来源、历史决策、实体关系和组织知识可追溯。
- 一项任务可跨 Work 与 Code，而不用复制上下文或新开产品。
- 每个主观决策由 Agent 生成结构化理由并进入审计链。
- 本地、Worktree、Sandbox、Cloud 和企业连接器共享一套权限模型。
- 最终交付以可审阅 Artifact 为中心，聊天只是协作过程的一部分。

## 7. Source Map

高信号官方来源：GitHub Docs / Blog、OpenAI 发布说明、ChatGPT Learn Codex 文档。
问题发现来源：openai/codex Issues、Reddit。社区来源只用于发现问题与表述方式，不用于估算发生率。
本地来源：`agi-stack/apps/desktop` 代码、现有 QA 记录、运行中的本地页面与设计原型。
