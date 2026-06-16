import { create } from 'zustand';
import { devtools } from 'zustand/middleware';

import { bindingsService } from '../services/agent/bindingsService';

import type { BindingListParams } from '../services/agent/bindingsService';
import type { UnknownError } from '../types/common';
import type { AgentBinding, CreateBindingRequest } from '../types/multiAgent';

function getErrorMessage(error: unknown, fallback: string): string {
  const err = error as UnknownError;
  if (err.response?.data?.detail) {
    const detail = err.response.data.detail;
    return typeof detail === 'string' ? detail : JSON.stringify(detail);
  }
  if (err.message) {
    return err.message;
  }
  return fallback;
}

// ============================================================================
// STATE INTERFACE
// ============================================================================

interface BindingFilters {
  agentId: string | null;
  enabledOnly: boolean;
}

type BindingListRequestParams = Omit<BindingListParams, 'agent_id' | 'tenant_id'> & {
  agent_id?: string | null | undefined;
  tenant_id?: string | null | undefined;
};

interface BindingActionOptions {
  tenant_id?: string | null | undefined;
}

interface AgentBindingState {
  bindings: AgentBinding[];
  isLoading: boolean;
  isSubmitting: boolean;
  error: string | null;
  filters: BindingFilters;

  listBindings: (params?: BindingListRequestParams) => Promise<void>;
  createBinding: (
    data: CreateBindingRequest,
    options?: BindingActionOptions
  ) => Promise<AgentBinding>;
  deleteBinding: (id: string, options?: BindingActionOptions) => Promise<void>;
  toggleBinding: (
    id: string,
    enabled: boolean,
    options?: BindingActionOptions
  ) => Promise<void>;

  setFilters: (filters: Partial<BindingFilters>) => void;
  resetFilters: () => void;
  clearError: () => void;
  reset: () => void;
}

// ============================================================================
// INITIAL STATE
// ============================================================================

const initialFilters: BindingFilters = {
  agentId: null,
  enabledOnly: false,
};

const initialState = {
  bindings: [],
  isLoading: false,
  isSubmitting: false,
  error: null,
  filters: initialFilters,
};

// ============================================================================
// STORE CREATION
// ============================================================================

export const useAgentBindingStore = create<AgentBindingState>()(
  devtools(
    (set, get) => ({
      ...initialState,

      listBindings: async (params = {}) => {
        set({ isLoading: true, error: null });
        try {
          const { filters } = get();
          const queryParams = {
            ...params,
            tenant_id: params.tenant_id ?? undefined,
            agent_id: params.agent_id ?? filters.agentId ?? undefined,
            enabled_only: params.enabled_only ?? (filters.enabledOnly || undefined),
          };
          const bindings = await bindingsService.list(queryParams);
          set({ bindings, isLoading: false });
        } catch (error: unknown) {
          const msg = getErrorMessage(error, 'Failed to list bindings');
          set({ error: msg, isLoading: false });
          throw error;
        }
      },

      createBinding: async (data: CreateBindingRequest, options = {}) => {
        set({ isSubmitting: true, error: null });
        try {
          const created = await bindingsService.create(data, options);
          const { bindings } = get();
          set({
            bindings: [created, ...bindings],
            isSubmitting: false,
          });
          return created;
        } catch (error: unknown) {
          const msg = getErrorMessage(error, 'Failed to create binding');
          set({ error: msg, isSubmitting: false });
          throw error;
        }
      },

      deleteBinding: async (id: string, options = {}) => {
        set({ isSubmitting: true, error: null });
        try {
          await bindingsService.delete(id, options);
          const { bindings } = get();
          set({
            bindings: bindings.filter((b) => b.id !== id),
            isSubmitting: false,
          });
        } catch (error: unknown) {
          const msg = getErrorMessage(error, 'Failed to delete binding');
          set({ error: msg, isSubmitting: false });
          throw error;
        }
      },

      toggleBinding: async (id: string, enabled: boolean, options = {}) => {
        const { bindings } = get();
        const original = [...bindings];
        set({
          bindings: bindings.map((b) => (b.id === id ? { ...b, enabled } : b)),
        });

        try {
          const updated = await bindingsService.setEnabled(id, enabled, options);
          set({
            bindings: get().bindings.map((b) => (b.id === id ? updated : b)),
          });
        } catch (error: unknown) {
          set({ bindings: original });
          const msg = getErrorMessage(error, 'Failed to toggle binding');
          set({ error: msg });
          throw error;
        }
      },

      setFilters: (filters: Partial<BindingFilters>) => {
        set({ filters: { ...get().filters, ...filters } });
      },

      resetFilters: () => {
        set({ filters: initialFilters });
      },

      clearError: () => {
        set({ error: null });
      },

      reset: () => {
        set(initialState);
      },
    }),
    {
      name: 'AgentBindingStore',
      enabled: import.meta.env.DEV,
    }
  )
);

// ============================================================================
// SELECTORS
// ============================================================================

export const useBindings = () => useAgentBindingStore((state) => state.bindings);
export const useBindingLoading = () => useAgentBindingStore((state) => state.isLoading);
export const useBindingSubmitting = () => useAgentBindingStore((state) => state.isSubmitting);
export const useBindingError = () => useAgentBindingStore((state) => state.error);
export const useBindingFilters = () => useAgentBindingStore((state) => state.filters);

export const useListBindings = () => useAgentBindingStore((state) => state.listBindings);
export const useCreateBinding = () => useAgentBindingStore((state) => state.createBinding);
export const useDeleteBinding = () => useAgentBindingStore((state) => state.deleteBinding);
export const useToggleBinding = () => useAgentBindingStore((state) => state.toggleBinding);
export const useSetBindingFilters = () => useAgentBindingStore((state) => state.setFilters);
export const useResetBindingFilters = () => useAgentBindingStore((state) => state.resetFilters);
export const useClearBindingError = () => useAgentBindingStore((state) => state.clearError);
export const useResetBindingStore = () => useAgentBindingStore((state) => state.reset);
