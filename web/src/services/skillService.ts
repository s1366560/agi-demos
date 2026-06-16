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
  SkillEvolutionConfigResponse,
  SkillEvolutionConfigUpdateRequest,
  SkillEvolutionJobResponse,
  SkillEvolutionOverviewResponse,
  SkillEvolutionRunResponse,
  SkillEvolutionTenantRunResponse,
  SkillVersionDetailResponse,
  SkillVersionListResponse,
  TenantSkillConfigResponse,
  TenantSkillConfigListResponse,
  SystemSkillStatus,
} from '../types/agent';

// Use centralized HTTP client
const api = httpClient;

const skillNamePathSegment = (systemSkillName: string): string =>
  encodeURIComponent(systemSkillName);

interface TenantScopedOptions {
  tenant_id?: string | null | undefined;
}

const tenantParams = (options: TenantScopedOptions = {}): { tenant_id?: string } =>
  options.tenant_id ? { tenant_id: options.tenant_id } : {};

const tenantConfig = (options: TenantScopedOptions = {}) => {
  const params = tenantParams(options);
  return params.tenant_id ? { params } : undefined;
};

const tenantQuery = (options: TenantScopedOptions = {}): string =>
  options.tenant_id ? `?tenant_id=${encodeURIComponent(options.tenant_id)}` : '';

export interface SkillListParams {
  search?: string | undefined;
  q?: string | undefined;
  status?: 'active' | 'disabled' | 'deprecated' | null | undefined;
  scope?: 'system' | 'tenant' | 'project' | null | undefined;
  project_id?: string | null | undefined;
  tenant_id?: string | null | undefined;
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
    params: { status?: string | undefined; tenant_id?: string | null | undefined } = {}
  ): Promise<SkillsListResponse> => {
    return await api.get<SkillsListResponse>('/skills/system/list', { params });
  },

  /**
   * Create a new Skill
   */
  create: async (data: SkillCreate, options: TenantScopedOptions = {}): Promise<SkillResponse> => {
    return await api.post<SkillResponse>('/skills/', data, tenantConfig(options));
  },

  /**
   * Get a Skill by ID
   */
  get: async (skillId: string, options: TenantScopedOptions = {}): Promise<SkillResponse> => {
    return await api.get<SkillResponse>(`/skills/${skillId}`, tenantConfig(options));
  },

  /**
   * Update a Skill
   */
  update: async (
    skillId: string,
    data: SkillUpdate,
    options: TenantScopedOptions = {}
  ): Promise<SkillResponse> => {
    return await api.put<SkillResponse>(`/skills/${skillId}`, data, tenantConfig(options));
  },

  /**
   * Delete a Skill
   */
  delete: async (skillId: string, options: TenantScopedOptions = {}): Promise<void> => {
    await api.delete(`/skills/${skillId}`, tenantConfig(options));
  },

  /**
   * Update Skill status
   */
  updateStatus: async (
    skillId: string,
    status: 'active' | 'disabled' | 'deprecated',
    options: TenantScopedOptions = {}
  ): Promise<SkillResponse> => {
    return await api.patch<SkillResponse>(`/skills/${skillId}/status`, null, {
      params: { status, ...tenantParams(options) },
    });
  },

  /**
   * Get skill content
   */
  getContent: async (
    skillId: string,
    options: TenantScopedOptions = {}
  ): Promise<SkillContentResponse> => {
    return await api.get<SkillContentResponse>(`/skills/${skillId}/content`, tenantConfig(options));
  },

  /**
   * Update skill content
   */
  updateContent: async (
    skillId: string,
    fullContent: string,
    options: TenantScopedOptions = {}
  ): Promise<SkillResponse> => {
    return await api.put<SkillResponse>(
      `/skills/${skillId}/content`,
      {
        full_content: fullContent,
      },
      tenantConfig(options)
    );
  },

  /**
   * Import a complete AgentSkills.io package.
   */
  importPackage: async (
    data: SkillImportRequest,
    options: TenantScopedOptions = {}
  ): Promise<SkillLifecycleResponse> => {
    return await api.post<SkillLifecycleResponse>('/skills/import', data, tenantConfig(options));
  },

  /**
   * Import a zipped Agent Skills directory containing SKILL.md and bundled files.
   */
  importZip: async (
    file: File,
    data: SkillZipImportRequest = {},
    options: TenantScopedOptions = {}
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
    return await api.upload<SkillLifecycleResponse>(
      `/skills/import/zip${tenantQuery(options)}`,
      formData
    );
  },

  /**
   * Export a Skill as an AgentSkills.io package.
   */
  exportPackage: async (
    skillId: string,
    options: TenantScopedOptions = {}
  ): Promise<SkillPackageResponse> => {
    return await api.get<SkillPackageResponse>(`/skills/${skillId}/export`, tenantConfig(options));
  },

  /**
   * List version snapshots for a Skill.
   */
  listVersions: async (
    skillId: string,
    params: {
      limit?: number | undefined;
      offset?: number | undefined;
      tenant_id?: string | null | undefined;
    } = {}
  ): Promise<SkillVersionListResponse> => {
    return await api.get<SkillVersionListResponse>(`/skills/${skillId}/versions`, { params });
  },

  /**
   * Read a specific version snapshot.
   */
  getVersion: async (
    skillId: string,
    versionNumber: number,
    options: TenantScopedOptions = {}
  ): Promise<SkillVersionDetailResponse> => {
    return await api.get<SkillVersionDetailResponse>(
      `/skills/${skillId}/versions/${String(versionNumber)}`,
      tenantConfig(options)
    );
  },

  /**
   * Roll a Skill back to a previous version snapshot.
   */
  rollback: async (
    skillId: string,
    versionNumber: number,
    options: TenantScopedOptions = {}
  ): Promise<SkillResponse> => {
    return await api.post<SkillResponse>(
      `/skills/${skillId}/rollback`,
      {
        version_number: versionNumber,
      },
      tenantConfig(options)
    );
  },

  /**
   * Get skill evolution trigger metadata, jobs, and route.
   */
  getEvolution: async (
    skillId: string,
    options: TenantScopedOptions = {}
  ): Promise<SkillEvolutionDetailResponse> => {
    return await api.get<SkillEvolutionDetailResponse>(
      `/skills/${skillId}/evolution`,
      tenantConfig(options)
    );
  },

  /**
   * Get tenant-wide skill evolution capture, scoring, and job state.
   */
  getEvolutionOverview: async (
    params: {
      skill_limit?: number | undefined;
      session_limit?: number | undefined;
      job_limit?: number | undefined;
      tenant_id?: string | null | undefined;
    } = {}
  ): Promise<SkillEvolutionOverviewResponse> => {
    return await api.get<SkillEvolutionOverviewResponse>('/skills/evolution/overview', {
      params,
    });
  },

  getEvolutionConfig: async (
    options: TenantScopedOptions = {}
  ): Promise<SkillEvolutionConfigResponse> => {
    return await api.get<SkillEvolutionConfigResponse>(
      '/skills/evolution/config',
      tenantConfig(options)
    );
  },

  updateEvolutionConfig: async (
    data: SkillEvolutionConfigUpdateRequest,
    options: TenantScopedOptions = {}
  ): Promise<SkillEvolutionConfigResponse> => {
    return await api.put<SkillEvolutionConfigResponse>(
      '/skills/evolution/config',
      data,
      tenantConfig(options)
    );
  },

  /**
   * Run one evolution cycle for a Skill.
   */
  runEvolution: async (
    skillId: string,
    options: TenantScopedOptions = {}
  ): Promise<SkillEvolutionRunResponse> => {
    return await api.post<SkillEvolutionRunResponse>(
      `/skills/${skillId}/evolution/run`,
      undefined,
      tenantConfig(options)
    );
  },

  /**
   * Run one tenant-wide skill evolution cycle.
   */
  runEvolutionOverview: async (
    options: TenantScopedOptions = {}
  ): Promise<SkillEvolutionTenantRunResponse> => {
    return await api.post<SkillEvolutionTenantRunResponse>(
      '/skills/evolution/run',
      undefined,
      tenantConfig(options)
    );
  },

  /**
   * Apply a pending skill evolution job.
   */
  applyEvolutionJob: async (
    jobId: string,
    options: TenantScopedOptions = {}
  ): Promise<SkillEvolutionJobResponse> => {
    return await api.post<SkillEvolutionJobResponse>(
      `/skills/evolution/jobs/${jobId}/apply`,
      undefined,
      tenantConfig(options)
    );
  },

  /**
   * Reject a pending skill evolution job.
   */
  rejectEvolutionJob: async (
    jobId: string,
    options: TenantScopedOptions = {}
  ): Promise<SkillEvolutionJobResponse> => {
    return await api.post<SkillEvolutionJobResponse>(
      `/skills/evolution/jobs/${jobId}/reject`,
      undefined,
      tenantConfig(options)
    );
  },
};

/**
 * Tenant Skill Config API
 */
export const tenantSkillConfigAPI = {
  /**
   * List all tenant skill configs
   */
  list: async (options: TenantScopedOptions = {}): Promise<TenantSkillConfigListResponse> => {
    return await api.get<TenantSkillConfigListResponse>(
      '/tenant/skills/config/',
      tenantConfig(options)
    );
  },

  /**
   * Get a specific tenant skill config
   */
  get: async (
    systemSkillName: string,
    options: TenantScopedOptions = {}
  ): Promise<TenantSkillConfigResponse> => {
    return await api.get<TenantSkillConfigResponse>(
      `/tenant/skills/config/${skillNamePathSegment(systemSkillName)}`,
      tenantConfig(options)
    );
  },

  /**
   * Disable a system skill
   */
  disable: async (
    systemSkillName: string,
    options: TenantScopedOptions = {}
  ): Promise<TenantSkillConfigResponse> => {
    return await api.post<TenantSkillConfigResponse>(
      '/tenant/skills/config/disable',
      {
        system_skill_name: systemSkillName,
      },
      tenantConfig(options)
    );
  },

  /**
   * Override a system skill
   */
  override: async (
    systemSkillName: string,
    overrideSkillId: string,
    options: TenantScopedOptions = {}
  ): Promise<TenantSkillConfigResponse> => {
    return await api.post<TenantSkillConfigResponse>(
      '/tenant/skills/config/override',
      {
        system_skill_name: systemSkillName,
        override_skill_id: overrideSkillId,
      },
      tenantConfig(options)
    );
  },

  /**
   * Enable a previously disabled/overridden system skill
   */
  enable: async (systemSkillName: string, options: TenantScopedOptions = {}): Promise<void> => {
    await api.post(
      '/tenant/skills/config/enable',
      {
        system_skill_name: systemSkillName,
      },
      tenantConfig(options)
    );
  },

  /**
   * Delete a tenant skill config
   */
  delete: async (systemSkillName: string, options: TenantScopedOptions = {}): Promise<void> => {
    await api.delete(
      `/tenant/skills/config/${skillNamePathSegment(systemSkillName)}`,
      tenantConfig(options)
    );
  },

  /**
   * Get status of a system skill
   */
  getStatus: async (
    systemSkillName: string,
    options: TenantScopedOptions = {}
  ): Promise<SystemSkillStatus> => {
    return await api.get<SystemSkillStatus>(
      `/tenant/skills/config/status/${skillNamePathSegment(systemSkillName)}`,
      tenantConfig(options)
    );
  },
};

export default skillAPI;
