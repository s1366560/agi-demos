/**
 * Pool Service - Agent Pool管理API
 *
 * 提供Agent Pool的状态查询和管理功能。
 *
 * 功能:
 * - 获取池状态概览
 * - 列出所有实例
 * - 管理实例生命周期 (暂停/恢复/终止)
 * - 设置项目分级
 * - 获取指标数据
 *
 * @packageDocumentation
 */

import { logger } from "../utils/logger";

import { httpClient } from "./client/httpClient";

// ============================================================================
// Types
// ============================================================================

/**
 * 项目分级
 */
export type ProjectTier = "hot" | "warm" | "cold";

/**
 * 实例状态
 */
export type InstanceStatus =
  | "created"
  | "initializing"
  | "initialization_failed"
  | "ready"
  | "executing"
  | "paused"
  | "unhealthy"
  | "degraded"
  | "terminating"
  | "terminated";

/**
 * 健康状态
 */
export type HealthStatus = "healthy" | "degraded" | "unhealthy" | "unknown";

/**
 * 池状态响应
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
 * 实例信息
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
 * 实例列表响应
 */
export interface InstanceListResponse {
  instances: PoolInstance[];
  total: number;
  page: number;
  page_size: number;
}

/**
 * 设置分级请求
 */
export interface SetTierRequest {
  tier: ProjectTier;
}

/**
 * 设置分级响应
 */
export interface SetTierResponse {
  project_id: string;
  previous_tier: ProjectTier | null;
  current_tier: ProjectTier;
  message: string;
}

/**
 * 操作响应
 */
export interface OperationResponse {
  success: boolean;
  message: string;
}

/**
 * 指标响应
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
 * 列表查询参数
 */
export interface ListInstancesParams {
  tier?: ProjectTier;
  status?: InstanceStatus;
  page?: number;
  page_size?: number;
}

// ============================================================================
// Pool Service
// ============================================================================

// Note: httpClient already has baseURL '/api/v1', so we only need the relative path
const BASE_PATH = "/admin/pool";

/**
 * Agent Pool管理服务
 */
export const poolService = {
  /**
   * 获取池状态概览
   */
  getStatus: async (): Promise<PoolStatus> => {
    try {
      const response = await httpClient.get<PoolStatus>(`${BASE_PATH}/status`);
      return response;
    } catch (error) {
      logger.error("[PoolService] Failed to get pool status:", error);
      throw error;
    }
  },

  /**
   * 列出所有实例
   */
  listInstances: async (
    params?: ListInstancesParams
  ): Promise<InstanceListResponse> => {
    try {
      const response = await httpClient.get<InstanceListResponse>(
        `${BASE_PATH}/instances`,
        { params }
      );
      return response;
    } catch (error) {
      logger.error("[PoolService] Failed to list instances:", error);
      throw error;
    }
  },

  /**
   * 获取实例详情
   */
  getInstance: async (instanceKey: string): Promise<PoolInstance> => {
    try {
      const response = await httpClient.get<PoolInstance>(
        `${BASE_PATH}/instances/${encodeURIComponent(instanceKey)}`
      );
      return response;
    } catch (error) {
      logger.error(
        `[PoolService] Failed to get instance ${instanceKey}:`,
        error
      );
      throw error;
    }
  },

  /**
   * 暂停实例
   */
  pauseInstance: async (instanceKey: string): Promise<OperationResponse> => {
    try {
      const response = await httpClient.post<OperationResponse>(
        `${BASE_PATH}/instances/${encodeURIComponent(instanceKey)}/pause`
      );
      return response;
    } catch (error) {
      logger.error(
        `[PoolService] Failed to pause instance ${instanceKey}:`,
        error
      );
      throw error;
    }
  },

  /**
   * 恢复实例
   */
  resumeInstance: async (instanceKey: string): Promise<OperationResponse> => {
    try {
      const response = await httpClient.post<OperationResponse>(
        `${BASE_PATH}/instances/${encodeURIComponent(instanceKey)}/resume`
      );
      return response;
    } catch (error) {
      logger.error(
        `[PoolService] Failed to resume instance ${instanceKey}:`,
        error
      );
      throw error;
    }
  },

  /**
   * 终止实例
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
      logger.error(
        `[PoolService] Failed to terminate instance ${instanceKey}:`,
        error
      );
      throw error;
    }
  },

  /**
   * 获取项目分级
   */
  getProjectTier: async (
    projectId: string,
    tenantId: string
  ): Promise<{ project_id: string; tenant_id: string; tier: ProjectTier }> => {
    try {
      const response = await httpClient.get<{ project_id: string; tenant_id: string; tier: ProjectTier }>(
        `${BASE_PATH}/projects/${projectId}/tier`,
        { params: { tenant_id: tenantId } }
      );
      return response;
    } catch (error) {
      logger.error(
        `[PoolService] Failed to get tier for project ${projectId}:`,
        error
      );
      throw error;
    }
  },

  /**
   * 设置项目分级
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
      logger.error(
        `[PoolService] Failed to set tier for project ${projectId}:`,
        error
      );
      throw error;
    }
  },

  /**
   * 获取指标 (JSON格式)
   */
  getMetrics: async (): Promise<MetricsResponse> => {
    try {
      const response = await httpClient.get<MetricsResponse>(
        `${BASE_PATH}/metrics`
      );
      return response;
    } catch (error) {
      logger.error("[PoolService] Failed to get metrics:", error);
      throw error;
    }
  },

  /**
   * 获取指标 (Prometheus格式)
   */
  getMetricsPrometheus: async (): Promise<string> => {
    try {
      const response = await httpClient.get<string>(
        `${BASE_PATH}/metrics/prometheus`,
        {
          headers: { Accept: "text/plain" },
        }
      );
      return response;
    } catch (error) {
      logger.error("[PoolService] Failed to get prometheus metrics:", error);
      throw error;
    }
  },
};

export default poolService;
