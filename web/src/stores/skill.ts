/**
 * Skill Zustand Store
 *
 * State management for Skill CRUD operations and filtering/search functionality.
 * Supports three-level scoping: system, tenant, and project skills.
 */

import { create } from 'zustand';
import { devtools } from 'zustand/middleware';

import { skillAPI, tenantSkillConfigAPI } from '../services/skillService';

import type {
  SkillResponse,
  SkillCreate,
  SkillUpdate,
  TenantSkillConfigResponse,
} from '../types/agent';
import type { UnknownError } from '../types/common';

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

interface SkillFilters {
  search: string;
  status: 'active' | 'disabled' | 'deprecated' | null;
  scope: 'system' | 'tenant' | 'project' | null;
}

interface SkillListParams {
  search?: string | undefined;
  status?: SkillFilters['status'] | undefined;
  scope?: SkillFilters['scope'] | undefined;
  project_id?: string | null | undefined;
  tenant_id?: string | null | undefined;
  skip?: number | undefined;
  offset?: number | undefined;
  limit?: number | undefined;
  page?: number | undefined;
  pageSize?: number | undefined;
}

interface SkillActionOptions {
  tenant_id?: string | null | undefined;
}

interface SkillState {
  // Data
  skills: SkillResponse[];
  systemSkills: SkillResponse[];
  currentSkill: SkillResponse | null;
  tenantConfigs: TenantSkillConfigResponse[];

  // Pagination
  total: number;
  page: number;
  pageSize: number;

  // Filters
  filters: SkillFilters;

  // Loading states
  isLoading: boolean;
  isSubmitting: boolean;

  // Error state
  error: string | null;

  // Actions - Skill CRUD
  listSkills: (params?: SkillListParams) => Promise<void>;
  listSystemSkills: (options?: SkillActionOptions) => Promise<void>;
  getSkill: (id: string, options?: SkillActionOptions) => Promise<SkillResponse>;
  createSkill: (data: SkillCreate, options?: SkillActionOptions) => Promise<SkillResponse>;
  updateSkill: (
    id: string,
    data: SkillUpdate,
    options?: SkillActionOptions
  ) => Promise<SkillResponse>;
  deleteSkill: (id: string, options?: SkillActionOptions) => Promise<void>;
  updateSkillStatus: (
    id: string,
    status: 'active' | 'disabled' | 'deprecated',
    options?: SkillActionOptions
  ) => Promise<void>;
  updateSkillContent: (
    id: string,
    content: string,
    options?: SkillActionOptions
  ) => Promise<SkillResponse>;
  setCurrentSkill: (skill: SkillResponse | null) => void;

  // Actions - Tenant Skill Config
  listTenantConfigs: (options?: SkillActionOptions) => Promise<void>;
  disableSystemSkill: (systemSkillName: string, options?: SkillActionOptions) => Promise<void>;
  enableSystemSkill: (systemSkillName: string, options?: SkillActionOptions) => Promise<void>;
  overrideSystemSkill: (
    systemSkillName: string,
    overrideSkillId: string,
    options?: SkillActionOptions
  ) => Promise<void>;

  // Actions - Filters
  setFilters: (filters: Partial<SkillFilters>) => void;
  resetFilters: () => void;

  // Actions - Utility
  clearError: () => void;
  reset: () => void;
}

// ============================================================================
// INITIAL STATE
// ============================================================================

const initialFilters: SkillFilters = {
  search: '',
  status: null,
  scope: null,
};

const initialState = {
  skills: [],
  systemSkills: [],
  currentSkill: null,
  tenantConfigs: [],
  total: 0,
  page: 1,
  pageSize: 20,
  filters: initialFilters,
  isLoading: false,
  isSubmitting: false,
  error: null,
};

let skillListRequestSequence = 0;
let tenantConfigRequestSequence = 0;

// ============================================================================
// STORE CREATION
// ============================================================================

export const useSkillStore = create<SkillState>()(
  devtools(
    (set, get) => ({
      ...initialState,

      // ========== Skill CRUD ==========

      listSkills: async (params = {}) => {
        const requestId = ++skillListRequestSequence;
        set({ isLoading: true, error: null });
        try {
          const { filters } = get();
          const nextPageSize = params.pageSize ?? params.limit ?? get().pageSize;
          const explicitOffset = params.offset ?? params.skip;
          const nextPage =
            params.page ??
            (explicitOffset !== undefined
              ? Math.floor(explicitOffset / nextPageSize) + 1
              : get().page);
          const offset = explicitOffset ?? (nextPage - 1) * nextPageSize;
          const search = params.search ?? filters.search;
          const status = params.status === undefined ? filters.status : params.status;
          const scope = params.scope === undefined ? filters.scope : params.scope;
          const queryParams = {
            search: search.trim() || undefined,
            status: status || undefined,
            scope: scope || undefined,
            project_id: params.project_id || undefined,
            ...(params.tenant_id ? { tenant_id: params.tenant_id } : {}),
            limit: nextPageSize,
            offset,
          };
          const response = await skillAPI.list(queryParams);
          if (skillListRequestSequence !== requestId) {
            return;
          }
          set({
            skills: response.skills,
            total: response.total,
            page: nextPage,
            pageSize: nextPageSize,
            isLoading: false,
          });
        } catch (error: unknown) {
          if (skillListRequestSequence !== requestId) {
            return;
          }
          const errorMessage = getErrorMessage(error, 'Failed to list skills');
          set({ error: errorMessage, isLoading: false });
          throw error;
        }
      },

      listSystemSkills: async (options = {}) => {
        set({ isLoading: true, error: null });
        try {
          const response = await skillAPI.listSystemSkills(options);
          set({
            systemSkills: response.skills,
            isLoading: false,
          });
        } catch (error: unknown) {
          const errorMessage = getErrorMessage(error, 'Failed to list system skills');
          set({ error: errorMessage, isLoading: false });
          throw error;
        }
      },

      getSkill: async (id: string, options = {}) => {
        set({ isLoading: true, error: null });
        try {
          const response = await skillAPI.get(id, options);
          set({ currentSkill: response, isLoading: false });
          return response;
        } catch (error: unknown) {
          const errorMessage = getErrorMessage(error, 'Failed to get skill');
          set({ error: errorMessage, isLoading: false });
          throw error;
        }
      },

      createSkill: async (data: SkillCreate, options = {}) => {
        set({ isSubmitting: true, error: null });
        try {
          const response = await skillAPI.create(data, options);
          const { skills } = get();
          set({
            skills: [response, ...skills],
            total: get().total + 1,
            isSubmitting: false,
          });
          return response;
        } catch (error: unknown) {
          const errorMessage = getErrorMessage(error, 'Failed to create skill');
          set({ error: errorMessage, isSubmitting: false });
          throw error;
        }
      },

      updateSkill: async (id: string, data: SkillUpdate, options = {}) => {
        set({ isSubmitting: true, error: null });
        try {
          const response = await skillAPI.update(id, data, options);
          const { skills } = get();
          set({
            skills: skills.map((s) => (s.id === id ? response : s)),
            currentSkill: response,
            isSubmitting: false,
          });
          return response;
        } catch (error: unknown) {
          const errorMessage = getErrorMessage(error, 'Failed to update skill');
          set({ error: errorMessage, isSubmitting: false });
          throw error;
        }
      },

      deleteSkill: async (id: string, options = {}) => {
        set({ isSubmitting: true, error: null });
        try {
          await skillAPI.delete(id, options);
          const { skills } = get();
          set({
            skills: skills.filter((s) => s.id !== id),
            total: get().total - 1,
            isSubmitting: false,
          });
        } catch (error: unknown) {
          const errorMessage = getErrorMessage(error, 'Failed to delete skill');
          set({ error: errorMessage, isSubmitting: false });
          throw error;
        }
      },

      updateSkillStatus: async (
        id: string,
        status: 'active' | 'disabled' | 'deprecated',
        options = {}
      ) => {
        set({ isSubmitting: true, error: null });
        try {
          const response = await skillAPI.updateStatus(id, status, options);
          const { skills } = get();
          set({
            skills: skills.map((s) => (s.id === id ? response : s)),
            isSubmitting: false,
          });
        } catch (error: unknown) {
          const errorMessage = getErrorMessage(error, 'Failed to update skill status');
          set({ error: errorMessage, isSubmitting: false });
          throw error;
        }
      },

      setCurrentSkill: (skill: SkillResponse | null) => {
        set({ currentSkill: skill });
      },

      updateSkillContent: async (id: string, content: string, options = {}) => {
        set({ isSubmitting: true, error: null });
        try {
          const response = await skillAPI.updateContent(id, content, options);
          const { skills } = get();
          set({
            skills: skills.map((s) => (s.id === id ? response : s)),
            currentSkill: response,
            isSubmitting: false,
          });
          return response;
        } catch (error: unknown) {
          const errorMessage = getErrorMessage(error, 'Failed to update skill content');
          set({ error: errorMessage, isSubmitting: false });
          throw error;
        }
      },

      // ========== Tenant Skill Config ==========

      listTenantConfigs: async (options = {}) => {
        const requestId = ++tenantConfigRequestSequence;
        set({ isLoading: true, error: null });
        try {
          const response = await tenantSkillConfigAPI.list(options);
          if (tenantConfigRequestSequence !== requestId) {
            return;
          }
          set({
            tenantConfigs: response.configs,
            isLoading: false,
          });
        } catch (error: unknown) {
          if (tenantConfigRequestSequence !== requestId) {
            return;
          }
          const errorMessage = getErrorMessage(error, 'Failed to list tenant configs');
          set({ error: errorMessage, isLoading: false });
          throw error;
        }
      },

      disableSystemSkill: async (systemSkillName: string, options = {}) => {
        set({ isSubmitting: true, error: null });
        try {
          const config = await tenantSkillConfigAPI.disable(systemSkillName, options);
          const { tenantConfigs } = get();
          const existingIndex = tenantConfigs.findIndex(
            (c) => c.system_skill_name === systemSkillName
          );
          if (existingIndex >= 0) {
            set({
              tenantConfigs: tenantConfigs.map((c, i) => (i === existingIndex ? config : c)),
              isSubmitting: false,
            });
          } else {
            set({
              tenantConfigs: [...tenantConfigs, config],
              isSubmitting: false,
            });
          }
        } catch (error: unknown) {
          const errorMessage = getErrorMessage(error, 'Failed to disable system skill');
          set({ error: errorMessage, isSubmitting: false });
          throw error;
        }
      },

      enableSystemSkill: async (systemSkillName: string, options = {}) => {
        set({ isSubmitting: true, error: null });
        try {
          await tenantSkillConfigAPI.enable(systemSkillName, options);
          const { tenantConfigs } = get();
          set({
            tenantConfigs: tenantConfigs.filter((c) => c.system_skill_name !== systemSkillName),
            isSubmitting: false,
          });
        } catch (error: unknown) {
          const errorMessage = getErrorMessage(error, 'Failed to enable system skill');
          set({ error: errorMessage, isSubmitting: false });
          throw error;
        }
      },

      overrideSystemSkill: async (
        systemSkillName: string,
        overrideSkillId: string,
        options = {}
      ) => {
        set({ isSubmitting: true, error: null });
        try {
          const config = await tenantSkillConfigAPI.override(
            systemSkillName,
            overrideSkillId,
            options
          );
          const { tenantConfigs } = get();
          const existingIndex = tenantConfigs.findIndex(
            (c) => c.system_skill_name === systemSkillName
          );
          if (existingIndex >= 0) {
            set({
              tenantConfigs: tenantConfigs.map((c, i) => (i === existingIndex ? config : c)),
              isSubmitting: false,
            });
          } else {
            set({
              tenantConfigs: [...tenantConfigs, config],
              isSubmitting: false,
            });
          }
        } catch (error: unknown) {
          const errorMessage = getErrorMessage(error, 'Failed to override system skill');
          set({ error: errorMessage, isSubmitting: false });
          throw error;
        }
      },

      // ========== Filters ==========

      setFilters: (filters: Partial<SkillFilters>) => {
        set((state) => ({
          filters: { ...state.filters, ...filters },
        }));
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
      name: 'SkillStore',
      enabled: import.meta.env.DEV,
    }
  )
);

// ============================================================================
// SELECTOR HOOKS
// ============================================================================

/**
 * Get all skills
 */
export const useSkills = () => useSkillStore((state) => state.skills);

/**
 * Get listSkills action
 */
export const useListSkills = () => useSkillStore((state) => state.listSkills);

/**
 * Get filtered skills based on search and filters
 */
export const useFilteredSkills = () =>
  useSkillStore((state) => {
    const { skills, filters } = state;
    return skills.filter((skill) => {
      // Search filter
      if (filters.search) {
        const search = filters.search.toLowerCase();
        const matchesName = skill.name.toLowerCase().includes(search);
        const matchesDescription = skill.description.toLowerCase().includes(search);
        if (!matchesName && !matchesDescription) {
          return false;
        }
      }

      // Status filter
      if (filters.status && skill.status !== filters.status) {
        return false;
      }

      // Scope filter
      if (filters.scope && skill.scope !== filters.scope) {
        return false;
      }

      return true;
    });
  });

/**
 * Get system skills
 */
export const useSystemSkills = () => useSkillStore((state) => state.systemSkills);

/**
 * Get tenant configs
 */
export const useTenantConfigs = () => useSkillStore((state) => state.tenantConfigs);

/**
 * Get config for a specific system skill
 */
export const useTenantConfigForSkill = (skillName: string) =>
  useSkillStore((state) => state.tenantConfigs.find((c) => c.system_skill_name === skillName));

/**
 * Get current skill
 */
export const useCurrentSkill = () => useSkillStore((state) => state.currentSkill);

/**
 * Get loading state
 */
export const useSkillLoading = () => useSkillStore((state) => state.isLoading);

/**
 * Get submitting state
 */
export const useSkillSubmitting = () => useSkillStore((state) => state.isSubmitting);

/**
 * Get error state
 */
export const useSkillError = () => useSkillStore((state) => state.error);

/**
 * Get total count
 */
export const useSkillTotal = () => useSkillStore((state) => state.total);

/**
 * Get filters
 */
export const useSkillFilters = () => useSkillStore((state) => state.filters);

/**
 * Get active skills count
 */
export const useActiveSkillsCount = () =>
  useSkillStore((state) => state.skills.filter((s) => s.status === 'active').length);

export default useSkillStore;
