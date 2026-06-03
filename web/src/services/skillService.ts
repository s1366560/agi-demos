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
  SkillContentResponse,
  SkillImportRequest,
  SkillZipImportRequest,
  SkillLifecycleResponse,
  SkillPackageResponse,
  SkillEvolutionDetailResponse,
  SkillEvolutionOverviewResponse,
  SkillEvolutionRunResponse,
  SkillVersionDetailResponse,
  SkillVersionListResponse,
  TenantSkillConfigResponse,
  TenantSkillConfigListResponse,
  SystemSkillStatus,
} from '../types/agent';

// Use centralized HTTP client
const api = httpClient;

export interface SkillListParams {
  search?: string | undefined;
  q?: string | undefined;
  status?: 'active' | 'disabled' | 'deprecated' | null | undefined;
  scope?: 'system' | 'tenant' | 'project' | null | undefined;
  project_id?: string | null | undefined;
  skip?: number | undefined;
  offset?: number | undefined;
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

  /**
   * Import a complete AgentSkills.io package.
   */
  importPackage: async (data: SkillImportRequest): Promise<SkillLifecycleResponse> => {
    return await api.post<SkillLifecycleResponse>('/skills/import', data);
  },

  /**
   * Import a zipped Agent Skills directory containing SKILL.md and bundled files.
   */
  importZip: async (
    file: File,
    data: SkillZipImportRequest = {}
  ): Promise<SkillLifecycleResponse> => {
    const formData = new FormData();
    formData.append('archive', file);
    formData.append('scope', data.scope ?? 'tenant');
    formData.append('overwrite', String(data.overwrite ?? false));
    if (data.project_id) {
      formData.append('project_id', data.project_id);
    }
    if (data.change_summary) {
      formData.append('change_summary', data.change_summary);
    }
    return await api.upload<SkillLifecycleResponse>('/skills/import/zip', formData);
  },

  /**
   * Export a Skill as an AgentSkills.io package.
   */
  exportPackage: async (skillId: string): Promise<SkillPackageResponse> => {
    return await api.get<SkillPackageResponse>(`/skills/${skillId}/export`);
  },

  /**
   * List version snapshots for a Skill.
   */
  listVersions: async (
    skillId: string,
    params: { limit?: number | undefined; offset?: number | undefined } = {}
  ): Promise<SkillVersionListResponse> => {
    return await api.get<SkillVersionListResponse>(`/skills/${skillId}/versions`, { params });
  },

  /**
   * Read a specific version snapshot.
   */
  getVersion: async (
    skillId: string,
    versionNumber: number
  ): Promise<SkillVersionDetailResponse> => {
    return await api.get<SkillVersionDetailResponse>(
      `/skills/${skillId}/versions/${String(versionNumber)}`
    );
  },

  /**
   * Roll a Skill back to a previous version snapshot.
   */
  rollback: async (skillId: string, versionNumber: number): Promise<SkillResponse> => {
    return await api.post<SkillResponse>(`/skills/${skillId}/rollback`, {
      version_number: versionNumber,
    });
  },

  /**
   * Get skill evolution trigger metadata, jobs, and route.
   */
  getEvolution: async (skillId: string): Promise<SkillEvolutionDetailResponse> => {
    return await api.get<SkillEvolutionDetailResponse>(`/skills/${skillId}/evolution`);
  },

  /**
   * Get tenant-wide skill evolution capture, scoring, and job state.
   */
  getEvolutionOverview: async (
    params: {
      skill_limit?: number | undefined;
      session_limit?: number | undefined;
      job_limit?: number | undefined;
    } = {}
  ): Promise<SkillEvolutionOverviewResponse> => {
    return await api.get<SkillEvolutionOverviewResponse>('/skills/evolution/overview', {
      params,
    });
  },

  /**
   * Run one evolution cycle for a Skill.
   */
  runEvolution: async (skillId: string): Promise<SkillEvolutionRunResponse> => {
    return await api.post<SkillEvolutionRunResponse>(`/skills/${skillId}/evolution/run`);
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
