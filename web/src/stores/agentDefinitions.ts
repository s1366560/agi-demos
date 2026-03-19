/**
 * Agent Definitions Zustand Store
 *
 * State management for agent definition CRUD operations,
 * filtering, and search functionality.
 */

import { create } from 'zustand';
import { devtools } from 'zustand/middleware';

import { definitionsService } from '../services/agent/definitionsService';

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

interface AgentDefinitionState {
  // Data
  definitions: AgentDefinition[];
  currentDefinition: AgentDefinition | null;

  // Loading states
  isLoading: boolean;
  isSubmitting: boolean;

  // Error state
  error: string | null;

  // Filters
  filters: DefinitionFilters;

  // Actions - CRUD
  listDefinitions: (params?: {
    project_id?: string | undefined;
    enabled_only?: boolean | undefined;
    limit?: number | undefined;
    offset?: number | undefined;
  }) => Promise<void>;
  getDefinition: (id: string) => Promise<AgentDefinition>;
  createDefinition: (data: CreateDefinitionRequest) => Promise<AgentDefinition>;
  updateDefinition: (id: string, data: UpdateDefinitionRequest) => Promise<AgentDefinition>;
  deleteDefinition: (id: string) => Promise<void>;
  toggleEnabled: (id: string, enabled: boolean) => Promise<void>;
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
  isLoading: false,
  isSubmitting: false,
  error: null,
  filters: initialFilters,
};

// ============================================================================
// STORE CREATION
// ============================================================================

export const useAgentDefinitionStore = create<AgentDefinitionState>()(
  devtools(
    (set, get) => ({
      ...initialState,

      // ========== CRUD ==========

      listDefinitions: async (params = {}) => {
        set({ isLoading: true, error: null });
        try {
          const { filters } = get();
          const queryParams = {
            ...params,
            project_id: params.project_id ?? filters.projectId ?? undefined,
            enabled_only: filters.enabled === true ? true : undefined,
          };
          const definitions = await definitionsService.list(queryParams);
          set({ definitions, isLoading: false });
        } catch (error: unknown) {
          const msg = getErrorMessage(error, 'Failed to list agent definitions');
          set({ error: msg, isLoading: false });
          throw error;
        }
      },

      getDefinition: async (id: string) => {
        set({ isLoading: true, error: null });
        try {
          const definition = await definitionsService.getById(id);
          set({ currentDefinition: definition, isLoading: false });
          return definition;
        } catch (error: unknown) {
          const msg = getErrorMessage(error, 'Failed to get agent definition');
          set({ error: msg, isLoading: false });
          throw error;
        }
      },

      createDefinition: async (data: CreateDefinitionRequest) => {
        set({ isSubmitting: true, error: null });
        try {
          const created = await definitionsService.create(data);
          const { definitions } = get();
          set({
            definitions: [created, ...definitions],
            currentDefinition: created,
            isSubmitting: false,
          });
          return created;
        } catch (error: unknown) {
          const msg = getErrorMessage(error, 'Failed to create agent definition');
          set({ error: msg, isSubmitting: false });
          throw error;
        }
      },

      updateDefinition: async (id: string, data: UpdateDefinitionRequest) => {
        set({ isSubmitting: true, error: null });
        try {
          const updated = await definitionsService.update(id, data);
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

      deleteDefinition: async (id: string) => {
        set({ isSubmitting: true, error: null });
        try {
          await definitionsService.delete(id);
          const { definitions, currentDefinition } = get();
          set({
            definitions: definitions.filter((d) => d.id !== id),
            currentDefinition: currentDefinition?.id === id ? null : currentDefinition,
            isSubmitting: false,
          });
        } catch (error: unknown) {
          const msg = getErrorMessage(error, 'Failed to delete agent definition');
          set({ error: msg, isSubmitting: false });
          throw error;
        }
      },

      toggleEnabled: async (id: string, enabled: boolean) => {
        // Optimistic update
        const { definitions } = get();
        const original = [...definitions];
        set({
          definitions: definitions.map((d) => (d.id === id ? { ...d, enabled } : d)),
        });

        try {
          const updated = await definitionsService.setEnabled(id, enabled);
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
