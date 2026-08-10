# 浏览器插件桥( Browser Extension Bridge ) - 技术设计文档

> 创建日期: 2026-08-07
> 作者: AI Assistant
> 状态: **M1-M3 已实现并通过实机冒烟验证**(桥接+只读+动作+同意+光标+硬化;side panel/iab 属 M4)
> 依据: 本机 Codex/ChatGPT 应用逆向(扩展 v1.2.27236.6274 + 插件包 26.803.41515 + ChatGPT.app asar)+ MemStack agi-stack 代码调研

## 1. 概述

为 MemStack 桌面客户端增加"浏览器插件"能力:让本地 agent (sidecar 内的 ReActEngine) 能观察并操作用户真实浏览器( Chrome )中的页面,复用其登录态,典型场景为需要真实会话的 Web 自动化、跨标签页信息聚合、站点内多步操作。

设计参照 OpenAI Codex for Chrome 的实现(已在本机完成深度逆向,见第 2 节),核心选型:

- **薄扩展 + 桌面侧智能**: 扩展只做 CDP 透传与 tab 租约管理,所有快照/动作智能在 Rust sidecar 侧,扩展协议冻结、极少需要随功能迭代发版。
- **agent loop 留在桌面**: 复用 sidecar 现有 ReActEngine / ToolHost / 授权体系,浏览器工具以 `ToolHost` 接缝接入,`ReActEngine` 零改动。
- **站点粒度同意 + run 级租约**: 同意规则持久化于 `authority_store`,执行经 `AuthorizedRunToolHost` 授权门控,符合 AGENTS.md "Agent First" 约束。

## 2. Codex for Chrome 逆向结论( ground truth )

逆向对象(本机实物):

| 组件 | 路径 |
|---|---|
| Chrome 扩展 v1.2.27236.6274 | `~/Library/Application Support/Google/Chrome/Default/Extensions/hehggadaopoacecdllhhajmbjkdcmajg/` |
| 插件包 | `~/.codex/plugins/cache/openai-bundled/chrome/26.803.41515/`(`latest` 软链) |
| agent 侧客户端 | `…/chrome/latest/scripts/browser-client.mjs`( 1.15 MB,内嵌完整 Playwright injected script ) |
| native messaging host ( Rust ) | `…/chrome/latest/extension-host/macos/arm64/ChatGPT for Chrome`( 1 MB,公证签名 ) |
| 浏览器桥配置 | `~/.codex/browser/config.toml`、`~/.codex/chrome-native-hosts-v2.json` |
| 桌面应用 | `/Applications/ChatGPT.app`( Electron,asar 已提取分析 ) |

### 2.1 总体拓扑

```
Agent loop ( ChatGPT.app worker / codex CLI )
  │  MCP 工具调用: mcp__node_repl__js        ← 浏览器能力以 MCP 暴露,非内部工具
  ▼
node_repl ( Rust MCP server + 内嵌 Node 内核, OpenAI 签名 )
  │  browser-client.mjs 加载进"受信 vm 上下文"
  │  信任门: NODE_REPL_TRUSTED_BROWSER_CLIENT_SHA256S 哈希钉死
  │  特权 API nodeRepl.nativePipe 仅注入受信上下文
  ▼  Unix socket /tmp/codex-browser-use/<uuid>.sock
  │  4 字节长度前缀 + JSON-RPC 2.0,单帧上限 8 MiB
extension-host "ChatGPT for Chrome" ( Rust broker )
  │  Chrome native messaging ( stdio )
  ▼
Chrome 扩展 service worker ( MV3 )
  │  chrome.debugger "1.3" 原始透传
  ▼
用户 Chrome 页面(真实 profile,带登录态)
```

### 2.2 扩展:薄桩

- MV3,`permissions`: `alarms, bookmarks, debugger, downloads, favicon, history, nativeMessaging, notifications, scripting, sessions, storage, tabGroups, tabs, topSites, webNavigation, contextMenus, sidePanel`;`host_permissions: <all_urls>`;硬编码 `key` 钉扩展 ID。
- 静态 content script 仅一个( chatgpt.com 集成 );agent 覆盖层脚本 `codex.js` 由 `chrome.scripting.executeScript` 按需注入。
- **扩展内无 a11y 树、无点击逻辑、无截图代码**。host→扩展 JSON-RPC 方法目录: `ping, executeCdp, attach, attachTarget, detach, detachTarget, getTabs, getUserTabs, getUserHistory, getBookmarks, createNotification, getRecentlyClosedSessions, getTopSites, claimUserTab, createTab, markTab, finalizeTabs, focusTab, nameSession, executeUnhandledCommand, turnEnded, getInfo, moveMouse`。扩展→host 通知: `onCDPEvent / onCDPDetach / onDownloadChange / onPageEvent / onBrowserTabMentionsInvalidated`。
- `executeCdp` 是原始 CDP 透传( 10s 超时,超时自动 detach );扩展自身只点名 6 个 CDP 方法,其余全部来自桌面侧。
- 心跳熔断: 每 30s `ping` native host,失败即全浏览器强制 detach 所有 debugger 并停掉覆盖层。
- `foreign-frame-monitor.js`( document_start、allFrames 注入受控 tab ):遍历 open/closed shadow root,中和指向其他扩展 `chrome-extension://` 的 iframe(防 clickjacking/冒充)。

### 2.3 桌面侧 browser-client:三条读取路径 + 动作

- **读取**: ① Playwright `incrementalAriaSnapshot(mode:"ai")` — YAML 角色树 + `[ref=eN]` 句柄,iframe 递归展开;② 自研可见 DOM 序列化器,硬预算 20,000 字符 / 200 元素(凭证审查激活时保留 5k/50);③ CDP `Page.captureScreenshot`( JPEG q80,先尝试 screencast 快路径),**从不用 captureVisibleTab**( agent tab 是后台不可见的)。
- **动作**: 坐标级 `Input.dispatchMouseEvent / dispatchKeyEvent`(内嵌 Playwright 键盘引擎);DOM 定位级 `DOM.getContentQuads → 坐标 → Input.*`;Playwright locator 引擎页内执行;文本输入 `execCommand("insertText")`;上传 `DOM.setFileInputFiles`。
- **裸 CDP 政策过滤**: `Storage/CacheStorage/Database/Target/WebAuthn` 整域拒绝,~27 个方法黑名单( `Page.setBypassCSP`、`Network.clearBrowserCookies` 等),cookie 方法强制 URL 作用域,部分方法改写为带"禁止绕道"指导的错误。

### 2.4 信任链(四跳均有强制检查)

1. browser-client 加载: sha256 钉死(实测 config 哈希与磁盘文件一致);非受信代码请求 pipe 抛 `browser-client is not trusted`。
2. unix socket: 扩展 host 的 socket 为 0600(但 iab 路径此 build 漏了 chmod,`srwxr-xr-x` — Codex 自身的疏漏,我们须避免)。
3. native host: macOS **audit token** 校验对端代码签名身份(浏览器 team ID 白名单 + OpenAI 自家 team `2DC432GLL2`);仅读 v2 注册清单并校验 `required_paths`。
4. Chrome 侧: `allowed_origins` 钉扩展 ID。

### 2.5 同意/策略模型(全在桌面侧,扩展无 allowlist)

- 导航 URL 先过服务端 `site_status` 接口;按 origin 的用户同意走 MCP elicitation,持久化到 `~/.codex/browser/config.toml`: `approval_mode / history_approval_mode / download_approval_mode / upload_approval_mode ∈ {always_ask, never_ask, disabled}`,`[origins] allowed/denied`,`[full_cdp] allowed` + `full_cdp_access_enabled`。
- 失败分类 fail-closed: `site_status_blocked / guardian_denied / persisted_user_denied / enterprise_policy_blocked / user_declined`,错误信息明确禁止模型绕道。
- 完整 CDP 三重门: 默认关 → 设置手动开 → 逐站点批准。

### 2.6 Tab 租约与 turn 生命周期

- 租约: `{tabId, sessionId, turnId, origin: agent|user, state: active|handoff, mark: handoff|deliverable, claimedAt, viewportSize?}`。
- 每个 session 一个重命名 Tab Group;agent tab 后台创建(`active:false`),不接管用户当前标签;从租约 tab 弹出的子 tab 经 `webNavigation.onCreatedNavigationTarget` 自动认领。
- `turnEnded`: deliverable 保留解组、handoff 跨 turn 续存、未标记 agent tab 关闭(恢复 favicon)、user tab 释放;debugger 尽力 detach。

### 2.7 虚拟鼠标指针(详细实现)

**定位**: 同步剧场 — 真实点击被假光标"视觉到达"门控(`await ui.moveMouse` 先于 `Input.dispatchMouseEvent`),兼作动作节流;与截图路径零交互。

**握手链路**:

```
browser-client ui.moveMouse(tabId,x,y)  (JSON-RPC request,吞所有错误)
 → socket → extension-host → native messaging → SW moveMouse handler:
     可观测性检查(tab 为活动 tab 且窗口 normal 未最小化)
     不可见 → animateMovement:false 瞬移且不等待
     可见   → moveSequence++,创建 1500ms 到达等待器
     publish AGENT_CURSOR_STATE (1s 超时熔断)
 → content script 动画 → AGENT_CURSOR_ARRIVED {sessionId,turnId,moveSequence}
 → SW 按 `sessionId:turnId:moveSequence` resolve → 真实 Input 事件发出
```

三重熔断: SW 发布 1s、到达 1.5s、client catch-all。拖拽 `waitForArrival:false`。

**动画引擎**( content script,纯 CSS transform,无 canvas ):

- SwiftUI 风格弹簧 `{response, dampingFraction}`,半隐式欧拉积分,固定 240Hz 子步,rAF 驱动;每光标 9 个弹簧( x/y、rotation、scoot 三件套、stretch、visibility )。
- 路径规划: 距离 ≤196px 走 "scoot" 小跳;否则生成 **20 条候选贝塞尔**( 2 普通 + 18 双段弧:弧缩放 `[.55,.8,1.05]` × 手柄缩放 `[.65,1,1.35]` × 法线两方向),代价函数选优:
  `length + overshoot·320 + angleChangeEnergy·140 + maxAngleChange·180 + totalTurn·18 + backtrack·90 + (arc?45:0)`
- 时长非定时: 路径进度本身是弹簧,response 由路径指标混合后 clamp [0.12s, 2.2s];位置弹簧以更小 response 追逐产生尾随滞后。
- 表现: 速度自适应拉伸 `clamp(1−speed/5500, .65, 1)`;scoot 有 `sin(π·progress)` 下沉+倾斜;到达后 1.41s ±12.5° "思考"摆动;到达判定 = 进度≥.999 且偏差 ≤0.85px 且速度 ≤12px/s。
- 渲染: 闭 shadow root,z-index 2147483646,pointer-events none,`@media print` 隐藏;46×48 PNG 按 23×24 绘制,预制旋转 44°,`#339cff` 双 drop-shadow;MutationObserver 被删即重挂;状态存 SW(页面侧无状态,导航后重注入恢复)。
- **坐标用视口 CSS 像素**,与 CDP Input 同一坐标系,全程无 dpr/scroll 换算;仅顶层 frame 渲染。

**iab 路径**: 同一动画引擎模块在 ChatGPT renderer 内 `createPortal` 合成到 `<webview>` 上方的 overlay div(带 scale 适配);IPC `browser-sidebar-browser-use-cursor-state` / `browser-use-cursor-arrived`,同样 1.5s 等待。隐藏会话不画光标。

### 2.8 iab 内置浏览器

- 宿主: 主窗口 renderer 内 `<webview>` 标签(非 WebContentsView),每会话×tab 一个;`will-attach-webview` 门控重写 session — 所有 iab tab 共享单一持久会话 `persist:codex-browser-app`(刻意的"用户浏览器"定位),强制 sandbox/contextIsolation/preload。
- 桥: 主进程每会话起一个 `/tmp/codex-browser-use/<uuid>.sock`,与扩展路径同一套 JSON-RPC 协议;macOS 对端验证由原生插件 `browser-use-peer-authorization.node` 执行。
- CDP: `webContents.debugger.attach('1.3')`,flat mode,20s 超时;`Target.getTargets` 本地仿真;`Page.navigate` 拦截做策略断言;截图先调整 webview 到 clip 尺寸再截取。
- **输入关键分歧**: `Input.*` 不走 CDP,翻译成页内 JS 合成事件(`executeJavaScript` 注入:`elementFromPoint` 命中测试 → 合成 PointerEvent/MouseEvent → 管理 DOM focus),理由 *"to preserve focus"* — agent 操作不抢用户焦点;跨域 iframe 不支持。
- 可见化: 同一 `<webview>` 在隐藏宿主与右/下面板间重挂载不刷新页面;agent 可 `browser_visibility_set` 主动亮出;用户直接真实交互即 handoff。
- 策略双层: client 侧 origin 规则优先级(会话拒绝 > 全局拒绝 > guardian 缓存 > 会话允许 > 全局允许 > never_ask)+ 主进程导航栅栏( browser-use 激活期 `will-navigate` 只放行 http(s)/about:blank,违规以合成 `Page.navigationBlocked` 事件回报 agent );下载授权 10s TTL。
- "cdp" 后端类型 = OpenAI 云端浏览器( gaas ),非本地 remote-debugging。

## 3. MemStack 现状地基

可直接复用(路径均在 `agi-stack/`):

- **sidecar 本地运行时**: `apps/desktop/sidecar/src/local_runtime/mod.rs` — 内嵌 axum HTTP+WS,`ReActEngine` 经 `build_engine` 装配;`AuthorizedRunToolHost`( fail-closed、run 级授权、5 分钟 TTL)+ `tool_authority.rs` / `authority_store.rs`。
- **ToolHost 三后端先例**: plugin-host 热插拔 / `adapters-local-tools`( 52 本地工具)/ `adapters-mcp`( WS MCP )— 新增第四个后端有成熟模式可循。
- **握手范式**: `control.rs` HMAC-SHA256 挑战应答( Electron↔sidecar stdio 控制管)。
- **保险库**: `application_vault.rs`( AES-256-GCM ),可存扩展配对凭据。
- **McpSupervisor**: stdio/HTTP/SSE/WS 四传输,租户/项目作用域 + tool-call lease。
- 桌面设置页 / HITL 权限块 / `x-agistack-launch` capability 中间件 / CORS 钉 `agistack://app`。

明确缺失: 无浏览器扩展、无 native messaging host、sidecar 无 CDP 客户端、桌面端无内嵌浏览表面(导航策略 deny-by-default)。

## 4. 目标架构

### 4.1 组件映射

| Codex 组件 | MemStack 对应物 |
|---|---|
| browser-client.mjs + node_repl | 新 crate `crates/adapters-browser`( Rust ):CDP 客户端 + 快照注入脚本( JS 字符串资产)+ 动作引擎 |
| extension-host ( Rust broker ) | sidecar 二进制 `--native-host` 子命令模式;broker 经 loopback API 连回主 sidecar(凭据来自安装时写的注册 JSON) |
| native messaging manifest | 安装/卸载/健康检查控制命令,枚举各 Chromium 系浏览器 manifest 目录 |
| `mcp__node_repl__js` MCP 入口 | `BrowserToolHost` 实现 `core::ports::ToolHost`,经 `AuthorizedRunToolHost` 包装;ReActEngine 零改动 |
| `~/.codex/browser/config.toml` | `authority_store.rs` 持久化 `[origins] allowed/denied`、`approval_mode`、`[full_cdp]` |
| site_status 云服务 | HITL `permission` 块 + 持久化 origin 同意(无云端依赖) |
| Tab Group 租约 / turnEnded 清理 | run 级 tab 租约绑定 `DesktopRun`,run 结束按 deliverable/handoff/close 清理 |
| audit token 对端验证 | v1: socket 0600 + HMAC 共享密钥握手(复用 control.rs 模式);v2: audit-token 签名验证 |
| 虚拟光标引擎 | 独立 TS 模块 `packages/agent-cursor`(扩展 content script 与桌面 renderer 共用) |

### 4.2 扩展协议(冻结面,照抄 Codex 稳定子集)

- 传输: 扩展↔host = Chrome native messaging;host↔sidecar = 长度前缀 JSON-RPC 2.0( 8 MiB 帧上限)。
- host→扩展方法: `hello / ping / attach / detach / executeCdp / getTabs / getUserTabs / claimUserTab / createTab / markTab / finalizeTabs / focusTab / nameSession / turnEnded / moveMouse`。
- 扩展→host 通知: `onCDPEvent / onCDPDetach / onPageEvent`。
- **所有智能以 `executeCdp` 参数形式存在**,扩展不为功能迭代发版。
- sidecar 侧 `executeCdp` 政策过滤: 禁 `Storage/WebAuthn/Target` 域、`Page.setBypassCSP` 等;cookie 方法强制 URL 作用域;错误信息带"禁止绕道"指导。

### 4.3 同意模型(符合 AGENTS.md Agent First)

- origin allow/blocklist 成员检查为确定性( set-membership ),持久化 `authority_store`。
- 模糊场景裁决走 agent 结构化 tool-call 并记审计日志。
- 高危能力( history、完整 CDP、file:// )永不给 always 选项。
- 完整 CDP 三重门: 默认关 → 设置开 → 逐站点批准。

### 4.4 隔离与光标

- Tab Group per run;租约绑定 run_id;turn 结束清理策略同 Codex。
- 虚拟光标: 到达握手门控动作( 1.5s )+ 发布熔断( 1s )+ client 吞错;可观测性检查(可见才动画);视口 CSS 像素坐标系。

## 5. 浏览器工具集( BrowserToolHost 暴露)

| 阶段 | 工具 |
|---|---|
| M1 只读 | `browser_list_tabs`、`browser_snapshot`(自研 aria 注入脚本,20k 字符预算)、`browser_screenshot`( CDP JPEG )、`browser_console_logs` |
| M2 动作 | `browser_navigate`、`browser_click(ref)`、`browser_type(ref,text)`、`browser_scroll`、`browser_new_tab`、`browser_claim_tab`、`browser_mark_tab` |
| M3 深度(三重门后) | `browser_network_log`、`browser_evaluate`、`browser_pdf`、`browser_cdp_raw` |

## 6. 分期路线

- **M1 桥+只读(约 2 周)**: 薄扩展( manifest + SW 透传 + tab 管理,~500 行 TS )、sidecar `--native-host` broker、`adapters-browser` CDP 客户端、`BrowserToolHost` 只读工具、安装/健康检查命令。验收: 桌面端对话中 agent 列出打开的标签并总结指定页面。
- **M2 动作+同意(约 2-3 周)**: 三档动作实现( locator→DOM quad→坐标 )、Tab Group 租约与 run 清理、origin 四档同意入 `authority_store`、HITL 接桌面 UI、心跳熔断、foreign-frame-monitor、虚拟光标。验收: agent 完成一个需登录的多步操作,全程有批准记录与可视光标。
- **M3 硬化**: 完整 CDP 三重门、audit-token 对端验证、凭证代理(值不回传模型)、审计报表。
- **M4 形态扩展**: side panel 聊天、iab 式内嵌后端(桌面端内嵌浏览表面复用同一桥协议,输入走 JS 合成保焦点)、商店上架。

## 7. 风险与开放问题

1. `chrome.debugger` attach 的黄色警告条无法消除( Codex 同样承受),需 UX 文案预期管理。
2. MV3 service worker 30s 闲置回收 → native messaging 长连断开,需 alarms keep-alive + 重连恢复( Codex 用 0.5min alarm + ping)。
3. 自研 aria 快照脚本是主要技术不确定性 → M1 先用 `Page.createIsolatedWorld` + `Runtime.evaluate` 做 PoC 验证再排期。
4. `--native-host` 被 Chrome 拉起时无 Electron 握手环境,凭据分发依赖安装时注册 JSON(带 `required_paths` 校验),必须 fail-closed。
5. socket 权限必须显式 0600( Codex iab 路径的疏漏为反面教材)。
6. iab 若实施,存储隔离(共享 session vs per-run partition)需产品决策,默认建议共享。

## 8. 附录:逆向工作副本

- `/tmp/codex-ext/` — 扩展反混淆副本( background.js / codex-cs.js / sidepanel chunks )
- `/tmp/codex-re/` — browser-client.pretty.js( 42,569 行 )、asar-full/、pretty/main.js、host-strings.txt
- 注: `/tmp` 副本重启后丢失;原始证据位置见第 2 节表格。

## 9. M1 实现记录( 2026-08-07 )

实现组件:

| 组件 | 位置 | 验证 |
|---|---|---|
| 协议/CDP 客户端 crate | `agi-stack/crates/adapters-browser/` | 38 单测 + 2 集成测试 |
| 扩展薄桩 ( WXT, MV3 ) | `agi-stack/apps/browser-extension/` | 28 单测 + 32 快照断言,构建 9.4 kB |
| sidecar 桥接模块 + broker | `sidecar/src/local_runtime/browser_bridge.rs` (950 行)、`sidecar/src/native_host.rs` (475 行) | sidecar 377 测试 |
| fan-out + 引擎接线 | `local_runtime/fan_out_tool_host.rs`、`agent_engine_for_role`、两个 wrapper 泛化为 `Arc<dyn ToolHost>` | 同上 |
| 桌面设置 UI | `apps/desktop/src/features/settings/BrowserIntegrationSettingsPage.tsx` | `pnpm build:electron` 绿 |
| 实机冒烟 | `apps/browser-extension/scripts/smoke-bridge.mjs`( `pnpm test:bridge` ) | **PASS**: 真实 Chromium + 扩展 → broker → WS 鉴权 → 4 工具上门控列表 |

实机验证修正的三个设计偏差(均已修复):

1. **argv 子命令不可行**: Chrome native messaging manifest 不能携带参数,Chrome 以扩展 origin 作为 argv[1] 拉起 host。`main.rs` 现同时匹配 `--native-host` 与 `chrome-extension://*` argv。
2. **品牌 Chrome 禁止 `--load-extension`**( "not allowed in Google Chrome, ignoring" ),自动化冒烟必须用 Playwright 控制的 Chromium(有头模式)。
3. **Chromium 的用户级 NativeMessagingHosts 目录是相对当前 user-data-dir 解析的**( `<user-data-dir>/NativeMessagingHosts` ),自定义 profile 下系统级安装不可见;冒烟脚本将 manifest 镜像进临时 profile。真实 Chrome 默认 profile 读取系统安装,无需变通。

其他落地事实:

- 扩展 ID(开发期钉死): `enbljdpbhdllbbkcjhccmbgpkfmcdkkl`(密钥在 manifest `key`,私钥不入库)。
- 注册表: `~/.memstack/browser-bridge/registry.json`( 0700/0600 ),bridge 停止时删除( fail-closed )。
- LLM 可见性机制(追踪确认): ReActEngine 仅消费工具**名**( `Available tools: [...]` prompt 插值 ),schema 只经 `/mcp/tools/list` 提供;浏览器工具遵循同一机制(FanOut 名字 + mcp listing 合并,broker 离线即消失)。若 M2 需要模型更精确地构造参数,应评估把 schema 注入 prompt 的独立改动。
- `/mcp/tools/list` 在 `require_user_session` 之后:调用方需先 `POST /api/v1/auth/local-session` 获取会话凭据。

## 10. M2 实现记录( 2026-08-07 )

实现组件:

| 组件 | 位置 | 验证 |
|---|---|---|
| 动作层( 7 工具 + world 缓存 + ref 解析 + 租约 ) | `crates/adapters-browser/src/actions.rs` (1299 行)、`host.rs` (+395) | 72 单测 + 2 集成 |
| 扩展 M2( tab group/turnEnded/光标/monitor ) | `apps/browser-extension/src/{tab-groups,cursor/,monitor.ts}` + 2 个内容脚本 | 87 测试,构建 31.65 kB |
| sidecar 接线 | `browser_run_tool_host.rs` (689 行,origin 门控)、`session_store.rs` schema 21→22 (`desktop_browser_origin_grants`)、HITL scope 扩展、run 终态清理钩子(含 cancel/review/恢复路径)、30s 心跳 | 398 测试 |
| 桌面 UI | HitlResponseCard 四档同意 + 设置页 origin 授权管理 | 见 M2-C 报告 |
| 实机冒烟 | `scripts/smoke-bridge.mjs` M2 段 + sidecar `browser_bridge_dev_call` 诊断命令 | **PASS**: 建组/分配/聚焦/光标 overlay 实机出现/CDP 点击改页面状态/turnEnded 关 tab |

关键设计落地事实:

- **隔离世界必须显式缓存**: `Page.createIsolatedWorld` 同名不复用,`(tabId,frameId)→executionContextId` 缓存 + 三类事件( `executionContextsCleared/Destroyed`、`frameNavigated` )失效,否则 snapshot 的 ref stash 每次调用即失效。
- **origin 同意全链路**: 未决/拒绝以 **Ok 工具结果**(非异常)返回结构化 JSON,由 LLM 决定发起 `HitlKind::Permission`(target kind `browser_origin`,scope once/site/all/deny);site/all/decline 持久化(`'*'` 为全局),once 仅 run 内存;判定顺序 decline > all > site > once > 未决(确定性 membership,符合 Agent First)。
- **browser_* 工具绕过幂等账本**: consent 短路结果若以 Completed 入账,字节相同重试会命中"已完成"重放;现 profile 检查后直接委托(授权模型是 origin 授权层,非工作区账本)。
- **光标注入用隔离世界而非 MAIN 世界**: MV3 MAIN 世界无 `chrome.runtime` 通道,握手协议依赖之;闭 shadow root 已提供隔离。
- **ensureTabGroup 需要锚定 tab**: `chrome.tabs.group` 必须有 tabId,建组时先开后台 about:blank 锚定 tab。
- **run 取消/评审通过/崩溃恢复路径同样触发租约清理**(不限于两个正常终态钩子)。

## 11. M3 实现记录( 2026-08-10 )

实现组件:

| 组件 | 位置 | 验证 |
|---|---|---|
| CDP 政策双模式 | `adapters-browser/src/cdp_policy.rs`( Conservative/FullAccess;硬禁域与契约方法两模式同拒) | 83+2 测试 |
| `browser_cdp_raw` 工具 | `adapters-browser/src/host.rs`( FullAccess 政策 + 4k 截断) | 同上 |
| 完整 CDP 三重门 | `BrowserBridgeConfig.full_cdp_access_enabled`(默认关)+ `desktop_browser_capability_grants` 表 + HITL kind `browser_full_cdp`(仅 once/site,无 all) | sidecar 433 测试 |
| 传输硬化 | bridge.sock unix socket(0700/0600)+ accept 时 getpeereid(macOS)/SO_PEERCRED(Linux) 同 UID 校验;TCP 回退(Windows);broker `pick_transport` 每轮重估 | 实机冒烟( socket mode 600 断言 ) |
| 凭证代理 | vault 记录 `site-credential.v1.<sha256>`( ProviderCredentialBroker 模式)+ 元数据表 + `browser_fill_credentials`( origin 门控 + per-run once HITL + 值不出 sidecar) | 433 测试(断言密文不出现在结果/审计) |
| 动作审计 | `desktop_browser_action_audit` 表 + `BrowserRunToolHost.call` 统一包裹(全工具、含失败、fire-and-forget)+ `GET /audit` 路由 + 30 天保留 | 同上 |
| 截图工件化 | base64 解码 → `record_artifact_version` 落盘 → 返回 `{artifact_id, width, height}`;无 run 绑定时降级 `{path}` | 同上 |
| 桌面 UI | full-CDP 开关 + 能力授权列表、站点凭证管理、审计查看器;`browser_full_cdp`/`browser_credential_fill` 同意卡片 | 桌面 2307 测试 |
| 扩展 tsc 清偿 | mock 类型改从 `ChromeApi` 接口派生;新增 `chrome` 全局类型声明 | tsc 33→0 |

关键设计落地事实:

- **HMAC 首帧握手被有意省略**: bearer token 已证明 0600 注册表读取权,getpeereid 在内核层证明同 UID;对同一秘密再做 HMAC 是对同一事实的重复证明,无新增防御面。
- **axum 0.7 不支持 UnixListener**: 经 `hyper_util::service::TowerToHyperService` + `hyper::server::conn::http1` per-connection 服务(两个 crate 均已在锁树,仅新增直接依赖边)。
- **完整 CDP 无 all 选项**: 高危能力(scope `all` 被 `valid_permission_response` 拒绝),与 Codex 的 history/CDP 策略一致。
- **sun_path 限制**: macOS 每用户临时目录长度接近 104 字节 socket 路径上限,测试夹具需短路径根。
- **browser_* 工具的审计独立于工作区账本**(M2 起绕过幂等账本),审计表是浏览器动作的完整取证记录。

## 12. M4 实现记录( 2026-08-10 )

实现组件:

| 组件 | 位置 | 验证 |
|---|---|---|
| 多后端桥接注册表 | sidecar `browser_bridge.rs`(服务器主动 hello 识别后端、per-backend 会话/心跳/路由、`request_on`) | sidecar 440 测试 |
| side panel 会话铸造 | `getSidePanelSession`(仅 unix 传输 + chrome-extension 后端,双门 + 审计) | 铸造凭证 `/auth/me` 端到端验证 |
| 扩展 side panel 聊天 | `apps/browser-extension/entrypoints/sidepanel/` + `src/sidepanel-chat.ts`(SW 内 HTTP/WS,绕 CORS;HITL 项降级引导桌面端) | 扩展 115 测试 |
| 多后端 crate 维度 | `BridgeEndpoint.request_on`、HostState 全量 `(backend, tabId)` 键、聚合 `list_tabs`(离线后端容错)、逐键键盘模式 | crate 97+2 测试 |
| iab 内嵌浏览器 | `electron/main/iab/`(WebContentsView 池、专属导航策略、手写 RFC6455 WS 客户端、JS 合成输入保焦点、光标注入 + chrome.runtime shim)、渲染器 Browser 面板 | 33 单测(含真 WS-over-unix 握手) |
| 上架准备 | 零依赖自绘图标(16/48/128)+ `docs/design/browser-extension-store-listing.md` | 构建 manifest 校验 |

关键设计落地事实:

- **side panel 认证路径**: 全部 HTTP/WS 在扩展 SW 内发起(`host_permissions: <all_urls>` 覆盖 loopback,天然绕过 CORS);面板页面是哑 UI;launch token 只在 UID 校验后的 unix socket 上传输。
- **iab 输入不抢焦点**: `Input.*` 翻译成页内合成事件(Codex iab 同构),跨域 iframe 不支持。
- **iab 光标通道**: 复用扩展编译产物 + 页内 chrome.runtime shim + console.log 前缀桥接回主进程。
- **registry  freshness**: 冒烟/崩溃会留下失效 registry+socket;broker/iab 的 stale 容错依赖重试循环(见下条修复)。
- **实机验证发现的缺陷(已修复)**: iab 重连循环在桥离线时使主进程停摆。根因: `backend.ts` 的 `onClose` 闭包引用 `await` 返回前的 `const socket`(TDZ),连接失败时同步抛出 `ReferenceError`,未捕获异常触发 Electron 模态 `NSAlert` 停泵(定时器饿死、窗口不出、DevTools 无响应、0% CPU)。修复: 握手完成前不发 `onClose`、TDZ 安全持有者、error 路径显式 `destroy()`、日志节流(每 12 次一条)。教训: **Electron 主进程的未捕获异常会变成模态对话框,异步闭包捕获 await 绑定的 const 是定时炸弹**。实机终验: 窗口正常、循环健康、iab 后端连接应用 sidecar(`connected_backends: ["iab"]`)、建 tab 成功。
