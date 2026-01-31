# MemStack 前端重构计划
## 基于 Vercel React Best Practices 分析

**生成日期**: 2026-01-31
**分析工具**: Vercel React Best Practices Skill
**目标**: 优化 React 19.2+ 前端性能和代码质量

---

## 执行摘要

根据 Vercel React Best Practices 57 条规则分析，MemStack 前端存在 **22 个可优化问题**，按严重程度分为：

| 优先级 | 类别 | 问题数 | 预估影响 |
|--------|------|--------|----------|
| **HIGH** | Re-render Optimization | 5 | 高 - 导致不必要的重渲染 |
| **HIGH** | Derived State Duplication | 1 | 高 - 内存和同步问题 |
| **MEDIUM** | Async Waterfalls | 3 | 中 - 延迟数据加载 |
| **MEDIUM** | Bundle Size | 4 | 中 - 增加 JS 大小 |
| **MEDIUM** | Rendering Performance | 3 | 中 - 影响 FPS |
| **LOW** | JavaScript Performance | 2 | 低 - 小幅优化 |
| **LOW** | Data Fetching Patterns | 4 | 低 - 可优化用户体验 |

---

## 第一部分：高优先级问题

### 1.1 useLocalStorage Hook - 依赖数组问题

**文件**: `web/src/hooks/useLocalStorage.ts:48-64`

**问题**: `setValue` 回调依赖 `storedValue`，每次状态变化都会重新创建回调。

**对应规则**: `rerender-functional-setstate`

**修复方案**: 使用函数式 setState 避免依赖 `storedValue`

---

### 1.2 agentV3 Store - Derived State 重复存储

**文件**: `web/src/stores/agentV3.ts:162-165`

**问题**: `messages` 是从 `timeline` 派生的，但两者都存储在状态中。

**对应规则**: `rerender-derived-state`, `rerender-derived-state-no-effect`

**修复方案**: 使用 Zustand selector 派生 messages，不存储在状态中

---

### 1.3 缺少 memo 的组件

**文件**:
- `web/src/pages/tenant/ProjectList.tsx`
- `web/src/components/agent/chat/MessageStream.tsx`

**对应规则**: `rerender-memo`

**修复方案**: 添加 `React.memo()` 包裹组件

---

## 第二部分：中优先级问题

### 2.1 并行 API 调用

**文件**: `web/src/stores/agentV3.ts:523-550`

**问题**: 三个独立 API 调用串行执行

**对应规则**: `async-parallel`

**修复方案**: 使用 `Promise.all()` 并行调用

---

### 2.2 Markdown 懒加载

**文件**: `web/src/components/agent/TimelineEventItem.tsx:15-16`

**对应规则**: `bundle-dynamic-imports`

**修复方案**: 使用 `React.lazy()` 懒加载 ReactMarkdown

---

### 2.3 非提升的 JSX/数组

**文件**: `web/src/components/agent/TimelineEventItem.tsx:295-298`

**对应规则**: `rendering-hoist-jsx`

**修复方案**: 将 `remarkPlugins` 数组提升到组件外部

---

### 2.4 formatStorage 函数重复创建

**文件**: `web/src/pages/tenant/ProjectList.tsx:21-27`

**对应规则**: `rendering-hoist-jsx`

**修复方案**: 将函数提升到组件外部

---

## 第三部分：低优先级优化

### 3.1 Content-Visibility 优化

**文件**: `web/src/components/agent/VirtualTimelineEventList.tsx`

**对应规则**: `rendering-content-visibility`

**建议**: 添加 CSS `content-visibility: auto`

---

### 3.2 Barrel Export 优化

**文件**:
- `web/src/components/agent/chat/index.ts`
- `web/src/components/agent/execution/index.ts`
- `web/src/components/index.ts`

**对应规则**: `bundle-barrel-imports`

---

### 3.3 数组操作优化

**文件**: `web/src/stores/agentV3.ts:42-145`

**对应规则**: `js-combine-iterations`

---

## 第四部分：实施计划

### Phase 1: 高优先级修复

| 任务 | 文件 | 规则 |
|------|------|------|
| 修复 useLocalStorage 依赖 | `hooks/useLocalStorage.ts` | `rerender-functional-setstate` |
| 移除派生状态 messages | `stores/agentV3.ts` | `rerender-derived-state` |
| 添加 memo 到 ProjectList | `pages/tenant/ProjectList.tsx` | `rerender-memo` |
| 添加 memo 到 MessageStream | `components/agent/chat/MessageStream.tsx` | `rerender-memo` |

### Phase 2: 中优先级修复

| 任务 | 文件 | 规则 |
|------|------|------|
| 并行化 API 调用 | `stores/agentV3.ts` | `async-parallel` |
| Markdown 懒加载 | `components/agent/TimelineEventItem.tsx` | `bundle-dynamic-imports` |
| 提升 remarkPlugins | `components/agent/TimelineEventItem.tsx` | `rendering-hoist-jsx` |
| 提升 formatStorage | `pages/tenant/ProjectList.tsx` | `rendering-hoist-jsx` |

### Phase 3: 低优先级优化

| 任务 | 文件 | 规则 |
|------|------|------|
| Content-visibility CSS | `components/agent/VirtualTimelineEventList.tsx` | `rendering-content-visibility` |
| 优化 barrel exports | 各 `index.ts` | `bundle-barrel-imports` |
| 合并数组遍历 | `stores/agentV3.ts` | `js-combine-iterations` |

---

## 附录：完整规则映射表

| 问题位置 | Vercel 规则 | 严重程度 |
|----------|-------------|----------|
| `useLocalStorage.ts:63` | `rerender-functional-setstate` | HIGH |
| `agentV3.ts:164-165` | `rerender-derived-state`, `rerender-derived-state-no-effect` | HIGH |
| `ProjectList.tsx:1` | `rerender-memo` | HIGH |
| `MessageStream.tsx:29` | `rerender-memo` | HIGH |
| `agentV3.ts:523-550` | `async-parallel` | MEDIUM |
| `TimelineEventItem.tsx:15-16` | `bundle-dynamic-imports` | MEDIUM |
| `TimelineEventItem.tsx:295` | `rendering-hoist-jsx` | MEDIUM |
| `ProjectList.tsx:21-27` | `rendering-hoist-jsx` | MEDIUM |
| `VirtualTimelineEventList.tsx` | `rendering-content-visibility` | LOW |
| `components/index.ts` | `bundle-barrel-imports` | LOW |
| `agentV3.ts:42-145` | `js-combine-iterations` | LOW |
