/**
 * Skill API Service
 *
 * Provides API methods for Skill management including CRUD operations,
 * status management, skill matching, and tenant skill configurations.
 */

import { httpClient } from './client/httpClient';

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
} from '../types/agent';

// Use centralized HTTP client
const api = httpClient;

export interface SkillListParams {
  status?: 'active' | 'disabled' | 'deprecated' | null | undefined;
  scope?: 'system' | 'tenant' | 'project' | null | undefined;
  trigger_type?: 'keyword' | 'semantic' | 'hybrid' | null | undefined;
  skip?: number | undefined;
  limit?: number | undefined;
}

export interface SkillMatchParams {
  query: string;
  threshold?: number | undefined;
  limit?: number | undefined;
}

export const skillAPI = {
  /**
   * List all Skills
   */
  list: async (params: SkillListParams = {}): Promise<SkillsListResponse> => {
    return await api.get<SkillsListResponse>('/skills/', { params });
  },

  /**
   * List system skills
   */
  listSystemSkills: async (
    params: { status?: string | undefined } = {}
  ): Promise<SkillsListResponse> => {
    return await api.get<SkillsListResponse>('/skills/system/list', { params });
  },

  /**
   * Create a new Skill
   */
  create: async (data: SkillCreate): Promise<SkillResponse> => {
    return await api.post<SkillResponse>('/skills/', data);
  },

  /**
   * Get a Skill by ID
   */
  get: async (skillId: string): Promise<SkillResponse> => {
    return await api.get<SkillResponse>(`/skills/${skillId}`);
  },

  /**
   * Update a Skill
   */
  update: async (skillId: string, data: SkillUpdate): Promise<SkillResponse> => {
    return await api.put<SkillResponse>(`/skills/${skillId}`, data);
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
    status: 'active' | 'disabled' | 'deprecated'
  ): Promise<SkillResponse> => {
    return await api.patch<SkillResponse>(`/skills/${skillId}/status`, null, {
      params: { status },
    });
  },

  /**
   * Match skills based on query
   */
  match: async (params: SkillMatchParams): Promise<SkillMatchResponse> => {
    return await api.post<SkillMatchResponse>('/skills/match', params);
  },

  /**
   * Get skill content
   */
  getContent: async (skillId: string): Promise<SkillContentResponse> => {
    return await api.get<SkillContentResponse>(`/skills/${skillId}/content`);
  },

  /**
   * Update skill content
   */
  updateContent: async (skillId: string, fullContent: string): Promise<SkillResponse> => {
    return await api.put<SkillResponse>(`/skills/${skillId}/content`, {
      full_content: fullContent,
    });
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
    return await api.get<TenantSkillConfigListResponse>('/tenant/skills/config/');
  },

  /**
   * Get a specific tenant skill config
   */
  get: async (systemSkillName: string): Promise<TenantSkillConfigResponse> => {
    return await api.get<TenantSkillConfigResponse>(`/tenant/skills/config/${systemSkillName}`);
  },

  /**
   * Disable a system skill
   */
  disable: async (systemSkillName: string): Promise<TenantSkillConfigResponse> => {
    return await api.post<TenantSkillConfigResponse>('/tenant/skills/config/disable', {
      system_skill_name: systemSkillName,
    });
  },

  /**
   * Override a system skill
   */
  override: async (
    systemSkillName: string,
    overrideSkillId: string
  ): Promise<TenantSkillConfigResponse> => {
    return await api.post<TenantSkillConfigResponse>('/tenant/skills/config/override', {
      system_skill_name: systemSkillName,
      override_skill_id: overrideSkillId,
    });
  },

  /**
   * Enable a previously disabled/overridden system skill
   */
  enable: async (systemSkillName: string): Promise<void> => {
    await api.post('/tenant/skills/config/enable', {
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
    return await api.get<SystemSkillStatus>(`/tenant/skills/config/status/${systemSkillName}`);
  },
};

export default skillAPI;
