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

import type {
  ClarificationAskedEventData,
  DecisionAskedEventData,
  EnvVarRequestedEventData,
  PermissionAskedEventData,
  EnvVarField as LegacyEnvVarField,
} from '../types/agent/events';
import type {
  UnifiedHITLRequest,
  HITLType,
  ClarificationOption,
  DecisionOption,
  EnvVarField as UnifiedEnvVarField,
} from '../types/hitl.unified';

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
 * Convert legacy EnvVarField to unified format
 */
function convertEnvVarFields(fields: LegacyEnvVarField[]): UnifiedEnvVarField[] {
  return fields.map((field) => ({
    name: field.name,
    label: field.label,
    description: field.description,
    required: field.required,
    secret: false, // Legacy format doesn't have this field, default to false
    inputType: field.input_type,
    defaultValue: field.default_value,
    placeholder: field.placeholder,
  }));
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
    if (!conversationId || !pendingClarification?.request_id) return;

    // Map ClarificationAskedEventData to unified format
    const data: ClarificationAskedEventData = pendingClarification;
    handleSSEEvent(
      'clarification_asked',
      {
        request_id: data.request_id,
        message: data.question,
        question: data.question,
        options: data.options as ClarificationOption[],
        allow_custom: data.allow_custom,
        timeout_seconds: 300,
        context: data.context,
        clarification_type: data.clarification_type,
      },
      conversationId
    );
  }, [conversationId, pendingClarification, handleSSEEvent]);

  useEffect(() => {
    if (!conversationId || !pendingDecision?.request_id) return;

    // Map DecisionAskedEventData to unified format
    const data: DecisionAskedEventData = pendingDecision;
    handleSSEEvent(
      'decision_asked',
      {
        request_id: data.request_id,
        title: data.question,
        description: data.question,
        options: data.options as DecisionOption[],
        default_option: data.default_option,
        timeout_seconds: 300,
        context: data.context,
        decision_type: data.decision_type,
      },
      conversationId
    );
  }, [conversationId, pendingDecision, handleSSEEvent]);

  useEffect(() => {
    if (!conversationId || !pendingEnvVarRequest?.request_id) return;

    // Map EnvVarRequestedEventData to unified format
    const data: EnvVarRequestedEventData = pendingEnvVarRequest;
    handleSSEEvent(
      'env_var_requested',
      {
        request_id: data.request_id,
        tool_name: data.tool_name,
        message: data.message || '',
        fields: convertEnvVarFields(data.fields),
        allow_save: true,
        timeout_seconds: 300,
        context: data.context || {},
      },
      conversationId
    );
  }, [conversationId, pendingEnvVarRequest, handleSSEEvent]);

  useEffect(() => {
    if (!conversationId || !pendingPermission?.request_id) return;

    // Map PermissionAskedEventData to unified format
    const data: PermissionAskedEventData = pendingPermission;
    handleSSEEvent(
      'permission_asked',
      {
        request_id: data.request_id,
        tool_name: data.tool_name,
        action: data.permission_type,
        risk_level: data.risk_level ?? 'medium',
        description: data.description,
        details: data.context ?? {},
        allow_remember: true,
        default_action: undefined,
        timeout_seconds: 300,
        context: data.context ?? {},
      },
      conversationId
    );
  }, [conversationId, pendingPermission, handleSSEEvent]);

  // Computed values
  const currentRequest = useMemo(() => {
    if (pendingRequests.length === 0) return null;

    // 按 createdAt 排序（最早的在前)
    const sorted = [...pendingRequests].sort(
      (a, b) => new Date(a.createdAt).getTime() - new Date(b.createdAt).getTime()
    );

    // 返回第一个 pending 状态的请求
    // 在多次 HITL 场景下，这确保用户按顺序处理每个请求
    const pending = sorted.find((r) => r.status === 'pending');
    // If no pending request, return the first one
    return pending ?? sorted[0] ?? null;
  }, [pendingRequests]);

  // 获取下一个待处理请求的函数（用于处理多个 HITL）
  const getNextPendingRequest = useMemo(() => {
    return (currentRequestId: string) => {
      if (pendingRequests.length <= 1) return null;

      const sorted = [...pendingRequests].sort(
        (a, b) => new Date(a.createdAt).getTime() - new Date(b.createdAt).getTime()
      );

      const currentIndex = sorted.findIndex((r) => r.requestId === currentRequestId);
      // If not found or last item, return null
      if (currentIndex === -1 || currentIndex >= sorted.length - 1) return null;
      return sorted[currentIndex + 1] ?? null;
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
