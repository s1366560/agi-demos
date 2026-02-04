# 前端集成指南

本文档说明如何在前端集成 HITL 功能。

## 组件层级

```
ChatInterface
├── MessageList
│   └── MessageBubble
│       └── InlineHITLCard (历史 HITL 渲染)
└── UnifiedHITLPanel (当前 HITL 请求)
    └── HITLRequestCard
```

## 核心组件

### UnifiedHITLPanel

统一的 HITL 请求面板，显示当前待处理的请求：

```tsx
// web/src/components/agent/UnifiedHITLPanel.tsx

interface UnifiedHITLPanelProps {
  conversationId: string;
  projectId: string;
}

const UnifiedHITLPanel: React.FC<UnifiedHITLPanelProps> = ({
  conversationId,
  projectId,
}) => {
  const {
    currentRequest,
    isLoading,
    error,
    submitResponse,
    cancelRequest,
  } = useHITLStore(
    useShallow((state) => ({
      currentRequest: state.currentRequest,
      isLoading: state.isLoading,
      error: state.error,
      submitResponse: state.submitResponse,
      cancelRequest: state.cancelRequest,
    }))
  );

  if (!currentRequest) return null;

  const handleSubmit = async (response: any) => {
    await submitResponse(currentRequest.id, response);
  };

  return (
    <div className="hitl-panel">
      {currentRequest.type === 'clarification' && (
        <ClarificationCard
          request={currentRequest}
          onSubmit={handleSubmit}
          onCancel={cancelRequest}
        />
      )}
      {currentRequest.type === 'decision' && (
        <DecisionCard
          request={currentRequest}
          onSubmit={handleSubmit}
          onCancel={cancelRequest}
        />
      )}
      {currentRequest.type === 'env_var' && (
        <EnvVarCard
          request={currentRequest}
          onSubmit={handleSubmit}
          onCancel={cancelRequest}
        />
      )}
      {currentRequest.type === 'permission' && (
        <PermissionCard
          request={currentRequest}
          onSubmit={handleSubmit}
          onCancel={cancelRequest}
        />
      )}
    </div>
  );
};
```

### InlineHITLCard

历史消息中的 HITL 卡片：

```tsx
// web/src/components/agent/InlineHITLCard.tsx

interface InlineHITLCardProps {
  requestId: string;
  type: HITLType;
  data: HITLRequestData;
  answered: boolean;
  decision?: string;
  timestamp: string;
}

const InlineHITLCard: React.FC<InlineHITLCardProps> = ({
  requestId,
  type,
  data,
  answered,
  decision,
  timestamp,
}) => {
  const [isSubmitting, setIsSubmitting] = useState(false);
  const { submitResponse } = useHITLStore(
    useShallow((state) => ({ submitResponse: state.submitResponse }))
  );

  // 如果已回答，显示只读状态
  if (answered) {
    return (
      <AnsweredHITLCard
        type={type}
        data={data}
        decision={decision}
        timestamp={timestamp}
      />
    );
  }

  // 未回答，显示交互式卡片
  const handleSubmit = async (response: any) => {
    setIsSubmitting(true);
    try {
      await submitResponse(requestId, response);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <PendingHITLCard
      type={type}
      data={data}
      onSubmit={handleSubmit}
      isSubmitting={isSubmitting}
    />
  );
};
```

## Zustand Store

### hitlStore.unified.ts

```typescript
// web/src/stores/hitlStore.unified.ts

import { create } from 'zustand';

interface HITLState {
  // 当前待处理的请求
  currentRequest: HITLRequest | null;
  
  // 请求历史 (用于历史消息渲染)
  requestHistory: Map<string, HITLRequest>;
  
  // 加载状态
  isLoading: boolean;
  error: string | null;
  
  // Actions
  setCurrentRequest: (request: HITLRequest | null) => void;
  addToHistory: (request: HITLRequest) => void;
  submitResponse: (requestId: string, response: any) => Promise<void>;
  cancelRequest: (requestId: string) => Promise<void>;
  fetchPendingRequests: (conversationId: string) => Promise<void>;
  clearError: () => void;
}

export const useHITLStore = create<HITLState>((set, get) => ({
  currentRequest: null,
  requestHistory: new Map(),
  isLoading: false,
  error: null,

  setCurrentRequest: (request) => set({ currentRequest: request }),

  addToHistory: (request) => {
    const history = new Map(get().requestHistory);
    history.set(request.id, request);
    set({ requestHistory: history });
  },

  submitResponse: async (requestId, response) => {
    set({ isLoading: true, error: null });
    try {
      await hitlService.respond({
        request_id: requestId,
        response: response,
      });
      
      // 更新状态
      const current = get().currentRequest;
      if (current?.id === requestId) {
        set({ currentRequest: null });
      }
      
      // 更新历史
      const history = new Map(get().requestHistory);
      const req = history.get(requestId);
      if (req) {
        history.set(requestId, { ...req, status: 'answered', response });
        set({ requestHistory: history });
      }
    } catch (error: any) {
      set({ error: error.message });
      throw error;
    } finally {
      set({ isLoading: false });
    }
  },

  cancelRequest: async (requestId) => {
    set({ isLoading: true, error: null });
    try {
      await hitlService.cancel({ request_id: requestId });
      
      const current = get().currentRequest;
      if (current?.id === requestId) {
        set({ currentRequest: null });
      }
    } catch (error: any) {
      set({ error: error.message });
      throw error;
    } finally {
      set({ isLoading: false });
    }
  },

  fetchPendingRequests: async (conversationId) => {
    try {
      const requests = await hitlService.getPending(conversationId);
      if (requests.length > 0) {
        set({ currentRequest: requests[0] });
      }
    } catch (error: any) {
      console.error('Failed to fetch pending HITL requests:', error);
    }
  },

  clearError: () => set({ error: null }),
}));
```

### useShallow 使用

为避免无限重渲染，使用 `useShallow` 选择 store 状态：

```typescript
import { useShallow } from 'zustand/react/shallow';

// ✅ 正确用法
const { currentRequest, submitResponse } = useHITLStore(
  useShallow((state) => ({
    currentRequest: state.currentRequest,
    submitResponse: state.submitResponse,
  }))
);

// ❌ 错误用法 - 会导致无限重渲染
const { currentRequest, submitResponse } = useHITLStore((state) => ({
  currentRequest: state.currentRequest,
  submitResponse: state.submitResponse,
}));
```

## SSE 事件订阅

### 事件类型

```typescript
// web/src/types/agent.ts

type HITLEventType =
  | 'hitl_request'      // 新的 HITL 请求
  | 'hitl_timeout'      // 请求超时
  | 'hitl_cancelled'    // 请求取消
  | 'hitl_completed';   // 请求完成

interface HITLEvent {
  type: HITLEventType;
  data: {
    request_id: string;
    hitl_type: 'clarification' | 'decision' | 'env_var' | 'permission';
    request_data?: any;
    status?: string;
  };
}
```

### SSE 订阅

```typescript
// web/src/hooks/useAgentSSE.ts

export const useAgentSSE = (conversationId: string) => {
  const { setCurrentRequest, addToHistory } = useHITLStore();

  useEffect(() => {
    const eventSource = new EventSource(
      `/api/v1/agent/conversations/${conversationId}/stream`
    );

    eventSource.addEventListener('hitl_request', (event) => {
      const data = JSON.parse(event.data);
      const request: HITLRequest = {
        id: data.request_id,
        type: data.hitl_type,
        data: data.request_data,
        status: 'pending',
        createdAt: new Date().toISOString(),
      };
      setCurrentRequest(request);
      addToHistory(request);
    });

    eventSource.addEventListener('hitl_timeout', (event) => {
      const data = JSON.parse(event.data);
      // 清除当前请求
      setCurrentRequest(null);
      // 显示超时提示
      message.warning('HITL 请求已超时');
    });

    eventSource.addEventListener('hitl_completed', (event) => {
      const data = JSON.parse(event.data);
      setCurrentRequest(null);
    });

    return () => eventSource.close();
  }, [conversationId]);
};
```

## API 服务

### hitlService.unified.ts

```typescript
// web/src/services/hitlService.unified.ts

import { httpClient } from './httpClient';

export interface HITLRespondRequest {
  request_id: string;
  response: any;
  metadata?: Record<string, any>;
}

export interface HITLCancelRequest {
  request_id: string;
  reason?: string;
}

export const hitlService = {
  /**
   * 获取待处理的 HITL 请求
   */
  getPending: async (conversationId: string): Promise<HITLRequest[]> => {
    const response = await httpClient.get(
      `/api/v1/agent/hitl/conversations/${conversationId}/pending`
    );
    return response.data.requests;
  },

  /**
   * 响应 HITL 请求
   */
  respond: async (request: HITLRespondRequest): Promise<void> => {
    await httpClient.post('/api/v1/agent/hitl/respond', request);
  },

  /**
   * 取消 HITL 请求
   */
  cancel: async (request: HITLCancelRequest): Promise<void> => {
    await httpClient.post('/api/v1/agent/hitl/cancel', request);
  },
};
```

## 历史消息渲染

### MessageBubble 中的 HITL 检测

```tsx
// web/src/components/agent/MessageBubble.tsx

const MessageBubble: React.FC<{ message: Message }> = ({ message }) => {
  // 检查是否是 HITL 事件
  if (message.type === 'hitl_request') {
    return (
      <InlineHITLCard
        requestId={message.event_data?.request_id}
        type={message.event_data?.hitl_type}
        data={message.event_data?.request_data}
        answered={message.event_data?.answered ?? false}
        decision={message.event_data?.decision}
        timestamp={message.created_at}
      />
    );
  }

  // 普通消息渲染
  return (
    <div className="message-bubble">
      <Markdown content={message.content} />
    </div>
  );
};
```

### 历史消息加载

```typescript
// web/src/pages/project/AgentChat.tsx

const AgentChat: React.FC = () => {
  const [messages, setMessages] = useState<Message[]>([]);
  const { fetchPendingRequests } = useHITLStore();

  useEffect(() => {
    const loadMessages = async () => {
      // 加载历史消息
      const response = await agentService.getMessages(conversationId);
      setMessages(response.messages);

      // 检查是否有未处理的 HITL 请求
      await fetchPendingRequests(conversationId);
    };

    loadMessages();
  }, [conversationId]);

  return (
    <div className="agent-chat">
      <MessageList messages={messages} />
      <UnifiedHITLPanel
        conversationId={conversationId}
        projectId={projectId}
      />
      <ChatInput onSend={handleSend} />
    </div>
  );
};
```

## 类型定义

### hitl.unified.ts

```typescript
// web/src/types/hitl.unified.ts

export type HITLType = 'clarification' | 'decision' | 'env_var' | 'permission';

export type HITLStatus = 'pending' | 'answered' | 'timeout' | 'cancelled' | 'completed';

export interface HITLOption {
  id: string;
  label: string;
  description?: string;
  risk_level?: 'low' | 'medium' | 'high' | 'critical';
}

export interface HITLField {
  name: string;
  label: string;
  type: 'text' | 'password' | 'select';
  required?: boolean;
  placeholder?: string;
  options?: { label: string; value: string }[];
}

export interface HITLRequest {
  id: string;
  type: HITLType;
  status: HITLStatus;
  data: HITLRequestData;
  response?: any;
  createdAt: string;
  answeredAt?: string;
}

export interface ClarificationData {
  question: string;
  options: HITLOption[];
  clarification_type: string;
  allow_custom: boolean;
  context?: Record<string, any>;
}

export interface DecisionData {
  question: string;
  options: HITLOption[];
  decision_type: string;
  allow_custom: boolean;
  default_option?: string;
  context?: Record<string, any>;
}

export interface EnvVarData {
  tool_name: string;
  fields: HITLField[];
  message?: string;
  allow_save: boolean;
  context?: Record<string, any>;
}

export interface PermissionData {
  tool_name: string;
  action: string;
  risk_level: 'low' | 'medium' | 'high' | 'critical';
  description?: string;
  details?: Record<string, any>;
  allow_remember: boolean;
  default_action?: 'allow' | 'deny';
}

export type HITLRequestData = 
  | ClarificationData 
  | DecisionData 
  | EnvVarData 
  | PermissionData;
```

## 样式指南

### HITL 卡片样式

```css
/* web/src/styles/hitl.css */

.hitl-card {
  border-radius: 8px;
  padding: 16px;
  margin: 8px 0;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
}

.hitl-card--pending {
  background: linear-gradient(135deg, #fff7e6 0%, #ffe7ba 100%);
  border-left: 4px solid #fa8c16;
}

.hitl-card--answered {
  background: #f6ffed;
  border-left: 4px solid #52c41a;
  opacity: 0.9;
}

.hitl-card--timeout {
  background: #fff1f0;
  border-left: 4px solid #f5222d;
}

.hitl-card__header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}

.hitl-card__icon {
  font-size: 20px;
}

.hitl-card__title {
  font-weight: 600;
  color: #262626;
}

.hitl-card__question {
  font-size: 14px;
  color: #595959;
  margin-bottom: 16px;
}

.hitl-card__options {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.hitl-option {
  padding: 12px;
  border: 1px solid #d9d9d9;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s;
}

.hitl-option:hover {
  border-color: #1890ff;
  background: #e6f7ff;
}

.hitl-option--selected {
  border-color: #1890ff;
  background: #e6f7ff;
}

.hitl-option--high-risk {
  border-color: #f5222d;
}

.hitl-option--high-risk:hover {
  background: #fff1f0;
}
```

## 错误处理

### 网络错误

```tsx
const handleSubmit = async (response: any) => {
  try {
    await submitResponse(requestId, response);
    message.success('响应已提交');
  } catch (error: any) {
    if (error.response?.status === 404) {
      message.error('请求已过期');
    } else if (error.response?.status === 409) {
      message.warning('请求已被处理');
    } else {
      message.error('提交失败，请重试');
    }
  }
};
```

### SSE 断连重试

```typescript
const useAgentSSE = (conversationId: string) => {
  const [retryCount, setRetryCount] = useState(0);
  const maxRetries = 3;

  useEffect(() => {
    let eventSource: EventSource;
    let reconnectTimer: NodeJS.Timeout;

    const connect = () => {
      eventSource = new EventSource(
        `/api/v1/agent/conversations/${conversationId}/stream`
      );

      eventSource.onopen = () => {
        setRetryCount(0); // 重置重试计数
      };

      eventSource.onerror = () => {
        eventSource.close();
        
        if (retryCount < maxRetries) {
          // 指数退避重连
          const delay = Math.pow(2, retryCount) * 1000;
          reconnectTimer = setTimeout(() => {
            setRetryCount((c) => c + 1);
            connect();
          }, delay);
        }
      };

      // ... 事件处理
    };

    connect();

    return () => {
      eventSource?.close();
      clearTimeout(reconnectTimer);
    };
  }, [conversationId, retryCount]);
};
```

## 最佳实践

1. **使用 useShallow**: 避免 Zustand 选择器导致的无限重渲染

2. **乐观更新**: 提交后立即更新 UI，失败时回滚

3. **错误边界**: 使用 React Error Boundary 包装 HITL 组件

4. **加载状态**: 显示明确的加载和提交状态

5. **超时处理**: 显示倒计时并在超时后禁用输入

6. **键盘支持**: 支持 Enter 提交和 Escape 取消

7. **无障碍**: 确保屏幕阅读器可以访问
