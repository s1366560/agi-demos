# 桌面客户端 UX 改进开发与验收

- 日期：2026-11-11
- 代码版本：`6baeec463` + 本次工作区改动
- 范围：桌面 Electron renderer（本地 Runtime 会话主链路）
- 验证方式：单元测试 + 生产构建 + 真实 Electron 实例（CDP 应用层操作）
- 关联审计：[desktop-ux-audit-20261111.md](desktop-ux-audit-20261111.md)

## 1. 交付摘要

本次实现聚焦审计中最高影响的 P0/P1 交互问题：

| 改进 | 状态 | 结果 |
|---|---|---|
| Plan 草稿可见、可审阅 | 已完成 | 对话内出现“计划已生成，等待审阅”卡片；点击打开 Plan 审阅页；批准按钮可执行 |
| Plan 消息本地化 | 已完成 | 英文 `Plan ready for review.` 在中文界面显示为“计划已生成，执行前请先审阅。” |
| 运行中禁止普通发送 | 已完成 | 运行 active 时发送按钮禁用，并提示“当前回复仍在生成…”；不再出现“已接受但被后端拒绝” |
| 停止后的结果与重试 | 已完成 | 停止后显示“已停止生成”状态条和“重试消息”；重试会复用原用户消息 |
| 选择器层级与可点击性 | 已完成 | 工作区/模型菜单改为侧向或候选区域布局；“无工作空间”不再被标题栏覆盖；模型菜单不再遮挡输入框 |
| 加载文案 | 已完成 | “正在加载会话权威状态…”改为“正在恢复会话…”；说明改为运行状态同步 |
| 慢恢复提示 | 已完成 | 10 秒后升级为“会话恢复时间较长”，提供“重试恢复”；输入框可编辑，慢加载期间可直接发送 |
| 冲突错误行重试 | 已完成 | `runtime_conflict`/`conversation already running` 失败行显示“重试” |
| 新线程工作区记忆 | 已完成 | 显式选择的工作区（含“无工作空间”）按项目记忆，启动新线程时恢复 |
| 会话标题可读性 | 已完成 | 窗口/会话标题压缩到 48 字符，按空格或中英文标点断句 |
| 慢加载提前发送 | 已完成 | 本地模式慢加载期间可先发送，用户消息立即出现，不被 projection 阻塞 |
| 计划消息历史兼容 | 已完成 | 仅对精确的旧 sidecar 文本做显示层本地化，不改写已存储历史 |

## 2. 实现明细

### 2.1 Plan 审阅入口

新增 [SessionPlanDraftNotice.tsx](agi-stack/apps/desktop/src/features/chat/SessionPlanDraftNotice.tsx)：
- 在对话底部、输入框上方渲染草稿计划提示。
- 显示步骤数、前三个步骤和“审阅计划”按钮。
- 点击按钮复用现有 Plan canvas 审阅页，不复制环境/权限审批逻辑。

配套：
- [sessionPlanApprovalModel.ts](agi-stack/apps/desktop/src/features/session/sessionPlanApprovalModel.ts) 新增 `draftPlanReviewNotice`、`localizePlanReadyMessage`。
- [App.tsx](agi-stack/apps/desktop/src/App.tsx) 传入 `draftPlan` 和 `onOpenPlanReview`。
- [ChatPanel.tsx](agi-stack/apps/desktop/src/features/chat/ChatPanel.tsx) 渲染提示。
- [ChatTimeline.tsx](agi-stack/apps/desktop/src/features/chat/ChatTimeline.tsx) 在正文与操作菜单两处统一本地化旧 plan-ready 消息。

### 2.2 运行 active 门控

- [ChatPanel.tsx](agi-stack/apps/desktop/src/features/chat/ChatPanel.tsx) 新增 `runActive`，由 `responseStreaming`、`canonicalRunStatus === 'running'`、`'queued'` 共同决定。
- 普通发送条件改为 `!runActive`：只要 run 处于活动状态，普通发送按钮禁用；运行状态清理前不再接受会触发 `runtime_conflict` 的输入。
- [composeAheadModel.ts](agi-stack/apps/desktop/src/features/chat/composeAheadModel.ts) 支持 `runActive` 入参，为已有排队能力保留扩展点。
- 发送按钮增加 `session.composerRunActiveHint` 提示文案。

### 2.3 停止状态与重试

- 修正停止状态被立即重置的问题：`stopRequest.status === 'stopped'` 现在会保留到下一次发送。
- 新增 `.session-stop-notice` 状态条：显示“已停止生成”、说明和“重试消息”。
- 重试使用停止轮次对应的用户消息内容，而不是要求存在 assistant 消息；修复了之前“没有可用于重试的上一条用户消息”的路径。
- 相关样式在 [ChatPanel.css](agi-stack/apps/desktop/src/features/chat/ChatPanel.css)。

### 2.4 选择器位置

- [pickerMenuPlacement.ts](agi-stack/apps/desktop/src/features/chat/pickerMenuPlacement.ts) 新增纯函数：优先右侧/左侧，空间不足时再上/下。
- [PickerMenu.tsx](agi-stack/apps/desktop/src/features/chat/PickerMenu.tsx) 根据锚点、视口和菜单尺寸选择 `right/left/up/down`，侧向时再按可用高度选择顶对齐/底对齐。
- [ComposerMenus.css](agi-stack/apps/desktop/src/features/chat/ComposerMenus.css) 增加对应位置类；工作区菜单不再被 36 px 标题栏覆盖。
- [ChatTimeline.css](agi-stack/apps/desktop/src/features/chat/ChatTimeline.css) 将会话内模型弹层锚定到输入框上方，避免遮挡正在编辑的 prompt。

### 2.5 慢恢复与冲突重试

- [App.tsx](agi-stack/apps/desktop/src/App.tsx) 增加 `sessionProjectionSlow`：projection 加载 10 秒后把加载提示升级为“会话恢复时间较长”，并提供重试动作。
- [sessionComposerDispatchModel.ts](agi-stack/apps/desktop/src/features/session/sessionComposerDispatchModel.ts) 增加本地慢路径 `allowConversationMessageWithoutAuthority`；[useConversationMessaging.ts](agi-stack/apps/desktop/src/hooks/useConversationMessaging.ts) 在慢加载时允许新消息直接入列。
- [ChatTimeline.tsx](agi-stack/apps/desktop/src/features/chat/ChatTimeline.tsx) 对 `runtime_conflict` 或包含 `conversation already running` 的失败行增加“重试”按钮；[ChatPanel.tsx](agi-stack/apps/desktop/src/features/chat/ChatPanel.tsx) 重发最后一条用户消息。

### 2.6 新线程工作区记忆

- 新增 [newThreadPreferenceModel.ts](agi-stack/apps/desktop/src/features/task/newThreadPreferenceModel.ts)：按项目保存最后一次显式选择的工作区，空字符串表示用户明确选择了“无工作空间”。
- [useConversationThreads.ts](agi-stack/apps/desktop/src/hooks/useConversationThreads.ts) 在启动新线程时读取并校验该偏好；工作区不存在时回退到无工作空间。
- 单测覆盖：项目隔离、空工作区、脏数据、存储抛错。

### 2.7 会话标题可读性

- 新增 [conversationTitleModel.ts](agi-stack/apps/desktop/src/features/chat/conversationTitleModel.ts)：把窗口/会话标题压缩到 48 字符，优先在空格、中文逗号/句号/冒号处断句。
- [App.tsx](agi-stack/apps/desktop/src/App.tsx) 的 `sessionTitle` 和 chatPanel `sessionTitle` 使用压缩标题；持久化标题不变。
- 单测覆盖中英文长标题、短标题、空白和边界长度。

### 2.8 文案

[i18n.tsx](agi-stack/apps/desktop/src/i18n.tsx)：
- `session.authorityLoading`：`Restoring session…` / `正在恢复会话…`
- `session.authorityLoadingDescription`：运行状态同步说明
- `session.authoritySlowTitle` / `session.authoritySlowDescription` / `session.authorityRetryLoading`：慢恢复提示与重试
- `session.planDraftReady*`：计划审阅提示
- `session.responseStopped` / `session.retryStoppedResponse`
- `session.composerRunActiveHint`

## 3. 验收结果

### 3.1 自动化

```bash
cd agi-stack/apps/desktop
node tests/run.mjs
```

结果：

- `tests 5395`
- `pass 5387`
- `fail 0`
- `skipped 8`

```bash
cd agi-stack/apps/desktop
corepack pnpm run build:electron
```

结果：`tsc --noEmit`、`tsc --noEmit -p tsconfig.electron.json`、`electron-vite build` 全部通过。

### 3.2 真实 Electron 验收

1. 打开含草稿计划的会话，确认：
   - 旧英文消息显示为中文；
   - 底部出现“计划已生成，等待审阅”卡片；
   - 卡片显示步骤和“审阅计划”按钮。
   证据：[20-plan-notice-localized.png](artifacts/desktop-ux-audit-20261111/20-plan-notice-localized.png)

2. 点击“审阅计划”，确认 Plan 标签页自动打开：
   - 显示“计划版本 1”“草稿 · 等待批准”；
   - “批准版本 1 并开始”按钮可用。
   证据：[21-plan-review-from-notice.png](artifacts/desktop-ux-audit-20261111/21-plan-review-from-notice.png)

3. 点击批准，确认：
   - 计划状态变为“已批准”；
   - 绑定的 run 开始执行；
   - 页面出现运行中状态和停止入口。
   证据：[22-plan-approved-run.png](artifacts/desktop-ux-audit-20261111/22-plan-approved-run.png)

4. 打开工作区选择器，确认：
   - 菜单在锚点右侧展开；
   - “无工作空间”完整可见且可点击；
   - 点击后 chip 更新为“工作空间 无工作空间”。
   证据：[23-picker-menu-right.png](artifacts/desktop-ux-audit-20261111/23-picker-menu-right.png)、[24-picker-no-workspace-selected.png](artifacts/desktop-ux-audit-20261111/24-picker-no-workspace-selected.png)

5. 运行中键入第二条消息，确认：
   - 输入框仍可编辑；
   - 发送按钮保持禁用；
   - 停止按钮仍可用；
   - 不再出现 `conversation already running` 的“已接受但被拒绝”路径。
   证据：[26-run-active-send-disabled.png](artifacts/desktop-ux-audit-20261111/26-run-active-send-disabled.png)

6. 点击停止，确认：
   - 出现“已停止生成”状态条；
   - 提供“重试消息”；
   - 点击重试后状态条消失，新的 run 启动。
   证据：[25-stop-notice-retry.png](artifacts/desktop-ux-audit-20261111/25-stop-notice-retry.png)

7. 打开会话内模型菜单，确认：
   - 弹层位于输入框上方；
   - 与输入框无重叠；
   - 模型列表可滚动/可选。
   证据：[27-model-popover-clears-input.png](artifacts/desktop-ux-audit-20261111/27-model-popover-clears-input.png)

8. 将 projection 请求人为延迟 14 秒，确认：
   - 10 秒后加载提示升级为“会话恢复时间较长”；
   - 出现“重试恢复”动作；
   - 11 秒时输入并发送成功，用户消息立即出现，不被 projection 阻塞；
   - 请求完成后恢复会话。
   证据：[28-slow-loading-retry.png](artifacts/desktop-ux-audit-20261111/28-slow-loading-retry.png)、[31-optimistic-send.png](artifacts/desktop-ux-audit-20261111/31-optimistic-send.png)

9. 打开历史 `runtime_conflict` 会话，确认失败行出现“重试”动作。
   证据：[29-conflict-retry.png](artifacts/desktop-ux-audit-20261111/29-conflict-retry.png)

10. 打开长标题会话，确认窗口标题压缩为 48 字符并在标点处断句。
    证据：[30-compact-title.png](artifacts/desktop-ux-audit-20261111/30-compact-title.png)

## 4. 未完成项与后续建议

以下审计项本次未改，仍建议按原优先级继续：

1. **P0-1 非阻塞首轮加载**：本地慢路径已支持提前发送；云模式和运行时预热尚未覆盖，投影失败后的恢复仍需继续验证。
2. **P0-4 统一运行状态与卡死恢复**：侧栏状态仍可能滞后；尚未实现 `stalled` 租约、强制停止/重置入口。
3. **P1-5 其余错误动作**：`runtime_conflict` 行已有“重试”；其他错误仍主要依赖“查看/诊断”，未提供“停止并重试/加入队列”。
4. **P2-8 工作区行动入口**：新线程工作区记忆已完成；工作区“未激活/未绑定智能体”的行动入口仍未补齐。
5. **P2-9 会话标题**：窗口标题已压缩并可读；仍未由模型生成语义标题。
6. **P2-10 消息列宽/归属信息/操作条可发现性**：未改。
7. **浏览器桥接退避**：未改。

## 5. 风险与说明

- 本次修改为 renderer/TS/CSS + 测试，无 Rust 或数据库迁移。
- `PickerMenu` 的侧向定位依赖 `window.innerWidth/innerHeight`；窗口尺寸变化后需要重新打开菜单才会重新计算。后续可在 resize 时重算。
- 模型弹层采用会话 composer 的固定偏移（124 px）来避开输入框；如果输入框高度大幅增长，可能需要改为动态测量。
- 计划审批仍复用现有 Plan canvas 的权威能力检查；当 projection 尚未就绪时，批准按钮可能短暂不可用，这是已有的 fail-closed 行为。
- 测试中产生的会话仍保留在 Local Desktop 侧栏；当前没有删除入口。
