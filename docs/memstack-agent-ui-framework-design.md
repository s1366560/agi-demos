# memstack-agent-ui 前端框架设计

> 从 MemStack 项目抽取的 Agent Chat 前端框架
> 参考: Vercel AI SDK, assistant-ui, CopilotKit

## 包命名确认

| 包名 | 作用 |
|------|------|
| `@agent-chat/sdk` | 核心包 (框架无关) - 类型、传输、状态管理 |
| `@agent-chat/react` | React 包 - Hooks、组件、Providers |

**API 风格**:
```typescript
import { useAgent, useThreadValue } from '@agent-chat/react'

const { submit, isRunning } = useAgent()
const messages = useThreadValue('messages')
```

## 目录结构

```
memstack-agent-ui/
├── packages/
│   ├── sdk/                    # 核心包 (框架无关)
│   │   ├── src/
│   │   │   ├── types/          # TypeScript 类型定义
│   │   │   │   ├── events.ts   # 事件类型
│   │   │   │   ├── conversation.ts  # 会话类型
│   │   │   │   ├── message.ts  # 消息类型
│   │   │   │   └── index.ts    # 类型导出
│   │   │   ├── client/         # 通信客户端
│   │   │   │   ├── websocket.ts    # WebSocket 客户端
│   │   │   │   ├── sse.ts          # SSE 客户端
│   │   │   │   └── transport.ts     # 传输层抽象
│   │   │   ├── store/          # 状态管理 (Zustand)
│   │   │   │   ├── agent-store.ts      # 主 store
│   │   │   │   ├── conversation-store.ts # 会话状态
│   │   │   │   └── middleware.ts      # 中间件
│   │   │   ├── handlers/       # 事件处理器
│   │   │   │   ├── factory.ts          # 处理器工厂
│   │   │   │   ├── timeline.ts          # Timeline 处理
│   │   │   │   ├── streaming.ts         # 流式处理
│   │   │   │   └── hitl.ts              # HITL 处理
│   │   │   ├── storage/        # 持久化
│   │   │   │   ├── indexeddb.ts         # IndexedDB 实现
│   │   │   │   └── storage-interface.ts # 存储接口
│   │   │   ├── sync/           # 跨 Tab 同步
│   │   │   │   └── broadcast.ts         # BroadcastChannel 实现
│   │   │   ├── utils/          # 工具函数
│   │   │   │   ├── delta.ts             # Delta 批处理
│   │   │   │   ├── lru.ts               # LRU 缓存
│   │   │   │   └── timeline.ts          # Timeline 转换
│   │   │   └── index.ts
│   │   └── package.json
│   │
│   └── react/                  # React 组件包
│       ├── src/
│       │   ├── hooks/          # React Hooks
│       │   │   ├── use-agent-chat.ts      # 主 Hook
│       │   │   ├── use-conversation.ts    # 会话 Hook
│       │   │   ├── use-messages.ts        # 消息 Hook
│       │   │   ├── use-tool-calls.ts      # 工具调用 Hook
│       │   │   └── use-streaming.ts       # 流式状态 Hook
│       │   ├── components/     # UI 组件
│       │   │   ├── chat/                # 聊天组件
│       │   │   │   ├── MessageArea.tsx
│       │   │   │   ├── InputBar.tsx
│       │   │   │   ├── MessageBubble.tsx
│       │   │   │   ├── AssistantMessage.tsx
│       │   │   │   ├── ThinkingBlock.tsx
│       │   │   │   ├── CodeBlock.tsx
│       │   │   │   ├── MarkdownContent.tsx
│       │   │   │   └── SuggestionChips.tsx
│       │   │   ├── execution/           # 执行展示
│       │   │   │   ├── ExecutionTimeline.tsx
│       │   │   │   ├── ToolExecutionLive.tsx
│       │   │   │   └── TimelineEventItem.tsx
│       │   │   ├── hitl/                # HITL 组件
│       │   │   │   ├── ClarificationCard.tsx
│       │   │   │   ├── DecisionCard.tsx
│       │   │   │   ├── EnvVarCard.tsx
│       │   │   │   └── PermissionCard.tsx
│       │   │   ├── status/              # 状态指示
│       │   │   │   ├── AgentStatusBar.tsx
│       │   │   │   └── StreamingIndicator.tsx
│       │   │   └── headless/            # Headless 组件
│       │   │       ├── MessageAreaRoot.tsx
│       │   │       └── InputBarRoot.tsx
│       │   ├── providers/      # Context Providers
│       │   │   ├── AgentProvider.tsx
│       │   │   └── ThemeProvider.tsx
│       │   ├── stores/         # React 专属状态
│       │   │   └── ui-store.ts
│       │   └── index.ts
│       └── package.json
│
├── package.json             # Monorepo root
├── pnpm-workspace.yaml     # PNPM workspace
├── tsconfig.json           # TypeScript 配置
└── turbo.json             # Turborepo 配置
```

## 核心类型定义

### types/events.ts

```typescript
/**
 * Agent 事件类型 (100+ 类型)
 */
export type AgentEventType =
  // 基础消息
  | 'message' | 'text_start' | 'text_delta' | 'text_end'
  // 思考过程
  | 'thought' | 'thought_delta'
  // ReAct 循环
  | 'act' | 'act_delta' | 'observe'
  // HITL
  | 'clarification_asked' | 'clarification_answered'
  | 'decision_asked' | 'decision_answered'
  | 'env_var_requested' | 'env_var_provided'
  | 'permission_asked' | 'permission_replied'
  // 任务系统
  | 'task_list_updated' | 'task_updated'
  | 'task_start' | 'task_complete'
  // Artifact
  | 'artifact_created' | 'artifact_ready' | 'artifact_error'
  // 子 Agent
  | 'sub_agent_routed' | 'sub_agent_started'
  | 'sub_agent_completed' | 'sub_agent_failed'
  // 状态
  | 'complete' | 'error'
  | 'doom_loop_detected' | 'doom_loop_intervened'
  // 成本
  | 'cost_update'
  // 工作流
  | 'skill_matched' | 'skill_execution_start'
  | 'reflection_complete';

/**
 * 基础事件接口
 */
export interface BaseAgentEvent<T = unknown> {
  type: AgentEventType;
  conversation_id?: string;
  data?: T;
  event_time_us?: number;
  event_counter?: number;
  timestamp?: string;
}

/**
 * 事件数据类型
 */
export interface EventData {
  // 消息
  MessageEventData: { content: string; message_id: string };
  TextDeltaEventData: { delta: string };
  // 思考
  ThoughtEventData: { thought: string };
  ThoughtDeltaEventData: { delta: string };
  // ReAct
  ActEventData: { tool_name: string; tool_input: Record<string, unknown> };
  ActDeltaEventData: { tool_name: string; accumulated_arguments: Record<string, unknown> };
  ObserveEventData: { tool_name: string; result?: string; error?: string };
  // HITL
  ClarificationAskedEventData: { request_id: string; question: string };
  DecisionAskedEventData: { request_id: string; question: string; options?: string[] };
  EnvVarRequestedEventData: { request_id: string; var_name: string };
  PermissionAskedEventData: { request_id: string; tool_name: string; reason: string };
  // 任务
  TaskListUpdatedEventData: { tasks: AgentTask[] };
  TaskUpdatedEventData: { task_id: string; status: TaskStatus };
  // 状态
  CompleteEventData: { content: string };
  ErrorEventData: { message: string; code?: string };
  // 成本
  CostUpdateEventData: {
    input_tokens: number;
    output_tokens: number;
    total_tokens: number;
    cost_usd: number;
    model: string;
  };
}
```

### types/conversation.ts

```typescript
/**
 * 会话状态
 */
export type ConversationStatus = 'active' | 'archived' | 'deleted';

/**
 * Agent 执行状态
 */
export type AgentState =
  | 'idle'
  | 'thinking'
  | 'preparing'
  | 'acting'
  | 'observing'
  | 'awaiting_input'
  | 'retrying';

/**
 * 流式状态
 */
export type StreamStatus = 'idle' | 'connecting' | 'streaming' | 'error';

/**
 * 会话内部状态 (per-conversation isolation)
 */
export interface ConversationState {
  // Timeline & Messages
  timeline: TimelineEvent[];
  hasEarlier: boolean;
  earliestTimeUs: number | null;
  earliestCounter: number | null;

  // Streaming State
  isStreaming: boolean;
  streamStatus: StreamStatus;
  streamingAssistantContent: string;
  error: string | null;

  // Agent Execution State
  agentState: AgentState;
  currentThought: string;
  streamingThought: string;
  isThinkingStreaming: boolean;
  activeToolCalls: Map<string, ToolCallWithStatus>;
  pendingToolsStack: string[];

  // HITL State
  pendingClarification: ClarificationAskedEventData | null;
  pendingDecision: DecisionAskedEventData | null;
  pendingEnvVarRequest: EnvVarRequestedEventData | null;
  pendingPermission: PermissionAskedEventData | null;
  doomLoopDetected: DoomLoopDetectedEventData | null;

  // Tasks
  tasks: AgentTask[];

  // Cost Tracking
  costTracking: CostTrackingState | null;

  // Suggestions
  suggestions: string[];

  // Metadata
  lastAccessed: number;
}

/**
 * 工具调用状态
 */
export interface ToolCallWithStatus {
  name: string;
  arguments: Record<string, unknown>;
  status: 'preparing' | 'running' | 'success' | 'failed';
  startTime: number;
  partialArguments?: string;
}
```

### types/message.ts

```typescript
/**
 * 消息角色
 */
export type MessageRole = 'user' | 'assistant' | 'system';

/**
 * 消息类型
 */
export type MessageType =
  | 'text'
  | 'thought'
  | 'tool_call'
  | 'tool_result'
  | 'error'
  | 'user_message'
  | 'assistant_message'
  | 'hitl_card';

/**
 * 基础消息接口
 */
export interface BaseMessage {
  id: string;
  conversation_id: string;
  role: MessageRole;
  type: MessageType;
  content: string;
  created_at: string;
  eventTimeUs?: number;
  eventCounter?: number;
}

/**
 * 用户消息
 */
export interface UserMessage extends BaseMessage {
  role: 'user';
  type: 'user_message';
  attachments?: FileMetadata[];
}

/**
 * 助手消息 (包含思考、工具调用)
 */
export interface AssistantMessage extends BaseMessage {
  role: 'assistant';
  type: 'assistant_message';
  thought?: string;
  toolCalls?: ToolCall[];
}

/**
 * HITL 卡片消息
 */
export interface HITLCardMessage extends BaseMessage {
  type: 'hitl_card';
  hitlType: 'clarification' | 'decision' | 'env_var' | 'permission';
  requestId: string;
  question: string;
  options?: string[];
  answered: boolean;
}

/**
 * 消息联合类型
 */
export type Message = UserMessage | AssistantMessage | HITLCardMessage;
```

## 核心 API 设计

### SDK 包 - 核心接口

```typescript
// packages/sdk/src/client/transport.ts

/**
 * 传输层接口
 * 支持 WebSocket 和 SSE 两种传输方式
 */
export interface AgentTransport {
  /**
   * 连接到服务器
   */
  connect(): Promise<void>;

  /**
   * 断开连接
   */
  disconnect(): void;

  /**
   * 发送消息
   */
  send(data: unknown): void;

  /**
   * 订阅会话事件
   */
  subscribe(conversationId: string, handler: EventHandler): void;

  /**
   * 取消订阅
   */
  unsubscribe(conversationId: string): void;

  /**
   * 获取连接状态
   */
  getStatus(): TransportStatus;

  /**
   * 监听状态变化
   */
  onStatusChange(callback: (status: TransportStatus) => void): void;
}

export type TransportStatus =
  | 'disconnected'
  | 'connecting'
  | 'connected'
  | 'error';

/**
 * 事件处理器接口
 */
export interface EventHandler {
  onMessage?(event: AgentEvent<'message'>): void;
  onTextDelta?(event: AgentEvent<'text_delta'>): void;
  onThought?(event: AgentEvent<'thought'>): void;
  onThoughtDelta?(event: AgentEvent<'thought_delta'>): void;
  onAct?(event: AgentEvent<'act'>): void;
  onObserve?(event: AgentEvent<'observe'>): void;
  onComplete?(event: AgentEvent<'complete'>): void;
  onError?(event: AgentEvent<'error'>): void;
  // ... 更多事件类型
}
```

### React 包 - Hooks API

```typescript
// packages/react/src/hooks/use-agent-chat.ts

/**
 * useAgentChat 核心参数
 */
export interface UseAgentChatOptions {
  /**
   * 项目 ID
   */
  projectId: string;

  /**
   * 初始会话 ID
   */
  initialConversationId?: string;

  /**
   * 自定义传输层
   */
  transport?: AgentTransport;

  /**
   * 自动加载会话列表
   */
  autoLoadConversations?: boolean;
}

/**
 * useAgentChat 返回值
 */
export interface UseAgentChatReturn {
  // === 会话 ===
  conversations: Conversation[];
  activeConversationId: string | null;
  setActiveConversation: (id: string | null) => void;
  createConversation: (title?: string) => Promise<void>;
  deleteConversation: (id: string) => Promise<void>;
  renameConversation: (id: string, title: string) => Promise<void>;

  // === 消息 ===
  messages: Message[];
  isStreaming: boolean;
  sendMessage: (content: string, attachments?: FileMetadata[]) => Promise<void>;
  abortStream: () => void;

  // === 状态 ===
  agentState: AgentState;
  currentThought: string;
  streamingThought: string;
  activeToolCalls: Map<string, ToolCallWithStatus>;
  tasks: AgentTask[];

  // === HITL ===
  pendingClarification: ClarificationAskedEventData | null;
  pendingDecision: DecisionAskedEventData | null;
  respondToClarification: (requestId: string, answer: string) => Promise<void>;
  respondToDecision: (requestId: string, answer: string) => Promise<void>;

  // === 加载状态 ===
  isLoadingConversations: boolean;
  isLoadingMessages: boolean;
  error: string | null;
}

/**
 * 主 Hook - 提供 Agent Chat 完整功能
 */
export function useAgentChat(
  options: UseAgentChatOptions
): UseAgentChatReturn;
```

## Delta 批处理

```typescript
// packages/sdk/src/utils/delta.ts

/**
 * Delta 缓冲状态
 */
export interface DeltaBufferState {
  textDeltaBuffer: string;
  textDeltaFlushTimer: ReturnType<typeof setTimeout> | null;
  thoughtDeltaBuffer: string;
  thoughtDeltaFlushTimer: ReturnType<typeof setTimeout> | null;
  actDeltaBuffer: ActDeltaEventData | null;
  actDeltaFlushTimer: ReturnType<typeof setTimeout> | null;
}

/**
 * Delta 管理器
 */
export class DeltaManager {
  private buffers = new Map<string, DeltaBufferState>();
  private config: Required<DeltaConfig>;

  constructor(config: DeltaConfig) {
    this.config = {
      textInterval: config.textInterval ?? 50,
      thoughtInterval: config.thoughtInterval ?? 50,
      actInterval: config.actInterval ?? 50,
    };
  }

  /**
   * 获取或创建缓冲区
   */
  getBuffer(conversationId: string): DeltaBufferState { /* ... */ }

  /**
   * 清除缓冲区
   */
  clearBuffer(conversationId: string): void { /* ... */ }

  /**
   * 添加文本 Delta
   */
  addTextDelta(
    conversationId: string,
    delta: string,
    onFlush: (content: string) => void
  ): void { /* ... */ }

  /**
   * 添加思考 Delta
   */
  addThoughtDelta(
    conversationId: string,
    delta: string,
    onFlush: (content: string) => void
  ): void { /* ... */ }

  /**
   * 添加 Act Delta
   */
  addActDelta(
    conversationId: string,
    delta: ActDeltaEventData,
    onFlush: (data: ActDeltaEventData) => void
  ): void { /* ... */ }
}
```

## LRU 缓存

```typescript
// packages/sdk/src/utils/lru.ts

/**
 * LRU 缓存管理器
 */
export class LRUManager<T> {
  private cache = new Map<string, T>();
  private accessOrder: string[] = [];
  private readonly maxSize: number;

  constructor(maxSize: number = 10) {
    this.maxSize = maxSize;
  }

  /**
   * 获取项目并更新访问顺序
   */
  get(key: string): T | undefined { /* ... */ }

  /**
   * 设置项目
   */
  set(key: string, value: T): void { /* ... */ }

  /**
   * 删除项目
   */
  delete(key: string): boolean { /* ... */ }

  /**
   * 淘汰最久未使用项目
   */
  private evict(): void { /* ... */ }

  /**
   * 清空缓存
   */
  clear(): void { /* ... */ }
}
```

## IndexedDB 持久化

```typescript
// packages/sdk/src/storage/indexeddb.ts

/**
 * 存储接口
 */
export interface StorageAdapter {
  get(key: string): Promise<unknown>;
  set(key: string, value: unknown): Promise<void>;
  delete(key: string): Promise<void>;
  clear(): Promise<void>;
}

/**
 * IndexedDB 实现
 */
export class IndexedDBStorage implements StorageAdapter {
  private db: IDBDatabase | null = null;
  private readonly dbName: string;
  private readonly storeName: string;
  private readonly version: number;

  constructor(
    dbName = 'memstack-agent',
    storeName = 'conversation-states',
    version = 1
  ) {
    this.dbName = dbName;
    this.storeName = storeName;
    this.version = version;
  }

  /**
   * 初始化数据库连接
   */
  async connect(): Promise<void> { /* ... */ }

  async get(key: string): Promise<ConversationState | undefined> { /* ... */ }
  async set(key: string, value: ConversationState): Promise<void> { /* ... */ }
  async delete(key: string): Promise<void> { /* ... */ }
  async clear(): Promise<void> { /* ... */ }
}
```

## 跨 Tab 同步

```typescript
// packages/sdk/src/sync/broadcast.ts

/**
 * 同步消息类型
 */
export type TabSyncMessageType =
  | 'user_message_sent'
  | 'streaming_state_changed'
  | 'conversation_completed'
  | 'hitl_state_changed'
  | 'conversation_deleted'
  | 'conversation_renamed'
  | 'request_sync'
  | 'sync_response';

/**
 * 同步管理器
 */
export class TabSyncManager {
  private channel: BroadcastChannel;
  private senderId: string;
  private handlers: Map<TabSyncMessageType, Set<MessageHandler>>;

  constructor(channelName = 'memstack-agent-sync') {
    this.channel = new BroadcastChannel(channelName);
    this.senderId = crypto.randomUUID();
    this.handlers = new Map();

    this.channel.onmessage = (event) => {
      this.handleMessage(event.data);
    };
  }

  /**
   * 注册消息处理器
   */
  on(type: TabSyncMessageType, handler: MessageHandler): void { /* ... */ }

  /**
   * 移除消息处理器
   */
  off(type: TabSyncMessageType, handler: MessageHandler): void { /* ... */ }

  /**
   * 广播消息
   */
  broadcast(message: Omit<TabSyncMessage, 'senderId' | 'timestamp'>): void { /* ... */ }
}
```

## 与现有代码映射

### 现有 → 框架

| 现有文件 | 框架位置 |
|---------|----------|
| `web/src/types/agent.ts` | `packages/sdk/src/types/` |
| `web/src/types/conversationState.ts` | `packages/sdk/src/types/conversation.ts` |
| `web/src/stores/agentV3.ts` | `packages/sdk/src/store/agent-store.ts` |
| `web/src/stores/agent/streamEventHandlers.ts` | `packages/sdk/src/handlers/` |
| `web/src/services/agentService.ts` | `packages/sdk/src/client/websocket.ts` |
| `web/src/utils/conversationDB.ts` | `packages/sdk/src/storage/indexeddb.ts` |
| `web/src/utils/tabSync.ts` | `packages/sdk/src/sync/broadcast.ts` |
| `web/src/components/agent/` | `packages/react/src/components/` |

## 重构计划

1. **阶段 1**: 核心类型 + 传输层
   - 提取 `types/` 到 `packages/sdk/src/types/`
   - 实现 `WebSocketTransport` 和 `SSETransport`

2. **阶段 2**: 状态管理 + 事件处理
   - 实现 `AgentStore`
   - 提取 `streamEventHandlers.ts` 到 `handlers/`
   - Delta 批处理工具

3. **阶段 3**: 持久化 + 同步
   - 实现 `IndexedDBStorage`
   - 实现 `TabSyncManager`
   - LRU 缓存

4. **阶段 4**: React Hooks
   - `useAgentChat`
   - `useConversation`
   - `useStreaming`

5. **阶段 5**: React 组件
   - Headless 组件
   - Styled 组件

## 使用示例

### 基础使用

```tsx
// App.tsx
import { AgentProvider, useAgentChat } from '@agent-chat/react';
import { MessageArea, InputBar } from '@agent-chat/react';

function ChatPage() {
  const {
    messages,
    isStreaming,
    sendMessage,
    agentState,
  } = useAgentChat({
    projectId: 'proj-123',
    autoLoadConversations: true,
  });

  return (
    <div className="flex h-screen flex-col">
      <div className="flex-1 overflow-y-auto">
        <MessageArea />
      </div>
      <div className="border-t p-4">
        <InputBar onSend={sendMessage} disabled={isStreaming} />
      </div>
    </div>
  );
}

function App() {
  return (
    <AgentProvider>
      <ChatPage />
    </AgentProvider>
  );
}
```

### Headless 模式

```tsx
import { MessageAreaRoot } from '@agent-chat/react';

function CustomMessageArea() {
  return (
    <MessageAreaRoot>
      {(state) => (
        <div className="custom-messages">
          {state.messages.map((msg) => (
            <div key={msg.id} className={msg.role}>
              {msg.content}
            </div>
          ))}
          {state.hasEarlier && (
            <button onClick={state.onLoadEarlier}>Load More</button>
          )}
          {state.isStreaming && (
            <div className="streaming-indicator">Thinking...</div>
          )}
        </div>
      )}
    </MessageAreaRoot>
  );
}
```
