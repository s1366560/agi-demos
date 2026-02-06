/**
 * useUnifiedHITL Hook
 *
 * Bridge hook that connects agentV3Store SSE events to the unified HITL store.
 * This allows gradual migration from the old HITL system to the new unified one.
 *
 * Usage in AgentChatContent:
 * ```tsx
 * const { currentRequest } = useUnifiedHITL(conversationId);
 *
 * return (
 *   <>
 *     {currentRequest && (
 *       <UnifiedHITLPanel
 *         request={currentRequest}
 *         onClose={() => {}}
 *       />
 *     )}
 *   </>
 * );
 * ```
 */

import { useEffect, useMemo } from 'react';

import { useAgentV3Store } from '../stores/agentV3';
import { useUnifiedHITLStore, usePendingRequests } from '../stores/hitlStore.unified';

import type { UnifiedHITLRequest, HITLType } from '../types/hitl.unified';

interface UseUnifiedHITLReturn {
  /** All pending HITL requests for this conversation */
  pendingRequests: UnifiedHITLRequest[];

  /** The highest priority pending request (first pending one) */
  currentRequest: UnifiedHITLRequest | null;

  /** Number of pending requests */
  pendingCount: number;

  /** Check if there are any pending requests */
  hasPending: boolean;

  /** Get requests by type */
  getByType: (type: HITLType) => UnifiedHITLRequest[];

  /** Get the next pending request after the given one (for multiple HITL) */
  getNextPendingRequest: (currentRequestId: string) => UnifiedHITLRequest | null;
}

/**
 * Bridge hook connecting agentV3Store to unifiedHITLStore
 */
export function useUnifiedHITL(conversationId: string | null): UseUnifiedHITLReturn {
  const { handleSSEEvent } = useUnifiedHITLStore();

  // Get pending HITL states from agentV3Store
  const pendingClarification = useAgentV3Store((state) => state.pendingClarification);
  const pendingDecision = useAgentV3Store((state) => state.pendingDecision);
  const pendingEnvVarRequest = useAgentV3Store((state) => state.pendingEnvVarRequest);
  const pendingPermission = useAgentV3Store((state) => state.pendingPermission);

  // Get pending requests from unified store
  const pendingRequests = usePendingRequests(conversationId || '');

  // Bridge: Forward SSE events to unified store when they change
  useEffect(() => {
    if (!conversationId) return;

    if (pendingClarification && pendingClarification.request_id) {
      // Construct SSE-like data from old format
      handleSSEEvent(
        'clarification_asked',
        {
          request_id: pendingClarification.request_id,
          message: pendingClarification.message || pendingClarification.question,
          question: pendingClarification.question || pendingClarification.message,
          options: pendingClarification.options,
          allow_custom: pendingClarification.allow_custom ?? true,
          timeout_seconds: pendingClarification.timeout_seconds || 300,
          context: pendingClarification.context || {},
          clarification_type: pendingClarification.clarification_type || 'custom',
        },
        conversationId
      );
    }
  }, [conversationId, pendingClarification, handleSSEEvent]);

  useEffect(() => {
    if (!conversationId) return;

    if (pendingDecision && pendingDecision.request_id) {
      handleSSEEvent(
        'decision_asked',
        {
          request_id: pendingDecision.request_id,
          title: pendingDecision.title,
          description: pendingDecision.description,
          options: pendingDecision.options,
          default_option: pendingDecision.default_option,
          timeout_seconds: pendingDecision.timeout_seconds || 300,
          context: pendingDecision.context || {},
          decision_type: pendingDecision.decision_type || 'custom',
        },
        conversationId
      );
    }
  }, [conversationId, pendingDecision, handleSSEEvent]);

  useEffect(() => {
    if (!conversationId) return;

    if (pendingEnvVarRequest && pendingEnvVarRequest.request_id) {
      handleSSEEvent(
        'env_var_requested',
        {
          request_id: pendingEnvVarRequest.request_id,
          tool_name: pendingEnvVarRequest.tool_name,
          message: pendingEnvVarRequest.message,
          fields: pendingEnvVarRequest.fields,
          allow_save: pendingEnvVarRequest.allow_save ?? true,
          timeout_seconds: pendingEnvVarRequest.timeout_seconds || 300,
          context: pendingEnvVarRequest.context || {},
        },
        conversationId
      );
    }
  }, [conversationId, pendingEnvVarRequest, handleSSEEvent]);

  useEffect(() => {
    if (!conversationId) return;

    if (pendingPermission && pendingPermission.request_id) {
      // Map from PermissionAskedEventData to unified format
      // Note: Some fields may not exist in the old format
      handleSSEEvent(
        'permission_asked',
        {
          request_id: pendingPermission.request_id,
          tool_name: pendingPermission.tool_name,
          // 'action' maps to 'permission_type' in old format
          action: pendingPermission.permission_type || 'ask',
          risk_level: pendingPermission.risk_level || 'medium',
          description: pendingPermission.description,
          // These may not exist in old format
          details: pendingPermission.context || {},
          allow_remember: true,
          default_action: undefined,
          timeout_seconds: 300,
          context: pendingPermission.context || {},
        },
        conversationId
      );
    }
  }, [conversationId, pendingPermission, handleSSEEvent]);

  // Computed values
  const currentRequest = useMemo(() => {
    if (pendingRequests.length === 0) return null;

    // 按 createdAt 排序（最早的在前）
    const sorted = [...pendingRequests].sort(
      (a, b) => new Date(a.createdAt).getTime() - new Date(b.createdAt).getTime()
    );

    // 返回第一个 pending 状态的请求
    // 在多次 HITL 场景下，这确保用户按顺序处理每个请求
    return sorted.find((r) => r.status === 'pending') || sorted[0];
  }, [pendingRequests]);

  // 获取下一个待处理请求的函数（用于处理多个 HITL）
  const getNextPendingRequest = useMemo(() => {
    return (currentRequestId: string) => {
      if (pendingRequests.length <= 1) return null;

      const sorted = [...pendingRequests].sort(
        (a, b) => new Date(a.createdAt).getTime() - new Date(b.createdAt).getTime()
      );

      const currentIndex = sorted.findIndex((r) => r.requestId === currentRequestId);
      return sorted[currentIndex + 1] || null;
    };
  }, [pendingRequests]);

  const getByType = useMemo(() => {
    return (type: HITLType) => pendingRequests.filter((r) => r.hitlType === type);
  }, [pendingRequests]);

  return {
    pendingRequests,
    currentRequest,
    pendingCount: pendingRequests.length,
    hasPending: pendingRequests.length > 0,
    getByType,
    getNextPendingRequest,
  };
}

export default useUnifiedHITL;
