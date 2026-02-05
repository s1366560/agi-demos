# HITL 前端修复建议

## 修复 1: 优化 HITL 状态更新顺序 (P1)

**文件**: `src/stores/hitlStore.unified.ts`

**修改**:
```typescript
submitResponse: async (
  requestId: string,
  hitlType: HITLType,
  responseData: HITLResponseData
) => {
  // 设置提交状态
  set({ 
    isSubmitting: true, 
    submittingRequestId: requestId,
    error: null 
  }, false, 'hitl/submitStart');

  try {
    // 先调用 API - 如果失败，状态不会更新
    await unifiedHitlService.respond(requestId, hitlType, responseData);
    
    // API 成功后再更新本地状态
    get().updateRequestStatus(requestId, 'answered');
  } catch (err) {
    const errorMessage = err instanceof Error ? err.message : 'Failed to submit response';
    set({ error: errorMessage }, false, 'hitl/submitError');
    throw err;
  } finally {
    set({ 
      isSubmitting: false,
      submittingRequestId: null 
    }, false, 'hitl/submitEnd');
  }
},
```

---

## 修复 2: 优化多次 HITL 的当前请求选择逻辑 (P2)

**文件**: `src/hooks/useUnifiedHITL.ts`

**修改**:
```typescript
// Computed values
const currentRequest = useMemo(() => {
  if (pendingRequests.length === 0) return null;
  
  // 按 createdAt 排序（最早的在前）
  const sorted = [...pendingRequests].sort(
    (a, b) => new Date(a.createdAt).getTime() - new Date(b.createdAt).getTime()
  );
  
  // 返回第一个 pending 状态的请求
  return sorted.find(r => r.status === 'pending') || sorted[0];
}, [pendingRequests]);

// 添加获取下一个待处理请求的函数
const getNextPendingRequest = useMemo(() => {
  return (currentRequestId: string) => {
    if (pendingRequests.length <= 1) return null;
    
    const sorted = [...pendingRequests].sort(
      (a, b) => new Date(a.createdAt).getTime() - new Date(b.createdAt).getTime()
    );
    
    const currentIndex = sorted.findIndex(r => r.requestId === currentRequestId);
    return sorted[currentIndex + 1] || null;
  };
}, [pendingRequests]);
```

---

## 修复 3: 添加多次 HITL 过渡动画 (P2)

**文件**: `src/components/agent/UnifiedHITLPanel.tsx`

**添加**:
```typescript
import { usePrevious } from '@/hooks/usePrevious'; // 或创建此 hook

// 在组件内部
const previousRequestId = usePrevious(request.requestId);
const [isTransitioning, setIsTransitioning] = useState(false);

useEffect(() => {
  if (previousRequestId && previousRequestId !== request.requestId) {
    setIsTransitioning(true);
    const timer = setTimeout(() => setIsTransitioning(false), 300);
    return () => clearTimeout(timer);
  }
}, [request.requestId, previousRequestId]);

// 在 JSX 中添加过渡效果
return (
  <Modal
    // ... 其他 props
    className={`hitl-panel-modal ${isTransitioning ? 'transitioning' : ''}`}
    transitionName="hitl-panel-transition"
  >
    {/* ... */}
  </Modal>
);
```

**添加 CSS**:
```css
.hitl-panel-transition-enter {
  opacity: 0;
  transform: scale(0.95);
}

.hitl-panel-transition-enter-active {
  opacity: 1;
  transform: scale(1);
  transition: opacity 200ms, transform 200ms;
}

.hitl-panel-transition-exit {
  opacity: 1;
}

.hitl-panel-transition-exit-active {
  opacity: 0;
  transition: opacity 150ms;
}
```

---

## 修复 4: 序列号连续性 (P3)

**文件**: `src/utils/sseEventAdapter.ts`

**修改**:
```typescript
/**
 * Convert a batch of SSE events to TimelineEvents
 * 
 * 注意：不要在批量转换时重置序列号计数器，
 * 以确保多次 HITL 场景下的事件序列连续性。
 */
export function batchConvertSSEEvents(
    events: AgentEvent<unknown>[]
): TimelineEvent[] {
    // 移除了 resetSequenceCounter() 调用
    // 计数器应该是全局递增的，不应该在每次批量转换时重置

    const timelineEvents: TimelineEvent[] = [];

    for (const event of events) {
        const sequenceNumber = getNextSequenceNumber();
        const timelineEvent = sseEventToTimeline(event, sequenceNumber);

        if (timelineEvent) {
            timelineEvents.push(timelineEvent);
        }
    }

    return timelineEvents;
}

// 添加一个新函数用于需要重置的场景
export function batchConvertSSEEventsWithReset(
    events: AgentEvent<unknown>[]
): TimelineEvent[] {
    resetSequenceCounter();
    return batchConvertSSEEvents(events);
}
```

---

## 修复 5: 验证后端字段映射 (P3)

**文件**: `src/stores/hitlStore.unified.ts`

**修改** `createRequestFromSSE` 函数，添加更健壮的字段映射：

```typescript
case 'env_var':
  // 尝试多个可能的字段名，以兼容不同的后端版本
  const message = (data.message as string) || 
                  (data.question as string) || 
                  'Please provide environment variables';
  
  return {
    ...base,
    question: message,
    envVarData: {
      toolName: (data.tool_name as string) || 
                (data.toolName as string) || 
                'unknown',
      fields: (data.fields as EnvVarField[]) || [],
      message: message,
      allowSave: (data.allow_save as boolean) ?? 
                 (data.allowSave as boolean) ?? 
                 true,
      context: (data.context as Record<string, unknown>) || {},
    },
  };
```

---

## 修复 6: 添加多次 HITL 的调试日志

**文件**: `src/stores/hitlStore.unified.ts`

**在关键位置添加日志**:

```typescript
handleSSEEvent: (
  eventType: string,
  data: Record<string, unknown>,
  conversationId: string
) => {
  console.log('[HITL] Received SSE event:', { eventType, conversationId, data });
  
  // Handle "asked" events
  const hitlType = SSE_EVENT_TO_HITL_TYPE[eventType];
  if (hitlType) {
    const request = createRequestFromSSE(eventType, data, conversationId);
    if (request) {
      console.log('[HITL] Created request:', request.requestId, request.hitlType);
      get().addRequest(request);
    }
    return;
  }

  // Handle "answered" events
  if (
    eventType.endsWith('_answered') ||
    eventType === 'env_var_provided' ||
    eventType === 'permission_replied' ||
    eventType === 'hitl_cancelled'
  ) {
    const requestId = data.request_id as string;
    console.log('[HITL] Received response event:', { eventType, requestId });
    if (requestId) {
      const status = eventType === 'hitl_cancelled' ? 'cancelled' : 'completed';
      get().updateRequestStatus(requestId, status);
    }
  }
},

// 在 addRequest 中
addRequest: (request: UnifiedHITLRequest) => {
  set((state) => {
    // Skip if already exists
    if (state.pendingRequests.has(request.requestId)) {
      console.log('[HITL] Request already exists:', request.requestId);
      return state;
    }

    console.log('[HITL] Adding request:', request.requestId, 
                'Total pending:', state.pendingRequests.size + 1);
    
    // ... rest of the code
  }, false, 'hitl/addRequest');
},
```

---

## 快速验证清单

在应用修复后，请验证以下场景：

### 单次 HITL
- [ ] 用户发送消息触发 HITL
- [ ] HITL UI 正确显示
- [ ] 用户提交响应
- [ ] Agent 继续执行
- [ ] 最终完成

### 两次 HITL
- [ ] 用户发送消息触发第一个 HITL
- [ ] 第一个 HITL UI 正确显示
- [ ] 用户提交响应
- [ ] 第二个 HITL UI 正确显示（第一个消失或显示为已回答）
- [ ] 用户提交响应
- [ ] Agent 完成

### 错误处理
- [ ] 网络错误时，HITL 状态保持 pending
- [ ] 用户可以在失败后重试提交

### 页面刷新
- [ ] 刷新页面后，待处理的 HITL 从后端恢复
- [ ] 用户可以正常响应

---

## 相关文件

| 文件 | 用途 |
|------|------|
| `src/stores/hitlStore.unified.ts` | 统一 HITL 状态管理 |
| `src/hooks/useUnifiedHITL.ts` | HITL Hook |
| `src/components/agent/UnifiedHITLPanel.tsx` | 模态框 HITL UI |
| `src/components/agent/InlineHITLCard.tsx` | 内联 HITL UI |
| `src/utils/sseEventAdapter.ts` | SSE 事件转换 |
| `src/services/hitlService.unified.ts` | HITL API 服务 |
