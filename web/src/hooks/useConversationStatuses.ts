/**
 * useConversationStatuses - Hook to get conversation status map
 * 
 * Provides a Map of conversation IDs to their status (streaming, HITL pending, etc.)
 * for use in conversation list components.
 * 
 * @packageDocumentation
 */

import { useMemo } from 'react';

import { useAgentV3Store } from '../stores/agentV3';

import type { ConversationStatus } from '../components/agent/ConversationSidebar';
import type { HITLSummary } from '../types/conversationState';

/**
 * Get status map for all conversations
 * 
 * @returns Map of conversation ID to status
 * 
 * @example
 * ```tsx
 * const { conversationStatuses, pendingHITLCount, streamingCount } = useConversationStatuses();
 * 
 * return (
 *   <ConversationSidebar
 *     conversations={conversations}
 *     conversationStatuses={conversationStatuses}
 *   />
 * );
 * ```
 */
export function useConversationStatuses() {
    const conversationStates = useAgentV3Store((state) => state.conversationStates);
    const getConversationsWithPendingHITL = useAgentV3Store((state) => state.getConversationsWithPendingHITL);
    const getStreamingConversationCount = useAgentV3Store((state) => state.getStreamingConversationCount);

    const conversationStatuses = useMemo(() => {
        const statusMap = new Map<string, ConversationStatus>();

        conversationStates.forEach((state, conversationId) => {
            // Determine HITL summary
            let pendingHITL: HITLSummary | null = null;
            if (state.pendingClarification) {
                pendingHITL = {
                    requestId: state.pendingClarification.request_id,
                    type: 'clarification',
                    title: 'Awaiting clarification',
                    createdAt: new Date().toISOString(),
                    isExpired: false,
                };
            } else if (state.pendingDecision) {
                pendingHITL = {
                    requestId: state.pendingDecision.request_id,
                    type: 'decision',
                    title: 'Awaiting decision',
                    createdAt: new Date().toISOString(),
                    isExpired: false,
                };
            } else if (state.pendingEnvVarRequest) {
                pendingHITL = {
                    requestId: state.pendingEnvVarRequest.request_id,
                    type: 'env_var',
                    title: 'Awaiting input',
                    createdAt: new Date().toISOString(),
                    isExpired: false,
                };
            }

            statusMap.set(conversationId, {
                isStreaming: state.isStreaming,
                pendingHITL,
            });
        });

        return statusMap;
    }, [conversationStates]);

    // Count conversations with pending HITL
    const pendingHITLCount = useMemo(() => {
        return getConversationsWithPendingHITL().length;
    }, [getConversationsWithPendingHITL]);

    // Count streaming conversations
    const streamingCount = useMemo(() => {
        return getStreamingConversationCount();
    }, [getStreamingConversationCount]);

    return {
        conversationStatuses,
        pendingHITLCount,
        streamingCount,
    };
}

/**
 * Get status for a single conversation
 * 
 * @param conversationId - Conversation ID to get status for
 * @returns Conversation status or undefined
 */
export function useConversationStatus(conversationId: string | null): ConversationStatus | undefined {
    const getConversationState = useAgentV3Store((state) => state.getConversationState);

    return useMemo(() => {
        if (!conversationId) return undefined;

        const state = getConversationState(conversationId);

        // Determine HITL summary
        let pendingHITL: HITLSummary | null = null;
        if (state.pendingClarification) {
            pendingHITL = {
                requestId: state.pendingClarification.request_id,
                type: 'clarification',
                title: 'Awaiting clarification',
                createdAt: new Date().toISOString(),
                isExpired: false,
            };
        } else if (state.pendingDecision) {
            pendingHITL = {
                requestId: state.pendingDecision.request_id,
                type: 'decision',
                title: 'Awaiting decision',
                createdAt: new Date().toISOString(),
                isExpired: false,
            };
        } else if (state.pendingEnvVarRequest) {
            pendingHITL = {
                requestId: state.pendingEnvVarRequest.request_id,
                type: 'env_var',
                title: 'Awaiting input',
                createdAt: new Date().toISOString(),
                isExpired: false,
            };
        }

        return {
            isStreaming: state.isStreaming,
            pendingHITL,
        };
    }, [conversationId, getConversationState]);
}

export default useConversationStatuses;
