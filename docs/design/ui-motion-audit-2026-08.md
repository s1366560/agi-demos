# Web + Desktop UI/动效全面审计与改进方案

> 日期:2026-08-06
> 方法:基于 `emilkowalski/skills` 技能包(`review-animations` / `improve-animations` / `find-animation-opportunities` / `emil-design-eng` / `apple-design`,安装于用户级 `~/.agents/skills/`)的规则体系,对 `web/`(AntD 6 + Tailwind 4)与 `agi-stack/apps/desktop/`(Electron + Radix + 手写 CSS)做静态代码审计 + 运行中视觉走查。
> 走查证据:`.tmp/design-audit/web-*.png`(Playwright,1440×900);desktop 经 Orca computer-use 截图(运行中的 release 实例 `ai.agistack.desktop`,pid 19128)。

## 审计规则基线(技能包核心条款)

- 频率决定动效:100+ 次/日(键盘动作、命令面板)**永不动画**;数十次/日只做近乎不可察觉的运动;偶发(Modal/Drawer/Toast)标准动画;罕见/首次可用 delight 预算。
- 进出元素用 `ease-out`(推荐强曲线 `cubic-bezier(0.23,1,0.32,1)`),**UI 禁用 `ease-in`**;内置弱缓动应替换为自定义曲线。
- UI 动画 < 300ms;按压反馈 100–160ms;Dropdown 150–250ms;Modal/Drawer 200–500ms。
- 只动画 `transform` / `opacity`(GPU);禁 `width/height/margin/padding/top/left`。
- 禁 `scale(0)` 入场(从 0.9–0.97 + opacity 起步);popover 从触发点缩放(Modal 豁免居中)。
- 高频触发元素(toast、toggle)用 **transition/@starting-style**,禁 keyframes(不可中断)。
- `prefers-reduced-motion` = 更温和而非零:保留 opacity/颜色,去掉位移;hover 动效需 `@media (hover:hover) and (pointer:fine)` 门控。
- 按压缩放 `:active { transform: scale(0.97) }` 是所有可压元素的基线反馈。

## 总体结论

两端动效底盘都**意外健康**:零 `ease-in` 误用、零 `transition: all`、零 `scale(0)`、时长普遍在预算内;desktop 有 18 个 reduced-motion 块,web 组件层有 187 处 `motion-reduce:` 配对。债务集中在:

- **web**:令牌层断裂(暗色主主题丢 AntD motion 缓动配置)、高频路径上的布局属性动画(进度条 `width` ×9 处)、全局 reduced-motion 兜底块重复 3 次且语义过激。
- **desktop**:toast 用 keyframes 且零退场(唯一硬违规)、全局无 `:active` 按压反馈、reduced-motion 覆盖有洞(chevron 旋转、开关滑块)且部分文件一刀切误伤颜色过渡。

单一最高杠杆修复:**web = 抽取双主题共享的 motion token fragment;desktop = 全局按钮基线加一行 `scale(0.97)` 按压反馈**。

---

## 一、Web 审计结果(`web/src`)

### 1.1 Findings(P0/P1/P2)

| # | 优先级 | 类别 | 位置 | 现状 (Before) | 建议 (After) | 依据规则 |
|---|---|---|---|---|---|---|
| W1 | P0 | 双主题 motion token 断裂 | `theme/antdTheme.ts:358-359` vs `155-161` | 暗色(主)主题只有 `motion: true`;缓动回退 AntD 默认,同一 Modal/Drawer/Dropdown 在亮/暗主题下缓动不同 | 5 个 motion token 抽成共享 fragment 两主题共用,统一为强曲线 `motionEaseOut: cubic-bezier(0.23,1,0.32,1)`、`motionEaseInOut: cubic-bezier(0.77,0,0.175,1)` | STANDARDS 缓动表;Cohesion |
| W2 | P0 | 高频/键盘动作动画 | `components/agent/chat/ChatSearch.tsx:184`(+ `hooks/useWorkspaceKeyboard.ts:19` Cmd+F) | 键盘唤出的搜索面板挂 `animate-fade-in-up`(250ms 位移)入场 | 键盘触发面板去位移动画,最多保留 ≤100ms opacity 淡入(Raycast 先例) | 频率表 100+/day;键盘动作永不动画 |
| W3 | P1 | 按压反馈缺失 | `index.css:856-910`(.btn-*)、`1321-1441`(.ant-btn)、`pages/Login.tsx:259` | 所有按钮 `:active` 只变色;全库 `active:scale-` 零命中 | `:active { transform: scale(0.97) }` + `transition: transform 160ms cubic-bezier(0.23,1,0.32,1)` | "Buttons must feel responsive";Apple §1 |
| W4 | P1 | 死代码 | `index.css:619-636` | `.interactive`(全库唯一 `:active{scale(0.98)}`)零引用,且 200ms ease 偏慢 | 删除,按压反馈落到 .btn-*/.ant-btn(160ms ease-out) | 死代码;按压预算 100–160ms |
| W5 | P1 | 布局属性动画+超时 | `ObjectiveCard.tsx:130`、`SubAgentTimeline.tsx:415`、`TaskList.tsx:159`、`WorkspaceTaskPlanPanel.tsx:195,395`、`TaskDashboard.tsx:534`、`ContextStatusIndicator.tsx:143`、`TaskLanePanel.tsx:286` | 8 处任务进度条 `transition-[width] duration-500`,运行期高频更新 | `transform: scaleX()` + `transform-origin: left`(`index.css:2397-2403` a2ui 进度条已是正确范式),≤300ms | GPU-only;UI <300ms |
| W6 | P1 | 流式布局动画 | `components/agent/chat/ThinkingBlock.tsx:182-183` | 流式思考进度条 `transition-[width] duration-300`,streaming 期间持续重排 | 同 W5:scaleX + origin-left | GPU-only;Interruptibility |
| W7 | P1 | reduced-motion 过激且重复 | `index.css:421-430`、`1631-1639`、`2580-2589` | 同一 `0.01ms !important` 全局块出现 3 次;opacity/颜色过渡也被清零;`animation-iteration-count:1` 让 spinner 冻结,减弱动效用户丢失"加载中"指示 | 合并为一块;保留 opacity/color 过渡;spinner 降级为慢速 opacity 脉冲 | "gentler, not zero" |
| W8 | P1→P2(降级) | 传送门式条件渲染 | `components/layout/TenantChatSidebar.tsx:1584-1586` | 折叠 `return null`,侧栏瞬消、主区瞬时 reflow | 侧栏常驻 DOM + `translateX(-100%)`,200ms `cubic-bezier(0.32,0.72,0,1)` | Preventing jarring change。**降级理由:触及布局逻辑且影响 desktop-web parity,需成对改动,本轮不动** |
| W9 | P2 | 手风琴布局动画 | `ThinkingBlock.tsx:199-201` | `max-height: 0↔400px` 过渡,属性清单厨房水槽式(7 项) | 只留 `max-height 300ms ease-out` 或 grid-rows 方案 | 精确属性;布局属性动画 |
| W10 | P2 | 布局属性动画 | `TenantChatSidebar.tsx:1595` | transition 清单含 `width` 300ms(拖拽中正确移除,好) | 随 W8 一并处理 | GPU-only |
| W11 | P2 | 进退不对称/死过渡 | `MobileSidebarDrawer.tsx:45,51,62` | 关闭 `return null` 瞬消;backdrop `transition-opacity` 无初态(死类);进入 keyframes 无退出 | transition + `@starting-style` 进入,退出 translateX(-100%) 200ms ease-out,backdrop 200ms 淡入淡出 | Interruptibility;进退同路径 |
| W12 | P2 | 入场缩放下限 | `index.css:2106-2119` | `status-pill-in` 从 `scale(0.8)` 入场 | `scale(0.95)` + opacity | Physicality 0.9–0.97 |
| W13 | P2 | 死动画成批 | `index.css:258-265,267-405,1527-1558` | `blob/pulse-slow/pulse-ring/subtle-float/glow-pulse/typing-dot/fade-in-left/fade-in-right/float/bounce-subtle/scale-in` 等全部零引用 | 删除(`shimmer` 保留,`tool-prep-shimmer` 在用) | 死代码;token 卫生 |
| W14 | P2 | 绘制属性动画 | `index.css:292-300,385-393` | `pulse-ring`/`glow-pulse` 动画 `box-shadow`(每帧重绘;当前为零引用死代码) | 若启用改伪元素 opacity 脉冲;否则随 W13 删除 | GPU-only |
| W15 | P2 | 双 spinner 体系 | AntD `Spin` 37 文件 vs Lucide `animate-spin` 157 处 | 两套加载指示并存,转速/缓动/视觉不一致 | 约定单一惯例(建议 Lucide `animate-spin motion-reduce:animate-none`),逐步收敛 | Cohesion |
| W16 | P2 | 事实上的 transition-all | `Login.tsx:186,230,259`、`EnhancedSearch.tsx:812`、`PromptTemplateLibrary.tsx:538`、`CanvasPanel.tsx:295,318`、`MessageArea.tsx:798,1110` 等 | 七属性 transition 清单挂在纯静态元素上 | 按实际会变属性收窄(多数只需 `transition-colors duration-150`) | 精确属性 |
| W17 | P2 | 高频元素 pulse | `ThinkingBlock.tsx:105`、`SubAgentTimeline.tsx:410` | 流式期间文本标签整体 `animate-pulse`,长会话持续可见 | 文本稳定,pulse 移到状态圆点 | 频率表;"阅读中的内容不应动" |
| W18 | P2 | hover 门控 | 全库 `hover:`/`group-hover:` 数百处 | 无 `@media (hover:hover) and (pointer:fine)` 门控,仅 `.touch-show` 兜底 | 当前只有颜色过渡危害低;未来引入 hover 位移/缩放前必须先加门控 | STANDARDS a11y |

**正面确认**:`html.app-ready` 防 FOUC 淡入正确;`fade-in/slide-up/fade-in-up` 系列全部 ease-out 且 ≤300ms;`scale-in` 从 0.95 起步;`CanvasPanel.tsx:635` 拖拽中 `transition:none`、松手回弹是教科书写法;`OnboardingTour.tsx` 已处理 reducedMotion;SplitPaneLayout 键盘调宽无动画(正确)。

### 1.2 动效机会(Gate 筛选后)

| # | 位置 | 现状 | 目的 | 频率 | 建议动效 |
|---|---|---|---|---|---|
| 1 | `.ant-btn`/`.btn-*`(index.css:856-910,1321-1441) | 按下无按压感 | Feedback | 数十次/日 | `:active scale(0.97)`,160ms `cubic-bezier(0.23,1,0.32,1)`;reduced-motion 保留变色去缩放 |
| 2 | `AgentChatContent.tsx:1335-1368` canvas 模式右 Pane | 右 Pane 瞬现、聊天列瞬跳 | 空间一致性 | 偶发 | 入场 `opacity 0→1 + translateX(16px)→0`,200ms `cubic-bezier(0.32,0.72,0,1)`,关闭原路返回 |
| 3 | `EmptyState.tsx:150-261` 建议卡组 | 卡片同时出现 | Delight(罕见档) | 罕见/首次 | `opacity 0 + translateY(8px)`→归位,250ms 强 ease-out,逐张 40ms stagger,不阻塞点击 |
| 4 | `MobileSidebarDrawer.tsx:45-62` | 关闭瞬消、backdrop 死过渡 | 进退同路径 | 偶发(移动端) | `@starting-style` 进入 300ms drawer 曲线;退出同路径 200ms;backdrop 200ms 淡入淡出 |
| 5 | `TaskList.tsx`/`WorkspaceTaskPlanPanel.tsx` 任务完成瞬间 | 100% 后状态直接替换 | State indication | 偶发 | 完成徽章 `scale(0.95)→1` + opacity 200ms 强 ease-out |

**已否决**:用户消息发送入场(Q1 频率)、路由级页面过渡(Q1)、流式 Markdown 逐字动画(Q4 阅读内容)、Dashboard 数字滚动(Q4)、表格行 hover 位移(Q1+Q2)。

---

## 二、Desktop 审计结果(`agi-stack/apps/desktop/src`)

parity 口径:parity 契约校验能力 JSON、路由清单与 DOM 结构(`data-parity-*`),非逐帧像素;纯 CSS 动效改动几乎不触碰 parity 门禁,仅改动静止态渲染或 DOM 结构时标"中"。

### 2.1 Findings

| # | 优先级 | 类别 | 位置 | 现状 (Before) | 建议 (After) | 依据规则 | parity 风险 |
|---|---|---|---|---|---|---|---|
| D1 | P0 | 可中断性 | `features/feedback/ToastCenter.css:24,85-95` + `ToastCenter.tsx:91` | toast 用 `@keyframes toast-enter` 入场;消失时直接从 DOM 移除**零退场**,堆叠 toast 瞬间上跳 | `transition: opacity 160ms ease-out, transform 160ms ease-out` + `@starting-style { opacity:0; transform: translateY(6px) }`;退场同路径反向(140ms);堆叠补位用 transition | 标准 6/9;Sonner 原则 5 | 低 |
| D2 | P1 | 按压反馈 | `styles.css:791` 全局 button 基线 | 全仓除 ResizeHandle 拖拽态外**没有任何 `:active` 反馈**;Radix `.rt-Button` 也无按下态 | 全局 `button { transition: transform 160ms ease-out } button:active { transform: scale(0.97) }`(例外:resize handle、拖动手柄) | 按压 100–160ms、scale 0.95–0.98;Apple §1 | 中(静止态不变) |
| D3 | P1 | reduced-motion 语义 | `ToastCenter.css:97-100` | reduced-motion 下 `animation:none`,toast 直接闪现 | 保留 opacity 渐显,只去 translateY | 标准 8;Apple §14 | 低 |
| D4 | P1 | reduced-motion 缺失 | `ChatPanel.css:74,2692,2784`、`SessionWorkspace.css:847`、`ConversationDetail.css:95,142`、`ComposerMenus.css:132`、`AssistantDuplicateDisclosure.css:48`、`ModelProviderWorkspace.css:215` | 8 处 chevron `transform: rotate()` 过渡无 reduced-motion 兜底 | reduced-motion 块中 `transition: none`(旋转属位移类) | 标准 8 | 低 |
| D5 | P1 | reduced-motion 缺失+hover 未门控 | `WorkspaceCreateDialog.css:101-111`、`MyWorkQueue.css:26-27`、`ComposerMenus.css:423-434` | `hover { transform: translateY(-1px) }` 无 reduced-motion,未 hover 门控 | reduced-motion 下 `transform:none`;加 `@media (hover:hover) and (pointer:fine)` | 标准 8 + ungated hover | 低 |
| D6 | P1 | 布局属性动画 | `features/settings/ModelProviderWorkspace.css:255` | 开关滑块 `transition: left 150ms ease`,动画 `left` 触发布局+绘制;无 reduced-motion | `transform: translateX(14px)`(GPU),补 reduced-motion | 标准 7 | 低 |
| D7 | P1 | reduced-motion 缺失 | `styles.css:3495,3505`(.review-event-switch::after) | 审批开关滑块 `translateX(16px)` 160ms,唯一 reduced-motion 块(5633)未覆盖 | 加入 5633 媒体查询块 | 标准 8 | 低 |
| D8 | P1 | reduced-motion 一刀切 | `ForcePasswordChangeScreen.css:192-198`、`KeyboardShortcutsDialog.css:135-138`、`SessionEvidenceCanvas.css:179-182` | `transition: none !important` 把颜色/透明度过渡也杀了 | 只对 transform/位移 `none`,保留 color/opacity | "gentler, not zero" | 低 |
| D9 | P2 | 缓动体系 | 全仓 `ease` ×44、`ease-in-out` ×12,**0 条 cubic-bezier** | 进出元素用内置弱缓动 | `:root` 引入 `--ease-out: cubic-bezier(0.23,1,0.32,1)`、`--ease-in-out: cubic-bezier(0.77,0,0.175,1)`、`--ease-drawer: cubic-bezier(0.32,0.72,0,1)` | "内置缓动太弱" | 低 |
| D10 | P2 | 布局属性动画 | `ChatPanel.css:3323,3944` | 进度条 `transition: width 180ms ease` | `scaleX()` + `transform-origin: left`(2px 小条代价小,可知情接受) | 标准 7 | 低 |
| D11 | P2 | 非 GPU 属性 | `styles.css:5622-5631`(tool-group-pulse) | 运行中工具组图标动画 `box-shadow`,每帧 paint | 改 `::after` 圆环 opacity 脉冲 | 标准 7 | 低 |
| D12 | P2 | spinner 碎片化 | 12 处 spinner 周期 750ms–1.2s 共 7 种 | 同类旋转指示器转速不一 | 统一 `--spin-duration: 800ms`(更快 spinner = 感知加载更快) | Cohesion;感知性能 | 低 |
| D13 | P2 | 缓动错配 | chevron 用 `ease`(ChatPanel.css:2692,2784 等) | 屏上形变应落 ease-in-out 档 | 随 D9 统一到 token | 缓动决策表 | 低 |
| D14 | P2 | 状态指示缺口 | `MyWorkQueue.css:44-46` | 不确定进度条是**静态** 38% 宽条,像卡死 | `translateX` 循环滑动 1.2s linear infinite;reduced-motion 静态 | 标准 1(该动没动) | 低 |
| D15 | P2 | 自建 overlay 无入场 | `ChatPanel.css:4313`(.voice-call-panel)、`KeyboardShortcutsDialog.css:1-24` | 手写 overlay 直接闪现;Radix 对话框有 200ms 默认动画,自建反而没有 | voice 面板加 `scale(0.96)+opacity` 200ms 入场;shortcuts 由 `?` 触发**保持无动画** | 标准 5;频率表 | 低 |

**正面确认**:零 `transition:all`/`scale(0)`/裸 `ease-in`/`will-change`;Radix Dialog 自带 200ms `cubic-bezier(0.16,1,0.3,1)` + `translateY(5px) scale(0.97)` 入场 + 100ms 不对称退场,质量在线;命令面板(cmdk,App.tsx:12709)正确地零动画;12 个 spinner/脉冲循环均有 reduced-motion 兜底。

### 2.2 动效机会(Gate 筛选后)

| # | 位置 | 现状 | 目的 | 频率 | 建议动效 |
|---|---|---|---|---|---|
| 1 | `styles.css:791` 全局按钮 | 无按压反馈 | Feedback | 数十次/日 | `:active scale(0.97)` + 160ms `cubic-bezier(0.23,1,0.32,1)`;reduced-motion 去缩放保留色变 |
| 2 | `ToastCenter.css`(配 D1) | 消失硬切、堆叠硬跳 | Preventing jarring change | 偶发 | 退场 `opacity 0 + translateY(4px)` 140ms 强 ease-out;堆叠补位 `transition: transform 200ms` |
| 3 | `SessionWorkspace.tsx:153` transitionSurface 面板 | canvas 面板开合瞬切 | 空间一致性 | 偶发 | `translateX(100%)→0` + opacity,240ms `--ease-drawer`;reduced-motion 仅 opacity 200ms |
| 4 | 路由页面容器(46 个 *Page) | 切换硬切 | Preventing jarring change | 数十次/日 | **仅 opacity** 淡入 120ms ease-out,禁位移缩放 |
| 5 | `Skeleton.css`→内容挂载 | 骨架屏瞬时被替换 | Preventing jarring change | 偶发 | 内容 `@starting-style { opacity:0 }` + 150ms 淡入,骨架同步淡出 120ms 交叉淡化 |
| 6 | `MyWorkQueue.css:25-27` 卡片网格首挂载 | 整屏同时弹出 | 状态指示 | 偶发 | 仅首挂载 stagger:200ms 强 ease-out,片间 30–50ms,上限 6 片,不阻塞交互 |
| 7 | `MyWorkQueue.css:46` 不确定进度条 | 静态 38% 条 | 状态指示 | 偶发 | `translateX(-100%)→260%` 1.2s linear infinite;reduced-motion 静态 |

**已否决**:命令面板开关动画(Q1 键盘 100+/day,Raycast 基准,务必保持零动画)、thought-timeline 手风琴高度动画(Q1+Q4 阅读内容)、聊天消息追加入场(Q1 高频)、搜索结果 stagger(Q1 随击键触发)、侧栏导航 hover 位移(Q1)。

---

## 三、运行中视觉走查记录

- **web**(Playwright,`localhost:3000`,证据 `.tmp/design-audit/`):Login 分屏页(亮)、租户 Overview、Agent Workspace、Settings、Projects 均渲染正常,无视觉破损。观察到:OnboardingTour 在 agent-workspace 自动弹出(罕见/首次 delight 面,符合预算);自动化强制暗色主题未生效(localStorage 注入被 system 覆盖),暗色样本以静态审计为准。
- **desktop**(Orca computer-use,运行中的 release 实例):工作空间总览(暗色单色主题)渲染良好,卡片层级清晰。发现 dev 实例无法与 release 实例并存(共享 userData 单实例锁,dev 端静默退出)——非 bug,但 `make -C agi-stack run-desktop` 前需先退出已运行的 release 客户端。demo 会话运行时不可用("Local runtime 状态不可用"),会话详情页未能走查,动效手感以静态审计结论为准。

## 四、两端共性问题与 parity 风险

1. **按压反馈双端皆缺**:web(W3)与 desktop(D2)都没有 `:active` 缩放回弹——这是"界面不听使唤"观感的最大来源,两端同点位修复,建议**同批落地**(像素变化一致,parity 风险可控)。
2. **进度条布局动画双端皆有**:web `transition-[width]` ×9(W5/W6)、desktop `transition: width` ×2(D10)——同一修法(scaleX + origin-left)。
3. **reduced-motion 语义双端皆粗糙**:web 一刀切 ×3(W7),desktop 漏盖 + 一刀切并存(D3/D4/D7/D8)——统一为"保留 opacity/color,去位移"。
4. **parity 敏感项**:W8(侧栏折叠)改动会影响两端布局 parity,本轮降级 P2;其余 P0/P1 均为纯 CSS/token 层,不触碰 DOM 结构与能力 JSON。

## 五、改进路线图

### 本轮落地(P0 + 低风险 P1)

- **web**:W1(共享 motion token fragment + 强曲线)、W2(ChatSearch 键盘面板去位移)、W3+W4(按钮按压反馈 + 删死类)、W5+W6(进度条 scaleX 化)、W7(reduced-motion 合并 + 温和化)
- **desktop**:D1+D3(toast 可中断化 + 退场 + reduced-motion 温和化)、D2(全局按压反馈)、D4+D5+D7(reduced-motion 补洞)、D6(开关滑块 transform 化)、D8(一刀切收窄)

### P2(2026-08-06 已全部落地)

- **web**:W8+W10 侧栏 off-canvas 滑入滑出(`inert`+`aria-hidden` 保持可及性,配套测试更新);W9 手风琴过渡收窄;W11 MobileSidebarDrawer 对称进退(`@starting-style` + 200ms 延迟卸载);W12 `status-pill-in` 改 scale(0.95) 起步;W13+W14 删除 11 个死 keyframes + 3 个死 token(`shimmer` 等活引用保留);W16 八处厨房水槽 transition 逐元素收窄;W17 流式文本 pulse 移到状态圆点;W15 补齐 22 处 `animate-spin` 的 `motion-reduce` 配对(100% 覆盖)+ 约定注释;W18 修复 4 处未门控 hover 位移(`pointer-fine:`);动效机会:canvas 右 Pane 入场、EmptyState 卡片 40ms stagger、任务完成徽章入场
- **desktop**:D9+D13 缓动 token 体系(`--ease-out/--ease-in-out/--ease-drawer` 入 `:root`,toast/按钮/chevron 全部消费);D10 进度条 scaleX 化;D11 `tool-group-pulse` 改 `::after` opacity 环;D12 十二个 spinner 统一 `--spin-duration: 800ms`;D14 不确定进度条滑动循环;D15 voice-call-panel 入场;动效机会:session canvas 面板 240ms 滑入、路由级 120ms 纯 opacity 页淡入(CSS-only,App.tsx 零改动)、时间线内容淡入、MyWorkQueue 首挂载 stagger(已验证稳定 key 不会在轮询时重放)

### 结构性重构(2026-08-06 已全部落地)

- **web Spin 替换**:新建 `components/common/Spinner.tsx`(`Spinner` + `LoadingOverlay`,复刻 AntD Spin 灰化/阻塞 UX);37 文件全部从 AntD `Spin`/`LazySpin` 迁出(31 独立指示器 + 5 inline small + 2 自定义 indicator 去壳 + 2 wrapper → LoadingOverlay);`lazyAntd.tsx` 的 Spin 复出口删除;新增 4 个 Spinner 渲染测试
- **web inline style 收敛**:12 个重点文件 151 → 27 处(转换 ~124 静态站点:字面量 margin/padding/width/fontSize → Tailwind,AntD 覆盖用 `!m-0` 前缀);保留的 27 处全部为动态值(theme token 色、计算几何、flow-root)
- **desktop styles.css 拆分**:8,412 行 → **文件删除**。Stage 0 删死代码 486 条规则(226 个零引用类,分 5 批逐批 grep 验证 + 全量测试);拆分为 `styles/tokens.css`(775)+ `styles/chrome.css`(300)+ `styles/base.css`(99)+ `styles/global.css`(@import 链)+ `src/app-shell.css`(1,145)+ 迁入 `features/chat/ChatTimeline.css`(1,685)、`features/auth/auth.css`(340)、`features/session/SessionPlanReview.css`(204)等属主文件;9 个测试文件同步重定向;38 个 qa 导入改指 `styles/global.css`
- **desktop App.tsx 拆分**:12,914 → **7,292 行**(Stage 1–8)。新增:`src/utils/format.ts`、`src/appShellTypes.ts`、`features/runtime/runStatusModel.ts`、`features/chat/appTimelineEventModel.ts`(+10 单测)、`features/session/workspaceArtifactModel.ts`(+8 单测)、`features/navigation/CommandPalette.tsx`、`features/session/WorkspaceReviewPanel.tsx`(1,787,含 5 个面板组件)、`features/navigation/appRouteRegistry.ts`(`createAppRouteRegistry(refs)` 工厂)、`src/hooks/useDesktopAuth.ts`、`src/hooks/useAgentConversation.ts`(params 对象模式,未引入 context/store);35 个测试文件为源码正则断言重定向

### 结构性重构验证结果(2026-08-06)

- web:**全量 Vitest 327 文件 / 3126 测试全绿**(基线 + 4 新增);tsc 通过;ESLint 改动文件 0 error;`vite build` 成功;Playwright 抽查(Plugins/Agents/AuditLogs)渲染正常,无新增 console 错误
- desktop:**2275 pass / 1 fail / 2 skipped**;tsc 干净;`pnpm run build` 成功;dev 实例截图复验无回归
  - 唯一 fail = `desktop-parity-reviewed-additional-web-entries` 的 "uncommitted-file hash binding"(design-qa.md:1561 记载的已知类目):App.tsx 工作区字节与 HEAD blob 不一致,**commit 后按既有流程 regenerate 即消解**;未削弱任何 parity 测试
- 全量 diff:190 文件,+1,658/−15,353;零 `data-parity-*` 变更、零 DOM 结构变更
- 遗留:desktop App.tsx 有少量未使用 import(tsc 未开 noUnusedLocals,不报错);`useDesktopAuth.ts`/`useAgentConversation.ts` 各 ~1,100 行(超 800 行指引,进一步拆分属额外设计决策);`auth.css` 属主 AuthPanel 为既有孤儿组件(行为与改动前等价)

### 验证结果(2026-08-06 已全部执行)

- web:`tokenSync` + 相关 Vitest(5 文件 66 测试)通过;`tsc --noEmit` 通过;ESLint 改动文件 0 error;Playwright 修复后截图复验无视觉回归
- desktop:`tsc --noEmit` 通过;全量测试 **2258 pass / 0 fail**;dev 实例(`make -C agi-stack run-desktop`)运行复验:
  - 服务层 CSS 断言:`@starting-style`、`toast-exiting`、`button:active scale(0.97)` 均存在,`@keyframes toast-enter` 已移除
  - 按压反馈实测:正常模式按下 `transform: matrix(0.97,...)`;`prefers-reduced-motion` 模式按下 `transform: none`(温和化生效)
- parity:diff 中零 `data-parity-*` 属性、零契约文件变更;paired visual diff 留待下次发版证据流程
- 已知限制:desktop demo 会话运行时不可用,会话详情页未走查;toast 实际进出动画未在运行实例中触发(依赖真实通知事件),以单测 + CSS 断言为准

### P2 验证结果(2026-08-06)

- web:`tsc --noEmit` 通过;**全量 Vitest 326 文件 / 3122 测试通过**(含更新的侧栏测试 40/40);ESLint 改动文件 0 error;`vite build` 成功且产物 CSS 确认新类/曲线生成、旧 `scale(.8)` 消失;Playwright 修复后截图无视觉回归
- desktop:`tsc --noEmit` 通过;**全量 2258 pass / 0 fail**;`render-performance-budget.test.mjs` 守卫(keyframes 必须带 reduced-motion、不得过渡 layout 属性)通过;dev 实例截图复验无回归
- 全量 diff:56 文件,+534/−379;零 `data-parity-*`、零契约文件变更
