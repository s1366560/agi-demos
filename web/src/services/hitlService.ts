/**
 * HITL Service - Human-in-the-Loop API Client
 * 
 * Provides methods to respond to HITL requests from the agent.
 */

import { httpClient } from './client/httpClient';

import type {
  ClarificationResponse,
  PermissionResponse,
  DecisionResponse,
  EnvVarResponse,
  HITLRequest,
  HITLResponse,
} from '../types/hitl';

/**
 * Base URL for HITL endpoints
 */
const HITL_BASE_URL = '/hitl';

/**
 * HITL Service API
 */
export const hitlService = {
  /**
   * Respond to a clarification request
   */
  async respondToClarification(
    conversationId: string,
    response: ClarificationResponse
  ): Promise<void> {
    await httpClient.post(
      `${HITL_BASE_URL}/clarification/${response.requestId}`,
      {
        conversation_id: conversationId,
        answer: response.answer,
      }
    );
  },

  /**
   * Respond to a permission request
   */
  async respondToPermission(
    conversationId: string,
    response: PermissionResponse
  ): Promise<void> {
    await httpClient.post(
      `${HITL_BASE_URL}/permission/${response.requestId}`,
      {
        conversation_id: conversationId,
        allowed: response.allowed,
        remember: response.remember,
      }
    );
  },

  /**
   * Respond to a decision request
   */
  async respondToDecision(
    conversationId: string,
    response: DecisionResponse
  ): Promise<void> {
    await httpClient.post(
      `${HITL_BASE_URL}/decision/${response.requestId}`,
      {
        conversation_id: conversationId,
        decision: response.decision,
      }
    );
  },

  /**
   * Respond to an environment variable request
   */
  async respondToEnvVar(
    conversationId: string,
    response: EnvVarResponse
  ): Promise<void> {
    await httpClient.post(
      `${HITL_BASE_URL}/env-var/${response.requestId}`,
      {
        conversation_id: conversationId,
        values: response.values,
        save: response.save,
      }
    );
  },

  /**
   * Generic respond method - dispatches to the correct handler
   */
  async respond(
    conversationId: string,
    request: HITLRequest,
    response: HITLResponse
  ): Promise<void> {
    switch (request.requestType) {
      case 'clarification':
        return this.respondToClarification(
          conversationId,
          response as ClarificationResponse
        );
      case 'permission':
        return this.respondToPermission(
          conversationId,
          response as PermissionResponse
        );
      case 'decision':
        return this.respondToDecision(
          conversationId,
          response as DecisionResponse
        );
      case 'env_var':
        return this.respondToEnvVar(
          conversationId,
          response as EnvVarResponse
        );
      default:
        throw new Error(`Unknown HITL request type: ${(request as HITLRequest).requestType}`);
    }
  },

  /**
   * Cancel a pending HITL request
   */
  async cancelRequest(
    conversationId: string,
    requestId: string
  ): Promise<void> {
    await httpClient.post(
      `${HITL_BASE_URL}/cancel/${requestId}`,
      {
        conversation_id: conversationId,
      }
    );
  },

  /**
   * Get pending HITL requests for a conversation
   */
  async getPendingRequests(conversationId: string): Promise<HITLRequest[]> {
    const response = await httpClient.get<{ requests: HITLRequest[] }>(
      `${HITL_BASE_URL}/pending`,
      {
        params: { conversation_id: conversationId },
      }
    );
    return response.requests;
  },

  /**
   * Get history of HITL interactions for a conversation
   */
  async getHistory(
    conversationId: string,
    limit = 50
  ): Promise<HITLRequest[]> {
    const response = await httpClient.get<{ requests: HITLRequest[] }>(
      `${HITL_BASE_URL}/history`,
      {
        params: { 
          conversation_id: conversationId,
          limit,
        },
      }
    );
    return response.requests;
  },
};

export default hitlService;
