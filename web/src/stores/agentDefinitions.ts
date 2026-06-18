/**
 * Agent Definitions Zustand Store
 *
 * State management for agent definition CRUD operations,
 * filtering, and search functionality.
 */

import { create } from 'zustand';
import { devtools } from 'zustand/middleware';
import { useShallow } from 'zustand/react/shallow';

import { definitionsService } from '../services/agent/definitionsService';

import type { DefinitionListParams } from '../services/agent/definitionsService';
import type { UnknownError } from '../types/common';
import type {
  AgentDefinition,
  CreateDefinitionRequest,
  UpdateDefinitionRequest,
} from '../types/multiAgent';

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

interface DefinitionFilters {
  search: string;
  enabled: boolean | null; // null = all, true = enabled only, false = disabled only
  projectId: string | null;
}

type DefinitionListRequestParams = Omit<DefinitionListParams, 'project_id' | 'tenant_id'> & {
  project_id?: string | null | undefined;
  tenant_id?: string | null | undefined;
};

interface DefinitionActionOptions {
  tenant_id?: string | null | undefined;
}

interface AgentDefinitionState {
  // Data
  definitions: AgentDefinition[];
  currentDefinition: AgentDefinition | null;
  total: number;
  page: number;
  pageSize: number;

  // Loading states
  isLoading: boolean;
  isSubmitting: boolean;

  // Error state
  error: string | null;

  // Filters
  filters: DefinitionFilters;

  // Actions - CRUD
  listDefinitions: (params?: DefinitionListRequestParams) => Promise<void>;
  listDefinitionsPage: (params?: DefinitionListRequestParams) => Promise<void>;
  getDefinition: (id: string, options?: DefinitionActionOptions) => Promise<AgentDefinition>;
  createDefinition: (
    data: CreateDefinitionRequest,
    options?: DefinitionActionOptions
  ) => Promise<AgentDefinition>;
  updateDefinition: (
    id: string,
    data: UpdateDefinitionRequest,
    options?: DefinitionActionOptions
  ) => Promise<AgentDefinition>;
  deleteDefinition: (id: string, options?: DefinitionActionOptions) => Promise<void>;
  toggleEnabled: (id: string, enabled: boolean, options?: DefinitionActionOptions) => Promise<void>;
  setCurrentDefinition: (definition: AgentDefinition | null) => void;

  // Actions - Filters
  setFilters: (filters: Partial<DefinitionFilters>) => void;
  resetFilters: () => void;

  // Actions - Utility
  clearError: () => void;
  reset: () => void;
}

// ============================================================================
// INITIAL STATE
// ============================================================================

const initialFilters: DefinitionFilters = {
  search: '',
  enabled: null,
  projectId: null,
};

const initialState = {
  definitions: [],
  currentDefinition: null,
  total: 0,
  page: 1,
  pageSize: 20,
  isLoading: false,
  isSubmitting: false,
  error: null,
  filters: initialFilters,
};

let definitionListRequestSequence = 0;

// ============================================================================
// STORE CREATION
// ============================================================================

export const useAgentDefinitionStore = create<AgentDefinitionState>()(
  devtools(
    (set, get) => ({
      ...initialState,

      // ========== CRUD ==========

      listDefinitions: async (params = {}) => {
        const requestId = ++definitionListRequestSequence;
        set({ isLoading: true, error: null });
        try {
          const { filters } = get();
          const enabledOnlyFilter =
            params.enabled_only ??
            (params.enabled !== undefined
              ? undefined
              : filters.enabled === true
                ? true
                : undefined);
          const queryParams = {
            ...params,
            tenant_id: params.tenant_id ?? undefined,
            project_id:
              params.project_id === null
                ? undefined
                : (params.project_id ?? filters.projectId ?? undefined),
            enabled_only: enabledOnlyFilter,
          };
          const definitions = await definitionsService.list(queryParams);
          if (definitionListRequestSequence !== requestId) {
            return;
          }
          set({ definitions, total: definitions.length, page: 1, isLoading: false });
        } catch (error: unknown) {
          if (definitionListRequestSequence !== requestId) {
            return;
          }
          const msg = getErrorMessage(error, 'Failed to list agent definitions');
          set({ error: msg, isLoading: false });
          throw error;
        }
      },

      listDefinitionsPage: async (params = {}) => {
        const requestId = ++definitionListRequestSequence;
        set({ isLoading: true, error: null });
        try {
          const { filters, pageSize: currentPageSize } = get();
          const queryParams = {
            ...params,
            tenant_id: params.tenant_id ?? undefined,
            project_id:
              params.project_id === null
                ? undefined
                : (params.project_id ?? filters.projectId ?? undefined),
            limit: params.limit ?? currentPageSize,
            offset: params.offset ?? 0,
          };
          const response = await definitionsService.listPage(queryParams);
          if (definitionListRequestSequence !== requestId) {
            return;
          }
          const pageSize = response.limit || queryParams.limit || currentPageSize;
          set({
            definitions: response.definitions,
            total: response.total,
            page: Math.floor(response.offset / Math.max(pageSize, 1)) + 1,
            pageSize,
            isLoading: false,
          });
        } catch (error: unknown) {
          if (definitionListRequestSequence !== requestId) {
            return;
          }
          const msg = getErrorMessage(error, 'Failed to list agent definitions');
          set({ error: msg, isLoading: false });
          throw error;
        }
      },

      getDefinition: async (id: string, options = {}) => {
        set({ isLoading: true, error: null });
        try {
          const definition = await definitionsService.getById(id, options);
          set({ currentDefinition: definition, isLoading: false });
          return definition;
        } catch (error: unknown) {
          const msg = getErrorMessage(error, 'Failed to get agent definition');
          set({ error: msg, isLoading: false });
          throw error;
        }
      },

      createDefinition: async (data: CreateDefinitionRequest, options = {}) => {
        set({ isSubmitting: true, error: null });
        try {
          const created = await definitionsService.create(data, options);
          const { definitions } = get();
          set({
            definitions: [created, ...definitions],
            currentDefinition: created,
            total: get().total + 1,
            isSubmitting: false,
          });
          return created;
        } catch (error: unknown) {
          const msg = getErrorMessage(error, 'Failed to create agent definition');
          set({ error: msg, isSubmitting: false });
          throw error;
        }
      },

      updateDefinition: async (id: string, data: UpdateDefinitionRequest, options = {}) => {
        set({ isSubmitting: true, error: null });
        try {
          const updated = await definitionsService.update(id, data, options);
          const { definitions, currentDefinition } = get();
          set({
            definitions: definitions.map((d) => (d.id === id ? updated : d)),
            currentDefinition: currentDefinition?.id === id ? updated : currentDefinition,
            isSubmitting: false,
          });
          return updated;
        } catch (error: unknown) {
          const msg = getErrorMessage(error, 'Failed to update agent definition');
          set({ error: msg, isSubmitting: false });
          throw error;
        }
      },

      deleteDefinition: async (id: string, options = {}) => {
        set({ isSubmitting: true, error: null });
        try {
          await definitionsService.delete(id, options);
          const { definitions, currentDefinition } = get();
          set({
            definitions: definitions.filter((d) => d.id !== id),
            currentDefinition: currentDefinition?.id === id ? null : currentDefinition,
            total: Math.max(get().total - 1, 0),
            isSubmitting: false,
          });
        } catch (error: unknown) {
          const msg = getErrorMessage(error, 'Failed to delete agent definition');
          set({ error: msg, isSubmitting: false });
          throw error;
        }
      },

      toggleEnabled: async (id: string, enabled: boolean, options = {}) => {
        // Optimistic update
        const { definitions } = get();
        const original = [...definitions];
        set({
          definitions: definitions.map((d) => (d.id === id ? { ...d, enabled } : d)),
        });

        try {
          const updated = await definitionsService.setEnabled(id, enabled, options);
          const { currentDefinition } = get();
          set({
            definitions: get().definitions.map((d) => (d.id === id ? updated : d)),
            currentDefinition: currentDefinition?.id === id ? updated : currentDefinition,
          });
        } catch (error: unknown) {
          // Rollback on error
          set({ definitions: original });
          const msg = getErrorMessage(error, 'Failed to toggle agent definition');
          set({ error: msg });
          throw error;
        }
      },

      setCurrentDefinition: (definition: AgentDefinition | null) => {
        set({ currentDefinition: definition });
      },

      // ========== Filters ==========

      setFilters: (filters: Partial<DefinitionFilters>) => {
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
        definitionListRequestSequence += 1;
        set(initialState);
      },
    }),
    {
      name: 'AgentDefinitionStore',
      enabled: import.meta.env.DEV,
    }
  )
);

// ============================================================================
// SELECTORS - Fine-grained subscriptions for performance
// ============================================================================

// Data selectors
export const useDefinitions = () => useAgentDefinitionStore((state) => state.definitions);
export const useCurrentDefinition = () =>
  useAgentDefinitionStore((state) => state.currentDefinition);
export const useDefinitionPagination = () =>
  useAgentDefinitionStore(
    useShallow((state) => ({
      total: state.total,
      page: state.page,
      pageSize: state.pageSize,
    }))
  );

// Loading selectors
export const useDefinitionLoading = () => useAgentDefinitionStore((state) => state.isLoading);
export const useDefinitionSubmitting = () => useAgentDefinitionStore((state) => state.isSubmitting);

// Error selector
export const useDefinitionError = () => useAgentDefinitionStore((state) => state.error);

// Filter selector
export const useDefinitionFilters = () => useAgentDefinitionStore((state) => state.filters);

// Computed selectors
export const useEnabledDefinitionsCount = () =>
  useAgentDefinitionStore((state) => state.definitions.filter((d) => d.enabled).length);

// Helper function to filter definitions (use with useMemo in components)
export const filterDefinitions = (
  definitions: AgentDefinition[],
  filters: DefinitionFilters
): AgentDefinition[] => {
  return definitions.filter((d) => {
    // Search filter
    if (filters.search) {
      const searchLower = filters.search.toLowerCase();
      const matchesSearch =
        d.name.toLowerCase().includes(searchLower) ||
        (d.display_name ?? '').toLowerCase().includes(searchLower);
      if (!matchesSearch) return false;
    }
    // Enabled filter
    if (filters.enabled !== null && d.enabled !== filters.enabled) {
      return false;
    }
    // Project filter
    if (filters.projectId !== null && d.project_id !== filters.projectId) {
      return false;
    }
    return true;
  });
};

// Action selectors - each returns a stable function reference
export const useListDefinitions = () => useAgentDefinitionStore((state) => state.listDefinitions);
export const useListDefinitionsPage = () =>
  useAgentDefinitionStore((state) => state.listDefinitionsPage);
export const useGetDefinition = () => useAgentDefinitionStore((state) => state.getDefinition);
export const useCreateDefinition = () => useAgentDefinitionStore((state) => state.createDefinition);
export const useUpdateDefinition = () => useAgentDefinitionStore((state) => state.updateDefinition);
export const useDeleteDefinition = () => useAgentDefinitionStore((state) => state.deleteDefinition);
export const useToggleDefinitionEnabled = () =>
  useAgentDefinitionStore((state) => state.toggleEnabled);
export const useSetCurrentDefinition = () =>
  useAgentDefinitionStore((state) => state.setCurrentDefinition);
export const useSetDefinitionFilters = () => useAgentDefinitionStore((state) => state.setFilters);
export const useResetDefinitionFilters = () =>
  useAgentDefinitionStore((state) => state.resetFilters);
export const useClearDefinitionError = () => useAgentDefinitionStore((state) => state.clearError);
export const useResetDefinitionStore = () => useAgentDefinitionStore((state) => state.reset);
