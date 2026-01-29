/**
 * Plan Mode service for managing plan documents.
 *
 * This service provides methods for entering/exiting Plan Mode and
 * managing plan documents during the planning phase.
 */

import { httpClient } from "./client/httpClient";
import type {
  EnterPlanModeRequest,
  ExitPlanModeRequest,
  PlanDocument,
  PlanModeStatus,
  UpdatePlanRequest,
} from "../types/agent";

// Use centralized HTTP client
const api = httpClient;

/**
 * Plan service interface
 */
export interface PlanService {
  enterPlanMode(request: EnterPlanModeRequest): Promise<PlanDocument>;
  exitPlanMode(request: ExitPlanModeRequest): Promise<PlanDocument>;
  getPlan(planId: string): Promise<PlanDocument>;
  getConversationPlans(conversationId: string): Promise<PlanDocument[]>;
  updatePlan(planId: string, request: UpdatePlanRequest): Promise<PlanDocument>;
  submitPlanForReview(planId: string): Promise<PlanDocument>;
  getPlanModeStatus(conversationId: string): Promise<PlanModeStatus>;
}

/**
 * Plan service implementation
 */
class PlanServiceImpl implements PlanService {
  /**
   * Enter Plan Mode for a conversation
   */
  async enterPlanMode(request: EnterPlanModeRequest): Promise<PlanDocument> {
    return await api.post<PlanDocument>("/agent/plan/enter", request);
  }

  /**
   * Exit Plan Mode for a conversation
   */
  async exitPlanMode(request: ExitPlanModeRequest): Promise<PlanDocument> {
    return await api.post<PlanDocument>("/agent/plan/exit", request);
  }

  /**
   * Get a plan by ID
   */
  async getPlan(planId: string): Promise<PlanDocument> {
    return await api.get<PlanDocument>(`/agent/plan/${planId}`);
  }

  /**
   * Get all plans for a conversation
   */
  async getConversationPlans(conversationId: string): Promise<PlanDocument[]> {
    return await api.get<PlanDocument[]>(
      `/agent/conversations/${conversationId}/plans`
    );
  }

  /**
   * Update a plan document
   */
  async updatePlan(
    planId: string,
    request: UpdatePlanRequest
  ): Promise<PlanDocument> {
    return await api.put<PlanDocument>(`/agent/plan/${planId}`, request);
  }

  /**
   * Get Plan Mode status for a conversation
   */
  async getPlanModeStatus(conversationId: string): Promise<PlanModeStatus> {
    return await api.get<PlanModeStatus>(
      `/agent/conversations/${conversationId}/plan-mode`
    );
  }

  /**
   * Submit a plan for review (changes status from draft to reviewing)
   */
  async submitPlanForReview(planId: string): Promise<PlanDocument> {
    return await api.post<PlanDocument>(`/agent/plan/${planId}/submit`, {});
  }
}

export const planService = new PlanServiceImpl();
