/**
 * Pool Service - Agent Pool Management API
 *
 * Provides Agent Pool status queries and management.
 *
 * Features:
 * - Get pool status overview
 * - List all instances
 * - Manage instance lifecycle (pause/resume/terminate)
 * - Set project tier
 * - Get metrics data
 *
 * @packageDocumentation
 */

import { logger } from '../utils/logger';

import { httpClient } from './client/httpClient';

// ============================================================================
// Types
// ============================================================================

/**
 * Project tier
 */
export type ProjectTier = 'hot' | 'warm' | 'cold';

/**
 * Instance status
 */
export type InstanceStatus =
  | 'created'
  | 'initializing'
  | 'initialization_failed'
  | 'ready'
  | 'executing'
  | 'paused'
  | 'unhealthy'
  | 'degraded'
  | 'terminating'
  | 'terminated';

/**
 * Health status
 */
export type HealthStatus = 'healthy' | 'degraded' | 'unhealthy' | 'unknown';

/**
 * Pool status response
 */
export interface PoolStatus {
  enabled: boolean;
  status: string;
  total_instances: number;
  hot_instances: number;
  warm_instances: number;
  cold_instances: number;
  ready_instances: number;
  executing_instances: number;
  unhealthy_instances: number;
  prewarm_pool: {
    l1: number;
    l2: number;
    l3: number;
  };
  resource_usage: {
    total_memory_mb: number;
    used_memory_mb: number;
    total_cpu_cores: number;
    used_cpu_cores: number;
  };
}

/**
 * Instance info
 */
export interface PoolInstance {
  instance_key: string;
  tenant_id: string;
  project_id: string;
  agent_mode: string;
  tier: ProjectTier;
  status: InstanceStatus;
  created_at: string | null;
  last_request_at: string | null;
  active_requests: number;
  total_requests: number;
  memory_used_mb: number;
  health_status: HealthStatus;
}

/**
 * Instance list response
 */
export interface InstanceListResponse {
  instances: PoolInstance[];
  total: number;
  page: number;
  page_size: number;
}

/**
 * Set tier request
 */
export interface SetTierRequest {
  tier: ProjectTier;
}

/**
 * Set tier response
 */
export interface SetTierResponse {
  project_id: string;
  previous_tier: ProjectTier | null;
  current_tier: ProjectTier;
  message: string;
}

/**
 * Operation response
 */
export interface OperationResponse {
  success: boolean;
  message: string;
}

/**
 * Metrics response
 */
export interface MetricsResponse {
  instances: {
    total: number;
    by_tier: {
      hot: number;
      warm: number;
      cold: number;
    };
    by_status: {
      ready: number;
      executing: number;
      unhealthy: number;
    };
  };
  health: {
    unhealthy_count: number;
  };
  prewarm: {
    l1: number;
    l2: number;
    l3: number;
  };
}

/**
 * List query parameters
 */
export interface ListInstancesParams {
  tier?: ProjectTier | undefined;
  status?: InstanceStatus | undefined;
  page?: number | undefined;
  page_size?: number | undefined;
}

// ============================================================================
// Pool Service
// ============================================================================

// Note: httpClient already has baseURL '/api/v1', so we only need the relative path
const BASE_PATH = '/admin/pool';

/**
 * Agent Pool management service
 */
export const poolService = {
  /**
   * Get pool status overview
   */
  getStatus: async (): Promise<PoolStatus> => {
    try {
      const response = await httpClient.get<PoolStatus>(`${BASE_PATH}/status`);
      return response;
    } catch (error) {
      logger.error('[PoolService] Failed to get pool status:', error);
      throw error;
    }
  },

  /**
   * List all instances
   */
  listInstances: async (params?: ListInstancesParams): Promise<InstanceListResponse> => {
    try {
      const response = await httpClient.get<InstanceListResponse>(`${BASE_PATH}/instances`, {
        params,
      });
      return response;
    } catch (error) {
      logger.error('[PoolService] Failed to list instances:', error);
      throw error;
    }
  },

  /**
   * Get instance details
   */
  getInstance: async (instanceKey: string): Promise<PoolInstance> => {
    try {
      const response = await httpClient.get<PoolInstance>(
        `${BASE_PATH}/instances/${encodeURIComponent(instanceKey)}`
      );
      return response;
    } catch (error) {
      logger.error(`[PoolService] Failed to get instance ${instanceKey}:`, error);
      throw error;
    }
  },

  /**
   * Pause an instance
   */
  pauseInstance: async (instanceKey: string): Promise<OperationResponse> => {
    try {
      const response = await httpClient.post<OperationResponse>(
        `${BASE_PATH}/instances/${encodeURIComponent(instanceKey)}/pause`
      );
      return response;
    } catch (error) {
      logger.error(`[PoolService] Failed to pause instance ${instanceKey}:`, error);
      throw error;
    }
  },

  /**
   * Resume an instance
   */
  resumeInstance: async (instanceKey: string): Promise<OperationResponse> => {
    try {
      const response = await httpClient.post<OperationResponse>(
        `${BASE_PATH}/instances/${encodeURIComponent(instanceKey)}/resume`
      );
      return response;
    } catch (error) {
      logger.error(`[PoolService] Failed to resume instance ${instanceKey}:`, error);
      throw error;
    }
  },

  /**
   * Terminate an instance
   */
  terminateInstance: async (
    instanceKey: string,
    graceful: boolean = true
  ): Promise<OperationResponse> => {
    try {
      const response = await httpClient.delete<OperationResponse>(
        `${BASE_PATH}/instances/${encodeURIComponent(instanceKey)}`,
        { params: { graceful } }
      );
      return response;
    } catch (error) {
      logger.error(`[PoolService] Failed to terminate instance ${instanceKey}:`, error);
      throw error;
    }
  },

  /**
   * Get project tier
   */
  getProjectTier: async (
    projectId: string,
    tenantId: string
  ): Promise<{ project_id: string; tenant_id: string; tier: ProjectTier }> => {
    try {
      const response = await httpClient.get<{
        project_id: string;
        tenant_id: string;
        tier: ProjectTier;
      }>(`${BASE_PATH}/projects/${projectId}/tier`, { params: { tenant_id: tenantId } });
      return response;
    } catch (error) {
      logger.error(`[PoolService] Failed to get tier for project ${projectId}:`, error);
      throw error;
    }
  },

  /**
   * Set project tier
   */
  setProjectTier: async (
    projectId: string,
    tenantId: string,
    tier: ProjectTier
  ): Promise<SetTierResponse> => {
    try {
      const response = await httpClient.post<SetTierResponse>(
        `${BASE_PATH}/projects/${projectId}/tier`,
        { tier },
        { params: { tenant_id: tenantId } }
      );
      return response;
    } catch (error) {
      logger.error(`[PoolService] Failed to set tier for project ${projectId}:`, error);
      throw error;
    }
  },

  /**
   * Get metrics (JSON format)
   */
  getMetrics: async (): Promise<MetricsResponse> => {
    try {
      const response = await httpClient.get<MetricsResponse>(`${BASE_PATH}/metrics`);
      return response;
    } catch (error) {
      logger.error('[PoolService] Failed to get metrics:', error);
      throw error;
    }
  },

  /**
   * Get metrics (Prometheus format)
   */
  getMetricsPrometheus: async (): Promise<string> => {
    try {
      const response = await httpClient.get<string>(`${BASE_PATH}/metrics/prometheus`, {
        headers: { Accept: 'text/plain' },
      });
      return response;
    } catch (error) {
      logger.error('[PoolService] Failed to get prometheus metrics:', error);
      throw error;
    }
  },
};

export default poolService;
