# Web 客户端会话流渲染设计参考（供桌面端复刻）

> 来源：`web/src`（React 19 + TypeScript + AntD 6 + Zustand + Tailwind v4）。
> 所有样式均为 Tailwind 工具类 + `web/src/index.css` 的设计 token；行号为当前 main 分支行号。

## 0. 渲染管线总览

```
AgentWorkspace.tsx (路由页)
└─ AgentChatContent.tsx (布局/模式编排, 5 种布局: chat/task/code/canvas/collab)
   └─ chatColumn (flex 列)
      ├─ 会话头 (ConversationAgentBadge + 标题 + 时间)
      ├─ MessageArea.tsx (虚拟化消息列表, @tanstack/react-virtual)
      │  ├─ groupTimelineEvents() 把 timeline 事件分组为:
      │  │    event(单条) / timeline(连续 act+observe 组) / subagent(子代理组)
      │  ├─ MessageBubble.tsx        → 单条事件按 event.type 分派
      │  ├─ ExecutionTimeline.tsx    → timeline 组(工具时间线)
      │  ├─ SubAgentTimeline.tsx     → subagent 组
      │  ├─ JitContextCard / MemoryCapturedStep → memory 事件
      │  ├─ StreamingAssistantSection → 流式 thought/文本(订阅 streamingStore)
      │  └─ SuggestionChips / TurnPlaceholderRow / 置顶区
      └─ InputBar.tsx (输入卡片 + InputToolbar)
```

事件流：`agentService.ts`（WebSocket，`wsConnection.ts`）→ `messageRouter.ts: routeToHandler(eventType, data, handler)` → `streamEventHandlers.ts: createStreamEventHandlers()`（写入 Zustand：timelineStore / streamingStore / executionStore / hitlStore）→ 组件按 store 订阅渲染。`text_delta/thought_delta/act_delta` 为高频事件，经 delta buffer 以 ~50ms 批量 flush（`deltaBuffers.ts`）。

---

## 1. 全局设计 Token（ monochrome 单色体系）

### 1.1 单一事实源 `web/src/theme/tokens.ts`

- 暗色为主主题：bg `#0a0a0a`，面板梯 `#121212 / #181818 / #1f1f1f`，边框 `#333333 / #404040`，文字 `#ededed / #9c9c9c / #8a8a8a`，accent 近白 `#f2f2f2`。
- 亮色派生：bg `#f7f7f7`，面板 `#ffffff / #f2f2f2 / #e9e9e9`，边框 `#e3e3e3 / #cccccc`，文字 `#141414 / #4f4f4f / #6b6b6b`，accent 近黑 `#262626`（白底 AA ≈13:1）。
- 状态色（双主题通用）：success `#35d399`，warning `#f0b35a`，error `#ff6978`，info `#38d6ff`。
- 几何：`radius: { sm: 2, md: 6, lg: 8, xl: 8 }`；`controlHeight: { sm: 28, md: 32, lg: 36 }`。
- 动效：`durationFast 0.1s / Mid 0.2s / Slow 0.3s`，`easeOut cubic-bezier(0.23,1,0.32,1)`，`easeInOut cubic-bezier(0.77,0,0.175,1)`。
- 字体：`"Inter", system-ui, -apple-system, "Segoe UI", Roboto, ...`；等宽 `"JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, ...`。

### 1.2 `web/src/index.css` `@theme`（Tailwind v4 token，L33–345）

关键值（亮色默认）：

```css
--color-primary: #262626;            /* L43  近黑主色 */
--color-background-light: #f7f7f7;   --color-background-dark: #0a0a0a;      /* L71-72 */
--color-surface-light: #ffffff;      --color-surface-dark: #121212;         /* L75-76 */
--color-surface-dark-alt: #181818;   --color-surface-elevated: #1f1f1f;     /* L77-78 */
--color-border-light: #e3e3e3;       --color-border-dark: #333333;          /* L81-82 */
--color-text-primary: #141414;       --color-text-secondary: #4f4f4f;       /* L86-87 */
--color-content: #141414; --color-content-secondary: #4f4f4f; --color-content-tertiary: #6b6b6b; /* L97-99 */
```

`.dark` 覆盖（L757–816）：`--color-primary: #f2f2f2`；并把 `blue-*` 与 `slate-*`/`gray-*` 整套 remap 成灰阶——

```css
.dark {
  --color-slate-50: #ededed; --color-slate-100: #dbdbdb; --color-slate-200: #bdbdbd;
  --color-slate-300: #9c9c9c; --color-slate-400: #8a8a8a; --color-slate-500: #404040;
  --color-slate-600: #262626; --color-slate-700: #1f1f1f; --color-slate-800: #181818;
  --color-slate-900: #121212; --color-slate-950: #0a0a0a;   /* L787-797 */
}
```

> 含义：组件里写 `bg-slate-50 dark:bg-slate-800` 这类成对类，暗色下自动落到面板梯。复刻时按此映射即可。

排版（commit 51d7f9d65 引入，L191–222）：

```css
--font-sans: 'Inter', system-ui, -apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
--font-mono: 'JetBrains Mono', ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, monospace;
--text-2xs: 0.625rem;  --text-2xs--line-height: 1.4;     /* 10px 密集标签 */
--text-xs-plus: 0.6875rem; --text-xs-plus--line-height: 1.45; /* 11px */
--text-code: 0.8125rem; --text-code--line-height: 1.6;   /* 13px 代码/表格 */
--tracking-label: 0.05em;                                 /* 大写微标签字距 */
```

圆角/阴影（L248–271）：`--radius-sm:2px; --radius-default:4px; --radius-md:6px; --radius-lg:8px; --radius-xl:8px; --radius-full:9999px`；`--shadow-xs/sm/md/...` 标准低透明度阴影。

基础交互（L423–452）：

```css
@layer base { button:not(:disabled), [role='button']:not([aria-disabled='true']), summary, label[for] { cursor: pointer; }
  :focus-visible { outline: 2px solid var(--color-primary); outline-offset: 2px; } }
::selection { background-color: var(--color-primary); color: var(--color-background-light); }
```

聊天滚动条（L519–543）：

```css
.chat-scrollbar::-webkit-scrollbar { width: 6px; }
.chat-scrollbar::-webkit-scrollbar-thumb { background: var(--color-border-light); border-radius: 3px; transition: background 0.2s ease; }
.dark .chat-scrollbar::-webkit-scrollbar-thumb { background: var(--color-border-dark); }
```

AntD 主题：`web/src/theme/antdTheme.ts`（`lightTheme` L103–200 起；另有 `darkTheme`），`colorPrimary` 近黑/近白，`colorLink` 固定为单色 accent，`borderRadius: 6 / LG 8 / SM 2`，控件高 32/36/28，字体 Inter 14px。

### 1.3 共享角色类 `web/src/components/agent/styles.ts`（复刻的核心文件，全文 100 行）

```ts
// L14-15 Markdown 正文统一类（与 .memstack-prose 配套）
export const MARKDOWN_PROSE_CLASSES =
  'memstack-prose max-w-none leading-[1.55] [&_p]:my-1 [&_h1]:mt-3 [&_h1]:mb-1.5 ... [&_pre]:my-2 [&_pre]:bg-transparent [&_pre]:p-0 [&_a]:text-primary [&_a]:no-underline hover:[&_a]:underline [&_img]:rounded-lg [&_img]:shadow-md [&>p:first-child]:mt-0 [&>p:last-child]:mb-0';

// L24-25 助手气泡
export const ASSISTANT_BUBBLE_CLASSES =
  'flex-1 min-w-0 bg-white dark:bg-surface-dark border border-slate-200/55 dark:border-slate-800/55 rounded-lg rounded-tl-sm shadow-[0_1px_2px_rgba(15,23,42,0.025)] px-4 py-2.5';

// L31-32 助手头像（32px 方圆角 + 主色浅底 + 细环）
export const ASSISTANT_AVATAR_CLASSES =
  'w-8 h-8 rounded-lg bg-primary/10 ring-1 ring-primary/15 dark:ring-primary/20 flex items-center justify-center shrink-0 mt-0.5';

// L38 / L43 内容最大宽
export const MESSAGE_MAX_WIDTH_CLASSES = 'max-w-[96%] md:max-w-[94%] lg:max-w-[92%]';
export const WIDE_MESSAGE_MAX_WIDTH_CLASSES = 'max-w-[98%] md:max-w-[96%] lg:max-w-[94%]';

// L49 布局底色
export const LAYOUT_BG_CLASSES = 'bg-slate-50 dark:bg-slate-950';

// L65 大写微标签（面板小节标题："EXECUTION"/"INPUT"/"OUTPUT"）
export const SECTION_LABEL_CLASSES = 'text-2xs font-semibold uppercase tracking-label';

// L76 / L81 / L88 面板缝/面板头/滚动体
export const PANEL_BORDER_CLASSES = 'border-slate-200/60 dark:border-slate-700/50';
export const PANEL_HEADER_CLASSES = `flex flex-shrink-0 items-center justify-between gap-2 border-b ${PANEL_BORDER_CLASSES} px-4 py-2`;
export const PANEL_SCROLL_BODY_CLASSES = 'flex-1 min-h-0 min-w-0 overflow-y-auto';

// L99-100 方形图标按钮（工具栏/悬停动作统一配方）
export const ICON_BUTTON_CLASSES =
  'inline-flex shrink-0 items-center justify-center rounded-md p-1.5 text-slate-400 transition-colors duration-150 hover:bg-slate-100 hover:text-slate-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent dark:hover:bg-slate-700 dark:hover:text-slate-300';
```

---

## 2. 布局骨架

### 2.1 入口 `web/src/pages/tenant/AgentWorkspace.tsx`

只负责项目/租户解析，渲染 `<AgentChatContent externalProjectId basePath headerExtra />` + `<ContextDetailPanel />`（L526–556）。加载/错误/空项目均为居中卡片：`max-w-lg rounded-xl border border-slate-200 bg-white p-8 shadow-sm dark:border-slate-800 dark:bg-surface-dark`（L487、L512）。

### 2.2 `web/src/components/agent/AgentChatContent.tsx`

五种布局模式（chat/task/code/canvas/collab，Cmd+1–5 切换，见文件头注释 L7-19），chat 主列 `chatColumn`（L977–1076）：

```tsx
<div className="flex-1 flex flex-col min-w-0 h-full overflow-hidden relative">
  {/* 会话头条：L989 */}
  <div className="flex-shrink-0 border-b border-slate-200/60 dark:border-slate-700/50 bg-white/60 dark:bg-slate-900/40 px-4 py-2 flex items-center gap-2 min-w-0">
    <ConversationAgentBadge conversation={currentConversation} />
    <span className="min-w-0 truncate text-sm font-medium text-slate-800 dark:text-slate-100">{conversationTitle}</span>
    {/* 子代理节点 chip: bg-blue-100 dark:bg-blue-900/50 text-blue-700 ... px-2 py-0.5 rounded-full */}
  </div>
  <div className="flex-1 overflow-hidden relative min-h-0">{messageArea}<ChatSearch .../></div>
  {/* 输入区外壳：L1032 —— 顶缝 + 微阴影 + 可拖拽高度 Resizer */}
  <div className="relative flex flex-shrink-0 flex-col border-t border-slate-200/60 bg-white shadow-[0_-1px_2px_rgba(15,23,42,0.025)] dark:border-slate-700/50 dark:bg-slate-900"
       style={{ minHeight: inputHeight }}>  {/* 160–560px 可调 */}
    <Resizer direction="vertical" ... /><InputBar ... />
  </div>
</div>
```

### 2.3 消息列表容器 `web/src/components/agent/MessageArea.tsx`

- 滚动容器（L819–826）：`flex-1 overflow-y-auto chat-scrollbar p-3 md:p-4 pb-20 min-h-0`，`role="log" aria-live="polite"`，`overflowAnchor:'none'`（自管理滚动）。
- 虚拟化：`useVirtualizer`，每行 `position:absolute; transform: translateY(...)`，按 displayItem key 测量。
- 分组：`groupTimelineEvents(timeline)`（`message/groupTimelineEvents.ts`）→ 三种 item：`event` / `timeline`（连续 act/observe）/ `subagent`；再经 `turnFolding` 支持按"用户轮次"折叠为 `TurnPlaceholderRow`。
- 非气泡行（timeline/subagent/memory）左侧用 `<div className="w-8 shrink-0" />` 占位与头像列对齐，内容列套 `MESSAGE_MAX_WIDTH_CLASSES` 或 `WIDE_MESSAGE_MAX_WIDTH_CLASSES`（L904–986）。
- 置顶消息区（L742–815）：灰底 `bg-slate-50/80 dark:bg-slate-800/50` + 折叠按钮 + 白色小卡片列表。
- 加载更早指示（L723–737）：顶部居中 `bg-slate-100 dark:bg-slate-800 rounded-lg shadow-sm border` 小胶囊。

---

## 3. 逐元素设计规范

### 3.1 用户消息气泡 — `messageBubble/MessageBubble.tsx` `UserMessage`（L878–1016）

右对齐：`group flex flex-col items-end gap-1 pb-1`；内容最大宽 `USER_MESSAGE_MAX_WIDTH_CLASSES = 'max-w-[85%] md:max-w-[75%] lg:max-w-[70%]'`（L126）。

```tsx
// L955-964 气泡本体
<div className="bg-slate-50/80 dark:bg-slate-800/70 border border-slate-200/40 dark:border-slate-700/40 rounded-lg rounded-br-sm px-4 py-2 shadow-[0_1px_2px_rgba(15,23,42,0.02)]">
  <p className="text-sm leading-[1.5] whitespace-pre-wrap break-words text-slate-800 dark:text-slate-100 font-normal">{content}</p>
</div>
// L987-989 右侧用户头像
<div className="w-8 h-8 rounded-lg bg-slate-100/80 dark:bg-slate-800/70 ring-1 ring-slate-200/45 dark:ring-slate-700/45 flex items-center justify-center flex-shrink-0">
  <User size={16} className="text-slate-500 dark:text-slate-400" />
</div>
```

- 时间戳在气泡上方右侧：`MessageTime`（L164–187）`text-2xs leading-none text-content-tertiary` + Clock 11px 图标。
- 强制执行装饰：skill → `bg-primary/30` 外框 + 圆形闪电徽章；subagent → `bg-purple-300/70 dark:bg-purple-700/60` 外框 + 紫色徽章 + 右下 `@name` 标签（L899–985）。
- 附件 chip（L994–1010）：`inline-flex items-center gap-2 px-3 py-1.5 bg-slate-100/80 dark:bg-slate-800/70 border border-slate-200/40 rounded-md`，文件名 `text-xs` + 大小 `text-2xs text-content-tertiary`。
- 悬停动作条见 §3.12。

### 3.2 助手气泡 — `AssistantMessage`（L1028–1098）/ `TextEnd`（L1398–1470）/ `TextDelta`（L1102–1132）

三者为同一视觉：左头像（Bot 18px，`ASSISTANT_AVATAR_CLASSES`）+ `ASSISTANT_BUBBLE_CLASSES` 白底卡片 + `MARKDOWN_PROSE_CLASSES` ReactMarkdown。时间戳在卡片上方左侧 `mb-1 flex pl-1`。卡片顶部可插 `ExecutionSummaryPanel`（§3.13），底部可插 `ArtifactReferenceList`。流式时无悬停动作条。

```tsx
<div className="group flex items-start gap-3 pb-1">          // L1041
  <div className={ASSISTANT_AVATAR_CLASSES}><Bot size={18} className="text-primary" /></div>
  <div className={`flex-1 ${MESSAGE_MAX_WIDTH_CLASSES}`}>
    <div className={ASSISTANT_BUBBLE_CLASSES}>
      <div className={MARKDOWN_PROSE_CLASSES}><ReactMarkdown ... /></div>
    </div>
  </div>
</div>
```

### 3.3 Markdown 正文 — `MARKDOWN_PROSE_CLASSES` + `.memstack-prose`（`index.css` L1768–1953）

```css
.memstack-prose :not(pre) > code {              /* L1768 行内代码 */
  padding: 0.15em 0.4em; border-radius: 0.25rem; font-size: 0.85em;
  color: var(--color-primary); background-color: var(--color-primary-50);
}
.memstack-prose pre { border-radius: 0.5rem; overflow: hidden; }   /* L1792 */
.memstack-prose pre > code {                     /* L1801 */
  font-size: var(--text-code); line-height: 1.65; background-color: var(--color-surface-muted); overflow-x: auto;
}
.memstack-prose table { width: 100%; border-collapse: collapse; font-size: var(--text-code); margin: 0.75rem 0; } /* L1813 */
.memstack-prose th { text-align: left; font-weight: 600; padding: 0.5rem 0.75rem;
  border-bottom: 2px solid var(--color-border-light); background-color: var(--color-background-light); } /* L1821 */
.memstack-prose td { padding: 0.5rem 0.75rem; border-bottom: 1px solid var(--color-border-subtle); }     /* L1836 */
.memstack-prose blockquote {                     /* L1854 */
  border: 1px solid var(--color-primary-200); border-radius: 0.5rem; background-color: var(--color-primary-50);
  padding: 0.75rem 1rem; margin-left: 0; color: var(--color-text-secondary); font-style: italic;
}
.memstack-prose hr { border: none; height: 1px; background-color: var(--color-border-light); margin: 1.5rem 0; } /* L1871 */
.memstack-prose a { color: var(--color-primary); }  /* L1887，hover 下划线 + primary-light */
.memstack-prose ul { list-style-type: disc; padding-left: 1.25rem; }  /* L1898 */
.memstack-prose li::marker { color: var(--color-text-muted-light); }  /* L1908 */
```

### 3.4 代码块 — `chat/CodeBlock.tsx`（ReactMarkdown `components.pre` 覆盖）

```tsx
// L108-146 外壳 + 语言标题栏
<div className="group/code relative rounded-lg border border-slate-200 dark:border-slate-600 overflow-hidden">
  <div className="flex items-center justify-between px-3 py-1.5 bg-slate-200/80 dark:bg-slate-700/80">
    <span className="text-xs font-medium text-slate-500 dark:text-slate-400 select-none">{language}</span>
    {/* 右侧：Open-in-Canvas(PanelRight) + Copy/Check 图标按钮，p-1 rounded hover:bg-slate-300/60 */}
  </div>
  <SyntaxHighlighter customStyle={{ margin: 0, borderRadius: 0, fontSize: '0.8125rem', lineHeight: 1.6 }} ... /> // L150-160
</div>
```

- 单行 <80 字符的短块不显示标题栏，按钮改为右上角悬停浮现（L168–199）。
- `language === 'mermaid'` 交给 `MermaidBlock` 渲染图。
- 语法高亮懒加载：`canvas/useSyntaxHighlighter.ts`（hljs 主题按亮/暗切换）。

### 3.5 思考/推理

**历史中 `thought` 事件 — `Thought`（L1135–1182）**：灯泡图标灰方块头像 + 可折叠卡：

```tsx
<div className="bg-slate-50/80 dark:bg-slate-800/50 border border-slate-200/45 dark:border-slate-700/45 rounded-md overflow-hidden"> // L1151
  <button className="w-full px-4 py-2.5 flex items-center gap-2 hover:bg-slate-100/50 dark:hover:bg-slate-700/30 ...">
    <span className="text-xs font-semibold text-slate-500 dark:text-slate-400">Reasoning</span>
    <MessageTime className="ml-auto" /><ChevronUp/ChevronDown size={14}/>
  </button>
  <p className="text-xs leading-5 text-slate-500 dark:text-slate-400 whitespace-pre-wrap">{reasoningText}</p> // L1172
</div>
```

**流式思考 — `chat/ThinkingBlock.tsx`**：Brain 图标 + `rounded-md border border-slate-200 bg-slate-50/80 dark:border-slate-700 dark:bg-slate-800/50`（L108）；标题为 `SECTION_LABEL` 风格 "Thinking"（L132–137）；流式时 3 个 `animate-pulse` 小圆点（L140–158）；右侧 `tabular-nums` 时长；折叠态显示 100 字预览（L161–164）；内容区 `max-h-[400px]` 过渡展开、内滚 `max-h-[360px]`（L191–200）。

### 3.6 工具调用

#### 3.6.1 单卡（未分组时）`ToolExecution`（L1185–1330）

扳手图标灰方块 + 折叠卡，状态胶囊用语义色：

```tsx
// L1219-1239 卡片与头部
<div className="bg-slate-50/80 dark:bg-slate-800/55 border border-slate-200/45 dark:border-slate-700/40 rounded-md overflow-hidden shadow-[0_1px_2px_rgba(15,23,42,0.02)]">
  <button className="w-full px-4 py-3 flex items-center justify-between hover:bg-slate-50 dark:hover:bg-slate-700/50 ...">
    <span className="font-medium text-xs text-slate-700 dark:text-slate-300 truncate">{toolName}</span>
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border ${statusColor}`}>
      {statusIcon}{statusText}   // Running: Loader2 旋转 blue；Success: CheckCircle2 emerald；Failed: XCircle red
    </span>
    {/* 右侧：Clock + formatDurationMs + Chevron */}
  </button>
</div>
// 状态色（L1208-1212）:
// 运行中 'bg-blue-50 text-blue-600 border-blue-200 dark:bg-blue-900/20 dark:text-blue-400 dark:border-blue-800/50'
// 成功   'bg-emerald-50 text-emerald-600 border-emerald-200 dark:bg-emerald-900/20 ...'
// 失败   'bg-red-50 text-red-600 border-red-200 dark:bg-red-900/20 ...'
```

展开区（L1257–1323）：`SECTION_LABEL` 小标题 "INPUT"/"OUTPUT"；输入是带 `JSON` 假窗口栏的代码框——栏 `bg-slate-50 dark:bg-slate-900/50 px-3 py-1.5 text-xs text-slate-500 border-b` + 圆点，体 `bg-white dark:bg-slate-900 p-3 text-xs font-mono whitespace-pre-wrap`；错误输出为 `bg-red-50 dark:bg-red-900/20 border-red-200` 红框。

#### 3.6.2 分组时间线 `timeline/ExecutionTimeline.tsx`（主要形态）

连续 act/observe 聚成一组。汇总头（L756–792）：`flex items-center gap-2 w-full text-left mb-1.5` 按钮，Chevron + `text-xs font-medium text-slate-600 dark:text-slate-300` 的动作摘要（如 "Read 3 files: a.ts, b.ts …"，由 `summarizeToolActions` 生成），右侧 `text-2xs text-slate-400` "3/5 done"、失败红胶囊、运行中 Loader2。折叠时下方列出其余动作行（L795–813）。

单个步骤 `TimelineStepItem`（L492–716）——竖向时间线：左侧 24px 圆点列（圆点 `w-6 h-6 rounded-full border-2`，按状态 `border-blue-400 bg-blue-50` / `border-emerald-400 bg-emerald-50` / `border-red-400 bg-red-50`，圆点下可选 `text-2xs tabular-nums` 时长，点间 `w-px bg-slate-200 dark:bg-slate-700` 连接线），右侧步骤卡：

```tsx
// L602 步骤卡
<div className="w-full rounded-md border border-slate-200/50 bg-white px-3 py-2 shadow-[0_1px_2px_rgba(15,23,42,0.02)] transition-[border-color,box-shadow] duration-200 hover:border-slate-300/70 hover:shadow-[0_1px_3px_rgba(15,23,42,0.045)] dark:border-slate-800/60 dark:bg-slate-950/70 dark:hover:border-slate-700/70">
  <span className="min-w-0 truncate text-xs font-normal text-slate-700 dark:text-slate-300">{toolPreview}</span>   // L623 人类化预览："Read: config.ts"
  <span className="shrink-0 text-2xs font-normal text-content-tertiary">{stepLabel}</span>                      // L626 工具名
</div>
// 展开区 L676-709：Input/Output 块 'bg-slate-50/75 dark:bg-slate-800/40 rounded-md p-2 border border-slate-200/40 dark:border-slate-700/35' + 'text-2xs font-semibold uppercase tracking-label' 标签 + mono pre max-h-50 滚动；错误输出换红色系。
```

错误步骤默认展开（L822 `defaultExpanded={step.status === 'error'}`）。MCP 工具成功后显示紫色 "Open App" 按钮（L654–665）。

#### 3.6.3 流式工具准备 `message/StreamingToolPreparation.tsx`

蓝点圆环 + 蓝色 shimmer 卡：`tool-prep-shimmer rounded-md border px-2.5 py-1.5 bg-blue-50 dark:bg-blue-950/30 border-blue-200 dark:border-blue-800/40`（L58），工具名 `text-xs font-medium` + "Preparing" 胶囊（`bg-blue-100 text-blue-600 text-2xs font-semibold uppercase tracking-label` + 脉冲点），部分参数流以 `text-xs-plus font-mono` 蓝底框 + 闪烁光标展示（L68–77）。

#### 3.6.4 L4 编排工具卡 `timeline-items/AgentToolCards.tsx`

`isAgentTool(toolName)` 的步骤用彩色整卡：圆点 + Brain 图标（L509–553），卡体按语义着色——启动绿 `rounded-lg border border-emerald-200 dark:border-emerald-800/50 bg-emerald-50/50` + 头部 `bg-emerald-100/60`（L104–105）；停止红（L172–173）；消息蓝（L234–235）。行内字段用 `w-12/w-14 shrink-0` 的 `SECTION_LABEL` 键 + `text-xs` 值。

### 3.7 工作计划 `WorkPlan`（L1333–1395）

Bot 头像 + 灰底折叠卡（同 Thought 外壳）：标题 "Work Plan" `font-semibold text-xs` + 步数胶囊 `text-xs text-primary bg-primary/10 px-2 py-0.5 rounded-full`（L1356–1363）；步骤行 `flex items-start gap-3 p-3 bg-slate-50 dark:bg-slate-800 rounded-lg border border-slate-200/70`，序号 `w-6 h-6 rounded-full bg-primary text-xs font-semibold text-slate-50`（L1377–1384）。

### 3.8 任务清单（todo）

- `task_list_updated` → executionStore.tasks → 右侧面板渲染；聊天气泡内不渲染（`task_start/task_complete` 返回 null，L2149–2152）。
- `TaskList.tsx`：顶部进度条 `h-1.5 bg-slate-200 dark:bg-slate-700 rounded-full` + 填充 `bg-emerald-500` scaleX（L150–162）；"completed/total" `text-xs text-slate-500`。任务行（L64–106）：`flex items-start gap-2.5 px-3 py-2 rounded-lg`，进行中 `bg-blue-50/60 dark:bg-blue-900/15` + Loader2 旋转；完成划线 `line-through text-content-tertiary`；状态色 pending 灰 / in_progress 蓝 / completed 祖母绿 / failed 红 / cancelled 灰（L21–48）；优先级点 high 红 / medium 琥珀 / low 灰（L50–54）。
- `tasks/TaskLanePanel.tsx`：看板四列 In progress(蓝)/Backlog(灰)/Done(绿)/Blocked(玫红)（LANES L48–81），列头带状态图标 + accent 色条，折叠状态按会话存 localStorage。

### 3.9 Artifact 卡片 `ArtifactCreated`（L1473–1792）

```tsx
// L1630-1635 左侧祖母绿图标块 + 白卡（双层描边阴影）
<div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-emerald-200 bg-emerald-50 dark:border-emerald-800/55 dark:bg-emerald-950/35">
  <FileOutput size={16} className="text-emerald-600 dark:text-emerald-400" /></div>
<div className="rounded-md bg-white p-4 shadow-[0_0_0_1px_rgba(15,23,42,0.055),0_6px_16px_-16px_rgba(15,23,42,0.22)] dark:bg-slate-950 dark:shadow-[0_0_0_1px_rgba(148,163,184,0.12)]">
```

- 头部：类别图标 + "File Generated" `text-xs font-semibold` + 来源工具胶囊 `rounded-full bg-emerald-50 px-2 py-0.5 text-2xs font-medium text-emerald-700 ring-1 ring-emerald-100`（L1637–1650）。
- 图片类内嵌预览：`rounded-md border max-h-[300px] object-contain` + 加载占位/失败刷新（L1653–1705）。
- 文件信息条：`flex flex-wrap gap-x-3 gap-y-2 rounded-md border border-slate-200/55 bg-slate-50/80 px-3 py-2.5 text-xs`（L1708），文件名 `font-medium` + 大小 + Download 绿链 + "Canvas" 主色按钮 + uploading/error 状态。
- 底部元数据 chip：`rounded border border-slate-200 bg-slate-50 px-2 py-1 text-2xs text-slate-500`（mimeType/category，L1779–1786）。

### 3.10 HITL 内联卡 `InlineHITLCard.tsx`（clarification/decision/env_var/permission）

类型→语义色（L126–203）：clarification 蓝、decision 琥珀、env_var 紫罗兰、permission 玫红（图标块 `bg-{color}-50` + `text-{color}-600`）。整体（L1297–1395）：

```tsx
<div className="flex items-start gap-3 animate-fade-in-up">
  <div className={`w-8 h-8 rounded-md border border-slate-200/70 dark:border-slate-800 ${iconBgClass} flex items-center justify-center flex-shrink-0 shadow-sm`}>...icon...</div>
  <div className="flex-1 max-w-[85%] md:max-w-[75%] lg:max-w-70%">
    <div className={`${bgClass} border rounded-md overflow-hidden shadow-[0_0_0_1px_rgba(15,23,42,0.03),0_6px_16px_-16px_rgba(15,23,42,0.22)]`}>
      {/* bgClass 全类型统一: 'bg-white dark:bg-slate-950 border-slate-200 dark:border-slate-800' (L142-155) */}
      <div className={`flex items-center justify-between gap-3 px-3 py-2 border-b ${headerBgClass}`}>
        {/* headerBg: 'bg-slate-50/80 dark:bg-slate-900/80 border-slate-200 dark:border-slate-800' (L158-171) */}
        <span className="text-sm font-semibold text-slate-800 dark:text-slate-200">{title}</span>
        {/* 待办: 彩色脉冲点 + "Pending" text-xs；已答: AntD Tag + 相对时间；右侧 CountdownTimer */}
      </div>
      <div className="p-3 bg-white dark:bg-slate-950">{/* 类型内容 */}</div>
    </div>
  </div>
</div>
```

- **clarification**（L381–520）：问题 `text-sm leading-6 text-slate-700`；选项卡 `p-3 rounded-md border`，选中 `border-blue-300 bg-blue-50/70 dark:bg-blue-950/30`，未选 hover 变蓝边；RadioIndicator 圆点（L205–223）；可自定义输入 + 右下主按钮。
- **decision**（L597–845）：同构但选中态/单选框用琥珀色（`border-amber-300 bg-amber-50/70`，CheckboxIndicator `border-amber-500 bg-amber-500`）；选项可有 cost/time 元信息 chip（`px-2 py-1 bg-slate-100 dark:bg-slate-800 rounded-md`）与风险清单（`bg-amber-50 border-amber-200` 框）。
- **env_var**（L847–1009）：AntD Form 字段（required 红星 `text-rose-500`），工具名条 `px-3 py-2 bg-slate-50 rounded-md border`；"Save configuration" checkbox `accent-violet-500`；已答为绿底完成框（L965–979）。
- **permission**（L1011–1158）：盾牌图标 + 工具名 + 风险 Tag；风险横幅按 low/medium/high 用 emerald/amber/rose 三色配置（riskConfig L1022–1041）；底部 "Remember this choice"（`accent-rose-500`）+ Deny(danger) / Allow(primary) 双按钮；已答按 granted 显示绿/玫红结果框（L1095–1116）。

### 3.11 子代理 `timeline/SubAgentTimeline.tsx`

整卡边框/图标随状态着色（L466–522）：

```ts
// 卡片底色（L466-500，节录）
running: 'bg-white dark:bg-slate-900/65 border-blue-200/45 dark:border-blue-800/30' + animate-subagent-pulse
success: '... border-emerald-200/45 dark:border-emerald-800/25'
error:   '... border-red-200/50 dark:border-red-800/30'
background: purple / queued: amber / killed: red-300 / steered: cyan / depth_limited: orange
// 最终: `rounded-md border ${bg} ${pulse} shadow-[0_1px_2px_rgba(15,23,42,0.02)] transition-[border-color,box-shadow] duration-200`
// 图标面（L502-522）：'bg-blue-50 text-blue-600 ring-blue-100 dark:bg-blue-950/40 ...'（各色同构 ring-1）
```

- 头部按钮（L608–666）：`w-full flex items-center gap-3 px-4 py-3 hover:bg-slate-50/70`，Chevron 方块 + ModeIcon 彩块（parallel Layers 靛 / chain GitBranch 琥珀 / 单 Bot 蓝，L146–158），标题 `text-code font-semibold leading-5 text-slate-800`（如 "SubAgent: xxx"），副行 `text-2xs` 事件数；右侧 confidence 蓝胶囊、tokens 灰胶囊（Zap 图标）、时长、StatusPill。
- StatusPill（L164–181 + `subagentUtils.ts` L47–56）：`inline-flex min-h-5 items-center px-2 text-2xs font-medium rounded-full animate-status-pill-in`，色板 running 蓝 / success 祖母绿 / error 红 / background 紫 / queued 灰 / killed·steered 琥珀 / depth_limited 橙。
- 运行中：进度相位条（L365–427，`h-1 bg-slate-200/60 rounded-full` + 蓝色 scaleX）+ 实时预览框（L672–684，`rounded-md bg-slate-50/75 px-3 py-2 text-xs font-mono` + "LIVE PREVIEW" 标签）。
- 展开体（L687–793，`px-4 pb-3.5 space-y-2.5`）：生命周期胶囊行（激活 `border-primary/30 bg-primary/10 text-primary`）、task 描述 `text-xs leading-relaxed max-w-[76ch]`、reason 斜体 `text-xs-plus text-content-tertiary italic`、Parallel 子任务网格（`grid sm:grid-cols-2 lg:grid-cols-3 gap-2`，子卡 `p-2.5 rounded-md bg-slate-50 border` 按成败着色边框，L203–291）、Chain 用 AntD `<Steps orientation="vertical" size="small">`（L314–341）、总结引用框 `rounded-md border border-slate-200/45 bg-slate-50/65 px-3 py-2.5`（L730）、错误红框（L740–746）、右下 "Show details" 小链。
- 动画（`index.css` L2023–2063）：`subagent-border-pulse` 2s 边框呼吸；`status-pill-in` 200ms 缩放入场；`prefers-reduced-motion` 下关闭。

### 3.12 错误/通知

- 错误气泡（MessageBubble L1809–1818）：`role="alert" className="rounded-lg border border-red-200 bg-red-50 p-4 text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-200"`，标题 `font-medium` + 正文 `whitespace-pre-wrap`。
- 加载更早失败条（MessageArea L831–848）：居中 `rounded-lg border border-red-200/70 bg-red-50 px-3 py-1.5 text-xs text-red-600` + Retry 下划线按钮。
- 悬停动作条 `chat/MessageActionBar.tsx`（L195–230）：气泡右上角 `-top-3 right-2` 浮条——`flex items-center gap-0.5 px-1.5 py-1 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg shadow-sm opacity-0 group-hover:opacity-100 transition-opacity duration-200`；按钮 `p-1.5 rounded-md text-slate-400 hover:bg-slate-100`，危险项 `hover:text-red-500 hover:bg-red-50`。动作：copy/pin/reply/retry/edit/delete/save-template。
- SuggestionChips（L27–66）：头像列占位 + `max-w-[85%] md:max-w-[75%] lg:max-w-[70%]`，圆角胶囊 `px-3.5 py-2 rounded-full bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 text-sm hover:border-primary/50 hover:text-primary hover:bg-primary/5` + ArrowUpRight。
- QueuedPromptStrip：队列胶囊 `inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs-plus` + Clock 图标 + 序号 mono 小块；区头 "QUEUE" 用 `SECTION_LABEL`。
- TurnPlaceholderRow（折叠轮次）：虚线框按钮 `rounded-md border border-dashed border-slate-200 bg-slate-50/60 px-3 py-1.5 text-xs text-slate-500 hover:border-slate-300 hover:bg-slate-100` + ChevronDown + "N items hidden"。

### 3.13 执行摘要 `ExecutionSummaryPanel`（L490–556）

助手卡顶部的一排统计 pill：`SUMMARY_PILL_CLASSES = 'inline-flex items-center gap-1 rounded-full border border-slate-200/60 bg-slate-50/80 px-2.5 py-1 text-xs text-neutral-600 dark:border-slate-800/60 dark:bg-slate-800/50'`（L111–112），label 灰 + value `font-medium text-neutral-800`；含 Steps/Tasks/Remaining/Artifacts/LLM calls/Tokens/Cost。

### 3.14 输入区 `InputBar.tsx`

主卡片（L665–685）：

```tsx
<section className={`flex-1 flex flex-col min-h-0 min-w-0 rounded-md border relative bg-white dark:bg-slate-800 transition-[border-color,box-shadow] duration-200 ease-out
  ${isDragging ? 'border-primary/55 ring-2 ring-primary/15 shadow-[0_1px_5px_rgba(0,112,243,0.08)]'
  : isPlanMode ? 'border-primary/40 ring-2 ring-primary/10 ...'
  : isFocused  ? 'border-primary/25 shadow-[0_1px_4px_rgba(0,112,243,0.045)] ring-2 ring-primary/5'
  : 'border-slate-200/45 dark:border-slate-700/45 shadow-[0_1px_3px_rgba(15,23,42,0.035)] dark:shadow-[0_1px_3px_rgba(0,0,0,0.12)]'}`}>
```

- Plan Mode 条（L688–722）：`rounded-md border border-primary/25 bg-primary/5 px-2.5 py-1.5` + 主色图标块 + "Plan Mode" `text-xs font-semibold text-primary`。
- textarea（L952–968）：`bg-transparent px-1 py-1 text-sm leading-relaxed text-slate-800 dark:text-slate-100 placeholder:text-content-tertiary focus:outline-none break-words font-sans`，minHeight 32，自适应高度。
- skill/subagent 选中 chip（L886–925）：skill `rounded border border-primary/20 bg-primary/5 text-primary` + Zap；subagent 紫色同构 + Workflow。
- 附件 chip（L1047–1095）：`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs border bg-slate-50 dark:bg-slate-700/50 border-slate-200 dark:border-slate-600`，错误态换红色系 + 重试按钮。
- 底部 `InputToolbar`：左侧附件/模板/语音图标按钮（ICON_BUTTON 风格），右侧字数 + 发送/中止按钮（主色实心/红色）。
- 运行中显示 delivery 切换胶囊（steer_now/queue_next，L752–786）与 run-input 回执行（L788–823）。

### 3.15 空态 `EmptyState.tsx`

居中列：64px `rounded-xl bg-primary shadow-md` Bot 图标块（L123–126）→ `text-2xl font-semibold` 标题 → `text-sm text-content-tertiary max-w-md` 副文案 → 可选"继续上次会话"卡（`rounded-lg border border-slate-200 bg-white dark:bg-slate-800/50`，L226）→ 示例提示网格 `grid sm:grid-cols-2 gap-4` → 底部快捷键提示 `text-xs text-content-tertiary`。

---

## 4. 事件 → UI 映射

链路：`agentService.ts`（`AgentServiceImpl`，WebSocket `/api/v1/agent/ws?token=`，L135–）收 `ServerMessage` → L429 `routeToHandler(type, data, handler)` → `messageRouter.ts` 按 `AgentEventType` 分发到 `AgentStreamHandler.onXxx` → `streamEventHandlers.ts` 写入 stores（`queueTimelineEvent` 入 timeline；delta 经 `deltaBuffers` 节流）→ 渲染：

| SSE 事件 | store 处理 | 渲染组件 |
|---|---|---|
| `user_message` / `assistant_message` | timeline | MessageBubble.UserMessage / AssistantMessage |
| `text_delta`（流式） | streamingStore.agentStreamingAssistantContent | StreamingAssistantSection（流式气泡）；历史中 `text_delta` 若已有 `text_end` 则不渲染 |
| `text_end` | timeline | MessageBubble.TextEnd（完整回答气泡 + 动作条 + 摘要 pill） |
| `thought_start/thought_delta/thought` | streamingThought + timeline | ThinkingBlock（流式）/ Thought（历史折叠卡） |
| `act` / `act_delta` / `observe` | timeline + executionStore.activeToolCalls | groupTimelineEvents 聚组 → ExecutionTimeline；单发时 ToolExecution 卡；preparing 时 StreamingToolPreparation |
| `work_plan` | timeline | MessageBubble.WorkPlan |
| `task_list_updated` / `task_updated` / `task_start` / `task_complete` | executionStore.tasks | RightPanel 的 TaskList / TaskLanePanel；聊天气泡 null；进度经 deriveTaskProgress → WorkspaceStatusBar slot |
| `artifact_created` | timeline + sandboxStore.artifacts | MessageBubble.ArtifactCreated 卡片 |
| `artifact_ready/artifact_error/artifacts_batch` | sandboxStore 更新 | 不另渲染（更新既有卡片 URL/状态） |
| `clarification_asked/answered`、`decision_asked/answered`、`env_var_requested/provided`、`permission_asked/requested/replied/granted` | timeline + hitlStore | InlineHITLCard（四种 hitlType）；answered 事件合并进同 requestId 的卡 |
| `subagent_routed/started/completed/failed/queued/killed/steered/depth_limited/session_*`、`parallel_*`、`chain_*`、`background_launched`、`subagent_run_*` | timeline 聚 SubAgentGroup + subagentPreviews | SubAgentTimeline（整组一卡） |
| `agent_spawned/completed/stopped/message_*` | agentNodes store | 无气泡（L4 生命周期，状态栏/图视图）；其工具调用走 AgentToolCards |
| `memory_recalled` / `memory_captured` | timeline | JitContextCard / MemoryCapturedStep（紧凑步骤卡） |
| `suggestions` | hitlStore.suggestions | SuggestionChips |
| `error` | streamingStore.agentError + timeline | 红色 error 气泡 |
| `execution_path_decided/selection_trace/policy_filtered/toolset_changed` | executionNarrative（STATE_ONLY） | 不直接渲染气泡（RunReview/诊断面板） |
| `complete` / `cancelled` | 复位 streaming 状态 | — |
| `plan_mode_changed` | executionStore.isPlanMode | InputBar Plan 条 |
| `doom_loop_detected` 等 | hitlStore | HITLCenterPanel/横幅 |

---

## 5. 横切约定

1. **左列对齐**：所有助手侧行 = `flex items-start gap-3` + `w-8 h-8` 图标块 + 内容列；timeline/subagent 组用 `w-8 shrink-0` 空占位对齐同一列。
2. **圆角语言**：气泡 `rounded-lg` 且近身侧角收窄（助手 `rounded-tl-sm`、用户 `rounded-br-sm`）；卡片/折叠面板 `rounded-md`；pill `rounded-full`；图标块 `rounded-lg`（头像）/`rounded-md`（卡片图标）。
3. **边框透明度**：浅色边一律 `/40–/60` 透明（如 `border-slate-200/45`），暗色 `dark:border-slate-700/40–/60`；面板缝统一 `PANEL_BORDER_CLASSES`。
4. **阴影极轻**：常用 `shadow-[0_1px_2px_rgba(15,23,42,0.02–0.025)]`；强调卡用 `0_0_0_1px` 描边 + 负扩散投影组合。
5. **文字阶梯**：正文 `text-sm`；卡片标题/工具名 `text-xs font-medium|semibold`；微标签 `text-2xs font-semibold uppercase tracking-label`；辅助 `text-xs-plus` / `text-content-tertiary`；代码 `text-code`/`font-mono`。
6. **状态色只在语义处出现**：蓝=进行中，祖母绿=成功/完成，红=失败/危险，琥珀=等待/警告，紫=subagent/后台，青=steered，橙=depth limit/注意。
7. **入场动画**：`animate-fade-in-up`（0.25s ease-out translateY 8px，token `--animate-fade-in-up`）用于流式气泡、HITL 卡、SuggestionChips；图标状态切换 `animate-fade-in`；全部动效带 `motion-reduce:` 降级。
8. **可访问性**：折叠按钮均 `aria-expanded`/`aria-controls`；`focus-visible:ring-2 ring-primary/50`；`role="log" aria-live="polite"` 消息区；`role="alert"` 错误；`role="progressbar"` 进度条。
9. **流式渲染优化**：快速变化值（streaming content/thought）只在 `StreamingAssistantSection` 叶子组件订阅（MessageArea.tsx L341–343 注释），避免整列重渲染；MessageBubble 用自定义 comparator（L2167–2179）。
