/**
 * Skill API Service
 *
 * Provides API methods for Skill management including CRUD operations,
 * status management, skill matching, and tenant skill configurations.
 */

import axios from "axios";
import type {
  SkillResponse,
  SkillCreate,
  SkillUpdate,
  SkillsListResponse,
  SkillMatchResponse,
  SkillContentResponse,
  TenantSkillConfigResponse,
  TenantSkillConfigListResponse,
  SystemSkillStatus,
} from "../types/agent";

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || "/api/v1",
  headers: {
    "Content-Type": "application/json",
  },
});

// Request interceptor to add auth token
api.interceptors.request.use((config) => {
  const token = localStorage.getItem("token");
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Response interceptor to handle errors
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

export interface SkillListParams {
  status?: "active" | "disabled" | "deprecated" | null;
  scope?: "system" | "tenant" | "project" | null;
  trigger_type?: "keyword" | "semantic" | "hybrid" | null;
  skip?: number;
  limit?: number;
}

export interface SkillMatchParams {
  query: string;
  threshold?: number;
  limit?: number;
}

export const skillAPI = {
  /**
   * List all Skills
   */
  list: async (params: SkillListParams = {}): Promise<SkillsListResponse> => {
    const response = await api.get("/skills/", { params });
    return response.data;
  },

  /**
   * List system skills
   */
  listSystemSkills: async (
    params: { status?: string } = {}
  ): Promise<SkillsListResponse> => {
    const response = await api.get("/skills/system/list", { params });
    return response.data;
  },

  /**
   * Create a new Skill
   */
  create: async (data: SkillCreate): Promise<SkillResponse> => {
    const response = await api.post("/skills/", data);
    return response.data;
  },

  /**
   * Get a Skill by ID
   */
  get: async (skillId: string): Promise<SkillResponse> => {
    const response = await api.get(`/skills/${skillId}`);
    return response.data;
  },

  /**
   * Update a Skill
   */
  update: async (
    skillId: string,
    data: SkillUpdate
  ): Promise<SkillResponse> => {
    const response = await api.put(`/skills/${skillId}`, data);
    return response.data;
  },

  /**
   * Delete a Skill
   */
  delete: async (skillId: string): Promise<void> => {
    await api.delete(`/skills/${skillId}`);
  },

  /**
   * Update Skill status
   */
  updateStatus: async (
    skillId: string,
    status: "active" | "disabled" | "deprecated"
  ): Promise<SkillResponse> => {
    const response = await api.patch(`/skills/${skillId}/status`, null, {
      params: { status },
    });
    return response.data;
  },

  /**
   * Match skills based on query
   */
  match: async (params: SkillMatchParams): Promise<SkillMatchResponse> => {
    const response = await api.post("/skills/match", params);
    return response.data;
  },

  /**
   * Get skill content
   */
  getContent: async (skillId: string): Promise<SkillContentResponse> => {
    const response = await api.get(`/skills/${skillId}/content`);
    return response.data;
  },

  /**
   * Update skill content
   */
  updateContent: async (
    skillId: string,
    fullContent: string
  ): Promise<SkillResponse> => {
    const response = await api.put(`/skills/${skillId}/content`, {
      full_content: fullContent,
    });
    return response.data;
  },
};

/**
 * Tenant Skill Config API
 */
export const tenantSkillConfigAPI = {
  /**
   * List all tenant skill configs
   */
  list: async (): Promise<TenantSkillConfigListResponse> => {
    const response = await api.get("/tenant/skills/config/");
    return response.data;
  },

  /**
   * Get a specific tenant skill config
   */
  get: async (systemSkillName: string): Promise<TenantSkillConfigResponse> => {
    const response = await api.get(`/tenant/skills/config/${systemSkillName}`);
    return response.data;
  },

  /**
   * Disable a system skill
   */
  disable: async (
    systemSkillName: string
  ): Promise<TenantSkillConfigResponse> => {
    const response = await api.post("/tenant/skills/config/disable", {
      system_skill_name: systemSkillName,
    });
    return response.data;
  },

  /**
   * Override a system skill
   */
  override: async (
    systemSkillName: string,
    overrideSkillId: string
  ): Promise<TenantSkillConfigResponse> => {
    const response = await api.post("/tenant/skills/config/override", {
      system_skill_name: systemSkillName,
      override_skill_id: overrideSkillId,
    });
    return response.data;
  },

  /**
   * Enable a previously disabled/overridden system skill
   */
  enable: async (systemSkillName: string): Promise<void> => {
    await api.post("/tenant/skills/config/enable", {
      system_skill_name: systemSkillName,
    });
  },

  /**
   * Delete a tenant skill config
   */
  delete: async (systemSkillName: string): Promise<void> => {
    await api.delete(`/tenant/skills/config/${systemSkillName}`);
  },

  /**
   * Get status of a system skill
   */
  getStatus: async (systemSkillName: string): Promise<SystemSkillStatus> => {
    const response = await api.get(
      `/tenant/skills/config/status/${systemSkillName}`
    );
    return response.data;
  },
};

export default skillAPI;
