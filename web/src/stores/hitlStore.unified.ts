/**
 * Unified HITL Store - Simplified state management for Human-in-the-Loop
 *
 * This store uses the new unified HITL types and service.
 * Manages pending HITL requests, timeouts, and responses.
 */

import { create } from 'zustand';
import { devtools, subscribeWithSelector } from 'zustand/middleware';
import { useShallow } from 'zustand/react/shallow';

import { unifiedHitlService } from '../services/hitlService.unified';
import { getRemainingTimeSeconds, SSE_EVENT_TO_HITL_TYPE } from '../types/hitl.unified';

import type {
  HITLType,
  HITLStatus,
  UnifiedHITLRequest,
  HITLResponseData,
  ClarificationOption,
  DecisionOption,
  EnvVarField,
} from '../types/hitl.unified';

// =============================================================================
// State Interface
// =============================================================================

interface UnifiedHITLState {
  /** Map of request ID → pending HITL request */
  pendingRequests: Map<string, UnifiedHITLRequest>;

  /** Map of conversation ID → Set of request IDs */
  requestsByConversation: Map<string, Set<string>>;

  /** Map of request ID → status (for tracking answered state) */
  requestStatuses: Map<string, HITLStatus>;

  /** History of completed requests (limited) */
  completedHistory: UnifiedHITLRequest[];

  /** Maximum history size */
  maxHistorySize: number;

  /** Whether a response is being submitted */
  isSubmitting: boolean;

  /** Current submitting request ID */
  submittingRequestId: string | null;

  /** Last error message */
  error: string | null;
}

interface UnifiedHITLActions {
  // Request management
  addRequest: (request: UnifiedHITLRequest) => void;
  removeRequest: (requestId: string) => void;
  updateRequestStatus: (requestId: string, status: HITLStatus) => void;

  // SSE event handling
  handleSSEEvent: (
    eventType: string,
    data: Record<string, unknown>,
    conversationId: string
  ) => void;

  // Response submission (uses unified endpoint)
  submitResponse: (
    requestId: string,
    hitlType: HITLType,
    responseData: HITLResponseData
  ) => Promise<void>;

  // Cancel request
  cancelRequest: (requestId: string, reason?: string) => Promise<void>;

  // Queries
  getRequest: (requestId: string) => UnifiedHITLRequest | undefined;
  getRequestsForConversation: (conversationId: string) => UnifiedHITLRequest[];
  getRequestsByType: (conversationId: string, type: HITLType) => UnifiedHITLRequest[];
  getPendingCount: (conversationId?: string) => number;

  // Timeout handling
  checkTimeouts: () => void;
  startTimeoutChecker: () => () => void;

  // Cleanup
  clearConversation: (conversationId: string) => void;
  clearError: () => void;
  reset: () => void;
}

type UnifiedHITLStore = UnifiedHITLState & UnifiedHITLActions;

// =============================================================================
// Initial State
// =============================================================================

const initialState: UnifiedHITLState = {
  pendingRequests: new Map(),
  requestsByConversation: new Map(),
  requestStatuses: new Map(),
  completedHistory: [],
  maxHistorySize: 100,
  isSubmitting: false,
  submittingRequestId: null,
  error: null,
};

// =============================================================================
// Store Implementation
// =============================================================================

export const useUnifiedHITLStore = create<UnifiedHITLStore>()(
  devtools(
    subscribeWithSelector((set, get) => ({
      ...initialState,

      // =========================================================================
      // Request Management
      // =========================================================================

      addRequest: (request: UnifiedHITLRequest) => {
        set(
          (state) => {
            // Skip if already exists
            if (state.pendingRequests.has(request.requestId)) {
              if (process.env.NODE_ENV === 'development') {
                console.log('[HITL Debug] Request already exists:', request.requestId);
              }
              return state;
            }

            if (process.env.NODE_ENV === 'development') {
              console.log(
                '[HITL Debug] Adding request:',
                request.requestId,
                'Type:',
                request.hitlType,
                'Total pending:',
                state.pendingRequests.size + 1
              );
            }

            const newPending = new Map(state.pendingRequests);
            newPending.set(request.requestId, request);

            const newByConv = new Map(state.requestsByConversation);
            const convRequests = newByConv.get(request.conversationId) || new Set();
            convRequests.add(request.requestId);
            newByConv.set(request.conversationId, convRequests);

            return {
              pendingRequests: newPending,
              requestsByConversation: newByConv,
            };
          },
          false,
          'hitl/addRequest'
        );
      },

      removeRequest: (requestId: string) => {
        set(
          (state) => {
            const request = state.pendingRequests.get(requestId);
            if (!request) return state;

            const newPending = new Map(state.pendingRequests);
            newPending.delete(requestId);

            const newByConv = new Map(state.requestsByConversation);
            const convRequests = newByConv.get(request.conversationId);
            if (convRequests) {
              convRequests.delete(requestId);
              if (convRequests.size === 0) {
                newByConv.delete(request.conversationId);
              }
            }

            return {
              pendingRequests: newPending,
              requestsByConversation: newByConv,
            };
          },
          false,
          'hitl/removeRequest'
        );
      },

      updateRequestStatus: (requestId: string, status: HITLStatus) => {
        set(
          (state) => {
            if (process.env.NODE_ENV === 'development') {
              console.log('[HITL Debug] Updating request status:', requestId, '->', status);
            }

            // Always update the status map (even if request not in pendingRequests)
            const newStatuses = new Map(state.requestStatuses);
            newStatuses.set(requestId, status);

            const request = state.pendingRequests.get(requestId);
            if (!request) {
              // Request not in pending (maybe from history), just update status
              return { requestStatuses: newStatuses };
            }

            const updatedRequest = { ...request, status };
            const newPending = new Map(state.pendingRequests);

            if (status === 'pending') {
              newPending.set(requestId, updatedRequest);
              return { pendingRequests: newPending, requestStatuses: newStatuses };
            }

            // Move to history for non-pending states
            newPending.delete(requestId);

            const newHistory = [updatedRequest, ...state.completedHistory].slice(
              0,
              state.maxHistorySize
            );

            // Remove from conversation map
            const newByConv = new Map(state.requestsByConversation);
            const convRequests = newByConv.get(request.conversationId);
            if (convRequests) {
              convRequests.delete(requestId);
              if (convRequests.size === 0) {
                newByConv.delete(request.conversationId);
              }
            }

            return {
              pendingRequests: newPending,
              requestsByConversation: newByConv,
              completedHistory: newHistory,
              requestStatuses: newStatuses,
            };
          },
          false,
          'hitl/updateRequestStatus'
        );
      },

      // =========================================================================
      // SSE Event Handling
      // =========================================================================

      handleSSEEvent: (
        eventType: string,
        data: Record<string, unknown>,
        conversationId: string
      ) => {
        // 调试日志：记录接收到的 SSE 事件
        if (process.env.NODE_ENV === 'development') {
          console.log('[HITL Debug] Received SSE event:', {
            eventType,
            conversationId,
            requestId: data.request_id,
            hitlType: SSE_EVENT_TO_HITL_TYPE[eventType],
          });
        }

        // Handle "asked" events
        const hitlType = SSE_EVENT_TO_HITL_TYPE[eventType];
        if (hitlType) {
          const request = createRequestFromSSE(eventType, data, conversationId);
          if (request) {
            if (process.env.NODE_ENV === 'development') {
              console.log('[HITL Debug] Created request:', request.requestId, request.hitlType);
            }
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
          if (requestId) {
            const status = eventType === 'hitl_cancelled' ? 'cancelled' : 'completed';
            get().updateRequestStatus(requestId, status);
          }
        }
      },

      // =========================================================================
      // Response Submission
      // =========================================================================

      submitResponse: async (
        requestId: string,
        hitlType: HITLType,
        responseData: HITLResponseData
      ) => {
        set(
          {
            isSubmitting: true,
            submittingRequestId: requestId,
            error: null,
          },
          false,
          'hitl/submitStart'
        );

        try {
          // 先调用 API - 确保后端成功接收响应后再更新本地状态
          // 这避免了 API 失败但状态已更新的竞态条件
          await unifiedHitlService.respond(requestId, hitlType, responseData);

          // API 成功后再更新本地状态
          get().updateRequestStatus(requestId, 'answered');
        } catch (err) {
          const errorMessage = err instanceof Error ? err.message : 'Failed to submit response';
          set({ error: errorMessage }, false, 'hitl/submitError');
          throw err;
        } finally {
          set(
            {
              isSubmitting: false,
              submittingRequestId: null,
            },
            false,
            'hitl/submitEnd'
          );
        }
      },

      cancelRequest: async (requestId: string, reason?: string) => {
        try {
          await unifiedHitlService.cancel(requestId, reason);
          get().updateRequestStatus(requestId, 'cancelled');
        } catch (err) {
          const errorMessage = err instanceof Error ? err.message : 'Failed to cancel request';
          set({ error: errorMessage }, false, 'hitl/cancelError');
          throw err;
        }
      },

      // =========================================================================
      // Queries
      // =========================================================================

      getRequest: (requestId: string) => {
        return get().pendingRequests.get(requestId);
      },

      getRequestsForConversation: (conversationId: string) => {
        const state = get();
        const requestIds = state.requestsByConversation.get(conversationId);
        if (!requestIds) return [];

        return Array.from(requestIds)
          .map((id) => state.pendingRequests.get(id))
          .filter((r): r is UnifiedHITLRequest => r !== undefined);
      },

      getRequestsByType: (conversationId: string, type: HITLType) => {
        return get()
          .getRequestsForConversation(conversationId)
          .filter((r) => r.hitlType === type);
      },

      getPendingCount: (conversationId?: string) => {
        const state = get();
        if (conversationId) {
          const requestIds = state.requestsByConversation.get(conversationId);
          return requestIds?.size || 0;
        }
        return state.pendingRequests.size;
      },

      // =========================================================================
      // Timeout Handling
      // =========================================================================

      checkTimeouts: () => {
        const state = get();
        const now = Date.now();

        for (const [requestId, request] of state.pendingRequests) {
          if (request.expiresAt && new Date(request.expiresAt).getTime() < now) {
            get().updateRequestStatus(requestId, 'timeout');
          }
        }
      },

      startTimeoutChecker: () => {
        const intervalId = setInterval(() => {
          get().checkTimeouts();
        }, 1000);

        return () => clearInterval(intervalId);
      },

      // =========================================================================
      // Cleanup
      // =========================================================================

      clearConversation: (conversationId: string) => {
        set(
          (state) => {
            const requestIds = state.requestsByConversation.get(conversationId);
            if (!requestIds) return state;

            const newPending = new Map(state.pendingRequests);
            for (const id of requestIds) {
              newPending.delete(id);
            }

            const newByConv = new Map(state.requestsByConversation);
            newByConv.delete(conversationId);

            return {
              pendingRequests: newPending,
              requestsByConversation: newByConv,
            };
          },
          false,
          'hitl/clearConversation'
        );
      },

      clearError: () => {
        set({ error: null }, false, 'hitl/clearError');
      },

      reset: () => {
        set(initialState, false, 'hitl/reset');
      },
    })),
    { name: 'unified-hitl-store' }
  )
);

// =============================================================================
// Helper: Create Request from SSE Event
// =============================================================================

function createRequestFromSSE(
  eventType: string,
  data: Record<string, unknown>,
  conversationId: string
): UnifiedHITLRequest | null {
  const hitlType = SSE_EVENT_TO_HITL_TYPE[eventType];
  if (!hitlType) return null;

  const requestId = data.request_id as string;
  if (!requestId) return null;

  const timeoutSeconds = (data.timeout_seconds as number) || 300;
  const now = new Date();
  const expiresAt = new Date(now.getTime() + timeoutSeconds * 1000);

  const base: UnifiedHITLRequest = {
    requestId,
    hitlType,
    conversationId,
    messageId: data.message_id as string | undefined,
    status: 'pending',
    timeoutSeconds,
    createdAt: now.toISOString(),
    expiresAt: expiresAt.toISOString(),
    question: (data.question as string) || '',
  };

  switch (hitlType) {
    case 'clarification':
      return {
        ...base,
        question: (data.question as string) || '',
        clarificationData: {
          question: (data.question as string) || '',
          clarificationType:
            (data.clarification_type as any) || (data.clarificationType as any) || 'custom',
          options: (data.options as ClarificationOption[]) || [],
          allowCustom: (data.allow_custom as boolean) ?? (data.allowCustom as boolean) ?? true,
          context: (data.context as Record<string, unknown>) || {},
          defaultValue:
            (data.default_value as string) || (data.defaultValue as string) || undefined,
        },
      };

    case 'decision':
      return {
        ...base,
        question: (data.question as string) || '',
        decisionData: {
          question: (data.question as string) || '',
          decisionType:
            (data.decision_type as any) || (data.decisionType as any) || 'single_choice',
          options: (data.options as DecisionOption[]) || [],
          allowCustom: (data.allow_custom as boolean) ?? (data.allowCustom as boolean) ?? false,
          defaultOption:
            (data.default_option as string) || (data.defaultOption as string) || undefined,
          maxSelections:
            (data.max_selections as number) || (data.maxSelections as number) || undefined,
          context: (data.context as Record<string, unknown>) || {},
        },
      };

    case 'env_var':
      // 尝试多个可能的字段名，以兼容不同的后端版本
      // 后端可能使用 'message' 或 'question' 字段
      const envMessage =
        (data.message as string) ||
        (data.question as string) ||
        'Please provide environment variables';

      return {
        ...base,
        question: envMessage,
        envVarData: {
          toolName: (data.tool_name as string) || (data.toolName as string) || 'unknown',
          fields: (data.fields as EnvVarField[]) || [],
          message: envMessage,
          allowSave: (data.allow_save as boolean) ?? (data.allowSave as boolean) ?? true,
          context: (data.context as Record<string, unknown>) || {},
        },
      };

    case 'permission':
      const toolName = (data.tool_name as string) || (data.toolName as string) || 'unknown';
      const action =
        (data.action as string) || (data.permission_type as string) || 'perform action';
      const description = (data.description as string) || (data.desc as string);

      return {
        ...base,
        question: description || `Allow ${toolName} to ${action}?`,
        permissionData: {
          toolName: toolName,
          action: action,
          riskLevel: (data.risk_level as any) || (data.riskLevel as any) || 'medium',
          details:
            (data.details as Record<string, unknown>) ||
            (data.context as Record<string, unknown>) ||
            {},
          description: description,
          allowRemember:
            (data.allow_remember as boolean) ?? (data.allowRemember as boolean) ?? true,
          defaultAction: (data.default_action as any) || (data.defaultAction as any),
          context: (data.context as Record<string, unknown>) || {},
        },
      };

    default:
      return null;
  }
}

// =============================================================================
// Selectors (Hooks)
// =============================================================================

/**
 * Get all pending requests for a conversation
 */
export function usePendingRequests(conversationId: string): UnifiedHITLRequest[] {
  return useUnifiedHITLStore(
    useShallow((state) => {
      const requestIds = state.requestsByConversation.get(conversationId);
      if (!requestIds || requestIds.size === 0) return [];

      return Array.from(requestIds)
        .map((id) => state.pendingRequests.get(id))
        .filter((r): r is UnifiedHITLRequest => r !== undefined);
    })
  );
}

/**
 * Get pending clarification requests
 */
export function useClarificationRequests(conversationId: string): UnifiedHITLRequest[] {
  return useUnifiedHITLStore(
    useShallow((state) => {
      const requestIds = state.requestsByConversation.get(conversationId);
      if (!requestIds || requestIds.size === 0) return [];

      return Array.from(requestIds)
        .map((id) => state.pendingRequests.get(id))
        .filter((r): r is UnifiedHITLRequest => r !== undefined && r.hitlType === 'clarification');
    })
  );
}

/**
 * Get pending decision requests
 */
export function useDecisionRequests(conversationId: string): UnifiedHITLRequest[] {
  return useUnifiedHITLStore(
    useShallow((state) => {
      const requestIds = state.requestsByConversation.get(conversationId);
      if (!requestIds || requestIds.size === 0) return [];

      return Array.from(requestIds)
        .map((id) => state.pendingRequests.get(id))
        .filter((r): r is UnifiedHITLRequest => r !== undefined && r.hitlType === 'decision');
    })
  );
}

/**
 * Get pending env var requests
 */
export function useEnvVarRequests(conversationId: string): UnifiedHITLRequest[] {
  return useUnifiedHITLStore(
    useShallow((state) => {
      const requestIds = state.requestsByConversation.get(conversationId);
      if (!requestIds || requestIds.size === 0) return [];

      return Array.from(requestIds)
        .map((id) => state.pendingRequests.get(id))
        .filter((r): r is UnifiedHITLRequest => r !== undefined && r.hitlType === 'env_var');
    })
  );
}

/**
 * Get pending permission requests
 */
export function usePermissionRequests(conversationId: string): UnifiedHITLRequest[] {
  return useUnifiedHITLStore(
    useShallow((state) => {
      const requestIds = state.requestsByConversation.get(conversationId);
      if (!requestIds || requestIds.size === 0) return [];

      return Array.from(requestIds)
        .map((id) => state.pendingRequests.get(id))
        .filter((r): r is UnifiedHITLRequest => r !== undefined && r.hitlType === 'permission');
    })
  );
}

/**
 * Check if there are pending requests
 */
export function useHasPendingRequests(conversationId?: string): boolean {
  return useUnifiedHITLStore((state) => {
    if (conversationId) {
      const requestIds = state.requestsByConversation.get(conversationId);
      return (requestIds?.size || 0) > 0;
    }
    return state.pendingRequests.size > 0;
  });
}

/**
 * Get remaining time for a request
 */
export function useRemainingTime(requestId: string): number | null {
  return useUnifiedHITLStore((state) => {
    const request = state.pendingRequests.get(requestId);
    if (!request) return null;
    return getRemainingTimeSeconds(request);
  });
}

/**
 * Check if currently submitting
 */
export function useIsSubmitting(requestId?: string): boolean {
  return useUnifiedHITLStore((state) => {
    if (requestId) {
      return state.submittingRequestId === requestId;
    }
    return state.isSubmitting;
  });
}

export default useUnifiedHITLStore;
