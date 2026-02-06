/**
 * Unified HITL Service - Human-in-the-Loop API Client
 *
 * New Temporal-based implementation that uses a single unified endpoint.
 * Replaces the legacy multiple endpoint approach.
 *
 * Architecture:
 *   Frontend → POST /hitl/respond → API → Temporal Signal → Workflow
 */

import { apiToUnifiedRequest, buildResponseData } from '../types/hitl.unified';

import { httpClient } from './client/httpClient';

import type {
  HITLType,
  HITLResponseData,
  HITLRespondRequest,
  HITLCancelRequest,
  HITLApiResponse,
  PendingHITLResponse,
  UnifiedHITLRequest,
  ClarificationResponseData,
  DecisionResponseData,
  EnvVarResponseData,
  PermissionResponseData,
} from '../types/hitl.unified';

/**
 * Base URL for HITL endpoints
 */
const HITL_BASE_URL = '/agent/hitl';

/**
 * Unified HITL Service
 */
export const unifiedHitlService = {
  /**
   * Submit a response to any HITL request using the unified endpoint.
   * This sends a Temporal Signal to the running workflow.
   *
   * @param requestId - The HITL request ID
   * @param hitlType - Type of HITL request
   * @param responseData - Type-specific response data
   */
  async respond(
    requestId: string,
    hitlType: HITLType,
    responseData: HITLResponseData
  ): Promise<HITLApiResponse> {
    const payload: HITLRespondRequest = {
      requestId,
      hitlType,
      responseData: buildResponseData(hitlType, responseData),
    };

    // Convert to snake_case for API
    const apiPayload = {
      request_id: payload.requestId,
      hitl_type: payload.hitlType,
      response_data: payload.responseData,
    };

    const response = await httpClient.post<HITLApiResponse>(`${HITL_BASE_URL}/respond`, apiPayload);

    return response;
  },

  /**
   * Convenience method for clarification responses
   */
  async respondToClarification(
    requestId: string,
    answer: string | string[]
  ): Promise<HITLApiResponse> {
    return this.respond(requestId, 'clarification', { answer });
  },

  /**
   * Convenience method for decision responses
   */
  async respondToDecision(
    requestId: string,
    decision: string | string[]
  ): Promise<HITLApiResponse> {
    return this.respond(requestId, 'decision', { decision });
  },

  /**
   * Convenience method for environment variable responses
   */
  async respondToEnvVar(
    requestId: string,
    values: Record<string, string>,
    save: boolean = false
  ): Promise<HITLApiResponse> {
    return this.respond(requestId, 'env_var', { values, save });
  },

  /**
   * Convenience method for permission responses
   */
  async respondToPermission(
    requestId: string,
    action: 'allow' | 'deny' | 'allow_always' | 'deny_always',
    remember: boolean = false
  ): Promise<HITLApiResponse> {
    return this.respond(requestId, 'permission', { action, remember });
  },

  /**
   * Cancel a pending HITL request
   */
  async cancel(requestId: string, reason?: string): Promise<HITLApiResponse> {
    const payload: HITLCancelRequest = {
      requestId,
      reason,
    };

    const apiPayload = {
      request_id: payload.requestId,
      reason: payload.reason,
    };

    return httpClient.post<HITLApiResponse>(`${HITL_BASE_URL}/cancel`, apiPayload);
  },

  /**
   * Get pending HITL requests for a conversation
   */
  async getPendingRequests(conversationId: string): Promise<UnifiedHITLRequest[]> {
    const response = await httpClient.get<PendingHITLResponse>(
      `/agent/hitl/conversations/${conversationId}/pending`
    );

    return response.requests.map((r) => apiToUnifiedRequest(r, conversationId));
  },

  /**
   * Get pending HITL requests for a project
   */
  async getProjectPendingRequests(
    projectId: string,
    limit: number = 50
  ): Promise<UnifiedHITLRequest[]> {
    const response = await httpClient.get<PendingHITLResponse>(
      `/agent/hitl/projects/${projectId}/pending`,
      { params: { limit } }
    );

    return response.requests.map((r) => apiToUnifiedRequest(r, r.conversation_id));
  },
};

// =============================================================================
// Response Builder Helpers
// =============================================================================

/**
 * Create a clarification response
 */
export function createClarificationResponse(answer: string | string[]): ClarificationResponseData {
  return { answer };
}

/**
 * Create a decision response
 */
export function createDecisionResponse(decision: string | string[]): DecisionResponseData {
  return { decision };
}

/**
 * Create an environment variable response
 */
export function createEnvVarResponse(
  values: Record<string, string>,
  save: boolean = false
): EnvVarResponseData {
  return { values, save };
}

/**
 * Create a permission response
 */
export function createPermissionResponse(
  action: 'allow' | 'deny' | 'allow_always' | 'deny_always',
  remember: boolean = false
): PermissionResponseData {
  return { action, remember };
}

export default unifiedHitlService;
