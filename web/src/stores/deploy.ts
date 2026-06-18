import { create } from 'zustand';
import { devtools } from 'zustand/middleware';
import { useShallow } from 'zustand/react/shallow';

import { deployService } from '../services/deployService';

import type { DeployResponse, DeployCreate } from '../services/deployService';

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

interface DeployState {
  deploys: DeployResponse[];
  currentDeploy: DeployResponse | null;
  total: number;
  page: number;
  pageSize: number;
  isLoading: boolean;
  isSubmitting: boolean;
  error: string | null;

  // Actions - Deploy CRUD
  listDeploys: (params?: Record<string, unknown>) => Promise<void>;
  getDeploy: (id: string) => Promise<DeployResponse>;
  createDeploy: (data: DeployCreate) => Promise<DeployResponse>;

  // Actions - Status transitions
  markSuccess: (id: string) => Promise<void>;
  markFailed: (id: string, message?: string) => Promise<void>;
  cancelDeploy: (id: string) => Promise<void>;

  // Actions - Query
  getLatestDeploy: (instanceId: string) => Promise<DeployResponse>;

  // Actions - UI
  setCurrentDeploy: (deploy: DeployResponse | null) => void;
  clearError: () => void;
  reset: () => void;
}

// ============================================================================
// INITIAL STATE
// ============================================================================

const initialState = {
  deploys: [] as DeployResponse[],
  currentDeploy: null as DeployResponse | null,
  total: 0,
  page: 1,
  pageSize: 20,
  isLoading: false,
  isSubmitting: false,
  error: null as string | null,
};

let latestListDeploysRequest = 0;
let latestGetDeployRequest = 0;
let latestGetLatestDeployRequest = 0;

function invalidateDeployReadRequests(): void {
  latestListDeploysRequest += 1;
  latestGetDeployRequest += 1;
  latestGetLatestDeployRequest += 1;
}

// ============================================================================
// STORE
// ============================================================================

export const useDeployStore = create<DeployState>()(
  devtools(
    (set, get) => ({
      ...initialState,

      listDeploys: async (params = {}) => {
        const requestId = latestListDeploysRequest + 1;
        latestListDeploysRequest = requestId;
        set({ isLoading: true, error: null });
        try {
          const response = await deployService.list(params);
          if (requestId !== latestListDeploysRequest) return;
          set({
            deploys: response.deployments,
            total: response.total,
            isLoading: false,
          });
        } catch (error: unknown) {
          if (requestId !== latestListDeploysRequest) return;
          set({ error: getErrorMessage(error, 'Failed to list deploys'), isLoading: false });
          throw error;
        }
      },

      getDeploy: async (id: string) => {
        const requestId = latestGetDeployRequest + 1;
        latestGetDeployRequest = requestId;
        set({ isLoading: true, error: null });
        try {
          const response = await deployService.getById(id);
          if (requestId !== latestGetDeployRequest) return response;
          set({ currentDeploy: response, isLoading: false });
          return response;
        } catch (error: unknown) {
          if (requestId !== latestGetDeployRequest) throw error;
          set({ error: getErrorMessage(error, 'Failed to get deploy'), isLoading: false });
          throw error;
        }
      },

      createDeploy: async (data: DeployCreate) => {
        set({ isSubmitting: true, error: null });
        try {
          const response = await deployService.create(data);
          const { deploys } = get();
          set({
            deploys: [response, ...deploys],
            total: get().total + 1,
            isSubmitting: false,
          });
          return response;
        } catch (error: unknown) {
          set({ error: getErrorMessage(error, 'Failed to create deploy'), isSubmitting: false });
          throw error;
        }
      },

      markSuccess: async (id: string) => {
        set({ isSubmitting: true, error: null });
        try {
          await deployService.markSuccess(id);
          const { deploys, currentDeploy } = get();
          set({
            deploys: deploys.map((d) => (d.id === id ? { ...d, status: 'success' as const } : d)),
            currentDeploy:
              currentDeploy?.id === id
                ? { ...currentDeploy, status: 'success' as const }
                : currentDeploy,
            isSubmitting: false,
          });
        } catch (error: unknown) {
          set({
            error: getErrorMessage(error, 'Failed to mark deploy as success'),
            isSubmitting: false,
          });
          throw error;
        }
      },

      markFailed: async (id: string, message?: string) => {
        set({ isSubmitting: true, error: null });
        try {
          await deployService.markFailed(id, message);
          const { deploys, currentDeploy } = get();
          set({
            deploys: deploys.map((d) => (d.id === id ? { ...d, status: 'failed' as const } : d)),
            currentDeploy:
              currentDeploy?.id === id
                ? { ...currentDeploy, status: 'failed' as const }
                : currentDeploy,
            isSubmitting: false,
          });
        } catch (error: unknown) {
          set({
            error: getErrorMessage(error, 'Failed to mark deploy as failed'),
            isSubmitting: false,
          });
          throw error;
        }
      },

      cancelDeploy: async (id: string) => {
        set({ isSubmitting: true, error: null });
        try {
          await deployService.cancel(id);
          const { deploys, currentDeploy } = get();
          set({
            deploys: deploys.map((d) => (d.id === id ? { ...d, status: 'cancelled' as const } : d)),
            currentDeploy:
              currentDeploy?.id === id
                ? { ...currentDeploy, status: 'cancelled' as const }
                : currentDeploy,
            isSubmitting: false,
          });
        } catch (error: unknown) {
          set({ error: getErrorMessage(error, 'Failed to cancel deploy'), isSubmitting: false });
          throw error;
        }
      },

      getLatestDeploy: async (instanceId: string) => {
        const requestId = latestGetLatestDeployRequest + 1;
        latestGetLatestDeployRequest = requestId;
        set({ isLoading: true, error: null });
        try {
          const response = await deployService.getLatestForInstance(instanceId);
          if (requestId !== latestGetLatestDeployRequest) return response;
          set({ isLoading: false });
          return response;
        } catch (error: unknown) {
          if (requestId !== latestGetLatestDeployRequest) throw error;
          set({
            error: getErrorMessage(error, 'Failed to get latest deploy'),
            isLoading: false,
          });
          throw error;
        }
      },

      setCurrentDeploy: (deploy: DeployResponse | null) => {
        set({ currentDeploy: deploy });
      },

      clearError: () => {
        set({ error: null });
      },

      reset: () => {
        invalidateDeployReadRequests();
        set(initialState);
      },
    }),
    {
      name: 'DeployStore',
      enabled: import.meta.env.DEV,
    }
  )
);

// ============================================================================
// SELECTOR HOOKS
// ============================================================================

export const useDeploys = () => useDeployStore((s) => s.deploys);
export const useCurrentDeploy = () => useDeployStore((s) => s.currentDeploy);
export const useDeployLoading = () => useDeployStore((s) => s.isLoading);
export const useDeploySubmitting = () => useDeployStore((s) => s.isSubmitting);
export const useDeployError = () => useDeployStore((s) => s.error);
export const useDeployTotal = () => useDeployStore((s) => s.total);

export const useDeployActions = () =>
  useDeployStore(
    useShallow((s) => ({
      listDeploys: s.listDeploys,
      getDeploy: s.getDeploy,
      createDeploy: s.createDeploy,
      markSuccess: s.markSuccess,
      markFailed: s.markFailed,
      cancelDeploy: s.cancelDeploy,
      getLatestDeploy: s.getLatestDeploy,
      setCurrentDeploy: s.setCurrentDeploy,
      clearError: s.clearError,
      reset: s.reset,
    }))
  );
