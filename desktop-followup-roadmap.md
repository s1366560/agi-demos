# 桌面客户端遗留事项 — 设计与规划

> 输入：2026-09-16 桌面端全面审计（`desktop-capability-audit-report.md`、
> `desktop-capability-audit-2.md`、`desktop-capability-audit-3.md`、
> `desktop-conversation-flow-parity-audit.md`）及既有文档
> `agi-stack/apps/desktop/docs/status-honesty-audit.md`（R1–R5）、
> `agi-stack/apps/desktop/docs/changes-review-gaps.md`、
> `agi-stack/apps/desktop/docs/steer-protocol-draft.md`、`agi-stack/apps/desktop/ELECTRON.md`。
>
> 规划红线（沿用审计红线）：展示状态必须与运行时事实一致；操作入口要么真实可用，
> 要么显式禁用并说明原因；绝不伪造数据范围或语义。

## 优先级框架

| 级别 | 含义 |
|---|---|
| P0 | 用户可见的能力缺失或协议半成品，设计已闭环，可直接排期 |
| P1 | 依赖后端契约或跨端决策的中型能力 |
| P2 | 低危健壮性/一致性打磨，可随手带入相邻改动 |
| P3 | 发布工程门禁，独立于功能迭代 |

---

## P0-1 steer_message 后端落地（compose-ahead 转向）

**背景**：桌面端已实现完整的"运行中追加指令"草案协议（`useAgentSocket.ts`），但后端无
`steer_message` 处理器，路由器只回无归属的 `Unknown message type` 错误
（`message_router.py:99`），客户端目前靠文本匹配兜底即时回退。

**关键发现（设计基础）**：注入机制已端到端存在，无需新造——
`AgentRunInputModel(delivery='steer_now')` 持久化 + 幂等 + 修订守卫
（`src/domain/model/agent/run_input.py`）、HTTP 参考实现
`POST /runs/{run_id}/inputs`（`run_input_authority.py:382-532`）、
`RedisControlChannel` 传输、`SessionProcessor._check_control_channel` 在轮次边界消费
（`processor.py:1680-1770`，含模型 I/O 期间中断重跑）。主聊天运行已接线该通道。

**设计**：新增 WS 处理器复用上述权威平面，不发明第二条路。

- 线协议：请求沿用桌面草案（`message_id` 作幂等键，可选 `run_id`/`expected_run_revision`）；
  接受/拒绝统一走 `{type:"ack", action:"steer_message", outcome:"accepted|rejected", reason_code?}`；
  校验错误走带 `code` + `message_id` 回显的 typed error。
- 步骤 0（独立可发布）：`message_router.py:99` 的未知类型错误加
  `code="UNKNOWN_MESSAGE_TYPE"` 与 `message_id` 回显——仅此一项即可让桌面端删掉文本匹配。
- 步骤 1：新 `handlers/steer_handler.py`（校验/HITL 挂起/作用域检查复用 `chat_handler.py`
  既有助手）；把 `run_input_authority.py` 的可复用核（`_dispatch_persisted_steer`、
  哈希、回执）抽入 `application/services/agent/run_input_dispatch.py`，HTTP 与 WS 共用。
- 步骤 2：处理器 STEER 分支对 run-input 来源的转向以 `user` 角色注入并打
  `injected_via:"steer"` 元数据（替代当前 `[Control]` 系统前缀），持久化可回溯。
- 步骤 3（后端发布后）：桌面删除 `agentSteerUnsupportedRouterError` 文本匹配分支；
  10s 超时保留为静默吞没兜底；本地模式 steer 维持不可用+排队（文档化）。

**验收**：后端单测覆盖畸形载荷/作用域/无活跃 run/修订冲突/HITL 挂起/幂等重放/派发失败；
集成测试 WS steer → accepted ack → settlement 落 `applied`；桌面测试钉住"无 code 的裸文本
错误不再被归属"。**工作量 M**（后端约 2 天含抽取，桌面 0.5 天）。
**依赖**：无，可立即启动；步骤 0 与 P0-2 可并行。

## P0-2 会话阶段步进器数据模型（R4 解除）

**背景**：`buildSessionDetailViewModel` 硬编码 `stage:'unavailable'`
（`sessionViewModel.ts:315`），步进器与右侧进度表永不渲染。`workspace_llm_stage`
只记录创建上下文，不可用。UI 分类法：understand / implement / verify / review。

**设计**：服务端在会话投影载荷中派生 `execution_stage`——投影服务
（`conversation_session_projection_service.py:237-343`）已聚合全部所需诚实信号
（计划模式状态、任务列表、run 生命周期、验证证据、评审就绪度、HITL 挂起）。
派生是纯函数式的枚举映射（结构性事实，不违反 Agent First 红线），单一权威源，
Web 与桌面共用；字段加进 `snapshot_revision` 摘要，阶段变化自动触发客户端刷新。

- 映射优先级（前者优先，取最新阶段；无匹配 → null）：review（attempt 已裁决或
  run `ready_review`/`completed` 且有产物）→ verify（活跃 attempt 有验证引用）→
  implement（run 运行中/已批准计划有未完成任务/build 模式）→ understand（plan 草稿
  或有活动但无以上）→ null（空会话/无产物的终态失败）。
- 版本化：字段additive带默认值，`schema_version` 保持 2，旧后端省略即视为 null。
- 桌面链路：`sessionProjectionTypes.ts` 加字段 → 解码器校验四枚举否则 null →
  `stage: projection?.executionStage ?? 'unavailable'`；schema-v1（本地 sidecar）恒 null，
  诚实不补齐。`SessionWorkspace`/`SessionContextRail` 无需改动。
- 兜底语义：null/缺失/不可解析 → 不渲染（现状）；pending HITL 不改阶段（UI 已有暂停态）。

**验收**：后端矩阵单测（各映射分支+优先级冲突取后者+空会话 null）；集成测试字段存在性与
revision 联动；桌面解码器/视图模型测试+"终态失败无产物永不渲染步进器"诚实钉；
`status-honesty-audit.md` R4 标记已解除。**工作量 M**（后端约 1 天，桌面 0.5 天）。

---

## P1-1 Changes 面板范围切换（本轮 / 全会话）

**背景**：`changes-review-gaps.md` 缺口 1——当前变更快照是单 run 扁平 diff，无 turn 归属、
无会话级基线端点，两种候选语义都缺数据，已刻意不 ship（绝不伪造范围）。

**设计**（后端二选一即可解锁）：
1. 快照增加会话级视图 `GET /runs/{id}/changes?scope=session`（或 `ChangeSnapshot` 增加
   `session_base_revision`），由后端产出会话基线→head 的 diff；**推荐**，前端零推断。
2. 或为 `ChangeFile`/`ChangeHunk` 增加 `turn_id`（或 `run_revision` 区间）归属字段，
   前端本地做真实范围过滤。

**验收**：范围切换两个选项的数字均与后端权威 diff 一致；切换不触发全量重渲染（沿用
空闲零重绘守卫）。**工作量 M**（主要在后端）。**依赖**：后端排期。

## P1-2 按文件/hunk 的 revert / stage

**背景**：缺口 2——diff 端点只读，依赖沙箱 git 写权限开放。

**设计**：沙箱写路径开放后，新增按文件/hunk 的 revert 端点（权限走既有 HITL 确认，
破坏性语义写入文案）；前端在 Changes 面板每文件/每 hunk 增加 revert 入口 + 确认卡片。
**验收**：revert 后快照 digest 联动失效旧评论锚点（既有设计）；权限拒绝时不产生部分写入。
**工作量 M**。**依赖**：沙箱写权限契约（跨团队决策）。

## P1-3 插件市场安装/审批/撤销 UI

**背景**：后端 `plugin_marketplace.py` 已有 install/approve/revoke 路由，但桌面与 Web
双端均只有列表/详情/卸载，获取走带外 desired-bundle 同步（审计 2 已核实）。

**设计**：先做产品决策（市场获取是否入端内）。若做：桌面 Skills/Plugins 管理页加
"安装"入口（云端模式调后端 install；本地模式按 fail-closed 契约显示结构化不可用）；
approve/revoke 归管理员工位。Web 端同设计保持 parity。**工作量 M**。
**依赖**：产品决策 + Web 端同步排期。

---

## P2 打磨项（可并入相邻改动）

| 项 | 证据 | 方案 | 量 |
|---|---|---|---|
| P2-1 侧栏断连状态滞后（R1） | status-honesty-audit.md:44 | 树模型引入"连接态×运行态"二维呈现：断连时运行点降级为"最后已知"样式 | M |
| P2-2 Composer 停止按钮断连可点（R2） | 同上:45 | 断连时禁用停止按钮并 tooltip 说明（现有 socket_unavailable 反馈保留为兜底） | S |
| P2-3 代码块 Open in Canvas | parity 审计 §1.8 | 桌面画布仅响应后端 `canvas_updated` 事件；需新增"本地片段打开"API 后接线 | S（依赖 API） |
| P2-4 NewTaskFlow 幂等冲突死局 | NewTaskFlow.tsx:1338-1361 | footer 被抑制时在按钮旁内联提示"修改任一字段可继续"，不限于错误横幅 | S |
| P2-5 WorkspaceOverview 权限别名 | App.tsx:7132 | `canResolveAutonomyAttention` 改接独立能力位（后端有自己的强制检查，纯前端健壮性） | S |
| P2-6 updater 契约失败不可重试 | automaticUpdateLoop.ts:199,231,246,281-284 | 契约校验失败不永久禁用（改为下次检查重试）；error 事件保留原始错误对象入日志 | S |
| P2-7 A2UI 组件命名漂移 | DesktopA2UISurface.tsx:57,113-122 | 注册表与 vendored renderer 命名对齐（Checkbox/Select 直名），消除 remapping | S |
| P2-8 MCP supervisor 启动恢复静默 | mcp_supervisor/mod.rs:500-527 | 启动恢复失败写入状态外，增加结构化诊断事件，便于排查 | S |
| P2-9 browser 工具传输错误烧毁一次性授权 | authorized_tool_host.rs:191 | Err 结果同样恢复预留的 once-permission（现仅 consent 短路恢复） | S |
| P2-10 MCP lease indeterminate 语义 | tool_call_lease.rs:81-106 | 文档化"indeterminate 按幂等键终态，重试须轮换键"；在调用方注释钉住 | S（文档） |

另：`runToneFromStatus('active')→'running'`（R3）为未接线隐患代码，下次触碰该函数时
一并修正或删除。

## P3-1 发布流水线真机门禁（Wave 8）

**背景**：tag CI 只验证签名/公证/摘要（package-artifacts-only），从不安装、启动或应用
真实更新（ELECTRON.md:97-137）。

**设计**：三平台门禁——安装包安装+启动冒烟；真实升级链路（旧版→新版）含 updater 事务
校验；失败升级回滚演练。复用 `scripts/updater-transaction.mjs` 与
`smoke-update-recovery.mjs` 既有事务/恢复逻辑，CI 产物升级为完整发布证据。
**工作量 L**。**依赖**：签名物料与 CI  runners（macOS/Windows/Linux）。

---

## 排序路线图

```
批次 1（立即，并行）        批次 2（后端落地后）      批次 3（契约/决策解锁）
├─ P0-1 步骤 0 路由器硬化   ├─ P0-1 步骤 3 桌面清理   ├─ P1-1 Changes 范围切换
├─ P0-1 步骤 1-2 steer 落地 ├─ P1-3 市场 UI（若决策）  ├─ P1-2 revert/stage
└─ P0-2 阶段步进器全链路    └─ P2 打磨项随手并入       └─ P3-1 发布门禁
```

- P0-1 与 P0-2 文件不相交，可全并行；P0-1 步骤 0 可单独先发。
- P2 项不设独立排期，随相邻文件改动带入，各自带测试。
- 每批次门禁：`make -C agi-stack desktop-check` + `desktop-browser-qa` 全绿 +
  原生 `run-desktop` CDP 冒烟（本轮已建立脚本模式，可复用）。

## 验收总口径

1.  honesty：所有新展示位必须有权威数据源或显式不可用态；审计文档（R 系残余风险）逐项销号。
2.  parity：Web 已有行为以 Web 为准；双端同改项（P1-3）需同步落地。
3.  测试：TDD，每修复/新能力配回归测试；契约改动配编解码器钉测试。
