# 渲染性能预算(Render Performance Budget)

对应路线图 P2-5(`docs/design/desktop-ux-benchmark-roadmap.md`)。目标:防止 Codex #15330 类回归——IDE diff 视图空闲时 CPU 跑到 200–330%。本文档把 P1-4 落在 `SessionChangesCanvas` 上的"事件驱动、无空闲重绘"约束推广为全桌面端的常设预算,并由 `tests/render-performance-budget.test.mjs` 在 CI 中强制执行。

## 核心指标

- **diff 视图(Changes canvas)空闲 CPU ≈ 0%**:会话无事件流入时,渲染进程不应有任何由本视图贡献的持续重绘、定时器回调或布局计算。
- **流式时间线空闲 CPU ≈ 0%**:agent 未运行、无流式事件时,除下列白名单外不得有定时器或动画在跑。

### 手动验证方法

1. `make -C agi-stack run-desktop` 启动原生客户端,打开一个带有改动的会话,切到 Changes canvas。
2. 打开 Chrome DevTools(开发者工具)→ Performance Monitor,观察 CPU 曲线:停止一切输入后,CPU 应回落到接近 0%,无周期性尖峰。
3. 或在终端 `top -pid $(pgrep -f "Electron Helper \(Renderer\)" | head -1)`,空闲时渲染 helper 的 %CPU 应稳定在低个位数以下。
4. 若出现持续高占用,用 Performance 面板录制 5 秒,检查是否有定时器回调、`requestAnimationFrame` 循环或无限 CSS 动画在驱动重绘。

## 预算规则(可检查)

### 规则 1:定时器与 rAF 白名单制

重渲染面(diff 视图、时间线、终端、artifact 画布)禁止引入 `setInterval(` / `setTimeout(` / `requestAnimationFrame(`,除非属于下列白名单。白名单在 `tests/render-performance-budget.test.mjs` 中显式枚举,每条都有注释说明理由;新增例外必须同步修改测试并写明理由。

现有白名单(全部满足"可见且处于活动状态才运行"):

- `CurrentActivityHeadline.tsx` 的 1 秒走时:仅当会话运行中(headline 条可见)才挂载,运行结束组件卸载,定时器随之清除。
- `ChatTimeline.tsx` `TimelineWorkingRow` 的 1 秒走时:仅当 working 指示器可见(agent 工作中)才启用。
- `HitlResponseCard.tsx` 的 1 秒倒计时:仅当请求未作答且处于 active 状态时启用。
- `VoiceCallPanel.tsx` 的 1 秒通话计时:仅当通话面板挂载(通话进行中)时启用。
- `useAgentSocket.ts` 的 heartbeat / watchdog:WebSocket 连接保活与看门狗,属于网络层结构性事实,不驱动渲染;连接关闭即清除。
- xterm 内部(`InteractiveTerminal.tsx`):xterm 自身的光标闪烁与渲染循环属第三方终端组件内部实现;挂载时的一次性 `requestAnimationFrame(fitAndNotify)` 为初始化适配,卸载时全部 dispose。
- 事件驱动的单次 `setTimeout` / `requestAnimationFrame`(如焦点恢复、滚动锚定、WS 事件的 16ms 合帧 flush)不算空闲负载:它们由用户输入或后端事件触发、一次性执行完毕,不在空闲时重复触发。此类调用允许存在,但禁止写成自续期(self-rescheduling)循环。
- 管理页的可见性门控轮询(如 `useRuntimePoolController.ts` 15 秒刷新):随页面卸载清除,且以 `document.visibilityState === 'visible'` 为闸门。新增轮询必须沿用同一模式(卸载清除 + 可见性门控 + 不小于 5 秒间隔)。

### 规则 2:hover / 高亮效果纯 CSS、仅 transform/opacity

- hover、选中、展开等视觉反馈用 CSS 实现,禁止用 JS 状态驱动逐帧更新。
- `transition` 只允许 `transform`、`opacity`、`color`、`background(-color)`、`border-color`、`box-shadow` 等不触发布局的属性。
- 常驻 chrome(侧栏、头部、面板骨架)中禁止对 `width` / `height` / `top` / `left` 等布局属性加 `transition`。
- 时间线卡片内的 2px 进度条(`.skill-progress-bar` / `.subagent-progress-bar`)当前使用 `transition: width`,布局影响被限制在独立轨道内,属已知豁免;若改为 `transform: scaleX` 更佳,列为后续优化,不强制。

### 规则 3:无限动画必须响应 prefers-reduced-motion

- 任何包含 `@keyframes` 的 CSS 文件,必须在同一文件内提供 `@media (prefers-reduced-motion: reduce)` 兜底(关闭或降级动画)。测试按文件强制检查。
- spinner / pulse 类"进行中"指示器同样适用:reduce 时退化为静态指示。

### 规则 4:diff / 列表渲染的渐进渲染上限

- 时间线已有渐进渲染模式:`ChatTimeline.tsx` 中 `TIMELINE_RENDER_THRESHOLD`(150 条)触发窗口化,初始窗口 `TIMELINE_RENDER_WINDOW`(100 条),每次"显示更早"步进 `TIMELINE_RENDER_STEP`(100 条)。新增长列表沿用该模式:先渲染尾部窗口,按用户操作分批向前扩展。
- diff 视图当前按文件折叠渲染(默认只展开首个文件,hunk 用 `<details>` 懒展开),展开全部时为有意的用户操作,可接受一次性渲染。
- **后续跟进项:长 diff 虚拟化**。触发阈值:单个文件展开后 diff 行数超过约 2000 行,或会话总改动行数超过约 10000 行且用户选择"全部展开"时,首屏渲染与滚动出现可感知掉帧(Performance 面板长任务 > 200ms)。达到阈值即立项做行级虚拟化(只渲染视口内行),不要在未达阈值前提前引入虚拟化复杂度。

### 规则 5:热路径派生必须 memo 化

- 时间线 / diff 的模型派生(分组、过滤、映射)必须挂在 `useMemo` 上,依赖项为不可变数据引用;禁止在组件函数体内对 `state.items` 级别的大数组做每次渲染都重算的派生。
- 现状:`ChatPanel.tsx` 的时间线派生(`visibleTimelineState`、`timelineDisplayItems` 等)与 `ChatTimeline.tsx` 的 narrative 分组均已 memo 化,composer 每次击键不会重跑时间线模型。

## 测试执行

`tests/render-performance-budget.test.mjs` 做三类静态检查:

1. **零容忍集**:diff 视图相关文件(`SessionChangesCanvas.tsx` / `sessionChangesModel.ts` / `sessionChangesReviewModel.ts`、`SessionTerminalCanvas.tsx`、`LiveArtifactCanvas.tsx`)不得出现 `setInterval(` / `setTimeout(` / `requestAnimationFrame(`。
2. **白名单集**:聊天 / 终端 / 网络层文件中的 `setInterval(` 出现次数必须等于该文件的白名单条目数(每条带注释);多一个或少一个都失败,防止静默新增或遗留死白名单。
3. **CSS 集**:`src/**/*.css` 中含 `@keyframes` 的文件必须含 `prefers-reduced-motion`;`SessionChangesCanvas.css` 额外要求完全无 `@keyframes` / `animation` / `infinite`(沿用 P1-4 红线)。

该测试是对 `tests/session-changes-review-model.test.mjs` 中 P1-4 pin 的一般化;原 pin 测试保留,两者任一失败都视为预算破坏。
