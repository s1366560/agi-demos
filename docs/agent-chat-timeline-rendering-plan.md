# Agent 聊天时间线渲染改进计划

## 概述

将 Agent 聊天内容从分组渲染模式改为按自然时间线渲染，并修复打字机效果。

**创建日期**: 2026-01-28
**状态**: ✅ 全部完成

---

## 需求

1. **按自然时间线渲染**：消息按事件发生的自然时间顺序显示，不聚合
2. **修复打字机效果**：启用 `text_delta` 事件支持，实现文本增量显示
3. **渲染模式切换**：用户可在分组和时间线模式间切换

---

## 实施进度

### Phase 1: 打字机效果 ✅ 已完成

**完成的更改**：

1. **类型定义** (`types/agent.ts`)
   - 添加 `TextDeltaEvent`、`TextStartEvent`、`TextEndEvent` 到 `TimelineEvent` 联合类型
   - 扩展 `TimelineEventType` 包含 `text_delta`、`text_start`、`text_end`

2. **SSE 适配器** (`utils/sseEventAdapter.ts`)
   - 从"不支持"列表移除 `text_*` 事件
   - 添加 `text_start`、`text_delta`、`text_end` 事件处理逻辑
   - 更新 `isSupportedEventType` 函数

3. **分组适配器** (`utils/timelineEventAdapter.ts`)
   - 添加 `text_delta` 事件处理，累积文本内容到当前助手组

4. **UI 组件**
   - `AssistantMessage.tsx`: 添加 `isStreaming` prop，支持打字机光标样式
   - `FinalResponseDisplay.tsx`: 添加 `isStreaming` prop
   - `TimelineEventGroup.tsx`: 传递 `isStreaming` 到 `AssistantMessage`

5. **测试**
   - 新增 8 个测试用例覆盖打字机效果
   - 所有 31 个 sseEventAdapter 测试通过

### Phase 2: 时间线渲染模式 ✅ 已完成

**完成的更改**：

1. **新组件** (`components/agent/TimelineEventItem.tsx`)
   - 按事件类型独立渲染单个 TimelineEvent
   - 支持: user_message, assistant_message, thought, act, observe, work_plan, step_start, text_delta
   - 包含动画效果和视觉层次

2. **虚拟列表扩展** (`components/agent/VirtualTimelineEventList.tsx`)
   - 添加 `RenderMode` 类型 (`'grouped'` | `'timeline'`)
   - 添加 `renderMode` prop
   - 时间线模式下直接渲染 TimelineEventItem
   - 分组模式下保持原有行为

3. **Barrel 导出** (`components/agent/index.ts`)
   - 导出 `TimelineEventItem` 组件
   - 导出 `RenderMode` 类型

### Phase 3: 时间线样式优化 ✅ 已完成

**完成的更改**：

1. **CSS 动画** (`index.css`)
   - 添加 `slide-up` 和 `fade-in-up` 关键帧动画
   - 添加 `.animate-slide-up` 和 `.animate-fade-in-up` 类

2. **测试**
   - 新增 `TimelineEventItem.test.tsx`: 10 个测试用例
   - 新增 `timelineStyles.test.tsx`: 9 个测试用例
   - 所有 19 个新测试通过

### Phase 4: 测试验证与UI集成 ✅ 已完成

**完成的更改**：

1. **RenderModeSwitch 组件** (`components/agent/RenderModeSwitch.tsx`)
   - 可视化切换开关在分组和时间线模式间切换
   - 支持 Material Icons 和无障碍标签
   - 10 个测试用例全部通过

2. **AgentV3 Store 更新** (`stores/agentV3.ts`)
   - 添加 `renderMode` 状态（默认: `'grouped'`）
   - 添加 `setRenderMode` action
   - 使用 `persist` 中间件持久化用户偏好

3. **AgentChat 页面集成** (`pages/project/AgentChat.tsx`)
   - 添加 `RenderModeSwitch` 到聊天界面工具栏
   - 连接 `renderMode` 状态到 `VirtualTimelineEventList`
   - 用户偏好自动保存

4. **ChatArea 重构** (`components/agent/chat/ChatArea.tsx`)
   - 使用 `VirtualTimelineEventList` 替代 `TimelineEventRenderer`
   - 添加 `renderMode` 和 `onRenderModeChange` props
   - 新增 18 个测试用例全部通过

5. **E2E 测试** (`e2e/timeline-rendering.spec.ts`)
   - 时间线模式渲染测试
   - 模式切换交互测试
   - 打字机效果验证

---

## 使用方式

### 渲染模式切换

用户可以在 Agent Chat 界面顶部找到渲染模式切换开关：

- **Grouped (分组模式)**: 消息按用户/助手分组聚合显示（默认）
- **Timeline (时间线模式)**: 每个事件按时间顺序独立显示

用户选择会自动保存，下次访问时保持偏好。

### 编程方式使用

```tsx
import { VirtualTimelineEventList, RenderModeSwitch } from '@/components/agent';

function ChatArea({ timeline, isStreaming }) {
  const [renderMode, setRenderMode] = useState<RenderMode>('grouped');

  return (
    <>
      {/* 模式切换开关 */}
      <RenderModeSwitch
        mode={renderMode}
        onToggle={setRenderMode}
      />

      {/* 时间线列表 */}
      <VirtualTimelineEventList
        timeline={timeline}
        isStreaming={isStreaming}
        renderMode={renderMode}
      />
    </>
  );
}
```

---

## 验收标准

- [x] 流式传输时文本逐字符/token 显示
- [x] 打字机光标闪烁
- [x] 事件按时间戳顺序渲染
- [x] 虚拟滚动正常工作
- [x] 动画效果流畅
- [x] 用户可切换渲染模式
- [x] 模式偏好持久化保存
- [x] 80%+ 测试覆盖率 (sseEventAdapter: 100%)

---

## 测试统计

| 测试套件 | 测试数量 | 状态 |
|---------|---------|------|
| sseEventAdapter | 31 | ✅ 全部通过 |
| TimelineEventItem | 10 | ✅ 全部通过 |
| timelineStyles | 9 | ✅ 全部通过 |
| RenderModeSwitch | 10 | ✅ 全部通过 |
| ChatArea | 18 | ✅ 全部通过 |
| E2E timeline-rendering | 4 | ✅ 全部通过 |
| **总计** | **82+** | ✅ **全部通过** |

---

## 文件修改清单

| 文件 | 类型 | 说明 |
|------|------|------|
| `types/agent.ts` | 修改 | 添加 TextDeltaEvent 等类型 |
| `utils/sseEventAdapter.ts` | 修改 | 支持 text_* 事件 |
| `utils/timelineEventAdapter.ts` | 修改 | text_delta 累积逻辑 |
| `components/agent/chat/AssistantMessage.tsx` | 修改 | 添加 isStreaming prop |
| `components/agent/chat/FinalResponseDisplay.tsx` | 修改 | 添加 isStreaming prop |
| `components/agent/chat/TimelineEventGroup.tsx` | 修改 | 传递 isStreaming |
| `components/agent/TimelineEventItem.tsx` | 新建 | 单事件渲染组件 |
| `components/agent/VirtualTimelineEventList.tsx` | 修改 | 添加 renderMode 支持 |
| `components/agent/RenderModeSwitch.tsx` | 新建 | 渲染模式切换开关 |
| `components/agent/chat/ChatArea.tsx` | 修改 | 集成 RenderModeSwitch 和 VirtualTimelineEventList |
| `components/agent/index.ts` | 修改 | 导出新组件和类型 |
| `stores/agentV3.ts` | 修改 | 添加 renderMode 状态 |
| `pages/project/AgentChat.tsx` | 修改 | 集成渲染模式切换 |
| `index.css` | 修改 | 添加动画关键帧 |
| `test/utils/sseEventAdapter.test.ts` | 修改 | 添加打字机效果测试 |
| `test/components/TimelineEventItem.test.tsx` | 新建 | 组件测试 |
| `test/components/timelineStyles.test.tsx` | 新建 | 样式测试 |
| `test/components/RenderModeSwitch.test.tsx` | 新建 | 开关组件测试 |
| `test/components/agent/chat/ChatArea.test.tsx` | 新建 | ChatArea 集成测试 |
| `e2e/timeline-rendering.spec.ts` | 新建 | E2E 测试 |

---

## 完成日期

**2026-01-28**

所有四个阶段已完成并通过测试验证。用户现在可以在 Agent Chat 界面中自由切换分组和时间线渲染模式。
