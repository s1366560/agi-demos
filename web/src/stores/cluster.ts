import { create } from 'zustand';
import { devtools } from 'zustand/middleware';
import { useShallow } from 'zustand/react/shallow';

import { clusterService } from '../services/clusterService';

import type {
  ClusterResponse,
  ClusterCreate,
  ClusterUpdate,
  ClusterHealthResponse,
} from '../services/clusterService';

// ============================================================================
// ERROR HELPER
// ============================================================================

interface UnknownError {
  response?: { data?: { detail?: string | Record<string, unknown> } };
  message?: string;
}

function getErrorMessage(error: unknown, fallback: string): string {
  const err = error as UnknownError;
  if (err.response?.data?.detail) {
    const detail = err.response.data.detail;
    return typeof detail === 'string' ? detail : JSON.stringify(detail);
  }
  if (err.message) return err.message;
  return fallback;
}

// ============================================================================
// STATE INTERFACE
// ============================================================================

interface ClusterState {
  clusters: ClusterResponse[];
  currentCluster: ClusterResponse | null;
  clusterHealth: ClusterHealthResponse | null;
  total: number;
  page: number;
  pageSize: number;
  isLoading: boolean;
  isSubmitting: boolean;
  error: string | null;

  // Actions - Cluster CRUD
  listClusters: (params?: Record<string, unknown>) => Promise<void>;
  getCluster: (id: string) => Promise<ClusterResponse>;
  createCluster: (data: ClusterCreate) => Promise<ClusterResponse>;
  updateCluster: (id: string, data: ClusterUpdate) => Promise<ClusterResponse>;
  deleteCluster: (id: string) => Promise<void>;

  // Actions - Health
  getClusterHealth: (id: string) => Promise<ClusterHealthResponse>;

  // Actions - UI
  setCurrentCluster: (cluster: ClusterResponse | null) => void;
  clearError: () => void;
  reset: () => void;
}

// ============================================================================
// INITIAL STATE
// ============================================================================

const initialState = {
  clusters: [] as ClusterResponse[],
  currentCluster: null as ClusterResponse | null,
  clusterHealth: null as ClusterHealthResponse | null,
  total: 0,
  page: 1,
  pageSize: 20,
  isLoading: false,
  isSubmitting: false,
  error: null as string | null,
};

// ============================================================================
// STORE
// ============================================================================

export const useClusterStore = create<ClusterState>()(
  devtools(
    (set, get) => ({
      ...initialState,

      listClusters: async (params = {}) => {
        set({ isLoading: true, error: null });
        try {
          const response = await clusterService.list(params);
          set({
            clusters: response.clusters,
            total: response.total,
            isLoading: false,
          });
        } catch (error: unknown) {
          set({ error: getErrorMessage(error, 'Failed to list clusters'), isLoading: false });
          throw error;
        }
      },

      getCluster: async (id: string) => {
        set({ isLoading: true, error: null });
        try {
          const response = await clusterService.getById(id);
          set({ currentCluster: response, isLoading: false });
          return response;
        } catch (error: unknown) {
          set({ error: getErrorMessage(error, 'Failed to get cluster'), isLoading: false });
          throw error;
        }
      },

      createCluster: async (data: ClusterCreate) => {
        set({ isSubmitting: true, error: null });
        try {
          const response = await clusterService.create(data);
          const { clusters } = get();
          set({
            clusters: [response, ...clusters],
            total: get().total + 1,
            isSubmitting: false,
          });
          return response;
        } catch (error: unknown) {
          set({ error: getErrorMessage(error, 'Failed to create cluster'), isSubmitting: false });
          throw error;
        }
      },

      updateCluster: async (id: string, data: ClusterUpdate) => {
        set({ isSubmitting: true, error: null });
        try {
          const response = await clusterService.update(id, data);
          const { clusters } = get();
          set({
            clusters: clusters.map((c) => (c.id === id ? response : c)),
            currentCluster: get().currentCluster?.id === id ? response : get().currentCluster,
            isSubmitting: false,
          });
          return response;
        } catch (error: unknown) {
          set({ error: getErrorMessage(error, 'Failed to update cluster'), isSubmitting: false });
          throw error;
        }
      },

      deleteCluster: async (id: string) => {
        set({ isSubmitting: true, error: null });
        try {
          await clusterService.delete(id);
          const { clusters } = get();
          set({
            clusters: clusters.filter((c) => c.id !== id),
            currentCluster: get().currentCluster?.id === id ? null : get().currentCluster,
            total: get().total - 1,
            isSubmitting: false,
          });
        } catch (error: unknown) {
          set({ error: getErrorMessage(error, 'Failed to delete cluster'), isSubmitting: false });
          throw error;
        }
      },

      getClusterHealth: async (id: string) => {
        set({ isLoading: true, error: null });
        try {
          const response = await clusterService.getHealth(id);
          set({ clusterHealth: response, isLoading: false });
          return response;
        } catch (error: unknown) {
          set({
            error: getErrorMessage(error, 'Failed to get cluster health'),
            isLoading: false,
          });
          throw error;
        }
      },

      setCurrentCluster: (cluster: ClusterResponse | null) => {
        set({ currentCluster: cluster });
      },

      clearError: () => {
        set({ error: null });
      },

      reset: () => {
        set(initialState);
      },
    }),
    {
      name: 'ClusterStore',
      enabled: import.meta.env.DEV,
    }
  )
);

// ============================================================================
// SELECTOR HOOKS
// ============================================================================

export const useClusters = () => useClusterStore((s) => s.clusters);
export const useCurrentCluster = () => useClusterStore((s) => s.currentCluster);
export const useClusterHealth = () => useClusterStore((s) => s.clusterHealth);
export const useClusterLoading = () => useClusterStore((s) => s.isLoading);
export const useClusterSubmitting = () => useClusterStore((s) => s.isSubmitting);
export const useClusterError = () => useClusterStore((s) => s.error);
export const useClusterTotal = () => useClusterStore((s) => s.total);

export const useClusterActions = () =>
  useClusterStore(
    useShallow((s) => ({
      listClusters: s.listClusters,
      getCluster: s.getCluster,
      createCluster: s.createCluster,
      updateCluster: s.updateCluster,
      deleteCluster: s.deleteCluster,
      getClusterHealth: s.getClusterHealth,
      setCurrentCluster: s.setCurrentCluster,
      clearError: s.clearError,
      reset: s.reset,
    }))
  );
