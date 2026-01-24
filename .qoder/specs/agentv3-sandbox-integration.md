# AgentV3 UI 整合 Sandbox Terminal 实施计划

## 概述

在 AgentV3 UI 中集成 Sandbox 调试能力，当 Agent 使用 sandbox 工具时自动展开终端面板，提供交互式 Shell 和实时输出查看。

## 架构设计

**布局方案**: Sandbox 与 Plan 共用右侧面板，通过 Tab 切换

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         AgentV3 UI (React)                              │
├───────────────┬─────────────────────────────┬───────────────────────────┤
│ Conversation  │         ChatArea            │  RightPanel (400px)       │
│ Sidebar       │  ┌───────────────────┐      │  ┌─────────────────────┐  │
│ (280px)       │  │ ExecutionTimeline │      │  │ [Plan] [Sandbox]    │  │ ← Tab 切换
│               │  │  └─ act event ────┼──────┼─▶├─────────────────────┤  │
│               │  └───────────────────┘      │  │ Plan Mode:          │  │
│               │                             │  │   PlanViewer        │  │
│               │                             │  │ Sandbox Mode:       │  │
│               │                             │  │   ┌───────────────┐ │  │
│               │                             │  │   │ Terminal      │ │  │
│               │                             │  │   │ (xterm.js)    │ │  │
│               │                             │  │   └───────────────┘ │  │
│               │                             │  │   ┌───────────────┐ │  │
│               │                             │  │   │ Output Viewer │ │  │
│               │                             │  │   └───────────────┘ │  │
└───────────────┴─────────────────────────────┴───────────────────────────┘
                              │                              ▲
                              │ SSE Events                   │ WebSocket
                              ▼                              │
┌─────────────────────────────────────────────────────────────────────────┐
│                         MemStack Backend                                │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────────┐  │
│  │ Agent Router    │  │ Sandbox Router  │  │ Terminal Router (新增)  │  │
│  │ (SSE 事件流)    │  │ (工具调用 API)  │  │ WS /terminal/{id}       │  │
│  └─────────────────┘  └─────────────────┘  └─────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
                                        │
                                        ▼
                        ┌───────────────────────────┐
                        │   Sandbox Container       │
                        │   ├─ MCP WebSocket :8765  │
                        │   └─ docker exec /bin/bash│
                        └───────────────────────────┘
```

## 实施阶段

### 阶段 1: 后端 Terminal WebSocket Proxy

**目标**: 提供 WebSocket 端点，代理前端到 Docker 容器的交互式 Shell

**文件清单**:
| 文件 | 操作 | 描述 |
|------|------|------|
| `src/infrastructure/adapters/primary/web/routers/terminal.py` | 新建 | Terminal WebSocket 路由 |
| `src/infrastructure/adapters/secondary/sandbox/terminal_proxy.py` | 新建 | Docker exec TTY 代理 |
| `src/infrastructure/adapters/primary/web/main.py` | 修改 | 注册 terminal router |

**关键接口**:
```python
# WebSocket 端点
@router.websocket("/{sandbox_id}/ws")
async def terminal_websocket(websocket: WebSocket, sandbox_id: str)

# 消息协议 (JSON)
{
    "type": "input" | "output" | "resize" | "error",
    "data": str,           # 输入/输出数据
    "cols": int,           # 终端列数 (resize)
    "rows": int            # 终端行数 (resize)
}
```

### 阶段 2: 前端 Terminal 组件

**目标**: 基于 xterm.js 实现 Web 终端组件

**依赖安装**:
```bash
cd web && pnpm add @xterm/xterm @xterm/addon-fit @xterm/addon-web-links
```

**文件清单**:
| 文件 | 操作 | 描述 |
|------|------|------|
| `web/src/components/agent/sandbox/SandboxPanel.tsx` | 新建 | 主面板容器 |
| `web/src/components/agent/sandbox/SandboxTerminal.tsx` | 新建 | xterm.js 终端 |
| `web/src/components/agent/sandbox/SandboxOutputViewer.tsx` | 新建 | 工具输出查看器 |
| `web/src/components/agent/sandbox/index.ts` | 新建 | 导出入口 |
| `web/src/hooks/useSandboxTerminal.ts` | 新建 | Terminal WebSocket Hook |

**组件接口**:
```typescript
interface SandboxPanelProps {
  sandboxId: string | null;
  visible: boolean;
  onClose: () => void;
}

interface SandboxTerminalProps {
  sandboxId: string;
  onConnect?: () => void;
  onDisconnect?: () => void;
}
```

### 阶段 3: 状态管理与事件检测

**目标**: 扩展 Zustand store，检测 sandbox 工具调用事件

**文件清单**:
| 文件 | 操作 | 描述 |
|------|------|------|
| `web/src/stores/sandbox.ts` | 新建 | Sandbox 状态管理 |
| `web/src/hooks/useSandboxDetection.ts` | 新建 | 事件检测 Hook |

**状态定义**:
```typescript
interface SandboxState {
  // 面板状态
  panelVisible: boolean;
  panelMode: "terminal" | "output" | "split";
  
  // Sandbox 连接
  activeSandboxId: string | null;
  connectionStatus: "idle" | "connecting" | "connected" | "error";
  
  // 工具执行追踪
  currentTool: { name: string; input: Record<string, any> } | null;
  toolOutput: string | null;
  toolHistory: ToolExecution[];
  
  // Actions
  openPanel: (sandboxId: string) => void;
  closePanel: () => void;
  setToolOutput: (output: string) => void;
}
```

**事件检测逻辑**:
```typescript
const SANDBOX_TOOLS = ["read", "write", "edit", "glob", "grep", "bash"];

// 在 agentService 的 onAct 回调中
onAct: (event) => {
  if (SANDBOX_TOOLS.includes(event.data.tool_name)) {
    sandboxStore.openPanel(activeSandboxId);
    sandboxStore.setCurrentTool(event.data);
  }
}
```

### 阶段 4: UI 集成

**目标**: 将 SandboxPanel 与 PlanPanel 整合为 Tab 面板

**文件清单**:
| 文件 | 操作 | 描述 |
|------|------|------|
| `web/src/components/agentV3/RightPanel.tsx` | 新建 | 右侧 Tab 面板容器 |
| `web/src/components/agentV3/ChatLayout.tsx` | 修改 | 替换原 planPanel 为 rightPanel |
| `web/src/pages/project/AgentChatV3.tsx` | 修改 | 组装 RightPanel |

**RightPanel 组件设计**:
```tsx
// RightPanel.tsx
type TabKey = "plan" | "sandbox";

interface RightPanelProps {
  workPlan: WorkPlan | null;
  sandboxId: string | null;
  defaultTab?: TabKey;
}

export function RightPanel({ workPlan, sandboxId, defaultTab = "plan" }: RightPanelProps) {
  const [activeTab, setActiveTab] = useState<TabKey>(defaultTab);
  const { panelVisible } = useSandboxStore();
  
  // 检测到 sandbox 事件时自动切换
  useEffect(() => {
    if (panelVisible) setActiveTab("sandbox");
  }, [panelVisible]);

  return (
    <div className="h-full flex flex-col">
      <Tabs activeKey={activeTab} onChange={setActiveTab} className="px-4 pt-2">
        <Tabs.TabPane tab="Plan" key="plan" />
        <Tabs.TabPane tab="Sandbox" key="sandbox" disabled={!sandboxId} />
      </Tabs>
      <div className="flex-1 overflow-hidden">
        {activeTab === "plan" && <PlanViewer plan={workPlan} />}
        {activeTab === "sandbox" && sandboxId && <SandboxPanel sandboxId={sandboxId} />}
      </div>
    </div>
  );
}
```

**布局变更**:
```tsx
// ChatLayout.tsx - 简化为三面板
<Layout className="h-full">
  <Sider width={280} collapsed={!showHistorySidebar}>{sidebar}</Sider>
  <Layout>
    <Content>{chatArea}</Content>
  </Layout>
  <Sider width={400} collapsed={!showRightPanel}>{rightPanel}</Sider>  {/* 合并后的面板 */}
</Layout>
```

## 关键代码示例

### 后端 Terminal Proxy
```python
# terminal.py
@router.websocket("/{sandbox_id}/ws")
async def terminal_websocket(websocket: WebSocket, sandbox_id: str):
    await websocket.accept()
    
    container = docker_client.containers.get(sandbox_id)
    exec_id = container.client.api.exec_create(
        container.id, "/bin/bash",
        stdin=True, tty=True, stdout=True, stderr=True
    )
    sock = container.client.api.exec_start(exec_id, socket=True, tty=True)
    
    async def read_from_container():
        while True:
            data = await asyncio.to_thread(sock.recv, 4096)
            if not data:
                break
            await websocket.send_json({"type": "output", "data": data.decode()})
    
    async def write_to_container():
        async for msg in websocket.iter_json():
            if msg["type"] == "input":
                sock.send(msg["data"].encode())
            elif msg["type"] == "resize":
                container.client.api.exec_resize(exec_id, msg["rows"], msg["cols"])
    
    await asyncio.gather(read_from_container(), write_to_container())
```

### 前端 Terminal 组件
```tsx
// SandboxTerminal.tsx
export function SandboxTerminal({ sandboxId }: Props) {
  const terminalRef = useRef<HTMLDivElement>(null);
  const { terminal, fitAddon } = useXterm();
  const ws = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!terminalRef.current) return;
    terminal.open(terminalRef.current);
    fitAddon.fit();
    
    ws.current = new WebSocket(`ws://localhost:8000/api/v1/terminal/${sandboxId}/ws`);
    ws.current.onmessage = (e) => {
      const msg = JSON.parse(e.data);
      if (msg.type === "output") terminal.write(msg.data);
    };
    
    terminal.onData((data) => {
      ws.current?.send(JSON.stringify({ type: "input", data }));
    });
    
    return () => ws.current?.close();
  }, [sandboxId]);

  return <div ref={terminalRef} className="h-full" />;
}
```

## 验证方法

### 单元测试
```bash
# 后端
uv run pytest src/tests/unit/test_terminal_proxy.py -v

# 前端
cd web && pnpm test -- SandboxTerminal
```

### 集成测试
```bash
# 启动服务
make dev
make sandbox-run

# 手动测试
1. 打开 AgentV3 Chat 页面
2. 发送消息触发 sandbox 工具调用 (如 "读取 /workspace 目录")
3. 验证 SandboxPanel 自动展开
4. 验证 Terminal 可交互输入命令
5. 验证工具输出正确显示
```

### E2E 测试
```bash
cd web && pnpm test:e2e -- sandbox-terminal.spec.ts
```

## 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| WebSocket 断连 | 终端不可用 | 自动重连 + 心跳检测 |
| 容器不存在 | 连接失败 | 前端提示 + 自动创建选项 |
| 大量输出卡顿 | UI 卡死 | 虚拟滚动 + 输出截断 |
| 安全风险 | 未授权访问 | API Key 认证 + 容器隔离 |

## 依赖关系

```
阶段 1 (后端) ──┐
               ├──▶ 阶段 4 (集成)
阶段 2 (前端) ──┤
               │
阶段 3 (状态) ──┘
```

阶段 1-3 可并行开发，阶段 4 依赖前三个阶段完成。
