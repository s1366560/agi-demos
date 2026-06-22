# Plan Mode UI 集成设计完整解决方案与执行计划

## 需求重述

基于代码库调查，Plan Mode 系统已有以下实现：
- **后端**: Plan Document 系统、Plan Mode 工具、Use Cases 已完成
- **前端类型**: 完整的 TypeScript 类型定义
- **前端状态管理**: `planModeStore` 和 `agentV3` 中已集成 Plan Mode 状态
- **前端组件**: 多个 UI 组件已实现（PlanModeIndicator、PlanEditor、PlanModeViewer 等）
- **服务层**: `planService` 已实现所有 API 调用

**当前集成状态**：
- `InputArea` 已有 Plan Mode 切换开关
- `RightPanel` 已有 Plan 标签页
- `AgentChat` 已传递 Plan Mode 相关 props
- **但存在以下问题**：
  1. `PlanEditor` 和 `PlanModeViewer` 组件未实际使用
  2. SSE 事件（`plan_mode_enter`, `plan_mode_exit`, `plan_created` 等）未处理
  3. Plan Mode 指示器未在聊天区域显示
  4. 缺少 Plan Mode 激活时的 UI 反馈

---

## 实现阶段

### Phase 1: UI 组件集成（核心功能）

**目标**: 将现有 Plan Mode 组件集成到主聊天界面

**任务列表**:

#### 1.1 在 AgentChat 中添加 PlanModeIndicator 显示
- **文件**: `web/src/pages/project/AgentChat.tsx`
- **修改**:
  - 在 `ChatArea` 顶部添加 `PlanModeIndicator` 组件
  - 从 `usePlanModeStore` 获取 `planModeStatus`
  - 实现 `onViewPlan` 回调打开 Plan Panel
  - 实现 `onExitPlanMode` 回调调用 `exitPlanMode`

#### 1.2 在 RightPanel 中集成 PlanEditor/PlanModeViewer
- **文件**: `web/src/components/agent/RightPanel.tsx`
- **修改**:
  - 在 Plan tab 中添加双视图切换
  - Draft 状态显示 `PlanEditor`（可编辑）
  - 执行中状态显示 `PlanModeViewer`（只读）
  - 集成 `usePlanModeStore` 获取 `currentPlan`

#### 1.3 增强 InputArea 的 Plan Mode 反馈
- **文件**: `web/src/components/agent/InputArea.tsx`
- **当前状态**: 已有 Plan Mode 开关
- **优化**:
  - 添加视觉反馈（背景色变化）
  - Plan Mode 下禁用部分功能按钮
  - 更新 placeholder 提示用户当前模式

---

### Phase 2: SSE 事件处理

**目标**: 处理 Plan Mode 相关的 SSE 事件，实现实时更新

**任务列表**:

#### 2.1 在 agentV3 store 中添加 Plan Mode SSE 处理
- **文件**: `web/src/stores/agentV3.ts`
- **添加处理**:
  ```typescript
  onPlanModeEnter: (event) => { /* 更新状态 */ }
  onPlanModeExit: (event) => { /* 更新状态 */ }
  onPlanCreated: (event) => { /* 加载计划 */ }
  onPlanUpdated: (event) => { /* 刷新计划 */ }
  ```

#### 2.2 创建 planModeSSEAdapter
- **新文件**: `web/src/utils/planModeSSEAdapter.ts`
- **功能**:
  - 将 Plan Mode SSE 事件转换为 UI 状态更新
  - 与 `sseEventAdapter` 类似的架构
  - 处理 `plan_execution_start`, `plan_step_complete` 等事件

#### 2.3 同步 planModeStore 与 agentV3 store
- **问题**: 当前两个 store 都有 Plan Mode 状态
- **解决方案**:
  - 保留 `planModeStore` 作为 Plan Mode 专用状态
  - `agentV3` 通过 `usePlanModeStore` 获取状态
  - 在 SSE 事件中更新 `planModeStore`

---

### Phase 3: 执行计划可视化

**目标**: 显示 ExecutionPlan 的实时执行状态

**任务列表**:

#### 3.1 创建 ExecutionPlanViewer 组件
- **新文件**: `web/src/components/agent/ExecutionPlanViewer.tsx`
- **功能**:
  - 显示 `ExecutionPlan` 的步骤状态
  - 实时更新步骤进度
  - 显示反思（Reflection）结果
  - 支持步骤展开/折叠

#### 3.2 集成到 RightPanel
- 在 Plan tab 中添加 "Execution" 子标签
- 当有 `ExecutionPlan` 时自动切换到 Execution 视图
- 显示执行进度百分比

#### 3.3 添加步骤调整 UI
- **新文件**: `web/src/components/agent/StepAdjustmentModal.tsx`
- **功能**:
  - 显示反思后的调整建议
  - 允许用户批准/拒绝调整
  - 发送调整决策到后端

---

### Phase 4: Plan 工作流完善

**目标**: 完善从创建到批准的完整工作流

**任务列表**:

#### 4.1 Plan 创建流程
- Plan Mode 进入时自动创建 Draft Plan
- 显示 PlanEditor 供用户编辑
- 保存更改到后端

#### 4.2 Plan 审查流程
- 提交审查时状态变为 `reviewing`
- 显示版本历史
- 批准后切换到 Build Mode

#### 4.3 Plan 执行流程
- 批准后自动进入执行阶段
- 显示 ExecutionPlan 进度
- 执行完成后显示摘要

---

### Phase 5: 自定义 Hooks

**目标**: 创建可复用的 Plan Mode hooks

**任务列表**:

#### 5.1 usePlanMode Hook
- **文件**: `web/src/hooks/usePlanMode.ts`
- **功能**:
  - 封装 planModeStore 操作
  - 提供便捷方法 (`enter`, `exit`, `update`)
  - 统一错误处理

#### 5.2 usePlanExecution Hook
- **文件**: `web/src/hooks/usePlanExecution.ts`
- **功能**:
  - 监听执行计划 SSE 事件
  - 维护执行状态
  - 提供进度信息

---

## 依赖关系

```
Phase 1 (UI 集成)
    ├── 依赖: 无（组件已存在）
    ├── 阻塞: Phase 2 (SSE 事件)

Phase 2 (SSE 事件)
    ├── 依赖: Phase 1
    ├── 阻塞: Phase 3 (执行可视化)

Phase 3 (执行可视化)
    ├── 依赖: Phase 2
    ├── 阻塞: Phase 4 (工作流)

Phase 4 (工作流)
    ├── 依赖: Phase 3
    ├── 阻塞: Phase 5 (Hooks)

Phase 5 (Hooks)
    ├── 依赖: Phase 4
    ├── 可并行: 与前面阶段部分并行
```

---

## 风险评估

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| **高**: SSE 事件格式与前端类型不匹配 | 阻塞实时更新 | 先验证后端 SSE 事件格式 |
| **中**: planModeStore 与 agentV3 状态不同步 | UI 显示不一致 | 使用 Zustand 的跨 store 订阅 |
| **中**: ExecutionPlan 数据结构变更 | UI 渲染错误 | 使用严格 TypeScript 检查 |
| **低**: 组件性能问题（大量重渲染） | 用户体验下降 | React.memo 和 useMemo 优化 |

---

## 复杂度评估

**总体复杂度: 中等**

| 阶段 | 复杂度 | 预估工作量 |
|------|--------|-----------|
| Phase 1 | 低 | 2-3 小时 |
| Phase 2 | 中 | 4-5 小时 |
| Phase 3 | 中 | 3-4 小时 |
| Phase 4 | 中 | 3-4 小时 |
| Phase 5 | 低 | 1-2 小时 |
| **总计** | **中等** | **13-18 小时** |

---

## 执行顺序建议

**推荐顺序**: Phase 1 → Phase 2 → Phase 3 → Phase 4 → Phase 5

**原因**:
1. Phase 1 建立基础 UI，快速可见成果
2. Phase 2 实现实时更新，是连接前后端的关键
3. Phase 3 提供执行可视化，是核心价值
4. Phase 4 完善工作流，提升用户体验
5. Phase 5 提供可复用性，便于后续维护

---

## 文件变更清单

### 新建文件
- `web/src/components/agent/ExecutionPlanViewer.tsx`
- `web/src/components/agent/StepAdjustmentModal.tsx`
- `web/src/utils/planModeSSEAdapter.ts`
- `web/src/hooks/usePlanMode.ts`
- `web/src/hooks/usePlanExecution.ts`

### 修改文件
- `web/src/pages/project/AgentChat.tsx`
- `web/src/components/agent/RightPanel.tsx`
- `web/src/components/agent/InputArea.tsx`
- `web/src/stores/agentV3.ts`
- `web/src/stores/agent/planModeStore.ts` (可能)
- `web/src/components/agent/index.ts` (导出新组件)

---

## 成功标准

### 功能完整性
- [ ] Plan Mode 开关正常工作
- [ ] Plan Editor 可以编辑和保存计划
- [ ] Execution Plan 实时显示执行进度
- [ ] SSE 事件正确更新 UI 状态
- [ ] 反思结果正确显示

### 用户体验
- [ ] 模式切换流畅，无明显延迟
- [ ] 视觉反馈清晰（状态指示器、进度条）
- [ ] 错误处理友好（显示提示消息）

### 代码质量
- [ ] TypeScript 无类型错误
- [ ] 通过 ESLint 检查
- [ ] 组件使用 React.memo 优化
- [ ] 遵循现有代码风格
