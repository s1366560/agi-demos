# Sandbox 在 Agent UI 的集成修复

## 需求描述

用户报告 **sandbox 没有正确在 Agent UI 集成**。经过代码审查，发现以下问题：

## 当前状态分析

### 已实现的功能 ✅

| 组件 | 文件路径 | 状态 |
|------|----------|------|
| SandboxPanel | `web/src/components/agent/sandbox/SandboxPanel.tsx` | ✅ 已实现 |
| RightPanel | `web/src/components/agent/RightPanel.tsx` | ✅ 已实现 |
| sandboxStore | `web/src/stores/sandbox.ts` | ✅ 已实现 |
| useSandboxDetection | `web/src/hooks/useSandboxDetection.ts` | ✅ 已实现 |
| useSandboxAgentHandlers | `web/src/hooks/useSandboxDetection.ts` | ✅ 已实现 |
| AgentChat 集成 | `web/src/pages/project/AgentChat.tsx` | ✅ 已传递处理器 |
| SSE 事件类型 | `web/src/services/agentService.ts` | ✅ act/observe 已支持 |
| 后端 SSE Bridge | `src/infrastructure/agent/cua/callbacks/sse_bridge.py` | ✅ 已实现 |
| **sandboxService** | `web/src/services/sandboxService.ts` | ✅ **已实现 (TDD)** |

### 存在的问题 ❌

| 问题 | 描述 | 影响 | 状态 |
|------|------|------|------|
| **sandboxId 未传递** | `activeSandboxId` 始终为 `null` | 无法连接到有效的 sandbox | 🔄 进行中 |
| **缺少 Sandbox API 服务** | 前端没有调用后端创建/连接 sandbox 的逻辑 | 无法创建 sandbox 实例 | ✅ 已完成 |
| **缺少 Desktop/Terminal SSE 事件** | 后端不发送 `desktop_started`/`terminal_started` 等事件 | UI 无法显示正确状态 | ⏳ 待处理 |
| **RightPanel Tab 切换问题** | sandbox 工具执行时不会自动切换到 sandbox tab | 用户体验差 | ⏳ 待处理 |
| **TODO 未实现** | sandboxStore 中的 API 调用只有 TODO 注解 | Desktop/Terminal 控制不工作 | ✅ 已完成 |

---

## 实施进度

### Phase 1: 创建 Sandbox API 服务 (前端) ✅

**文件**: `web/src/services/sandboxService.ts`

**状态**: ✅ 已完成 (TDD)

**实现内容**:
- ✅ `createSandbox(request)` - 创建新 sandbox
- ✅ `getSandbox(sandboxId)` - 获取 sandbox 信息
- ✅ `listSandboxes(projectId)` - 列出项目的所有 sandbox
- ✅ `deleteSandbox(sandboxId)` - 删除 sandbox
- ✅ `startDesktop(sandboxId, resolution?)` - 启动远程桌面
- ✅ `stopDesktop(sandboxId)` - 停止远程桌面
- ✅ `startTerminal(sandboxId)` - 启动终端服务
- ✅ `stopTerminal(sandboxId)` - 停止终端服务
- ✅ `getDesktopStatus(sandboxId)` - 获取桌面状态
- ✅ `getTerminalStatus(sandboxId)` - 获取终端状态

**测试**: 16 个测试用例全部通过

```bash
$ pnpm test sandboxService.test.ts
Test Files: 1 passed (1)
Tests: 16 passed (16)
```

### Phase 2: 更新 SandboxStore 集成 sandboxService ✅

**文件**: `web/src/stores/sandbox.ts`

**状态**: ✅ 已完成

**修改内容**:
- ✅ 移除 `startDesktop` 中的 TODO，实现实际的 API 调用
- ✅ 移除 `stopDesktop` 中的 TODO，实现实际的 API 调用
- ✅ 移除 `startTerminal` 中的 TODO，实现实际的 API 调用
- ✅ 移除 `stopTerminal` 中的 TODO，实现实际的 API 调用
- ✅ 添加错误处理和日志记录

### Phase 3: 后端 Sandbox SSE 事件 ⏳

**文件**: `src/infrastructure/agent/core/processor.py`

**需要添加的 SSE 事件**:

```python
# 在 AgentEventType 中添加:
SANDBOX_CREATED = "sandbox_created"
DESKTOP_STARTED = "desktop_started"
DESKTOP_STOPPED = "desktop_stopped"
TERMINAL_STARTED = "terminal_started"
TERMINAL_STOPPED = "terminal_stopped"
```

**状态**: ⏳ 待实施

### Phase 4: 修复 RightPanel Tab 切换逻辑 ⏳

**文件**: `web/src/components/agent/RightPanel.tsx`

**修改内容**:

```typescript
// 当检测到 sandbox 工具执行时自动切换到 sandbox tab
useEffect(() => {
  if (currentTool && isSandboxTool(currentTool.name)) {
    setInternalActiveTab("sandbox");
  }
}, [currentTool]);
```

**状态**: ⏳ 待实施

### Phase 5: 修复 AgentChat 中的 Sandbox 集成 ⏳

**文件**: `web/src/pages/project/AgentChat.tsx`

**修改内容**:

1. 在组件挂载时创建或获取活跃的 sandbox
2. 将 sandboxId 正确传递给 `RightPanel` 和 `useSandboxAgentHandlers`

```typescript
// 在发送消息前确保 sandbox 存在
const ensureSandbox = useCallback(async (projectId: string) => {
  if (activeSandboxId) return activeSandboxId;

  const sandbox = await sandboxService.createSandbox(projectId);
  useSandboxStore.getState().setSandboxId(sandbox.id);
  return sandbox.id;
}, [activeSandboxId]);
```

**状态**: ⏳ 待实施

### Phase 6: 后端路由验证 ⏳

**文件**: `src/infrastructure/adapters/primary/web/routers/sandbox.py`

**验证点**:
- ⏳ POST `/api/v1/sandbox` - 创建 sandbox
- ⏳ GET `/api/v1/sandbox/{id}` - 获取 sandbox 信息
- ⏳ GET `/api/v1/sandbox` - 列出 sandbox
- ⏳ DELETE `/api/v1/sandbox/{id}` - 删除 sandbox
- ⏳ POST `/api/v1/sandbox/{id}/desktop` - 启动 desktop
- ⏳ DELETE `/api/v1/sandbox/{id}/desktop` - 停止 desktop
- ⏳ POST `/api/v1/sandbox/{id}/terminal` - 启动 terminal
- ⏳ DELETE `/api/v1/sandbox/{id}/terminal` - 停止 terminal

**状态**: ⏳ 待验证

---

## 依赖关系图

```
┌─────────────────────────────────────────────────────────────────┐
│                         AgentChat.tsx                            │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  - 创建/获取 sandbox (sandboxService)                     │  │
│  │  - 传递 onAct/onObserve (useSandboxAgentHandlers)        │  │
│  │  - 传递 sandboxId to RightPanel                          │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              │
                ┌─────────────┴─────────────┐
                ▼                           ▼
┌───────────────────────────┐   ┌───────────────────────────┐
│      RightPanel.tsx       │   │    sandboxService.ts      │
│  ┌─────────────────────┐  │   │  ┌─────────────────────┐  │
│  │ - Tab 切换逻辑       │  │   │  │ - createSandbox()   │  │
│  │ - 渲染 SandboxPanel │  │   │  │ - startDesktop()    │  │
│  └─────────────────────┘  │   │  │ - startTerminal()   │  │
└───────────────────────────┘   │  └─────────────────────┘  │
                │                 └───────────────────────────┘
                ▼                              │
┌───────────────────────────┐                 │
│      SandboxPanel.tsx     │                 │
│  ┌─────────────────────┐  │                 │
│  │ - Terminal 标签页   │  │                 │
│  │ - Desktop 标签页    │  │                 │
│  │ - Output 标签页     │  │                 │
│  │ - Control 标签页    │  │                 │
│  └─────────────────────┘  │                 │
└───────────────────────────┘                 │
                │                              │
                ▼                              ▼
┌───────────────────────────┐   ┌───────────────────────────┐
│      sandbox.ts (store)   │   │   Backend API Routes      │
│  ┌─────────────────────┐  │   │   /sandbox.py             │
│  │ - activeSandboxId   │  │   │  ┌─────────────────────┐  │
│  │ - desktopStatus     │◄─┼───┼──┤ - POST /sandbox      │  │
│  │ - terminalStatus    │◄─┼───┼──┤ - POST /desktop      │  │
│  │ - toolExecutions    │  │   │  │ - POST /terminal     │  │
│  └─────────────────────┘  │   │  └─────────────────────┘  │
└───────────────────────────┘   └───────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────────────────────────────┐
│                      SSE Events (WebSocket)                      │
│  act / observe / sandbox_created / desktop_started / ...       │
└─────────────────────────────────────────────────────────────────┘
```

---

## 风险评估

| 风险 | 级别 | 影响 | 缓解措施 |
|------|------|------|----------|
| 后端 sandbox 端点不完整 | **MEDIUM** | 无法创建/控制 sandbox | 先验证后端 API，必要时补充实现 |
| WebSocket 事件类型冲突 | **LOW** | 事件路由错误 | 使用命名空间 `sandbox_*` 避免冲突 |
| sandboxId 同步问题 | **LOW** | 状态不一致 | 使用 Zustand store 作为单一数据源 |
| Desktop/Terminal 连接失败 | **MEDIUM** | 功能不可用 | 添加错误处理和用户提示 |

---

## 预估工作量

| 任务 | 预估时间 |
|------|----------|
| Phase 1: 创建 sandboxService.ts | 1 小时 |
| Phase 2: 后端 SSE 事件 | 1 小时 |
| Phase 3: 修复 RightPanel 逻辑 | 30 分钟 |
| Phase 4: 修复 AgentChat 集成 | 1 小时 |
| Phase 5: 更新 sandboxStore | 1 小时 |
| Phase 6: 后端路由验证 | 1 小时 |
| 测试与调试 | 2-3 小时 |
| **总计** | **7-10 小时** |

---

## 验收标准

### 功能验收
- [ ] Agent Chat 页面加载时自动创建 sandbox
- [ ] `activeSandboxId` 正确设置并传递到所有组件
- [ ] 当 agent 执行 sandbox 工具 (read/write/bash) 时，RightPanel 自动切换到 Sandbox 标签
- [ ] Terminal 标签页可以连接并显示终端输出
- [ ] Desktop 标签页可以启动/停止远程桌面
- [ ] Output 标签页显示工具执行历史
- [ ] Control 标签页的按钮工作正常

### 技术验收
- [ ] 所有新代码有 80%+ 测试覆盖率
- [ ] 没有 TypeScript 类型错误
- [ ] 没有控制台错误或警告
- [ ] WebSocket 事件正确路由
- [ ] API 错误正确处理和显示

---

## 参考资料

**相关文件**:
- 前端 Agent 类型: `web/src/types/agent.ts`
- SSE 适配器: `web/src/utils/sseEventAdapter.ts`
- Agent WebSocket 服务: `web/src/services/agentService.ts`
- 后端事件定义: `src/domain/events/agent_events.py`
- 后端 SSE Bridge: `src/infrastructure/agent/cua/callbacks/sse_bridge.py`

**相关文档**:
- CLAUDE.md - Agent 系统架构
- docs/agent-system.md - Agent 系统设计文档
