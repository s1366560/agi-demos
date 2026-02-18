# 修复计划：前端工具流式渲染偶尔看不见

## 问题描述
前端工具的流式渲染偶尔会看不见，导致用户无法看到工具执行的实时状态。

## 根本原因分析

经过代码探索，识别出以下7个潜在问题，按影响程度排序：

### 高优先级问题

#### 1. Observe 事件未更新 activeToolCalls (最可能)
**位置:** `web/src/stores/agent/streamEventHandlers.ts:289-344`

**问题:** `onObserve` 处理器从 `pendingToolsStack` 弹出工具，但**没有更新** `activeToolCalls` Map 来标记工具完成。工具在 `activeToolCalls` 中保持 `status: 'running'` 状态，直到 `onComplete` 清空整个 Map。

**影响:** 如果工具执行很快，用户可能看不到工具执行过程。

#### 2. Timeline 更新在流式传输期间被跳过
**位置:** `web/src/stores/agentV3.ts:1236-1256`

**问题:** 当 `loadMessages` 在活跃流式传输期间被调用时（如页面刷新后恢复），如果 `isStreaming` 为 true，API 响应中的 timeline 更新会被跳过。

**影响:** 页面刷新后，已存在的工具执行可能不显示。

#### 3. 对话切换时 Delta Buffer 丢失
**位置:** `web/src/stores/agentV3.ts:724-878`

**问题:** 切换对话时调用 `clearAllDeltaBuffers()`，如果用户快速切换回原对话，部分流式状态会丢失。

**影响:** 快速切换对话时，工具状态可能不完整。

### 中优先级问题

#### 4. Virtualizer 定位期间阻止更新
**位置:** `web/src/components/agent/MessageArea.tsx:1038-1093`

**问题:** 对话切换时 `isPositioningRef.current = true` 会抑制滚动事件。如果工具事件在此期间到达，可能不会触发自动滚动。

**影响:** 新工具可能出现在视口外，用户需要手动滚动。

#### 5. Timeline 事件分组竞态条件
**位置:** `web/src/components/agent/MessageArea.tsx:78-173`

**问题:** observe 事件匹配首先使用 `execution_id`，然后回退到 `toolName`。如果事件乱序到达或 `execution_id` 缺失，工具状态可能显示错误。

**影响:** 工具状态可能卡在 "running" 而实际已完成。

### 低优先级问题

#### 6. Delta Buffer 定时器问题
**位置:** `web/src/stores/agentV3.ts:95-125`

**问题:** 如果 `act` 事件在 `act_delta` buffer 待刷新时到达，定时器被清除但 buffer 数据可能丢失。

#### 7. StreamingToolPreparation 渲染条件
**位置:** `web/src/components/agent/MessageArea.tsx:584-606`

**问题:** 流式工具准备指示器仅在 `agentState === 'preparing'` 时渲染。如果状态快速转换到 `'acting'`，指示器可能闪现或从未出现。

## 修复方案

### Phase 1: 修复核心问题 (必须)

#### 1.1 修复 onObserve 未更新 activeToolCalls
**文件:** `web/src/stores/agent/streamEventHandlers.ts`

**修改:**
```typescript
onObserve: (event) => {
  // 现有逻辑...
  const stack = [...convState.pendingToolsStack];
  stack.pop();

  // 新增: 更新 activeToolCalls 中对应工具的状态
  const newMap = new Map(convState.activeToolCalls);
  const toolName = event.tool_name;
  const existingCall = newMap.get(toolName);
  if (existingCall) {
    newMap.set(toolName, {
      ...existingCall,
      status: 'completed',
      result: event.result,
      completedAt: Date.now(),
    });
  }

  return {
    pendingToolsStack: stack,
    activeToolCalls: newMap,  // 添加这个更新
    // ...其他字段
  };
}
```

#### 1.2 修复 Timeline 更新在流式传输期间被跳过
**文件:** `web/src/stores/agentV3.ts`

**修改:** 在 `loadMessages` 中，不跳过 timeline 更新，而是使用增量合并：
```typescript
// 修改前: 完全跳过
const isCurrentlyStreaming = state.isStreaming;
const timelineChanged = !isCurrentlyStreaming && ...;

// 修改后: 增量合并
const timelineChanged = state.timeline.length !== mergedTimeline.length || ...;
// 即使在流式传输期间也合并，但要保留本地的新事件
const mergedWithLocal = mergeTimelinesPreservingLocal(mergedTimeline, state.timeline, state.lastEventTimestamp);
```

### Phase 2: 改进事件处理 (推荐)

#### 2.1 改进 Delta Buffer 清理逻辑
**文件:** `web/src/stores/agentV3.ts`

**修改:** 在 `clearAllDeltaBuffers` 之前先刷新待处理的 buffer：
```typescript
const flushBeforeClear = () => {
  // 刷新所有待处理的 delta buffer
  if (deltaBufferTimer) {
    clearTimeout(deltaBufferTimer);
    flushTokenDeltaBuffer();  // 先刷新再清除
  }
  // ... 其他 buffer
};
```

#### 2.2 添加 execution_id 回退匹配改进
**文件:** `web/src/components/agent/MessageArea.tsx`

**修改:** 改进 `groupTimelineEvents` 中的 observe 匹配逻辑，添加时间窗口限制：
```typescript
// 只有在合理的时间窗口内（如5秒）的 observe 才能匹配
const MAX_MATCH_DELAY_MS = 5000;
const candidates = observeByToolName.get(act.toolName) || [];
const obs = candidates.find(o =>
  o.timestamp - act.timestamp < MAX_MATCH_DELAY_MS
);
```

### Phase 3: 增强可观测性 (可选)

#### 3.1 添加调试日志
在以下位置添加条件日志：
- `streamEventHandlers.ts` - `onAct`/`onObserve` 调用时
- `agentV3.ts` - `loadMessages` 跳过更新时
- `MessageArea.tsx` - timeline 分组结果

#### 3.2 添加状态一致性检查
在 `onComplete` 时检查 `activeToolCalls` 和 `pendingToolsStack` 是否一致。

## 风险评估

| 风险 | 等级 | 缓解措施 |
|------|------|----------|
| 修改影响现有流式行为 | 中 | 添加单元测试覆盖新逻辑 |
| 状态更新冲突 | 低 | 使用 Zustand 的 immutable 更新模式 |
| 性能影响 | 低 | 增量合并使用 Map 优化 |

## 测试计划

### 单元测试
1. `streamEventHandlers.test.ts` - 测试 `onObserve` 更新 `activeToolCalls`
2. `agentV3.test.ts` - 测试流式期间 `loadMessages` 增量合并

### 集成测试
1. 完整工具执行流程：act -> observe -> complete
2. 快速切换对话场景
3. 页面刷新后恢复流式状态

### 手动测试
1. 执行快速完成的工具（如简单的 todowrite）
2. 在工具执行期间切换对话
3. 在流式传输期间刷新页面

## 预估复杂度

| 阶段 | 工作量 |
|------|--------|
| Phase 1 (核心修复) | 2-3 小时 |
| Phase 2 (改进) | 1-2 小时 |
| Phase 3 (可观测性) | 1 小时 |
| 测试 | 2 小时 |
| **总计** | **6-8 小时** |

---

**等待确认**: 是否按此计划执行修复？
