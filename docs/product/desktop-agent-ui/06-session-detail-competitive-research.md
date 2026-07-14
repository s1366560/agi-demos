# 会话详情竞品研究：Codex App × GitHub Copilot App

日期：2026-07-13  
范围：桌面客户端的 Agent Session / Conversation Detail  
目标用户：同时监督通用 Agent 与编程 Agent 的个人贡献者、技术负责人和评审者

## 1. 执行摘要

会话详情的核心矛盾不是“聊天记录是否完整”，而是 Agent 产生的工作已经超过聊天能够承载的复杂度。Codex App 将线程和可审阅变更放在同一任务空间，减少从叙事到代码证据的跳转；GitHub Copilot App 进一步把右侧 Canvas 定义为与对话协作、可编辑、可验证的工作对象。两者共同说明：对话负责意图、解释与纠偏，结构化工作面负责计划、变更、终端、浏览器和验证；但工作面不应在用户尚未审阅具体对象时持续挤压会话。

当前 MemStack 原型已经具备会话消息、工具活动和 Task 上下文，但仍把过程日志作为主内容，并用固定右栏展示静态运行信息。用户需要在长时间线中寻找“真正变化了什么”和“现在要我做什么”，也无法直接从变更行引用上下文进行 Steering。重新设计应把会话压缩为可读叙事，把工作证据提升为可切换 Canvas，并让审批、验证和引用成为一等交互。

## 2. 观察证据

### 2.1 Codex App

官方定位把 Codex App 定义为多 Agent 指挥中心：任务按 Project 组织为独立 Thread，用户可在线程中审阅变更、评论 Diff，并在编辑器中继续修改；Worktree 隔离允许多个 Agent 并行工作而不污染本地 Git 状态。最新桌面产品文档进一步把“保持所有任务可见、在同一工作空间打开真实输出、跨浏览器/桌面应用/插件继续工作”作为桌面体验的三项基础能力；跨设备能力则强调从运行机器恢复 Threads、Approvals、Plugins 与 Project context 的实时状态。

最新桌面界面进一步将 Conversation 与 Thread context 并排：左侧保留用户意图、Agent 总结和简化活动；右侧以 Tab 呈现 Code changes、文档、表格或其他产物。Diff 支持直接编辑、批注、请求 Codex 修改选中内容；PR Review 在侧边栏与 Diff 同屏。

Review 不是单一“变更列表”，而是可切换 Last turn、Unstaged、Staged、Commit、Branch 等范围的任务内工作面；终端同样属于当前 Project/Worktree，可从任务中直接打开并把运行证据留在 Thread。Local、Worktree 与 Cloud 是任务创建时的执行环境，Handoff 负责在不丢失任务状态的前提下迁移工作位置。

来源：

- [Introducing the Codex app](https://openai.com/index/introducing-the-codex-app/)
- [ChatGPT desktop app](https://learn.chatgpt.com/docs/app)
- [Work with Codex from anywhere](https://openai.com/index/work-with-codex-from-anywhere/)
- [OpenAI product release notes](https://openai.com/products/release-notes/)
- [Code review](https://learn.chatgpt.com/docs/code-review)
- [Integrated terminal](https://learn.chatgpt.com/docs/integrated-terminal)
- [Local, worktree, and cloud modes](https://learn.chatgpt.com/docs/environments/modes)
- [Git worktrees](https://learn.chatgpt.com/docs/environments/git-worktrees)
- [Agent approvals and security](https://learn.chatgpt.com/docs/agent-approvals-security)
- 视觉证据：`design-prototype/memstack-desktop-agent-mission-control/qa/reference-codex-app-session-focused.png`

### 2.2 GitHub Copilot App

Copilot App 将每个 Session 定义为独立的 Branch、Files、Conversation 和 Task state，并将“Plan / Diff / Terminal / Browser / PR”放进同一 Session。2026 年 6 月引入 Canvas 后，GitHub 明确区分 Chat 与工作面：Chat 用于定义意图和讨论歧义，Canvas 用于让工作对象可见、可编辑、可重排、可审批和可验证。

Session 创建时显式选择执行位置、Interactive / Plan / Autopilot 模式、模型与推理强度；Quick Chat 与会产生分支或 Worktree 的可执行 Session 分离。运行中的消息支持立即 Steering 或顺序 Queueing，子智能体活动默认折叠，只保留当前目标、状态和耗时的 HUD，需要审计时再展开完整输出。

Session logs 采用相似工具调用分组、内联输出预览、可展开 Diff、工具图标和可见 Bash 命令来降低噪声。Session 详情还提供实时状态、Token/时长、Steer、Stop、Archive、Share、CLI/IDE 交接以及与 Commit/PR 的追溯关系。2026 年 6 月，GitHub 又把 Session logs 暴露给 Copilot Chat，并提供 Session search，使用户可以在新对话中追问过去 Session “改了什么、验证了什么、为什么这么做”；这说明会话详情需要既适合实时监督，也必须形成可检索、可复用的长期记录。

来源：

- [About the GitHub Copilot app](https://docs.github.com/en/copilot/concepts/agents/github-copilot-app)
- [Expanded GitHub Copilot app technical preview](https://github.blog/changelog/2026-06-02-expanded-technical-preview-availability-for-the-github-copilot-app/)
- [GitHub Copilot app generally available](https://github.blog/changelog/2026-06-17-github-copilot-app-generally-available/)
- [Managing agent sessions](https://docs.github.com/en/copilot/how-tos/copilot-on-github/use-copilot-agents/manage-and-track-agents)
- [Working with canvas extensions](https://docs.github.com/en/copilot/how-tos/github-copilot-app/working-with-canvas-extensions)
- [Working with agent sessions in the GitHub Copilot app](https://docs.github.com/en/copilot/how-tos/github-copilot-app/agent-sessions)
- [Managing issues and pull requests with the GitHub Copilot app](https://docs.github.com/en/copilot/how-tos/github-copilot-app/managing-issues-and-pull-requests)
- [More visibility into coding-agent sessions](https://github.blog/changelog/2026-03-19-more-visibility-into-copilot-coding-agent-sessions/)
- [Copilot Chat now sees your agent sessions](https://github.blog/changelog/2026-06-10-copilot-chat-now-sees-your-agent-sessions/)
- 视觉证据：`design-prototype/memstack-desktop-agent-mission-control/qa/reference-copilot-app-session.png`

### 2.3 公开反馈信号

GitHub Community 对新版 Session logs 的正向信号集中在“工具分组后更易读”和“文件变更内联预览”。反向信号则说明工作面与对话之间的引用链仍然脆弱：用户明确要求恢复点击某行代码后自动复制 `FileName#lines` 到聊天的能力；另有反馈认为折叠代码需要反复点击、Session 页面未充分利用横向空间，以及将变更摘要移到外部 PR 页面会破坏工作流连续性。

这些反馈属于早期技术预览中的高信号个案，不代表普遍频率，但对桌面 Agent 会话的信息架构具有直接设计价值。

来源：[GitHub Community — Introducing the Agents tab](https://github.com/orgs/community/discussions/185364)

## 3. 模式对比

| 维度 | Codex App | GitHub Copilot App | MemStack 采用策略 |
| --- | --- | --- | --- |
| 主对象 | Thread + reviewable changes | Session + bidirectional Canvas | Conversation + mode-aware Work Canvas |
| 过程呈现 | 轻量活动摘要，证据进入 Context | 分组 Session logs，工具输出内联 | 叙事时间线只保留关键转折，工具组默认折叠 |
| 结果审阅 | Thread 内 Diff、批注、编辑器交接 | Plan / Diff / Terminal / Browser / PR | 通用与编程模式共享 Canvas 框架，内容按 Mode 变化 |
| Steering | Composer、Diff 评论、选区修改 | Composer、Canvas 操作、CLI/IDE 交接 | Composer + 可点击引用 + Canvas 直接操作 |
| 人类介入 | Permission / approval / annotations | Stop / steer / review / merge policies | HITL 固定在当前阶段上方，不埋入历史日志 |
| 运行状态 | Worktree、权限、模型、进度 | Branch、checks、token、duration | Header status strip + Overview，不占用常驻第三栏 |

### 3.1 证据强度与边界

- 高置信度：官方文档明确描述的隔离 Workspace、Thread/Session 切换、Review、模式/模型选择、Canvas、权限、恢复与交接能力。
- 中置信度：官方截图与产品视频中稳定出现的左右分栏、Tab、状态 HUD、折叠工具组和 Diff 内联交互；这些视觉细节会随版本变化，因此只抽象为交互原则，不逐像素复制。
- 方向性信号：GitHub Community 个案反馈。用于发现“引用链断裂、过度折叠、横向空间浪费”等风险，不用于推断普遍使用频率。
- 不采用：把 Git Branch 等同于 Session、把 PR 作为唯一交付终点、或把编程专用 Diff 结构硬套到通用 Agent。MemStack 必须让 Work 与 Code 共享生命周期，但保留各自的工作对象语言。

## 4. 当前原型问题

1. **Conversation 与执行日志竞争主视图**：消息、工具卡和验证卡都使用相似视觉重量，关键结论不突出。
2. **Task context 静态占宽**：右栏展示任务、耗时、费用与参与者，但无法直接审阅工作对象。
3. **缺少工作面切换**：变更、终端、验证、产物和计划没有成为可持久选择的 Canvas。
4. **Steering 缺少引用**：用户无法从 Diff、文件或验证项直接生成结构化上下文。
5. **阶段与下一动作不明确**：用户需要推断 Agent 正处于理解、实现、验证还是等待审批。
6. **通用与编程场景只有文案差异**：没有利用同一结构呈现 Artifact/Sources 与 Changes/Terminal 的不同工作对象。

## 5. 设计决策

### 5.1 三层会话模型

1. **Session Header**：标题、阶段、Run 状态、隔离环境、权限、模型、耗时、费用和主动作。
2. **Narrative Thread**：用户意图、Agent 决策摘要、关键事件、分组工具活动和 Steering Composer。
3. **Context Inspector + Work Canvas**：默认以窄栏显示待处理事项、运行快照和工作面入口；按 Mode 打开 Plan、Changes/Artifact、Terminal/Sources、Checks/Verification。

### 5.2 关键交互

- 工具活动按目标分组，默认只展示调用数、耗时、状态和最新结果。
- 点击 Diff 行或文件把结构化引用加入 Composer；引用与消息一起发送。
- 会话默认使用 Conversation-first 布局，右侧窄 Inspector 只保留待处理事项、运行快照、最新证据和工作面入口，避免静态上下文与对话争夺主视图。
- 点击 Plan、Changes、Checks 或 Artifact 后进入 Split Canvas；Canvas Tab 保持当前选择，切换不会改变 Conversation 或 Run。
- Canvas 支持 Split、Focus 和关闭三种布局：打开工作对象时默认并排，在 Diff、终端或长产物审阅时聚焦，关闭后返回 Conversation + Inspector。
- 运行中 Composer 区分 `Steer now` 与 `Queue next`，避免用户无法判断新消息会中断当前 Turn 还是排在后续执行。
- Setup、工具调用与 Subagent 按 Agent turn 聚合，默认只显示目标、状态、耗时和最终结果，展开后才显示完整审计明细。
- `Expand all` 控制 Diff 全量展开，避免逐文件重复操作。
- HITL 请求固定显示在当前进度附近，主动作明确说明授权范围。
- Overview 统一承载完整 Task、Run、参与者、产物和验证摘要；常驻 Inspector 只保留可操作、会随运行变化的最小信息集。

### 5.3 信息密度规则

- 一条 Agent Turn 只保留“结论、当前目标、可审阅输出、需要人类动作”；命令与原始输出进入可展开审计层。
- Header 只显示会影响判断或控制执行的字段。模型、权限、环境、耗时与用量在窄宽度下折叠到 Overview，不挤压 Thread。
- 只有权威状态可以产生主 CTA：Needs input 显示处理请求，Ready review 显示审阅 Run，Approved Artifact 才显示交付。不得根据消息文案猜测状态。
- 历史必须保持可追溯：Run、Artifact version、Decision 与 Delivery receipt 使用稳定 ID 和 revision；继续对话不得覆写旧版本或旧审计事件。

## 6. 成功标准

- 用户在 5 秒内回答：Agent 正在做什么、完成到哪一步、当前证据是什么、是否需要我操作。
- 从会话进入变更/产物只需一次点击，不打开外部页面。
- 从任一关键工作对象生成 Steering 引用只需一次点击。
- 1100×800 保留 Thread、Canvas Tab、Composer 与主动作，不产生页面级横向溢出。
- Work 与 Code 使用同一状态模型，但 Canvas 的工作对象与验证语言符合各自任务。
