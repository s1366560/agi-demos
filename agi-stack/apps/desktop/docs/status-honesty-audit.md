# 会话状态真实性审计(P0-2)

范围:桌面端全部会话状态展示点。红线:任何展示的会话状态必须与运行时事实一致;任何操作入口要么真实可用,要么显式禁用并说明原因;停止/取消必须说明对已产出的影响(非破坏性语义写进文案)。

## 状态枚举 × 展示点矩阵

运行状态枚举(`DesktopRunStatus`):`queued / running / needs_input / needs_approval / paused / ready_review / completed / failed / disconnected / interrupted / cancelled`;另有会话记录态 `active / archived` 与兜底 `unavailable`。

| 展示点 | 数据源(权威链) | 终态可呈现为运行中? | 修复前问题 | 现状 |
|---|---|---|---|---|
| 侧栏工作区树状态点(`workspaceTreeModel.ts` + `WorkspaceDock.tsx`) | `metadata.run.status`(WS `run_status` 事件 + 权威合并)回退 `conversation.status` | 不会(枚举直接映射) | 断连期间保留最后已知的 running(残余风险 R1) | 诚实;依赖服务端 watchdog 补 disconnected |
| 工作区根节点聚合点(同文件 `workspaceTreeRootStatusPresentation`) | 子会话运行态按优先级聚合 | 仅当有子会话真实 running | 无 | 诚实 |
| My Work 分组(`myWorkModel.ts` + `MyWorkQueue.tsx`) | 后端 `item.group` + `item.status` | 修复前:可能 | F1:`group='running'` 与终态 `status` 不一致时归入 Running | 已修复:`myWorkEffectiveGroup` 以 status 校正 |
| My Work 卡片状态点(`MyWorkQueue.tsx` InboxCard) | 同上 | 修复前:可能 | 状态点颜色直接取原始 `item.group` | 已修复:改用 `myWorkEffectiveGroup` |
| Activity 收件箱分类(`activityInboxModel.ts`) | 后端 `group`/`status`/`required_action` | 修复前:可能(误分为 needs_input) | F2:`status='completed'` 且分组滞后为 needs_input/needs_approval 时显示为待输入 | 已修复:复用 `myWorkEffectiveGroup` 校正分类 |
| 会话头状态 badge(`SessionWorkspace.tsx` + `sessionViewModel.ts`) | projection `currentRun.status` / attempt.status / conversation.status | 不会 | 无 | 诚实 |
| 会话头 live 指示(`SessionWorkspace.tsx`) | 全局 socket 连接态 + 会话状态 | 修复前:会(误导) | F3:终态会话在 socket 断开时显示「正在重连更新」,暗示还有更新会来 | 已修复:`sessionLiveIndicator` 对终态显示「更新已结束」 |
| stage stepper(`SessionWorkspace.tsx`) | `viewModel.stage` | 不展示 | stage 恒为 `unavailable`,stepper 实际不渲染 | 不展示(非误导),见 R4 |
| 运行控制按钮 pause/resume/cancel/reconnect/fork(同文件 + `sessionProjectionModel.ts`) | projection `capabilities.runActions`,由 `runActionsForStatus` 从运行态派生并经一致性校验 | 不会 | 无(按钮集与状态严格一致;云端会话恒为空) | 诚实 |
| 审批按钮 approve/request-changes(同文件) | 仅 `ready_review` 时由能力集给出 | 不会 | 无 | 诚实 |
| HITL 卡片可响应性(`App.tsx` → `respondableHitlRequestIds` → `ChatTimeline.tsx`) | projection `capabilities.canRespondToHitl` + pending 列表 | 修复前:可能 | F4:终态运行残留 pending HITL 时卡片仍可操作,提交必然失败 | 已修复:`respondableHitlRequestsForProjection` 对终态运行返回空 |
| 停止/取消文案(`SessionWorkspace.tsx` 更多菜单) | — | — | F5:停止按钮无破坏性语义说明 | 已修复:tooltip 注明「已产出的改动与文件会保留」(`session.stopRunHint`) |
| 标题栏运行态映射(`App.tsx` `titlebarRunStateFromStatus`) | `sessionDetailViewModel.status` | 修复前:会(潜在) | F6:`ready_review`/`completed` 映射为 `'running'`(当前为未接线代码,属隐患) | 已修复:映射为 `'stopped'` |
| Composer 停止按钮(`ChatPanel.tsx`) | `conversationResponseIsStreaming` + WS 发送结果 | 不会(断连时点击有错误反馈) | 断连期间停止按钮仍显示,但点击返回 `socket_unavailable` 错误 | 可接受;残余风险 R2 |

## 发现与修复

- F1(已修复)My Work 把终态会话归入 Running。根因:展示分组直接信任后端 `item.group`,不做客户端真值校正。修复:`myWorkModel.ts` 新增 `myWorkEffectiveGroup`,`groupMyWorkDisplayItems` / `countMyWorkDisplayGroups` / `filterMyWorkDisplayItems` 与卡片状态点统一走校正;`completed` 恒归 `ready_review`;分组为 running 但状态不在 `queued/running/paused/needs_input/needs_approval` 时按状态重归(`ready_review` → ready_review,`failed/cancelled/disconnected/interrupted` → needs_input);状态未知时信任后端分组。
- F2(已修复)Activity 收件箱把已完成会话显示为待输入。根因:分类只看原始 `group`。修复:`activityCategoryForItem` 复用 `myWorkEffectiveGroup`。
- F3(已修复)终态会话显示「正在重连更新」。根因:live 指示只看全局 socket 连接态,不看会话终态。修复:`sessionViewModel.ts` 新增 `sessionLiveIndicator`,终态(completed/failed/cancelled)显示「更新已结束」(`session.liveUpdatesEnded`,en+zh)。
- F4(已修复)终态运行上的残留 HITL 卡片仍可操作。根因:可响应集合只由能力位 `canRespondToHitl`(= pending 非空)决定,与运行终态脱钩。修复:`respondableHitlRequestsForProjection` 对终态运行返回空,`App.tsx` 的可响应 ID 列表改走该助手。
- F5(已修复)停止运行按钮未说明对已产出的影响。修复:新增 `session.stopRunHint`(en+zh)作为 tooltip:「停止当前运行;已产出的改动与文件会保留。」
- F6(已修复)标题栏映射把 `ready_review`/`completed` 视为 running。当前该映射未接线渲染,属隐患代码,已一并改为 `'stopped'`。

## 测试证据

- `tests/my-work-model.test.mjs`:「My Work never groups a terminal or stalled run as Running」「My Work never presents a completed run as needing input」。
- `tests/activity-inbox-model.test.mjs`:「Activity inbox corrects stale groups with runtime truth」。
- `tests/session-view-model.test.mjs`:「terminal session never claims reconnecting live updates」「terminal run leaves no respondable HITL requests」。
- `tests/desktop-shell-fidelity.test.mjs`:live 指示改钉 `sessionLiveIndicator(viewModel.status, liveConnected)`,并禁止回退到旧的裸三元表达式。

## 残余风险(本次未修复)

- R1 侧栏树断连期间的状态滞后:WS 断开后,树中运行点保留最后已知状态(如 running),直到服务端心跳 watchdog 将运行标记为 disconnected 并在重连后随游标订阅补发 `run_status`。缓解已存在(游标续订、权威合并);要做到断连即刻降级显示需要在树模型引入「连接态 × 状态」二维呈现,改动面大,留待后续迭代。
- R2 Composer 停止按钮在断连期间仍可点击:`conversationResponseIsStreaming` 的信号分支绕过 `activityPresence`,陈旧的非终态信号会维持 streaming 观感。点击后有 `socket_unavailable` 错误反馈,非静默失效,故仅记录。
- R3 `runToneFromStatus('active') → 'running'`:会话记录态 active 不等于运行中;该函数当前未接线渲染,记录为隐患,未改动以避免无关 churn。
- R4 stage stepper 永不渲染:`buildSessionDetailViewModel` 中 `stage` 恒为 `'unavailable'`。不误导但等于无该功能;恢复 stage 派生属 P0-3 之后的独立工作。
- R5 后端为唯一权威的分组/能力来源:F1/F2/F4 的客户端校正属于防御层,后端若持续产出不一致的 group 或 pending HITL,应在服务端修复并补合同测试。
