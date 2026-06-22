# Implementation Plan: SSE Event Adapter Integration into AgentChat

## 1. Requirements Restatement

将 `appendSSEEventToTimeline()` 函数集成到 AgentChat 组件和 agentV3 store，用于处理实时 SSE 事件流。确保 SSE 事件转换为统一的 TimelineEvent 格式，保持流式和历史消息渲染的一致性。

**具体需求：**
1. 在 `agentV3.ts` store 中用 `appendSSEEventToTimeline()` 替换当前的手动 SSE 事件处理
2. 确保 timeline 状态接收正确格式的 TimelineEvent 对象
3. 保持向后兼容性
4. 维持 80%+ 测试覆盖率

## 2. 当前状态分析

### 数据流架构
```
SSE 后端事件 → sseEventAdapter → TimelineEvent[] → timelineEventAdapter → EventGroup[] → UI
                (待集成)                        (已使用)
```

### 当前问题
- `agentV3.ts` 中的 `sendMessage` 动作直接修改 `messages` 状态
- SSE 流**不更新** `timeline` 状态
- timeline 只在 `loadMessages` (API 调用) 时填充
- 存在双重状态管理：timeline + messages

## 3. 实施阶段

| 阶段 | 描述 | 复杂度 | 预计时间 |
|------|------|--------|----------|
| **Phase 1** | Store 核心集成 - 修改 sendMessage 使用 appendSSEEventToTimeline() | Medium-High | 4-6h |
| **Phase 2** | 用户消息处理 - 创建 user_message TimelineEvent | Low | 1-2h |
| **Phase 3** | 移除冗余更新 - 简化 handler callbacks，让 timeline 成为单一数据源 | Medium | 2-3h |
| **Phase 4** | 特殊事件处理 - decision_asked, doom_loop_detected 等非 timeline 事件 | Low | 1-2h |
| **Phase 5** | 测试验证 - 单元测试 + 集成测试 | Medium | 3-4h |
| **总计** | | **Medium** | **11-17h** |

## 4. 关键文件

1. **`src/stores/agentV3.ts`** - 主要集成点
2. **`src/utils/sseEventAdapter.ts`** - 已实现，作为参考
3. **`src/pages/project/AgentChat.tsx`** - 验证组件
4. **`src/types/agent.ts`** - TimelineEvent 类型定义

## 5. 风险评估

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| timeline/messages 同步问题 | High | messages 从 timeline 派生；添加同步验证 |
| 序列号冲突 | Medium | 新对话时重置；加载 timeline 时继续 |
| 破坏现有功能 | High | 合并前全面 E2E 测试 |
| text_delta 打字效果失效 | Medium | 保持 text_delta handler 分离处理 |

## 6. 实施细节

### Phase 1: Store 核心集成

**文件:** `src/stores/agentV3.ts`

**修改内容:**

1. 添加 SSE adapter 导入
2. 修改 `sendMessage` 动作使用 `appendSSEEventToTimeline()`
3. 直接更新 `timeline` 状态而不是只更新 `messages`
4. 处理序列号计数器生命周期

### Phase 2: 用户消息处理

创建 `user_message` TimelineEvent 并在发送前追加到 timeline。

### Phase 3: 移除冗余更新

简化 handler callbacks，让 timeline 成为单一数据源，derive `messages` from `timeline`。

### Phase 4: 特殊事件处理

保持非 timeline 事件（如 `decision_asked`, `doom_loop_detected`）的现有 handler 逻辑。

### Phase 5: 测试验证

- 更新 `src/stores/agentV3-timeline.test.ts`
- 添加 SSE 流的集成测试
- 验证序列号管理
- 验证向后兼容性

## 7. 验收标准

- [ ] SSE 事件正确转换为 TimelineEvent
- [ ] timeline 在流式传输期间实时更新
- [ ] 序列号正确管理
- [ ] 现有功能无回归
- [ ] 测试覆盖率 80%+
