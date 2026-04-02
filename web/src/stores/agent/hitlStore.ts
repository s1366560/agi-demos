/**
 * Agent HITL Interactivity Store - Extracted from agentV3.ts (Wave 2)
 *
 * READ consumers read from this store. WRITE consumers (respond actions)
 * stay in agentV3.ts because they atomically set cross-domain state
 * (agentState, isStreaming, streamStatus). agentV3.ts bridges writes
 * via exported setters from updateConversationState/setActiveConversation.
 */

import { create } from 'zustand';
import { devtools } from 'zustand/middleware';

import { agentService } from '../../services/agentService';
import { logger } from '../../utils/logger';

import type {
  ClarificationAskedEventData,
  ClarificationType,
  ClarificationOption,
  DecisionAskedEventData,
  DecisionType,
  DecisionOption,
  EnvVarRequestedEventData,
  EnvVarField,
  PermissionAskedEventData,
  DoomLoopDetectedEventData,
} from '../../types/agent';
import type { CostTrackingState } from '../../types/conversationState';

// -- State --

interface AgentHITLState {
  pendingClarification: ClarificationAskedEventData | null;
  pendingDecision: DecisionAskedEventData | null;
  pendingEnvVarRequest: EnvVarRequestedEventData | null;
  pendingPermission: PermissionAskedEventData | null;
  doomLoopDetected: DoomLoopDetectedEventData | null;
  costTracking: CostTrackingState | null;
  suggestions: string[];
  pinnedEventIds: Set<string>;

  togglePinEvent: (eventId: string) => void;
  loadPendingHITL: (conversationId: string) => Promise<void>;

  setPendingClarification: (value: ClarificationAskedEventData | null) => void;
  setPendingDecision: (value: DecisionAskedEventData | null) => void;
  setPendingEnvVarRequest: (value: EnvVarRequestedEventData | null) => void;
  setPendingPermission: (value: PermissionAskedEventData | null) => void;
  setDoomLoopDetected: (value: DoomLoopDetectedEventData | null) => void;
  setCostTracking: (value: CostTrackingState | null) => void;
  setSuggestions: (value: string[]) => void;
  setPinnedEventIds: (value: Set<string>) => void;

  syncFromConversation: (fields: {
    pendingClarification?: ClarificationAskedEventData | null | undefined;
    pendingDecision?: DecisionAskedEventData | null | undefined;
    pendingEnvVarRequest?: EnvVarRequestedEventData | null | undefined;
    pendingPermission?: PermissionAskedEventData | null | undefined;
    doomLoopDetected?: DoomLoopDetectedEventData | null | undefined;
    costTracking?: CostTrackingState | null | undefined;
    suggestions?: string[] | undefined;
    pinnedEventIds?: Set<string> | undefined;
  }) => void;
}

// -- Store --

export const useAgentHITLStore = create<AgentHITLState>()(
  devtools(
    (set, get) => ({
      pendingClarification: null,
      pendingDecision: null,
      pendingEnvVarRequest: null,
      pendingPermission: null,
      doomLoopDetected: null,
      costTracking: null,
      suggestions: [],
      pinnedEventIds: new Set(),

      togglePinEvent: (eventId: string) => {
        const { pinnedEventIds } = get();
        const next = new Set(pinnedEventIds);
        if (next.has(eventId)) {
          next.delete(eventId);
        } else {
          next.add(eventId);
        }
        set({ pinnedEventIds: next });
      },

      loadPendingHITL: async (conversationId: string) => {
        logger.debug(
          '[hitlStore] Loading pending HITL requests for conversation:',
          conversationId
        );
        try {
          const response = await agentService.getPendingHITLRequests(conversationId);
          logger.debug('[hitlStore] Pending HITL response:', response);

          if (response.requests.length === 0) {
            logger.debug('[hitlStore] No pending HITL requests');
            return;
          }

          // Process each pending request and restore dialog state
          for (const request of response.requests) {
            logger.debug(
              '[hitlStore] Restoring pending HITL request:',
              request.request_type,
              request.id
            );

            switch (request.request_type) {
              case 'clarification':
                set({
                  pendingClarification: {
                    request_id: request.id,
                    question: request.question,
                    clarification_type:
                      (request.metadata?.clarification_type as ClarificationType) || 'custom',
                    options: (request.options as ClarificationOption[] | undefined) || [],
                    allow_custom: (request.metadata?.allow_custom as boolean) ?? true,
                    context: request.context || {},
                  },
                });
                break;

              case 'decision':
                set({
                  pendingDecision: {
                    request_id: request.id,
                    question: request.question,
                    decision_type:
                      (request.metadata?.decision_type as DecisionType) || 'custom',
                    options: (request.options as DecisionOption[] | undefined) || [],
                    allow_custom: (request.metadata?.allow_custom as boolean) ?? true,
                    context: request.context || {},
                  },
                });
                break;

              case 'env_var': {
                const fields = (request.options as EnvVarField[] | undefined) || [];
                set({
                  pendingEnvVarRequest: {
                    request_id: request.id,
                    tool_name: (request.metadata?.tool_name as string) || 'unknown',
                    fields: fields,
                    message: request.question,
                    context: request.context || {},
                  },
                });
                break;
              }
            }

            // Only restore the first pending request (user should answer one at a time)
            break;
          }
        } catch (error) {
          console.error('[hitlStore] Failed to load pending HITL requests:', error);
          // Don't throw - this is a recovery mechanism, not critical
        }
      },

      // Setter actions for bridge from agentV3.ts
      setPendingClarification: (value) => set({ pendingClarification: value }),
      setPendingDecision: (value) => set({ pendingDecision: value }),
      setPendingEnvVarRequest: (value) => set({ pendingEnvVarRequest: value }),
      setPendingPermission: (value) => set({ pendingPermission: value }),
      setDoomLoopDetected: (value) => set({ doomLoopDetected: value }),
      setCostTracking: (value) => set({ costTracking: value }),
      setSuggestions: (value) => set({ suggestions: value }),
      setPinnedEventIds: (value) => set({ pinnedEventIds: value }),

      syncFromConversation: (fields) => {
        const updates: Partial<AgentHITLState> = {};
        if (fields.pendingClarification !== undefined)
          updates.pendingClarification = fields.pendingClarification;
        if (fields.pendingDecision !== undefined)
          updates.pendingDecision = fields.pendingDecision;
        if (fields.pendingEnvVarRequest !== undefined)
          updates.pendingEnvVarRequest = fields.pendingEnvVarRequest;
        if (fields.pendingPermission !== undefined)
          updates.pendingPermission = fields.pendingPermission;
        if (fields.doomLoopDetected !== undefined)
          updates.doomLoopDetected = fields.doomLoopDetected;
        if (fields.costTracking !== undefined) updates.costTracking = fields.costTracking;
        if (fields.suggestions !== undefined) updates.suggestions = fields.suggestions;
        if (fields.pinnedEventIds !== undefined) updates.pinnedEventIds = fields.pinnedEventIds;
        if (Object.keys(updates).length > 0) {
          set(updates);
        }
      },
    }),
    { name: 'agent-hitl-store' }
  )
);

// -- Selectors (single-value, no useShallow needed) --

export const usePendingClarification = () =>
  useAgentHITLStore((state) => state.pendingClarification);
export const usePendingDecision = () => useAgentHITLStore((state) => state.pendingDecision);
export const usePendingEnvVarRequest = () =>
  useAgentHITLStore((state) => state.pendingEnvVarRequest);
export const usePendingPermission = () => useAgentHITLStore((state) => state.pendingPermission);
export const useDoomLoopDetected = () => useAgentHITLStore((state) => state.doomLoopDetected);
export const useCostTracking = () => useAgentHITLStore((state) => state.costTracking);
export const useSuggestions = () => useAgentHITLStore((state) => state.suggestions);
export const usePinnedEventIds = () => useAgentHITLStore((state) => state.pinnedEventIds);
