/**
 * Skill Zustand Store
 *
 * State management for Skill CRUD operations and filtering/search functionality.
 * Supports three-level scoping: system, tenant, and project skills.
 */

import { create } from "zustand";
import { skillAPI, tenantSkillConfigAPI } from "../services/skillService";
import type {
  SkillResponse,
  SkillCreate,
  SkillUpdate,
  TenantSkillConfigResponse,
} from "../types/agent";

// ============================================================================
// STATE INTERFACE
// ============================================================================

interface SkillFilters {
  search: string;
  status: "active" | "disabled" | "deprecated" | null;
  scope: "system" | "tenant" | "project" | null;
  trigger_type: "keyword" | "semantic" | "hybrid" | null;
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
  listSkills: (params?: {
    status?: string;
    scope?: string;
    trigger_type?: string;
    skip?: number;
    limit?: number;
  }) => Promise<void>;
  listSystemSkills: () => Promise<void>;
  getSkill: (id: string) => Promise<SkillResponse>;
  createSkill: (data: SkillCreate) => Promise<SkillResponse>;
  updateSkill: (id: string, data: SkillUpdate) => Promise<SkillResponse>;
  deleteSkill: (id: string) => Promise<void>;
  updateSkillStatus: (
    id: string,
    status: "active" | "disabled" | "deprecated"
  ) => Promise<void>;
  updateSkillContent: (id: string, content: string) => Promise<SkillResponse>;
  setCurrentSkill: (skill: SkillResponse | null) => void;

  // Actions - Tenant Skill Config
  listTenantConfigs: () => Promise<void>;
  disableSystemSkill: (systemSkillName: string) => Promise<void>;
  enableSystemSkill: (systemSkillName: string) => Promise<void>;
  overrideSystemSkill: (
    systemSkillName: string,
    overrideSkillId: string
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
  search: "",
  status: null,
  scope: null,
  trigger_type: null,
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

// ============================================================================
// STORE CREATION
// ============================================================================

export const useSkillStore = create<SkillState>((set, get) => ({
  ...initialState,

  // ========== Skill CRUD ==========

  listSkills: async (params = {}) => {
    set({ isLoading: true, error: null });
    try {
      const { filters } = get();
      const queryParams = {
        ...params,
        status: filters.status || undefined,
        scope: filters.scope || undefined,
        trigger_type: filters.trigger_type || undefined,
      };
      const response = await skillAPI.list(queryParams);
      set({
        skills: response.skills || [],
        total: response.total || 0,
        isLoading: false,
      });
    } catch (error: any) {
      const errorMessage = error.response?.data?.detail
        ? typeof error.response.data.detail === "string"
          ? error.response.data.detail
          : JSON.stringify(error.response.data.detail)
        : "Failed to list skills";
      set({ error: errorMessage, isLoading: false });
      throw error;
    }
  },

  listSystemSkills: async () => {
    set({ isLoading: true, error: null });
    try {
      const response = await skillAPI.listSystemSkills();
      set({
        systemSkills: response.skills || [],
        isLoading: false,
      });
    } catch (error: any) {
      const errorMessage = error.response?.data?.detail
        ? typeof error.response.data.detail === "string"
          ? error.response.data.detail
          : JSON.stringify(error.response.data.detail)
        : "Failed to list system skills";
      set({ error: errorMessage, isLoading: false });
      throw error;
    }
  },

  getSkill: async (id: string) => {
    set({ isLoading: true, error: null });
    try {
      const response = await skillAPI.get(id);
      set({ currentSkill: response, isLoading: false });
      return response;
    } catch (error: any) {
      const errorMessage = error.response?.data?.detail
        ? typeof error.response.data.detail === "string"
          ? error.response.data.detail
          : JSON.stringify(error.response.data.detail)
        : "Failed to get skill";
      set({ error: errorMessage, isLoading: false });
      throw error;
    }
  },

  createSkill: async (data: SkillCreate) => {
    set({ isSubmitting: true, error: null });
    try {
      const response = await skillAPI.create(data);
      const { skills } = get();
      set({
        skills: [response, ...skills],
        total: get().total + 1,
        isSubmitting: false,
      });
      return response;
    } catch (error: any) {
      const errorMessage = error.response?.data?.detail
        ? typeof error.response.data.detail === "string"
          ? error.response.data.detail
          : JSON.stringify(error.response.data.detail)
        : "Failed to create skill";
      set({ error: errorMessage, isSubmitting: false });
      throw error;
    }
  },

  updateSkill: async (id: string, data: SkillUpdate) => {
    set({ isSubmitting: true, error: null });
    try {
      const response = await skillAPI.update(id, data);
      const { skills } = get();
      set({
        skills: skills.map((s) => (s.id === id ? response : s)),
        currentSkill: response,
        isSubmitting: false,
      });
      return response;
    } catch (error: any) {
      const errorMessage = error.response?.data?.detail
        ? typeof error.response.data.detail === "string"
          ? error.response.data.detail
          : JSON.stringify(error.response.data.detail)
        : "Failed to update skill";
      set({ error: errorMessage, isSubmitting: false });
      throw error;
    }
  },

  deleteSkill: async (id: string) => {
    set({ isSubmitting: true, error: null });
    try {
      await skillAPI.delete(id);
      const { skills } = get();
      set({
        skills: skills.filter((s) => s.id !== id),
        total: get().total - 1,
        isSubmitting: false,
      });
    } catch (error: any) {
      const errorMessage = error.response?.data?.detail
        ? typeof error.response.data.detail === "string"
          ? error.response.data.detail
          : JSON.stringify(error.response.data.detail)
        : "Failed to delete skill";
      set({ error: errorMessage, isSubmitting: false });
      throw error;
    }
  },

  updateSkillStatus: async (
    id: string,
    status: "active" | "disabled" | "deprecated"
  ) => {
    set({ isSubmitting: true, error: null });
    try {
      const response = await skillAPI.updateStatus(id, status);
      const { skills } = get();
      set({
        skills: skills.map((s) => (s.id === id ? response : s)),
        isSubmitting: false,
      });
    } catch (error: any) {
      const errorMessage = error.response?.data?.detail
        ? typeof error.response.data.detail === "string"
          ? error.response.data.detail
          : JSON.stringify(error.response.data.detail)
        : "Failed to update skill status";
      set({ error: errorMessage, isSubmitting: false });
      throw error;
    }
  },

  setCurrentSkill: (skill: SkillResponse | null) => {
    set({ currentSkill: skill });
  },

  updateSkillContent: async (id: string, content: string) => {
    set({ isSubmitting: true, error: null });
    try {
      const response = await skillAPI.updateContent(id, content);
      const { skills } = get();
      set({
        skills: skills.map((s) => (s.id === id ? response : s)),
        currentSkill: response,
        isSubmitting: false,
      });
      return response;
    } catch (error: any) {
      const errorMessage = error.response?.data?.detail
        ? typeof error.response.data.detail === "string"
          ? error.response.data.detail
          : JSON.stringify(error.response.data.detail)
        : "Failed to update skill content";
      set({ error: errorMessage, isSubmitting: false });
      throw error;
    }
  },

  // ========== Tenant Skill Config ==========

  listTenantConfigs: async () => {
    set({ isLoading: true, error: null });
    try {
      const response = await tenantSkillConfigAPI.list();
      set({
        tenantConfigs: response.configs || [],
        isLoading: false,
      });
    } catch (error: any) {
      const errorMessage = error.response?.data?.detail
        ? typeof error.response.data.detail === "string"
          ? error.response.data.detail
          : JSON.stringify(error.response.data.detail)
        : "Failed to list tenant configs";
      set({ error: errorMessage, isLoading: false });
      throw error;
    }
  },

  disableSystemSkill: async (systemSkillName: string) => {
    set({ isSubmitting: true, error: null });
    try {
      const config = await tenantSkillConfigAPI.disable(systemSkillName);
      const { tenantConfigs } = get();
      const existingIndex = tenantConfigs.findIndex(
        (c) => c.system_skill_name === systemSkillName
      );
      if (existingIndex >= 0) {
        set({
          tenantConfigs: tenantConfigs.map((c, i) =>
            i === existingIndex ? config : c
          ),
          isSubmitting: false,
        });
      } else {
        set({
          tenantConfigs: [...tenantConfigs, config],
          isSubmitting: false,
        });
      }
    } catch (error: any) {
      const errorMessage = error.response?.data?.detail
        ? typeof error.response.data.detail === "string"
          ? error.response.data.detail
          : JSON.stringify(error.response.data.detail)
        : "Failed to disable system skill";
      set({ error: errorMessage, isSubmitting: false });
      throw error;
    }
  },

  enableSystemSkill: async (systemSkillName: string) => {
    set({ isSubmitting: true, error: null });
    try {
      await tenantSkillConfigAPI.enable(systemSkillName);
      const { tenantConfigs } = get();
      set({
        tenantConfigs: tenantConfigs.filter(
          (c) => c.system_skill_name !== systemSkillName
        ),
        isSubmitting: false,
      });
    } catch (error: any) {
      const errorMessage = error.response?.data?.detail
        ? typeof error.response.data.detail === "string"
          ? error.response.data.detail
          : JSON.stringify(error.response.data.detail)
        : "Failed to enable system skill";
      set({ error: errorMessage, isSubmitting: false });
      throw error;
    }
  },

  overrideSystemSkill: async (
    systemSkillName: string,
    overrideSkillId: string
  ) => {
    set({ isSubmitting: true, error: null });
    try {
      const config = await tenantSkillConfigAPI.override(
        systemSkillName,
        overrideSkillId
      );
      const { tenantConfigs } = get();
      const existingIndex = tenantConfigs.findIndex(
        (c) => c.system_skill_name === systemSkillName
      );
      if (existingIndex >= 0) {
        set({
          tenantConfigs: tenantConfigs.map((c, i) =>
            i === existingIndex ? config : c
          ),
          isSubmitting: false,
        });
      } else {
        set({
          tenantConfigs: [...tenantConfigs, config],
          isSubmitting: false,
        });
      }
    } catch (error: any) {
      const errorMessage = error.response?.data?.detail
        ? typeof error.response.data.detail === "string"
          ? error.response.data.detail
          : JSON.stringify(error.response.data.detail)
        : "Failed to override system skill";
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
}));

// ============================================================================
// SELECTOR HOOKS
// ============================================================================

/**
 * Get all skills
 */
export const useSkills = () => useSkillStore((state) => state.skills);

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
        const matchesDescription = skill.description
          .toLowerCase()
          .includes(search);
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

      // Trigger type filter
      if (filters.trigger_type && skill.trigger_type !== filters.trigger_type) {
        return false;
      }

      return true;
    });
  });

/**
 * Get system skills
 */
export const useSystemSkills = () =>
  useSkillStore((state) => state.systemSkills);

/**
 * Get tenant configs
 */
export const useTenantConfigs = () =>
  useSkillStore((state) => state.tenantConfigs);

/**
 * Get config for a specific system skill
 */
export const useTenantConfigForSkill = (skillName: string) =>
  useSkillStore((state) =>
    state.tenantConfigs.find((c) => c.system_skill_name === skillName)
  );

/**
 * Get current skill
 */
export const useCurrentSkill = () =>
  useSkillStore((state) => state.currentSkill);

/**
 * Get loading state
 */
export const useSkillLoading = () => useSkillStore((state) => state.isLoading);

/**
 * Get submitting state
 */
export const useSkillSubmitting = () =>
  useSkillStore((state) => state.isSubmitting);

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
  useSkillStore(
    (state) => state.skills.filter((s) => s.status === "active").length
  );

/**
 * Get average success rate
 */
export const useAverageSuccessRate = () =>
  useSkillStore((state) => {
    const { skills } = state;
    if (skills.length === 0) return 0;
    const totalSuccessRate = skills.reduce((sum, s) => sum + s.success_rate, 0);
    return totalSuccessRate / skills.length;
  });

/**
 * Get total usage count
 */
export const useTotalUsageCount = () =>
  useSkillStore((state) =>
    state.skills.reduce((sum, s) => sum + s.usage_count, 0)
  );

export default useSkillStore;
