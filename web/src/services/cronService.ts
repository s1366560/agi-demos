/**
 * Cron API Service
 *
 * Provides API methods for scheduled tasks/cron jobs.
 */

import { httpClient } from './client/httpClient';

import type {
  CronJobCreate,
  CronJobUpdate,
  CronJobListResponse,
  CronJobResponse,
  ManualRunRequest,
  CronJobRunListResponse,
} from '../types/cron';

// Use centralized HTTP client
const api = httpClient;

export interface CronJobListParams {
  include_disabled?: boolean | undefined;
  limit?: number | undefined;
  offset?: number | undefined;
}

export interface CronJobRunListParams {
  limit?: number | undefined;
  offset?: number | undefined;
}

export const cronAPI = {
  /**
   * List all cron jobs for a project
   */
  list: async (projectId: string, params: CronJobListParams = {}): Promise<CronJobListResponse> => {
    return await api.get<CronJobListResponse>(`/projects/${projectId}/cron-jobs`, { params });
  },

  /**
   * Create a new cron job
   */
  create: async (projectId: string, data: CronJobCreate): Promise<CronJobResponse> => {
    return await api.post<CronJobResponse>(`/projects/${projectId}/cron-jobs`, data);
  },

  /**
   * Get a specific cron job by ID
   */
  get: async (projectId: string, jobId: string): Promise<CronJobResponse> => {
    return await api.get<CronJobResponse>(`/projects/${projectId}/cron-jobs/${jobId}`);
  },

  /**
   * Update an existing cron job
   */
  update: async (
    projectId: string,
    jobId: string,
    data: CronJobUpdate
  ): Promise<CronJobResponse> => {
    return await api.patch<CronJobResponse>(`/projects/${projectId}/cron-jobs/${jobId}`, data);
  },

  /**
   * Delete a cron job
   */
  delete: async (projectId: string, jobId: string): Promise<void> => {
    await api.delete(`/projects/${projectId}/cron-jobs/${jobId}`);
  },

  /**
   * Toggle the enabled state of a cron job
   */
  toggle: async (projectId: string, jobId: string, enabled: boolean): Promise<CronJobResponse> => {
    return await api.post<CronJobResponse>(
      `/projects/${projectId}/cron-jobs/${jobId}/toggle`,
      null,
      {
        params: { enabled },
      }
    );
  },

  /**
   * Manually trigger a cron job execution
   */
  run: async (projectId: string, jobId: string, data?: ManualRunRequest): Promise<void> => {
    await api.post(`/projects/${projectId}/cron-jobs/${jobId}/run`, data || {});
  },

  /**
   * List run history for a specific cron job
   */
  listRuns: async (
    projectId: string,
    jobId: string,
    params: CronJobRunListParams = {}
  ): Promise<CronJobRunListResponse> => {
    return await api.get<CronJobRunListResponse>(`/projects/${projectId}/cron-jobs/${jobId}/runs`, {
      params,
    });
  },
};

export default cronAPI;
