# 桌面客户端交互体验改进路线图 — Codex / Copilot 对标调研

> 调研日期:2026-08-03。调研对象:OpenAI Codex app(macOS/Windows 桌面、chatgpt.com/codex、CLI TUI,含 2026-07 并入 ChatGPT 桌面版后的状态)与 GitHub Copilot 代理面(github.com Agents panel / repo Agents tab、VS Code agent mode、Copilot CLI)。
> 适用对象:`agi-stack/apps/desktop`(Electron + React 渲染器,Radix Themes,自绘 CSS)。
> 本文只做研究与路线规划,不含已实现代码。

---

## Part 1 对标研究摘要

### 1.1 Codex app

**信息架构**
- 三栏布局:项目侧栏(项目≈文件夹,线程按项目分组)→ 线程/会话主区 → 右侧面板(Plans / Sources / Artifacts / Git summary)+ Review pane。([app features](https://developers.openai.com/codex/app/features))
- 线程是一等公民:pin、双击重命名、一键归档、全局搜索(含会话内容与 git 分支名)、跳转最近线程的快捷键。
- 侧栏分区:Threads / Skills / Automations / Sites / PR 列表 + **Activity 视图**(铃铛,`Cmd/Ctrl+Opt+U`)聚合"近期参与且需要关注"的会话;分区可折叠。
- Codex web 的组织轴是 GitHub 环境(environment):选环境 → 发起任务 → 选 **Code(改代码)vs Ask(只读分析)** → 后台运行 → 完成后看摘要 + diff。

**线程视图**
- Composer 内置模型选择器;reasoning effort 可用 slash 命令在输入中切换;模型/reasoning 设置**按任务作用域**保存。
- 线程创建时选运行模式:**Local / Worktree / Cloud**;可指定分支、创建 worktree、跑环境 setup 脚本。
- @ 菜单:文件、app、skill、MCP server(Add context 子菜单带安装建议);`Cmd+P` 工作区文件搜索;图片/文件粘贴带预览。
- **Queue vs Steer**:运行中发送的消息进入可拖拽重排的 queued chips;每条 chip 有 "Steer" 动作可提升进当前 run;有设置项选默认行为。([issue #32709](https://codexissues.com/issue/32709-add-a-persistent-steer-by-default-toggle-for-mid-run-messages))
- 工具活动渲染为分组摘要项(带进度);子代理有**稳定 identicon** 便于区分。
- 完成会话有 durable 摘要卡片(文件、automations 等持久产出)。

**Review pane(旗舰面)**
- 反映 **git 仓库真实状态**(agent + 用户 + 其他未提交改动),不只 agent 编辑。
- 三种范围切换:**Uncommitted changes(默认)/ All branch changes / Last turn changes**;另有 Staged/Unstaged 与分支对比过滤。
- 三级 git 操作:Stage all / Revert all(头部)、按文件、按 hunk;文件树带 diff 统计;一键展开/折叠全部。
- **行内评论**:悬停 diff 行 → gutter `+` → 锚定评论 → 对 agent 说 "address the inline comments" 即精准应用;`/review` 结果也落成行内评论。([review workflow](https://developertoolkit.ai/en/codex/quick-start/review-workflow/))
- 点文件名在配置的外部编辑器打开;Cmd+点击跳行;diff 空白符处理、折行开关。

**审批与自主度**
- 沙箱档位:`read-only` / `workspace-write`(默认)/ `danger-full-access`。
- `/permissions` 预设菜单:**Default / Auto-review / Full Access**(预设替代原始策略矩阵);Full Access 有显式警告。
- **Auto-review**:符合条件的审批先由评审 agent 过一遍,UI 显示自动评审项(状态 + 风险等级)再交人决定。([changelog 2026-04-23](https://help.openai.com/en/articles/11428266-codex-changelog))
- MCP 审批提供作用域选择(当前会话 / 跨会话)+ "Don't ask again"。

**通知与后台任务**
- Automations(定时任务)结果进入 **review queue**;运行历史支持批量已读/归档。
- Dock 未读角标;plan-mode 提问通知;移动端可远程审批、从推送直接打开已完成任务。
- 发布初期教训:云任务的 Dock 角标**在应用内无处查看/消除**([issue #10605](https://github.com/openai/codex/issues/10605))——后来用 Activity 视图修复。

**被批评点(我们的反面教材)**
- 侧栏线程"消失" bug(本地 DB 缓存 + 重建索引缺陷)严重侵蚀信任([#26634](https://github.com/openai/codex/issues/26634)、[#17970](https://github.com/openai/codex/issues/17970))。
- IDE 插件 diff 视图空闲 CPU 200–330%([#15330](https://github.com/openai/codex/issues/15330))。
- agent 自建 worktree 时 UI 仍挂在旧 workspace/分支,状态脱钩([discussion #16440](https://github.com/openai/codex/discussions/16440))。
- 并入 ChatGPT 后模式混淆、历史被挤进浮层。

### 1.2 GitHub Copilot

**信息架构**
- **Agents panel**(2025-08):全局顶栏按钮唤出的轻量浮层,官方定位即 "mission control center";不离开当前页即可发起/跟踪任务;可升级为全屏页与可收藏 URL。([launch post](https://github.blog/news-insights/product-news/agents-panel-launch-copilot-coding-agent-tasks-anywhere-on-github/))
- 发起入口多面合一:Issue 指派(👀 表情即时回执)、Agents panel 提示、Copilot Chat、VS Code、MCP 工具。
- **Repo 内 Agents tab**(2026-01):会话列表住进仓库,与 Code/Issues/PR 并列;一键跳 PR;可归档、翻页。([hands-on](https://visualstudiomagazine.com/articles/2026/01/29/hands-on-new-github-agents-tab-for-repo-level-copilot-coding-agent-workflows.aspx))
- 会话共享模型:云会话默认共享,本地会话默认私有可分享;云端会话永不删除。
- 可追溯性:agent 提交带 co-author、签名,**commit message 链回会话日志**。

**会话视图**
- 双视图:log(推理 + 工具,人看的摘要在 PR 描述持续更新)。
- **渐进披露**:子代理工作默认折叠 + 一行"正在做 X"标题;环境 setup 步骤可见化。([changelog 2026-03](https://github.blog/changelog/2026-03-19-more-visibility-into-copilot-coding-agent-sessions/))
- **Turn 粒度 steering**:日志下方输入框,追加消息在当前工具调用结束后生效;**Stop 非破坏**(保留已推送提交)。
- Chat 可查询会话状态、完成后回答"改了什么、验证了什么、为什么";自然语言搜索会话。

**PR 闭环**
- 工作 → draft PR(持续推进 + 更新标题/正文)→ 完成时请求人类 review;@copilot 评论触发迭代(**用 "Start a review" 批量评论**,因为每条评论立即触发)。
- "Step aside, Copilot":人推到 agent 分支再交还——人机接力被社区盛赞。
- 被批评:完成的 PR 仍以 "active sessions" 呈现;会话默认不再自动建 PR 的静默变更([devActivity](https://devactivity.com/insights/improving-software-development-activity-a-call-for-a-pr-centric-github-copilot-view/));后端未启用时按钮静默无效的 affordance([discussion #192765](https://github.com/orgs/community/discussions/192765))。

**VS Code agent mode(桌面客户端直接参照)**
- 输入区分层选择器:agent(Agent/Plan/Ask + 自定义)、agent 类型(local/CLI background/cloud)、模型、**权限等级**——会话中随时可切,按会话作用域。
- 权限等级(自主度拨盘):**Default Approvals / Assisted permissions(LLM 裁判自动放行低风险)/ Bypass Approvals / Autopilot(自动批准 + 自动回答澄清 + 自动重试直至完成)**;高风险档首用有警告。([approvals docs](https://code.visualstudio.com/docs/agents/approvals))
- 工具确认:显示工具名 + 参数,**chevron 展开可编辑参数后再 Allow**;作用域 once / session / workspace / always;`Chat: Manage Tool Approval` 按来源(MCP server/扩展)集中管理 pre-approval 与 post-approval(防 prompt injection)。
- 终端命令**按命令**审批:安全 allowlist + 危险 denylist(`rm` 永远人工),regex 可扩展;长命令旁出现 **"Continue in Background"**。
- 工具调用默认折叠;todo-list widget;**Checkpoints**:每次请求前快照,可 Restore(带 Redo)、**Fork Conversation**、编辑历史请求(回滚其改动并重发)。
- 运行中发送按钮变下拉:**Add to Queue / Steer with Message(默认,当前工具结束后让位)/ Stop and Send**;待发送消息可拖拽重排。

**Copilot CLI**
- 启动目录信任门(仅本次 / 记住此目录 / 退出)。
- 审批三选一:`Yes` / `Yes, 本次会话内都批准该 TOOL`(明示风险)/ **`No, and tell Copilot what to do differently`——拒绝即引导**。([About Copilot CLI](https://docs.github.com/copilot/concepts/agents/about-copilot-cli))
- `Shift+Tab` 循环 ask/execute ↔ plan mode;`Esc` 中断;"Thinking" 时 `Ctrl+T` 切推理可见性;`/usage` 展示 token、时长、改动行数;成功静默/失败详细(Task 子代理模式)。

**被批评点**
- 审批疲劳:allowlist 需重启生效;"Continue/Cancel" 语义不适合迭代;Keep/Undo 有误删风险。([vscode#261549](https://github.com/microsoft/vscode/issues/261549))
- 终端泛滥(dev server 尤其),后由 Continue-in-Background + 自动清理缓解。
- 卡在静态 "Working..." 无任何原因可见([vscode#271124](https://github.com/microsoft/vscode/issues/271124));要求 token/上下文用量指示。
- 验证声明不可信:"修复 CI"实为改测试配置然后宣布胜利——摘要中的验证声明需要可审视。

### 1.3 两个产品共同收敛的范式

1. **线程/会话是主工作区**,任务列表 + 全局可达的发起浮层是标配入口。
2. **渐进披露**是对付日志噪音的统一答案:默认折叠 + 一行实时 headline,成功静默、失败详细。
3. **Turn 粒度 steering**:运行中消息排队/让位于当前工具调用结束后生效,而非打断;队列可重排。
4. **审批即对话**:拒绝带反馈、Allow 前可看/改参数、作用域分级、自主度分档(含 LLM 裁判档)。
5. **非破坏性安全网**:Stop 保留工作、Checkpoints 可回滚/分叉——这是用户敢开高自主度档位的前提。
6. **状态诚实是信任基线**:被批评最狠的都是误导性状态(完成显示为 active、按钮静默无效、无原因的 "Working...")。

---

## Part 2 现状差距矩阵

当前客户端已有坚实基础:My Work 收件箱(Needs input / Running / Ready)、内联 HITL 卡(Allow once / Allow always / Deny,工作区级记忆)、compose-ahead 队列、右侧 canvas 十个 tab(Overview/Plan/Activity/Changes/Terminal/Checks/Artifacts/Apps/Sources/Verification)、stage stepper、fork、会话内搜索、命令面板、Toast、明暗主题、双语 i18n。设计方向(prototype README)本就是 Codex 式线程中心模型,差距主要在以下四处。

| 维度 | 竞品标杆 | 当前实现 | 差距 |
|---|---|---|---|
| 并行任务指挥中心 | Codex Activity 视图(铃铛 + 快捷键)+ 完成摘要卡 + review queue;Copilot Agents panel 全局浮层 | `DesktopSidebar.tsx:222` Notifications 是假入口:硬编码 `<i />` 未读点,点击只跳设置页;无真实通知收件箱;完成会话无 durable 摘要;automations 完成无回顾队列 | **大** |
| 运行中引导与审批 | Queue vs Steer(Codex chips / VS Code 下拉三选);拒绝带反馈;Allow 前编辑参数;权限预设 Default/Auto/Full | `composeAheadModel.ts` 只有 queue 无 steer;`HitlResponseCard.tsx` 拒绝=终点无反馈通道;无参数预览编辑;无权限预设概念(仅有单条 allow 作用域) | **大** |
| 变更审查面板 | Codex Review pane:范围三切换、stage/revert 三级、行内评论回喂 agent | `SessionChangesCanvas.tsx`(224 行)只读 diff 查看器:文件 tab + 行渲染,无范围切换、无 stage/revert、无行内评论 | **大** |
| 进度与状态透明 | 子代理"正在做 X" headline + 默认折叠;`/usage` token/时长/行数;完成 OS 通知可点击聚焦 | 工具/子代理已默认折叠(好),但无"当前活动"一句话 headline;无 token/上下文用量、无耗时可读化;卡住无检测呈现;无完成通知 | **中** |

---

## Part 3 改进路线图

### P0 — 信任与诚实(本轮最高优先)

**P0-1 真实 Activity 收件箱,替换假 Notifications 入口**
- 问题:侧栏铃铛是装饰,用户形成"点了也没用"的预期,损害整个产品的可信度。
- 参照:Codex Activity 视图(`Cmd+Opt+U`);Copilot Agents panel。
- 目标交互:点击铃铛打开收件箱视图(或浮层),聚合三类条目:需要输入(HITL 待答)、运行完成待回顾、运行失败/卡住;每条带会话跳转;支持逐条/批量已读;未读数真实驱动侧栏角标。
- 涉及:`src/features/navigation/DesktopSidebar.tsx`、`src/features/my-work/MyWorkQueue.tsx`(数据源复用其 Needs input / Running / Ready 分组逻辑)、新增 `src/features/activity/`;Toast/WS 事件补充未读状态。
- 依赖:纯前端可起步(从现有会话状态派生);持久化已读位需后端小改(可后置)。
- 验收:每个有未读角标的条目在应用内可达、可消除(对照 Codex issue #10605 的教训)。

**P0-2 会话状态真实性审计**
- 问题:对标产品被骂最狠的是误导性状态;我们应先于功能补齐建立"状态诚实"红线。
- 目标:审计全部会话状态展示点(侧栏树状态点、My Work 分组、会话头 badge、stage stepper),确保:终态会话不出现在 Running;任何按钮的后端能力不可用时显式禁用并说明,而非静默无效;停止/取消操作明确说明对已产出的影响(非破坏性语义写进 UI 文案)。
- 涉及:`workspaceTreeModel.ts`、`sessionViewModel.ts`、`MyWorkQueue.tsx`、`SessionWorkspace.tsx`。
- 验收:列出现有状态枚举 × 展示点矩阵,每个单元格有测试或设计 QA 截图证据。

**P0-3 "当前活动" headline**
- 问题:运行中只有静态进行中指示,用户无法回答"它现在在干嘛"。
- 参照:Copilot 子代理折叠块的"正在做 X"标题行。
- 目标交互:会话运行期间,在 timeline 底部(或 composer 上方)显示一行实时 headline(当前工具/子代理 + 目标),默认折叠,点击展开当前活动组;子代理已有分组模型(`subagentTimelineGroupModel.ts`),headline 从 `sessionNarrativeModel.ts` 的活动存在感数据派生。
- 验收:长运行中任意时刻截图都能看出当前活动;运行结束 headline 消失。

### P1 — 控制感与审查闭环

**P1-1 Queue vs Steer**
- 参照:Codex queued chips + Steer;VS Code Send 下拉(Add to Queue / Steer / Stop and Send)。
- 目标交互:运行中发送的消息默认排队(现状),队列 chip 增加 "Steer" 动作——在当前工具调用结束后注入为下一条用户输入;发送按钮带下拉选 Queue/Steer 默认行为;chip 支持拖拽重排。
- 涉及:`composeAheadModel.ts`(增加 steer 语义)、`ChatPanel.tsx`/`ComposerControls.tsx`。
- **跨端依赖**:Steer 需要后端在 turn 边界接受注入消息(WS 协议扩展),标注为后端任务;前端可先做队列 UI + 协议草案。
- 验收:Steer 的消息在当前工具完成后生效,且 timeline 中可辨识其为 steer 注入。

**P1-2 审批即对话**
- 参照:Copilot CLI "No, and tell Copilot what to do differently";VS Code 参数编辑后 Allow。
- 目标交互:`HitlResponseCard` 的 Deny 展开为可选反馈输入(拒绝原因作为引导消息发给 agent);permission 类卡片 Allow 前可展开查看/编辑关键参数;权限卡片增加预设入口(Default / Auto / Full)映射到现有 allow 作用域模型(once / workspace-always)。
- 涉及:`HitlResponseCard.tsx`、`hitlAuthorityRecovery.ts`;文案走 i18n。
- 验收:拒绝 + 反馈后 agent 的下一步行为体现该反馈;预设切换影响后续审批弹出频率,可在设计 QA 中演示。

**P1-3 完成会话 durable 摘要卡 + 回顾队列**
- 参照:Codex 完成摘要卡;automations review queue。
- 目标交互:会话进入终态时在 timeline 尾部生成摘要卡(改动文件统计、产出 artifacts、验证/检查结果、失败原因若适用);My Work 的 Ready 分组即回顾队列,点击摘要卡条目跳回会话。
- 涉及:新增 timeline 卡(参照 `ConversationSummaryCard` 现有模式)、`MyWorkQueue.tsx`。
- 验收:摘要中的验证声明可点击跳转到 Checks/Verification canvas 的证据(对照 Copilot "宣布胜利" 教训)。

**P1-4 Changes canvas 升级为审查面板**
- 参照:Codex Review pane。
- 目标交互(分期):
  - 1a:范围切换(本轮改动 / 会话全部改动)+ 按文件展开折叠;
  - 1b:diff 行内评论,锚定到行,一键 "发送给 agent"(复用 `sessionChangesModel.ts` 的 `referenceForChangeLine` code-range 引用机制,评论作为带引用的 composer 消息);
  - 1c(可选,依赖沙箱 git 写权限):按文件/hunk 的 revert 入口。
- 涉及:`SessionChangesCanvas.tsx`、`sessionChangesModel.ts`、composer 引用管线。
- 验收:行内评论回喂后 agent 的下一轮改动精确命中评论位置;diff 视图空闲渲染不引入持续重绘(见 Part 4 性能预算)。

### P2 — 打磨

- **P2-1 用量与耗时透明**:会话头或 composer footer 展示 token 用量/上下文水位、本轮耗时;终态会话显示总耗时与改动行数(参照 `/usage`)。
- **P2-2 卡住检测呈现**:运行超过可配置静默阈值时,headline 区显示"似乎在 N 分钟无进展"并提供取消/继续引导(触发可确定性,判定交 agent,符合 Agent First 原则)。
- **P2-3 完成 OS 通知**:窗口失焦时会话完成/需要输入触发系统通知,点击聚焦到该会话(参照 VS Code `notifyWindowOnConfirmation` 三档设置)。
- **P2-4 键盘快捷键设置页**:快捷键目录(`keyboardShortcutModel.ts`)已有,补可视化设置页(按键搜索 + 重置,参照 Codex 26.527)。
- **P2-5 diff 渲染性能预算**:为 Changes canvas 立性能基线(空闲 CPU、长 diff 虚拟化),防止 Codex #15330 类回归。

---

## Part 4 反面清单(竞品的坑 → 我们的预防设计)

| 竞品事故 | 预防设计 |
|---|---|
| Codex 侧栏线程静默丢失(#26634 等) | 侧栏数据源以后端为准,本地缓存只做加速;任何重建/迁移不删用户历史;加数据一致性自检 |
| Codex 云任务角标应用内无处可消(#10605) | P0-1 的硬验收:每个未读信号都有应用内对应视图 |
| Copilot 完成 PR 显示为 active;按钮静默无效(#192765) | P0-2 状态真实性红线 + affordance 能力检查 |
| Codex diff 视图空闲 CPU 200%+(#15330) | P2-5 性能预算进 CI 或设计 QA 检查表 |
| agent 自建 worktree 与 UI 状态脱钩(#16440) | UI 展示的 branch/workspace 从 runtime 事实派生,不从发起时的选择缓存 |
| Copilot "修复 CI" 实为改测试配置后宣布胜利 | P1-3 摘要卡中的验证声明必须链接到可审视证据 |
| 审批疲劳(Copilot allowlist 需重启) | P1-2 预设与作用域即时生效,不需要重启/重连 |
| 终端泛滥 | 长命令后台化入口(Continue in Background 类),后台终端自动清理 |

---

## 落地建议

1. 评审本文 P0/P1 优先级排序,确认后按 P0-1 → P0-2 → P0-3 → P1-x 顺序开迭代。
2. 实施迭代遵循 `agi-demos-desktop-parity-delivery` skill 流程;桌面端验证统一用 `make -C agi-stack run-desktop`(不得用 `pnpm run dev` 代替原生验证)。
3. 每项落地时在 `agi-stack/apps/desktop/design-qa.md` 补设计 QA 证据(1440×1024 与 1100×800 两档截图)。
4. P1-1 的 Steer 与 P1-2 的拒绝反馈涉及 WS 协议与后端行为,需提前与后端排期对齐。
