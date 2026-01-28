# 实施计划：将 Sandbox 远程桌面与 Shell 集成到 Agent 聊天界面

## 需求重述

将现有的 Sandbox 系统（基于 MCP 协议的 Docker 沙箱）的远程桌面（LXDE + noVNC）和 Shell 终端（ttyd）功能集成到 Agent 聊天界面中，使用户可以在与 Agent 对话的同时：
1. 查看和控制远程桌面
2. 交互式使用 Shell 终端
3. 通过 SSE 事件接收桌面/终端状态更新

## 现有架构分析

### 后端已有功能
| 组件 | 路径 | 功能 |
|------|------|------|
| **MCP Sandbox Adapter** | `src/infrastructure/adapters/secondary/sandbox/mcp_sandbox_adapter.py` | Docker 容器管理和 MCP 工具调用 |
| **Terminal Router** | `src/infrastructure/adapters/primary/web/routers/terminal.py` | WebSocket 终端会话 |
| **Terminal Proxy** | `src/infrastructure/adapters/secondary/sandbox/terminal_proxy.py` | 终端连接代理 |
| **Sandbox MCP Server** | `sandbox-mcp-server/` | 独立的 MCP 服务器，提供桌面和终端工具 |

### 前端已有功能
| 组件 | 路径 | 功能 |
|------|------|------|
| **SandboxPanel** | `web/src/components/agent/sandbox/SandboxPanel.tsx` | 沙箱面板（Terminal + Output 标签） |
| **SandboxTerminal** | `web/src/components/agent/sandbox/SandboxTerminal.tsx` | xterm.js 终端组件 |
| **SandboxOutputViewer** | `web/src/components/agent/sandbox/SandboxOutputViewer.tsx` | 工具执行历史 |

### 现有 SSE 事件类型
- `message`, `thought`, `act`, `observe`, `work_plan`, `step_start`, `step_end` 等
- 需要添加：`desktop_started`, `desktop_stopped`, `terminal_ready`, `screenshot_update` 等

---

## 实施阶段

### Phase 1: 后端 SSE 事件扩展

**目标**: 扩展 SSE 事件系统，支持桌面和终端状态推送

**任务**:
1. 在 `src/domain/events/agent_events.py` 添加新事件类型
2. 创建桌面管理工具（Agent Tool）
3. 创建终端管理工具

**依赖**: 无
**风险**: 低
**复杂度**: 中等

---

### Phase 2: 后端 API 路由扩展

**目标**: 添加桌面和终端的 WebSocket 代理端点

**任务**:
1. 扩展 terminal.py 路由
2. 添加桌面截图端点

**依赖**: Phase 1
**风险**: 中
**复杂度**: 中等

---

### Phase 3: 前端类型定义扩展

**目标**: 扩展前端类型以支持新事件

**任务**:
1. 在 `web/src/types/agent.ts` 添加新事件类型
2. 添加桌面和终端相关接口

**依赖**: Phase 1
**风险**: 低
**复杂度**: 低

---

### Phase 4: 前端 SSE 事件适配器

**目标**: 扩展事件适配器以处理新事件

**任务**:
1. 在 `web/src/utils/sseEventAdapter.ts` 添加新事件处理
2. 在 `web/src/stores/agentV3.ts` 添加状态管理

**依赖**: Phase 3
**风险**: 低
**复杂度**: 低

---

### Phase 5: 前端组件开发

**目标**: 创建桌面和终端查看器组件

**任务**:
1. 创建 RemoteDesktopViewer.tsx
2. 增强 SandboxTerminal.tsx
3. 创建 SandboxControlPanel.tsx

**依赖**: Phase 4
**风险**: 中
**复杂度**: 中等

---

### Phase 6: Agent 聊天界面集成

**目标**: 将组件集成到主聊天界面

**任务**:
1. 在 AgentChat.tsx 集成控制面板
2. 在时间线中显示桌面/终端事件
3. 添加 Agent 工具调用联动

**依赖**: Phase 5
**风险**: 中
**复杂度**: 中等

---

### Phase 7: MCP 工具注册

**目标**: 在 Agent 中注册桌面和终端工具

**任务**:
1. 在 tools/__init__.py 注册新工具
2. 更新 DI 容器

**依赖**: Phase 1
**风险**: 低
**复杂度**: 低

---

### Phase 8: 测试与验证

**目标**: 确保功能稳定可靠

**任务**:
1. 单元测试
2. 集成测试
3. E2E 测试

**依赖**: 所有前置阶段
**风险**: 中
**复杂度**: 中等

---

## 架构决策

### 通信方式

| 场景 | 通信方式 | 理由 |
|------|----------|------|
| Agent → 后端 | SSE | 现有架构，支持流式响应 |
| 后端 → 前端 | SSE | 状态更新推送 |
| 前端 → 桌面 | WebSocket + noVNC | 低延迟实时交互 |
| 前端 → 终端 | WebSocket + xterm.js | 标准终端实现 |

### 集成方式

- **嵌入式**: 桌面和终端作为聊天界面右侧面板
- **可切换**: 通过标签在桌面/终端/输出之间切换
- **自动弹出**: Agent 调用相关工具时自动打开

### 端口分配

| 服务 | 容器内端口 | 宿主机端口范围 |
|------|------------|----------------|
| MCP WebSocket | 8765 | 18765-19765 |
| noVNC | 6080 | 16080-17080 |
| ttyd | 7681 | 17681-18681 |

---

## 风险评估

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 跨域问题 | iframe 无法加载 noVNC | 配置 CORS 和代理端点 |
| WebSocket 代理复杂度 | 延迟增加，连接不稳定 | 使用 FastAPI WebSocket 代理，添加心跳 |
| 资源消耗 | 桌面占用大量内存 | 设置资源限制，自动清理闲置会话 |
| 安全性 | 恶意代码执行 | 容器隔离，网络隔离，权限控制 |
| 多用户并发 | 端口冲突 | 动态端口分配，会话管理 |

---

## 实施顺序

1. **第一阶段**（核心功能）: Phase 1 → Phase 3 → Phase 4 → Phase 7
2. **第二阶段**（用户界面）: Phase 5 → Phase 6
3. **第三阶段**（优化）: Phase 2 → Phase 8

---

## 预估复杂度

| 阶段 | 后端 | 前端 | 测试 |
|------|------|------|------|
| 1 | 4h | - | 1h |
| 2 | 6h | - | 2h |
| 3 | - | 2h | 1h |
| 4 | - | 3h | 2h |
| 5 | - | 8h | 3h |
| 6 | - | 6h | 2h |
| 7 | 2h | - | 1h |
| 8 | - | - | 6h |
| **总计** | **12h** | **19h** | **18h** |
| **合计** | **约 49 小时** (6-8 工作日) |

---

## 技术栈

- **后端**: Python 3.12+, FastAPI, Docker, MCP 协议
- **前端**: React 19.2+, xterm.js, noVNC, Zustand
- **通信**: SSE, WebSocket, HTTP REST
- **沙箱**: Docker 容器，LXDE 桌面，ttyd 终端
