/**
 * HITL Store - State management for Human-in-the-Loop interactions
 * 
 * Manages pending HITL requests, timeouts, and responses.
 */

import { create } from 'zustand';
import { devtools, subscribeWithSelector } from 'zustand/middleware';
import type {
  HITLRequest,
  HITLResponse,
  HITLRequestStatus,
  ClarificationRequest,
  PermissionRequest,
  DecisionRequest,
  EnvVarRequest,
} from '../types/hitl';
import {
  getRemainingTime,
  createHITLRequest,
  isClarificationRequest,
  isPermissionRequest,
  isDecisionRequest,
  isEnvVarRequest,
} from '../types/hitl';
import { hitlService } from '../services/hitlService';
import type { AgentEventType } from '../types/generated/eventTypes';

// =============================================================================
// State Interface
// =============================================================================

interface HITLState {
  /** Map of request ID → pending HITL request */
  pendingRequests: Map<string, HITLRequest>;
  
  /** Map of conversation ID → array of request IDs */
  requestsByConversation: Map<string, Set<string>>;
  
  /** History of answered requests (limited) */
  answeredHistory: HITLRequest[];
  
  /** Maximum history size */
  maxHistorySize: number;
  
  /** Whether a response is being submitted */
  isSubmitting: boolean;
  
  /** Last error message */
  error: string | null;
}

interface HITLActions {
  // Request management
  addRequest: (request: HITLRequest) => void;
  removeRequest: (requestId: string) => void;
  updateRequestStatus: (requestId: string, status: HITLRequestStatus) => void;
  
  // Event handling
  handleHITLEvent: (
    eventType: AgentEventType,
    data: Record<string, unknown>,
    conversationId: string
  ) => void;
  
  // Response submission
  submitResponse: (
    conversationId: string,
    request: HITLRequest,
    response: HITLResponse
  ) => Promise<void>;
  
  // Queries
  getRequest: (requestId: string) => HITLRequest | undefined;
  getRequestsForConversation: (conversationId: string) => HITLRequest[];
  getPendingCount: (conversationId?: string) => number;
  
  // Timeout handling
  checkTimeouts: () => void;
  startTimeoutChecker: () => () => void;
  
  // Cleanup
  clearConversation: (conversationId: string) => void;
  clearError: () => void;
  reset: () => void;
}

type HITLStore = HITLState & HITLActions;

// =============================================================================
// Initial State
// =============================================================================

const initialState: HITLState = {
  pendingRequests: new Map(),
  requestsByConversation: new Map(),
  answeredHistory: [],
  maxHistorySize: 100,
  isSubmitting: false,
  error: null,
};

// =============================================================================
// Store Implementation
// =============================================================================

export const useHITLStore = create<HITLStore>()(
  devtools(
    subscribeWithSelector((set, get) => ({
      ...initialState,

      // =========================================================================
      // Request Management
      // =========================================================================

      addRequest: (request: HITLRequest) => {
        set((state) => {
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
        }, false, 'hitl/addRequest');
      },

      removeRequest: (requestId: string) => {
        set((state) => {
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
        }, false, 'hitl/removeRequest');
      },

      updateRequestStatus: (requestId: string, status: HITLRequestStatus) => {
        set((state) => {
          const request = state.pendingRequests.get(requestId);
          if (!request) return state;

          const updatedRequest = { ...request, status };
          const newPending = new Map(state.pendingRequests);

          if (status === 'pending') {
            newPending.set(requestId, updatedRequest);
          } else {
            // Move to history
            newPending.delete(requestId);
            
            const newHistory = [updatedRequest, ...state.answeredHistory]
              .slice(0, state.maxHistorySize);

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
              answeredHistory: newHistory,
            };
          }

          return { pendingRequests: newPending };
        }, false, 'hitl/updateRequestStatus');
      },

      // =========================================================================
      // Event Handling
      // =========================================================================

      handleHITLEvent: (
        eventType: AgentEventType,
        data: Record<string, unknown>,
        conversationId: string
      ) => {
        // Check if this is an "asked" event
        if (eventType.endsWith('_asked') || eventType === 'env_var_requested') {
          const request = createHITLRequest(eventType, data, conversationId);
          if (request) {
            get().addRequest(request);
          }
        }
        // Check if this is an "answered" event
        else if (
          eventType.endsWith('_answered') || 
          eventType === 'env_var_provided' ||
          eventType === 'permission_replied'
        ) {
          const requestId = data.request_id as string;
          if (requestId) {
            get().updateRequestStatus(requestId, 'answered');
          }
        }
      },

      // =========================================================================
      // Response Submission
      // =========================================================================

      submitResponse: async (
        conversationId: string,
        request: HITLRequest,
        response: HITLResponse
      ) => {
        set({ isSubmitting: true, error: null }, false, 'hitl/submitStart');

        try {
          await hitlService.respond(conversationId, request, response);
          get().updateRequestStatus(request.requestId, 'answered');
        } catch (err) {
          const errorMessage = err instanceof Error ? err.message : 'Failed to submit response';
          set({ error: errorMessage }, false, 'hitl/submitError');
          throw err;
        } finally {
          set({ isSubmitting: false }, false, 'hitl/submitEnd');
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
          .map(id => state.pendingRequests.get(id))
          .filter((r): r is HITLRequest => r !== undefined);
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
          if (request.timeoutAt && now > request.timeoutAt) {
            get().updateRequestStatus(requestId, 'timeout');
          }
        }
      },

      startTimeoutChecker: () => {
        const intervalId = setInterval(() => {
          get().checkTimeouts();
        }, 1000); // Check every second

        return () => clearInterval(intervalId);
      },

      // =========================================================================
      // Cleanup
      // =========================================================================

      clearConversation: (conversationId: string) => {
        set((state) => {
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
        }, false, 'hitl/clearConversation');
      },

      clearError: () => {
        set({ error: null }, false, 'hitl/clearError');
      },

      reset: () => {
        set(initialState, false, 'hitl/reset');
      },
    })),
    { name: 'hitl-store' }
  )
);

// =============================================================================
// Selectors
// =============================================================================

/**
 * Get all pending clarification requests for a conversation
 */
export function useClarificationRequests(conversationId: string): ClarificationRequest[] {
  return useHITLStore((state) => {
    const requests = state.requestsByConversation.get(conversationId);
    if (!requests) return [];
    
    return Array.from(requests)
      .map(id => state.pendingRequests.get(id))
      .filter((r): r is ClarificationRequest => 
        r !== undefined && isClarificationRequest(r)
      );
  });
}

/**
 * Get all pending permission requests for a conversation
 */
export function usePermissionRequests(conversationId: string): PermissionRequest[] {
  return useHITLStore((state) => {
    const requests = state.requestsByConversation.get(conversationId);
    if (!requests) return [];
    
    return Array.from(requests)
      .map(id => state.pendingRequests.get(id))
      .filter((r): r is PermissionRequest => 
        r !== undefined && isPermissionRequest(r)
      );
  });
}

/**
 * Get all pending decision requests for a conversation
 */
export function useDecisionRequests(conversationId: string): DecisionRequest[] {
  return useHITLStore((state) => {
    const requests = state.requestsByConversation.get(conversationId);
    if (!requests) return [];
    
    return Array.from(requests)
      .map(id => state.pendingRequests.get(id))
      .filter((r): r is DecisionRequest => 
        r !== undefined && isDecisionRequest(r)
      );
  });
}

/**
 * Get all pending env var requests for a conversation
 */
export function useEnvVarRequests(conversationId: string): EnvVarRequest[] {
  return useHITLStore((state) => {
    const requests = state.requestsByConversation.get(conversationId);
    if (!requests) return [];
    
    return Array.from(requests)
      .map(id => state.pendingRequests.get(id))
      .filter((r): r is EnvVarRequest => 
        r !== undefined && isEnvVarRequest(r)
      );
  });
}

/**
 * Check if there are any pending HITL requests
 */
export function useHasPendingRequests(conversationId?: string): boolean {
  return useHITLStore((state) => {
    if (conversationId) {
      const requests = state.requestsByConversation.get(conversationId);
      return (requests?.size || 0) > 0;
    }
    return state.pendingRequests.size > 0;
  });
}

/**
 * Get remaining time for a specific request
 */
export function useRemainingTime(requestId: string): number | null {
  return useHITLStore((state) => {
    const request = state.pendingRequests.get(requestId);
    if (!request) return null;
    return getRemainingTime(request);
  });
}

export default useHITLStore;
