/**
 * Plan Mode service for managing plan documents.
 *
 * This service provides methods for entering/exiting Plan Mode and
 * managing plan documents during the planning phase.
 */

import axios from "axios";
import type {
  EnterPlanModeRequest,
  ExitPlanModeRequest,
  PlanDocument,
  PlanModeStatus,
  UpdatePlanRequest,
} from "../types/agent";

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || "",
  headers: {
    "Content-Type": "application/json",
  },
});

// Add auth token to requests
api.interceptors.request.use((config) => {
  const token = localStorage.getItem("token");
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Handle auth errors
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem("token");
      localStorage.removeItem("user");
      if (window.location.pathname !== "/login") {
        window.location.href = "/login";
      }
    }
    return Promise.reject(error);
  }
);

/**
 * Plan service interface
 */
export interface PlanService {
  enterPlanMode(request: EnterPlanModeRequest): Promise<PlanDocument>;
  exitPlanMode(request: ExitPlanModeRequest): Promise<PlanDocument>;
  getPlan(planId: string): Promise<PlanDocument>;
  getConversationPlans(conversationId: string): Promise<PlanDocument[]>;
  updatePlan(planId: string, request: UpdatePlanRequest): Promise<PlanDocument>;
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
    const response = await api.post<PlanDocument>(
      "/api/v1/agent/plan/enter",
      request
    );
    return response.data;
  }

  /**
   * Exit Plan Mode for a conversation
   */
  async exitPlanMode(request: ExitPlanModeRequest): Promise<PlanDocument> {
    const response = await api.post<PlanDocument>(
      "/api/v1/agent/plan/exit",
      request
    );
    return response.data;
  }

  /**
   * Get a plan by ID
   */
  async getPlan(planId: string): Promise<PlanDocument> {
    const response = await api.get<PlanDocument>(
      `/api/v1/agent/plan/${planId}`
    );
    return response.data;
  }

  /**
   * Get all plans for a conversation
   */
  async getConversationPlans(conversationId: string): Promise<PlanDocument[]> {
    const response = await api.get<PlanDocument[]>(
      `/api/v1/agent/conversations/${conversationId}/plans`
    );
    return response.data;
  }

  /**
   * Update a plan document
   */
  async updatePlan(
    planId: string,
    request: UpdatePlanRequest
  ): Promise<PlanDocument> {
    const response = await api.put<PlanDocument>(
      `/api/v1/agent/plan/${planId}`,
      request
    );
    return response.data;
  }

  /**
   * Get Plan Mode status for a conversation
   */
  async getPlanModeStatus(conversationId: string): Promise<PlanModeStatus> {
    const response = await api.get<PlanModeStatus>(
      `/api/v1/agent/conversations/${conversationId}/plan-mode`
    );
    return response.data;
  }
}

export const planService = new PlanServiceImpl();
