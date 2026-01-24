# SSE会话切换优化方案

## 问题概述

当多个Agent在AgentWorker中并行执行时，前端切换会话存在以下问题：
1. **旧SSE连接未关闭** - 切换会话时旧连接继续运行
2. **事件混淆** - 旧会话的SSE事件可能被错误处理  
3. **状态竞速** - 快速切换时可能导致消息混乱

---

## 架构优化方案对比

### 方案对比表

| 维度 | 方案A: 修复当前SSE | 方案B: SSE多路复用 | 方案C: WebSocket替代 |
|------|-------------------|-------------------|---------------------|
| **改造成本** | ~1天 | ~1天 | 2-3周 |
| **连接数** | N个/用户 | 1个/用户 | 1个/用户 |
| **中止信号** | ❌ 无法主动发送 | ❌ 无法主动发送 | ✅ 实时双向 |
| **会话切换延迟** | ~200ms | <10ms | <10ms |
| **浏览器连接限制** | 受限(6个/域) | 突破限制 | 突破限制 |
| **实现复杂度** | 低 | 中 | 高 |
| **长期维护** | 持续痛点 | 中等 | 最优 |

### 方案A: 修复当前SSE架构（短期推荐）

**适用场景**: 快速修复，立即解决会话切换问题

**修改内容**:
1. `setCurrentConversation()` 中添加 `stopChat()` 调用
2. handler中添加会话有效性验证
3. `useAgentChat` hook添加cleanup effect

**优点**: 改动小，风险低，当天可完成
**缺点**: 不解决根本架构问题（每次消息新建连接）

---

### 方案B: SSE单连接多路复用（中期方案）

**核心思路**: 一个SSE连接订阅多个会话，通过Redis PSUBSCRIBE实现

```
当前架构：                          改造后：
User Browser                       User Browser
  ├─ SSE(conv-1)                     └─ SSE(unified)
  ├─ SSE(conv-2)         →              └─ PSUBSCRIBE agent:stream:*
  └─ SSE(conv-3)                           ├─ conv-1 events
                                           ├─ conv-2 events
                                           └─ conv-3 events
```

**实现要点**:
1. **Redis**: 使用PSUBSCRIBE订阅模式 `agent:stream:*`
2. **后端**: 新增 `/chat/unified` endpoint
3. **前端**: 事件路由器根据`_channel`字段分发

**改造文件**:
- `src/infrastructure/adapters/secondary/event/redis_event_bus.py` - 添加`subscribe_pattern()`
- `src/infrastructure/adapters/primary/web/routers/agent.py` - 新增unified endpoint
- `web/src/services/agentService.ts` - 事件路由器

**优点**: 
- 减少90%连接数
- 会话切换无延迟
- 兼容现有架构

**缺点**:
- 仍无法主动发送中止信号
- 单连接故障影响所有会话

**预估工时**: 5-7小时

---

### 方案C: WebSocket替代（长期最优）

**核心优势**: 双向通信，真正解决所有痛点

```typescript
// WebSocket消息协议
{ type: 'send_message', conversation_id: 'conv-123', message: '...' }
{ type: 'stop_session', conversation_id: 'conv-123' }  // ✅ 主动中止
{ type: 'heartbeat' }
```

**收益量化**:
| 指标 | 当前SSE | WebSocket | 改进 |
|------|---------|-----------|------|
| 中止响应延迟 | 需新连接(200ms+) | 立即(50ms) | **75%↓** |
| 多会话切换 | 重建连接(200ms) | 消息切换(<10ms) | **95%↓** |
| 浏览器连接数 | 6个/域限制 | 无限制 | **突破限制** |

**挑战与解决**:
| 挑战 | 解决方案 |
|------|---------|
| 负载均衡Sticky Session | Redis会话存储（现有架构支持） |
| 重连机制 | 前端已有实现(`websocketService.ts`) |
| Temporal集成 | 进度状态存Redis，WebSocket推送 |

**预估工时**: 2-3周

---

## 推荐实施路径

**用户选择**: 方案C - WebSocket替代SSE

---

## WebSocket架构设计

### 1. 消息协议设计

```typescript
// 客户端 → 服务端
interface ClientMessage {
  type: 'send_message' | 'stop_session' | 'subscribe' | 'unsubscribe' | 'heartbeat';
  conversation_id?: string;
  project_id?: string;
  message?: string;
  timestamp: number;
}

// 服务端 → 客户端
interface ServerMessage {
  type: 'message' | 'thought' | 'text_delta' | 'tool_call' | 'work_plan' | 
        'step_start' | 'step_end' | 'error' | 'complete' | 'ack' | 'pong';
  conversation_id: string;
  data: any;
  seq: number;  // 序列号，用于重放
}
```

### 2. 核心功能

| 功能 | 客户端消息 | 服务端响应 |
|------|-----------|-----------|
| **发送消息** | `{type:'send_message', conversation_id, message}` | 启动Agent工作流 |
| **中止执行** | `{type:'stop_session', conversation_id}` | 中止Temporal工作流 |
| **订阅会话** | `{type:'subscribe', conversation_id}` | 开始推送该会话事件 |
| **取消订阅** | `{type:'unsubscribe', conversation_id}` | 停止推送该会话事件 |
| **心跳** | `{type:'heartbeat'}` | `{type:'pong'}` |

### 3. 连接生命周期

```
[连接建立] → [认证] → [就绪] → [活跃] → [关闭]
     ↓          ↓         ↓        ↓
   握手      JWT验证   可订阅会话  收发消息   释放资源
```

---

## 实施计划

### Phase 1: 基础WebSocket路由 (Week 1)

**后端实现**:

**新建文件**: `src/infrastructure/adapters/primary/web/routers/websocket.py`

```python
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from src.infrastructure.adapters.primary.web.dependencies import get_current_user_ws

router = APIRouter()

class ConnectionManager:
    """管理WebSocket连接"""
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}  # user_id -> websocket
        self.subscriptions: Dict[str, Set[str]] = {}  # user_id -> conversation_ids
    
    async def connect(self, user_id: str, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[user_id] = websocket
        self.subscriptions[user_id] = set()
    
    def disconnect(self, user_id: str):
        self.active_connections.pop(user_id, None)
        self.subscriptions.pop(user_id, None)
    
    async def send_to_user(self, user_id: str, message: dict):
        if ws := self.active_connections.get(user_id):
            await ws.send_json(message)

manager = ConnectionManager()

@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str = Query(...),
):
    user = await authenticate_websocket(token)
    await manager.connect(user.id, websocket)
    
    try:
        while True:
            data = await websocket.receive_json()
            await handle_message(user.id, data)
    except WebSocketDisconnect:
        manager.disconnect(user.id)
```

**修改文件**: `src/infrastructure/adapters/primary/web/main.py`
- 注册WebSocket路由

### Phase 2: 消息处理与Agent集成 (Week 1-2)

**新建文件**: `src/infrastructure/adapters/primary/web/websocket/handlers.py`

```python
async def handle_message(user_id: str, message: dict):
    msg_type = message.get('type')
    
    if msg_type == 'send_message':
        await handle_send_message(user_id, message)
    elif msg_type == 'stop_session':
        await handle_stop_session(user_id, message)
    elif msg_type == 'subscribe':
        await handle_subscribe(user_id, message)
    elif msg_type == 'heartbeat':
        await manager.send_to_user(user_id, {'type': 'pong'})

async def handle_send_message(user_id: str, message: dict):
    conversation_id = message['conversation_id']
    
    # 验证权限
    # 启动Temporal工作流
    # 自动订阅该会话
    manager.subscriptions[user_id].add(conversation_id)
    
async def handle_stop_session(user_id: str, message: dict):
    conversation_id = message['conversation_id']
    
    # 取消Temporal工作流
    await temporal_client.cancel_workflow(
        workflow_id=f"agent-execution-{conversation_id}-*"
    )
    
    # 发送确认
    await manager.send_to_user(user_id, {
        'type': 'ack',
        'conversation_id': conversation_id,
        'action': 'stopped'
    })
```

### Phase 3: Redis事件桥接 (Week 2)

**修改文件**: `src/application/services/agent_service.py`

```python
class WebSocketEventBridge:
    """将Redis事件桥接到WebSocket"""
    
    async def start_bridge(self, user_id: str, conversation_id: str):
        channel = f"agent:stream:{conversation_id}"
        
        async for event in self._event_bus.subscribe(channel):
            # 检查用户是否仍订阅该会话
            if conversation_id not in manager.subscriptions.get(user_id, set()):
                break
            
            # 转发到WebSocket
            await manager.send_to_user(user_id, {
                'type': event['type'],
                'conversation_id': conversation_id,
                'data': event['data'],
                'seq': event['seq']
            })
```

### Phase 4: 前端适配 (Week 2-3)

**修改文件**: `web/src/services/agentService.ts`

```typescript
class AgentWebSocketService {
  private ws: WebSocket | null = null;
  private handlers: Map<string, AgentStreamHandler> = new Map();
  private reconnectAttempts = 0;
  
  connect(token: string): Promise<void> {
    return new Promise((resolve, reject) => {
      const url = `${WS_BASE_URL}/ws?token=${token}`;
      this.ws = new WebSocket(url);
      
      this.ws.onopen = () => {
        this.reconnectAttempts = 0;
        resolve();
      };
      
      this.ws.onmessage = (event) => {
        const message = JSON.parse(event.data);
        this.routeMessage(message);
      };
      
      this.ws.onclose = () => this.handleReconnect();
    });
  }
  
  sendMessage(conversationId: string, message: string): void {
    this.ws?.send(JSON.stringify({
      type: 'send_message',
      conversation_id: conversationId,
      message,
      timestamp: Date.now()
    }));
  }
  
  stopSession(conversationId: string): void {
    this.ws?.send(JSON.stringify({
      type: 'stop_session',
      conversation_id: conversationId,
      timestamp: Date.now()
    }));
  }
  
  private routeMessage(message: ServerMessage): void {
    const handler = this.handlers.get(message.conversation_id);
    if (!handler) return;
    
    switch (message.type) {
      case 'text_delta':
        handler.onTextDelta?.(message);
        break;
      case 'thought':
        handler.onThought?.(message);
        break;
      // ... 其他事件类型
    }
  }
}
```

**修改文件**: `web/src/stores/agent.ts`
- 替换SSE调用为WebSocket调用
- 简化handler逻辑（WebSocket服务层已做路由）

### Phase 5: 测试与优化 (Week 3)

**测试用例**:
1. 连接建立和认证
2. 发送消息并接收流式响应
3. 中止执行（验证Temporal工作流被取消）
4. 会话切换（验证事件正确路由）
5. 断线重连
6. 并发多会话

---

## 修改文件清单

| 文件 | 操作 | 内容 |
|------|------|------|
| `src/infrastructure/adapters/primary/web/routers/websocket.py` | 新建 | WebSocket路由和ConnectionManager |
| `src/infrastructure/adapters/primary/web/websocket/handlers.py` | 新建 | 消息处理器 |
| `src/infrastructure/adapters/primary/web/websocket/bridge.py` | 新建 | Redis→WebSocket事件桥接 |
| `src/infrastructure/adapters/primary/web/main.py` | 修改 | 注册WebSocket路由 |
| `src/application/services/agent_service.py` | 修改 | 添加WebSocket事件发送 |
| `web/src/services/agentService.ts` | 重构 | WebSocket客户端实现 |
| `web/src/stores/agent.ts` | 修改 | 使用WebSocket服务 |
| `web/src/hooks/useAgentChat.ts` | 修改 | 连接生命周期管理 |

---

## SSE代码移除清单

WebSocket实现完成后，彻底移除SSE相关代码：

**后端移除**:
| 文件 | 操作 |
|------|------|
| `src/infrastructure/adapters/primary/web/routers/agent.py` | 移除 `chat()` SSE endpoint |
| `src/application/services/agent_service.py` | 移除 `stream_chat_v2()`, `connect_chat_stream()` |
| `pyproject.toml` | 移除 `sse-starlette` 依赖 |

**前端移除**:
| 文件 | 操作 |
|------|------|
| `web/src/services/agentService.ts` | 移除 `chat()`, `chatWithStream()`, `stopChat()` SSE方法 |
| `web/src/services/agentService.ts` | 移除 `streamStates` Map |
| `web/src/types/agent.ts` | 移除 SSE 相关类型定义（如有） |

---

## 验证方法

1. **连接测试**: 
   - 打开浏览器DevTools Network面板
   - 确认WebSocket连接建立（Status 101）
   - 检查心跳消息正常

2. **消息测试**:
   - 发送消息，验证Agent响应流式到达
   - 点击停止按钮，验证立即中止（<100ms）

3. **会话切换测试**:
   - 同时打开多个会话
   - 快速切换，验证事件正确路由
   - 无消息混乱或丢失

4. **重连测试**:
   - 手动断开网络，验证自动重连
   - 重连后验证会话状态恢复

5. **SSE移除验证**:
   - 确认无 `/api/v1/agent/chat` POST端点
   - 确认前端无EventSource或fetch流式调用
   - 运行 `grep -r "sse-starlette\|EventSource\|streamStates" --include="*.py" --include="*.ts"` 确认无残留

## 当前架构分析

### 后端（AgentWorker）- 设计良好 ✅

```
AgentWorker (Temporal Worker)
├── 支持50个并发工作流
├── 每个消息独立工作流ID: agent-execution-{conv_id}-{msg_id}
├── Redis频道隔离: agent:stream:{conversation_id}
└── PostgreSQL事件持久化 + 重放机制
```

**后端无需修改**：
- 每个会话的SSE流通过独立的Redis频道广播
- 后端已检测客户端断开: `await http_request.is_disconnected()`
- 工作流支持检查点和自动恢复
- `stopChat()` 已实现 `reader.cancel()` (agentService.ts:131-145)

### 前端 - 存在关键问题 ❌

**问题1: setCurrentConversation未停止旧SSE** (`web/src/stores/agent.ts:358-427`)
```typescript
setCurrentConversation: (conversation) => {
  // ❌ 只清空UI状态，没有停止旧SSE连接
  set({
    currentConversation: conversation,
    messages: [],
    // ...清空执行状态...
  });
}
```

**问题2: handler闭包捕获过时conversationId** (`web/src/stores/agent.ts:640+`)
```typescript
const handler: AgentStreamHandler = {
  onComplete: async (event) => {
    // ❌ conversationId是闭包捕获的，用户切换后仍指向旧会话
    const assistantMessage = {
      conversation_id: conversationId, // 可能已过时
    };
    get().addMessage(assistantMessage);
  }
};
```

**问题3: 缺少会话有效性验证**
- handler未检查事件是否属于当前活跃会话
- 可能将旧会话的消息错误更新到UI

---

## 实施方案

### 方案1: setCurrentConversation中停止旧SSE [P0]

**文件**: `web/src/stores/agent.ts:358-427`

**修改位置**: 在`setCurrentConversation`函数开头，防御性检查之前

```typescript
setCurrentConversation: (
  conversation: Conversation | null,
  skipLoadMessages = false
) => {
  const { currentConversation: current, isNewConversationPending } = get();

  // ✅ 新增: 切换会话时停止旧SSE连接
  if (current && current.id !== conversation?.id) {
    console.log('[Agent] Switching conversation, stopping old SSE:', current.id);
    agentService.stopChat(current.id);
  }

  // 防御性检查: 跳过相同会话 (保持原有逻辑)
  if (
    conversation &&
    current?.id === conversation.id &&
    !isNewConversationPending &&
    !skipLoadMessages
  ) {
    return;
  }

  // ... 原有清理逻辑保持不变
};
```

### 方案2: handler中验证会话有效性 [P0]

**文件**: `web/src/stores/agent.ts` (sendMessage函数内的handler)

**实现方式**: 提取验证函数，在每个handler开头调用

```typescript
// 在sendMessage函数内，handler定义之前添加验证函数
const shouldProcessEvent = (eventName: string): boolean => {
  const latestConversation = get().currentConversation;
  if (!latestConversation || latestConversation.id !== conversationId) {
    console.warn(
      `[Agent] Ignoring ${eventName} event for stale conversation ${conversationId}, ` +
      `current is ${latestConversation?.id}`
    );
    return false;
  }
  return true;
};

const handler: AgentStreamHandler = {
  onThought: (event) => {
    if (!shouldProcessEvent('thought')) return;  // ✅ 验证
    // ... 原有逻辑
  },
  onTextDelta: (event) => {
    if (!shouldProcessEvent('text_delta')) return;  // ✅ 验证
    // ... 原有逻辑
  },
  // ... 其他handler同理
};
```

**需要添加验证的handler** (共15个):
- onMessage, onThought, onWorkPlan, onPatternMatch
- onStepStart, onStepEnd, onAct, onObserve
- onTextStart, onTextDelta, onTextEnd
- onClarificationAsked, onDecisionAsked, onDoomLoopDetected
- Skill相关handlers

### 方案3: useAgentChat组件卸载清理 [P1]

**文件**: `web/src/hooks/useAgentChat.ts`

**实现位置**: 添加新的useEffect（建议在第112行后）

```typescript
// Cleanup effect: Stop SSE when component unmounts
useEffect(() => {
  const currentConvId = currentConversation?.id;
  
  return () => {
    // Cleanup function - runs when:
    // 1. Component unmounts (route change)
    // 2. currentConversation.id changes (conversation switch)
    if (currentConvId) {
      console.log('[useAgentChat] Cleanup: stopping SSE for', currentConvId);
      stopChat(currentConvId);
    }
  };
}, [currentConversation?.id, stopChat]);
```

---

## 修改文件清单

| 文件 | 修改内容 | 行数 | 优先级 |
|------|---------|------|-------|
| `web/src/stores/agent.ts` | setCurrentConversation添加stopChat | ~5行 | P0 |
| `web/src/stores/agent.ts` | 15个handler添加验证 | ~50行 | P0 |
| `web/src/hooks/useAgentChat.ts` | 添加cleanup useEffect | ~10行 | P1 |

---

## 验证场景

### 场景1: 快速切换会话
1. 用户在会话A发送消息，SSE开始流式响应
2. 2秒后用户点击会话B（SSE仍在streaming）
3. **预期**: 会话A的SSE立即停止，UI显示会话B内容

### 场景2: 多Agent并行执行
1. 打开3个浏览器标签页，同一项目的不同会话
2. 几乎同时在3个会话发送消息
3. **预期**: 3个Agent独立运行，事件不互相干扰

### 场景3: 组件卸载（路由切换）
1. 用户在AgentChat页面，会话A正在streaming
2. 用户点击导航栏切换到MemoryList页面
3. **预期**: SSE连接被关闭，无资源泄漏

---

## 验证方法

1. 启动服务：`make dev` + `make dev-web`
2. 打开两个会话，在会话A发送长文本生成请求
3. 在SSE流式传输过程中切换到会话B
4. 验证：
   - Console日志显示 `[Agent] Switching conversation, stopping old SSE: xxx`
   - 会话B的消息列表正确显示
   - Network面板无持续的SSE连接（会话A）
   - 切回会话A时，消息完整（通过历史消息API加载）
5. 检查内存泄漏：Chrome DevTools > Memory > Heap snapshot
