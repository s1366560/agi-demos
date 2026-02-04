/**
 * Pool Store - State management for Agent Pool
 *
 * 管理Agent Pool的状态、实例列表和指标数据。
 *
 * @packageDocumentation
 */

import { create } from "zustand";
import { devtools } from "zustand/middleware";
import { logger } from "../utils/logger";
import {
  poolService,
  type PoolStatus,
  type PoolInstance,
  type MetricsResponse,
  type ProjectTier,
  type ListInstancesParams,
} from "../services/poolService";

// ============================================================================
// Types
// ============================================================================

export interface PoolState {
  // Status
  status: PoolStatus | null;
  isStatusLoading: boolean;
  statusError: string | null;

  // Instances
  instances: PoolInstance[];
  totalInstances: number;
  currentPage: number;
  pageSize: number;
  isInstancesLoading: boolean;
  instancesError: string | null;

  // Filters
  tierFilter: ProjectTier | null;
  statusFilter: string | null;

  // Metrics
  metrics: MetricsResponse | null;
  isMetricsLoading: boolean;
  metricsError: string | null;

  // Auto-refresh
  autoRefresh: boolean;
  refreshInterval: number; // seconds
}

export interface PoolActions {
  // Status
  fetchStatus: () => Promise<void>;

  // Instances
  fetchInstances: (params?: ListInstancesParams) => Promise<void>;
  setPage: (page: number) => void;
  setPageSize: (size: number) => void;
  setTierFilter: (tier: ProjectTier | null) => void;
  setStatusFilter: (status: string | null) => void;

  // Instance operations
  pauseInstance: (instanceKey: string) => Promise<boolean>;
  resumeInstance: (instanceKey: string) => Promise<boolean>;
  terminateInstance: (instanceKey: string) => Promise<boolean>;

  // Project tier
  setProjectTier: (
    projectId: string,
    tenantId: string,
    tier: ProjectTier
  ) => Promise<boolean>;

  // Metrics
  fetchMetrics: () => Promise<void>;

  // Auto-refresh
  setAutoRefresh: (enabled: boolean) => void;
  setRefreshInterval: (seconds: number) => void;

  // Reset
  reset: () => void;
}

// ============================================================================
// Initial State
// ============================================================================

const initialState: PoolState = {
  status: null,
  isStatusLoading: false,
  statusError: null,

  instances: [],
  totalInstances: 0,
  currentPage: 1,
  pageSize: 20,
  isInstancesLoading: false,
  instancesError: null,

  tierFilter: null,
  statusFilter: null,

  metrics: null,
  isMetricsLoading: false,
  metricsError: null,

  autoRefresh: false,
  refreshInterval: 30,
};

// ============================================================================
// Store
// ============================================================================

export const usePoolStore = create<PoolState & PoolActions>()(
  devtools(
    (set, get) => ({
      ...initialState,

      // ======================================================================
      // Status
      // ======================================================================

      fetchStatus: async () => {
        set({ isStatusLoading: true, statusError: null });
        try {
          const status = await poolService.getStatus();
          set({ status, isStatusLoading: false });
          logger.debug("[PoolStore] Status fetched:", status);
        } catch (error) {
          const message =
            error instanceof Error ? error.message : "Failed to fetch status";
          set({ statusError: message, isStatusLoading: false });
          logger.error("[PoolStore] Failed to fetch status:", error);
        }
      },

      // ======================================================================
      // Instances
      // ======================================================================

      fetchInstances: async (params?: ListInstancesParams) => {
        const { currentPage, pageSize, tierFilter, statusFilter } = get();

        set({ isInstancesLoading: true, instancesError: null });
        try {
          const response = await poolService.listInstances({
            page: params?.page ?? currentPage,
            page_size: params?.page_size ?? pageSize,
            tier: params?.tier ?? tierFilter ?? undefined,
            status: params?.status ?? statusFilter ?? undefined,
          });

          set({
            instances: response.instances,
            totalInstances: response.total,
            currentPage: response.page,
            pageSize: response.page_size,
            isInstancesLoading: false,
          });

          logger.debug(
            `[PoolStore] Instances fetched: ${response.total} total`
          );
        } catch (error) {
          const message =
            error instanceof Error
              ? error.message
              : "Failed to fetch instances";
          set({ instancesError: message, isInstancesLoading: false });
          logger.error("[PoolStore] Failed to fetch instances:", error);
        }
      },

      setPage: (page: number) => {
        set({ currentPage: page });
        get().fetchInstances({ page });
      },

      setPageSize: (size: number) => {
        set({ pageSize: size, currentPage: 1 });
        get().fetchInstances({ page: 1, page_size: size });
      },

      setTierFilter: (tier: ProjectTier | null) => {
        set({ tierFilter: tier, currentPage: 1 });
        get().fetchInstances({ page: 1, tier: tier ?? undefined });
      },

      setStatusFilter: (status: string | null) => {
        set({ statusFilter: status, currentPage: 1 });
        get().fetchInstances({ page: 1, status: status ?? undefined });
      },

      // ======================================================================
      // Instance Operations
      // ======================================================================

      pauseInstance: async (instanceKey: string) => {
        try {
          const result = await poolService.pauseInstance(instanceKey);
          if (result.success) {
            // Refresh instances list
            await get().fetchInstances();
            logger.info(`[PoolStore] Instance paused: ${instanceKey}`);
          }
          return result.success;
        } catch (error) {
          logger.error(
            `[PoolStore] Failed to pause instance ${instanceKey}:`,
            error
          );
          return false;
        }
      },

      resumeInstance: async (instanceKey: string) => {
        try {
          const result = await poolService.resumeInstance(instanceKey);
          if (result.success) {
            await get().fetchInstances();
            logger.info(`[PoolStore] Instance resumed: ${instanceKey}`);
          }
          return result.success;
        } catch (error) {
          logger.error(
            `[PoolStore] Failed to resume instance ${instanceKey}:`,
            error
          );
          return false;
        }
      },

      terminateInstance: async (instanceKey: string) => {
        try {
          const result = await poolService.terminateInstance(instanceKey);
          if (result.success) {
            await get().fetchInstances();
            logger.info(`[PoolStore] Instance terminated: ${instanceKey}`);
          }
          return result.success;
        } catch (error) {
          logger.error(
            `[PoolStore] Failed to terminate instance ${instanceKey}:`,
            error
          );
          return false;
        }
      },

      // ======================================================================
      // Project Tier
      // ======================================================================

      setProjectTier: async (
        projectId: string,
        tenantId: string,
        tier: ProjectTier
      ) => {
        try {
          const result = await poolService.setProjectTier(
            projectId,
            tenantId,
            tier
          );
          logger.info(
            `[PoolStore] Project ${projectId} tier set to ${tier}:`,
            result.message
          );
          // Refresh data
          await get().fetchStatus();
          await get().fetchInstances();
          return true;
        } catch (error) {
          logger.error(
            `[PoolStore] Failed to set tier for project ${projectId}:`,
            error
          );
          return false;
        }
      },

      // ======================================================================
      // Metrics
      // ======================================================================

      fetchMetrics: async () => {
        set({ isMetricsLoading: true, metricsError: null });
        try {
          const metrics = await poolService.getMetrics();
          set({ metrics, isMetricsLoading: false });
          logger.debug("[PoolStore] Metrics fetched:", metrics);
        } catch (error) {
          const message =
            error instanceof Error ? error.message : "Failed to fetch metrics";
          set({ metricsError: message, isMetricsLoading: false });
          logger.error("[PoolStore] Failed to fetch metrics:", error);
        }
      },

      // ======================================================================
      // Auto-refresh
      // ======================================================================

      setAutoRefresh: (enabled: boolean) => {
        set({ autoRefresh: enabled });
      },

      setRefreshInterval: (seconds: number) => {
        set({ refreshInterval: Math.max(5, seconds) }); // Minimum 5 seconds
      },

      // ======================================================================
      // Reset
      // ======================================================================

      reset: () => {
        set(initialState);
      },
    }),
    { name: "pool-store" }
  )
);

export default usePoolStore;
