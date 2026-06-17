/**
 * SubAgent Zustand Store
 *
 * State management for SubAgent CRUD operations, templates,
 * and filtering/search functionality.
 */

import { create } from 'zustand';
import { devtools } from 'zustand/middleware';

import { subagentAPI } from '../services/subagentService';

import type {
  SubAgentResponse,
  SubAgentCreate,
  SubAgentUpdate,
  SubAgentTemplate,
} from '../types/agent';
import type { UnknownError } from '../types/common';
import type { SubAgentListParams } from '../services/subagentService';

/**
 * Helper function to extract error message from unknown error
 */
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

interface SubAgentFilters {
  search: string;
  enabled: boolean | null; // null = all, true = enabled only, false = disabled only
}

interface SubAgentActionOptions {
  tenant_id?: string | null | undefined;
}

interface SubAgentState {
  // Data
  subagents: SubAgentResponse[];
  currentSubAgent: SubAgentResponse | null;
  templates: SubAgentTemplate[];

  // Pagination
  total: number;
  enabledTotal: number;
  averageSuccessRate: number;
  totalInvocations: number;
  page: number;
  pageSize: number;

  // Filters
  filters: SubAgentFilters;

  // Loading states
  isLoading: boolean;
  isTemplatesLoading: boolean;
  isSubmitting: boolean;

  // Error state
  error: string | null;

  // Actions - SubAgent CRUD
  listSubAgents: (params?: SubAgentListParams) => Promise<void>;
  getSubAgent: (id: string, options?: SubAgentActionOptions) => Promise<SubAgentResponse>;
  createSubAgent: (
    data: SubAgentCreate,
    options?: SubAgentActionOptions
  ) => Promise<SubAgentResponse>;
  updateSubAgent: (
    id: string,
    data: SubAgentUpdate,
    options?: SubAgentActionOptions
  ) => Promise<SubAgentResponse>;
  deleteSubAgent: (id: string, options?: SubAgentActionOptions) => Promise<void>;
  toggleSubAgent: (id: string, enabled: boolean, options?: SubAgentActionOptions) => Promise<void>;
  setCurrentSubAgent: (subagent: SubAgentResponse | null) => void;

  // Actions - Templates
  listTemplates: (options?: SubAgentActionOptions) => Promise<void>;
  createFromTemplate: (
    templateId: string,
    options?: SubAgentActionOptions
  ) => Promise<SubAgentResponse>;

  // Actions - Filesystem
  importFilesystem: (
    name: string,
    projectId?: string,
    options?: SubAgentActionOptions
  ) => Promise<SubAgentResponse>;

  // Actions - Filters
  setFilters: (filters: Partial<SubAgentFilters>) => void;
  resetFilters: () => void;

  // Actions - Utility
  clearError: () => void;
  reset: () => void;
}

// ============================================================================
// INITIAL STATE
// ============================================================================

const initialFilters: SubAgentFilters = {
  search: '',
  enabled: null,
};

const initialState = {
  subagents: [],
  currentSubAgent: null,
  templates: [],
  total: 0,
  enabledTotal: 0,
  averageSuccessRate: 0,
  totalInvocations: 0,
  page: 1,
  pageSize: 20,
  filters: initialFilters,
  isLoading: false,
  isTemplatesLoading: false,
  isSubmitting: false,
  error: null,
};

// ============================================================================
// STORE CREATION
// ============================================================================

export const useSubAgentStore = create<SubAgentState>()(
  devtools(
    (set, get) => ({
      ...initialState,

      // ========== SubAgent CRUD ==========

      listSubAgents: async (params = {}) => {
        set({ isLoading: true, error: null });
        try {
          const { filters } = get();
          const limit = params.limit ?? get().pageSize;
          const offset = params.offset ?? params.skip ?? 0;
          const queryParams = {
            ...params,
            limit,
            offset,
            enabled_only:
              params.enabled_only !== undefined
                ? params.enabled_only
                : filters.enabled === true
                  ? true
                  : undefined,
          };
          const response = await subagentAPI.list(queryParams);
          const subagents = response.subagents ?? [];
          set({
            subagents,
            total: response.total ?? subagents.length,
            enabledTotal:
              response.enabled_total ?? subagents.filter((subagent) => subagent.enabled).length,
            averageSuccessRate:
              response.average_success_rate ??
              (() => {
                const ratedSubagents = subagents.filter(
                  (subagent) => subagent.enabled && subagent.total_invocations > 0
                );
                return ratedSubagents.length > 0
                  ? ratedSubagents.reduce((sum, subagent) => sum + subagent.success_rate, 0) /
                      ratedSubagents.length
                  : 0;
              })(),
            totalInvocations:
              response.total_invocations ??
              subagents.reduce((sum, subagent) => sum + subagent.total_invocations, 0),
            page: Math.floor(offset / Math.max(limit, 1)) + 1,
            pageSize: limit,
            isLoading: false,
          });
        } catch (error: unknown) {
          const errorMessage = getErrorMessage(error, 'Failed to list subagents');
          set({ error: errorMessage, isLoading: false });
          throw error;
        }
      },

      getSubAgent: async (id: string, options = {}) => {
        set({ isLoading: true, error: null });
        try {
          const response = await subagentAPI.get(id, options);
          set({ currentSubAgent: response, isLoading: false });
          return response;
        } catch (error: unknown) {
          const errorMessage = getErrorMessage(error, 'Failed to get subagent');
          set({ error: errorMessage, isLoading: false });
          throw error;
        }
      },

      createSubAgent: async (data: SubAgentCreate, options = {}) => {
        set({ isSubmitting: true, error: null });
        try {
          const response = await subagentAPI.create(data, options);
          const { subagents } = get();
          set({
            subagents: [response, ...subagents],
            currentSubAgent: response,
            total: get().total + 1,
            isSubmitting: false,
          });
          return response;
        } catch (error: unknown) {
          const errorMessage = getErrorMessage(error, 'Failed to create subagent');
          set({ error: errorMessage, isSubmitting: false });
          throw error;
        }
      },

      updateSubAgent: async (id: string, data: SubAgentUpdate, options = {}) => {
        set({ isSubmitting: true, error: null });
        try {
          const response = await subagentAPI.update(id, data, options);
          const { subagents, currentSubAgent } = get();
          set({
            subagents: subagents.map((sa) => (sa.id === id ? response : sa)),
            currentSubAgent: currentSubAgent?.id === id ? response : currentSubAgent,
            isSubmitting: false,
          });
          return response;
        } catch (error: unknown) {
          const errorMessage = getErrorMessage(error, 'Failed to update subagent');
          set({ error: errorMessage, isSubmitting: false });
          throw error;
        }
      },

      deleteSubAgent: async (id: string, options = {}) => {
        set({ isSubmitting: true, error: null });
        try {
          await subagentAPI.delete(id, options);
          const { subagents, currentSubAgent } = get();
          set({
            subagents: subagents.filter((sa) => sa.id !== id),
            currentSubAgent: currentSubAgent?.id === id ? null : currentSubAgent,
            total: Math.max(0, get().total - 1),
            isSubmitting: false,
          });
        } catch (error: unknown) {
          const errorMessage = getErrorMessage(error, 'Failed to delete subagent');
          set({ error: errorMessage, isSubmitting: false });
          throw error;
        }
      },

      toggleSubAgent: async (id: string, enabled: boolean, options = {}) => {
        // Optimistic update
        const { subagents } = get();
        const originalSubagents = [...subagents];
        set({
          subagents: subagents.map((sa) => (sa.id === id ? { ...sa, enabled } : sa)),
        });

        try {
          const response = await subagentAPI.toggle(id, enabled, options);
          const { currentSubAgent } = get();
          set({
            subagents: get().subagents.map((sa) => (sa.id === id ? response : sa)),
            currentSubAgent: currentSubAgent?.id === id ? response : currentSubAgent,
          });
        } catch (error: unknown) {
          // Rollback on error
          set({ subagents: originalSubagents });
          const errorMessage = getErrorMessage(error, 'Failed to toggle subagent');
          set({ error: errorMessage });
          throw error;
        }
      },

      setCurrentSubAgent: (subagent: SubAgentResponse | null) => {
        set({ currentSubAgent: subagent });
      },

      // ========== Templates ==========

      listTemplates: async (options = {}) => {
        set({ isTemplatesLoading: true, error: null });
        try {
          const response = await subagentAPI.listTemplates(options);
          set({
            templates: response.templates,
            isTemplatesLoading: false,
          });
        } catch (error: unknown) {
          const errorMessage = getErrorMessage(error, 'Failed to list templates');
          set({ error: errorMessage, isTemplatesLoading: false });
          throw error;
        }
      },

      createFromTemplate: async (templateId: string, options = {}) => {
        set({ isSubmitting: true, error: null });
        try {
          const response = await subagentAPI.createFromTemplate(templateId, options);
          const { subagents } = get();
          set({
            subagents: [response, ...subagents],
            currentSubAgent: response,
            total: get().total + 1,
            isSubmitting: false,
          });
          return response;
        } catch (error: unknown) {
          const errorMessage = getErrorMessage(error, 'Failed to create from template');
          set({ error: errorMessage, isSubmitting: false });
          throw error;
        }
      },

      // ========== Filesystem Import ==========

      importFilesystem: async (name: string, projectId?: string, options = {}) => {
        set({ isSubmitting: true, error: null });
        try {
          const response = await subagentAPI.importFilesystem(name, projectId, options);
          // Refresh the full list to get merged view
          await get().listSubAgents(options);
          set({ isSubmitting: false });
          return response;
        } catch (error: unknown) {
          const errorMessage = getErrorMessage(error, 'Failed to import filesystem SubAgent');
          set({ error: errorMessage, isSubmitting: false });
          throw error;
        }
      },

      // ========== Filters ==========

      setFilters: (filters: Partial<SubAgentFilters>) => {
        set({ filters: { ...get().filters, ...filters } });
      },

      resetFilters: () => {
        set({ filters: initialFilters });
      },

      // ========== Utility ==========

      clearError: () => {
        set({ error: null });
      },

      reset: () => {
        set(initialState);
      },
    }),
    {
      name: 'SubAgentStore',
      enabled: import.meta.env.DEV,
    }
  )
);

// ============================================================================
// SELECTORS - Fine-grained subscriptions for performance
// ============================================================================

// Data selectors
export const useSubAgents = () => useSubAgentStore((state) => state.subagents);
export const useCurrentSubAgent = () => useSubAgentStore((state) => state.currentSubAgent);
export const useSubAgentTemplates = () => useSubAgentStore((state) => state.templates);
export const useSubAgentTotal = () => useSubAgentStore((state) => state.total);
export const useSubAgentPage = () => useSubAgentStore((state) => state.page);
export const useSubAgentPageSize = () => useSubAgentStore((state) => state.pageSize);

// Filter selectors
export const useSubAgentFilters = () => useSubAgentStore((state) => state.filters);

// Loading selectors
export const useSubAgentLoading = () => useSubAgentStore((state) => state.isLoading);
export const useSubAgentTemplatesLoading = () =>
  useSubAgentStore((state) => state.isTemplatesLoading);
export const useSubAgentSubmitting = () => useSubAgentStore((state) => state.isSubmitting);

// Error selector
export const useSubAgentError = () => useSubAgentStore((state) => state.error);

// Computed selectors
// Returns raw data for filtering - use useMemo in component to compute filtered results
export const useSubAgentData = () => useSubAgentStore((state) => state.subagents);
export const useSubAgentFiltersData = () => useSubAgentStore((state) => state.filters);

// Helper function to filter subagents (use with useMemo in components)
export const filterSubAgents = (subagents: SubAgentResponse[], filters: SubAgentFilters) => {
  return subagents.filter((sa) => {
    // Search filter
    if (filters.search) {
      const searchLower = filters.search.toLowerCase();
      const matchesSearch =
        sa.name.toLowerCase().includes(searchLower) ||
        sa.display_name.toLowerCase().includes(searchLower) ||
        sa.trigger.description.toLowerCase().includes(searchLower) ||
        sa.trigger.keywords.some((k) => k.toLowerCase().includes(searchLower));
      if (!matchesSearch) return false;
    }
    // Enabled filter
    if (filters.enabled !== null && sa.enabled !== filters.enabled) {
      return false;
    }
    return true;
  });
};

export const useEnabledSubAgentsCount = () => useSubAgentStore((state) => state.enabledTotal);

export const useAverageSuccessRate = () => useSubAgentStore((state) => state.averageSuccessRate);

export const useTotalInvocations = () => useSubAgentStore((state) => state.totalInvocations);

// Action selectors - each returns a stable function reference
export const useListSubAgents = () => useSubAgentStore((state) => state.listSubAgents);
export const useGetSubAgent = () => useSubAgentStore((state) => state.getSubAgent);
export const useCreateSubAgent = () => useSubAgentStore((state) => state.createSubAgent);
export const useUpdateSubAgent = () => useSubAgentStore((state) => state.updateSubAgent);
export const useDeleteSubAgent = () => useSubAgentStore((state) => state.deleteSubAgent);
export const useToggleSubAgent = () => useSubAgentStore((state) => state.toggleSubAgent);
export const useSetCurrentSubAgent = () => useSubAgentStore((state) => state.setCurrentSubAgent);
export const useListTemplates = () => useSubAgentStore((state) => state.listTemplates);
export const useCreateFromTemplate = () => useSubAgentStore((state) => state.createFromTemplate);
export const useImportFilesystem = () => useSubAgentStore((state) => state.importFilesystem);
export const useSetSubAgentFilters = () => useSubAgentStore((state) => state.setFilters);
export const useResetSubAgentFilters = () => useSubAgentStore((state) => state.resetFilters);
export const useClearSubAgentError = () => useSubAgentStore((state) => state.clearError);
export const useResetSubAgentStore = () => useSubAgentStore((state) => state.reset);
