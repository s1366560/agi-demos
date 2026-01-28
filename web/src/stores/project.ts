import { create } from 'zustand';
import { projectAPI } from '../services/api';
import type { Project, ProjectCreate, ProjectUpdate, ProjectListResponse } from '../types/memory';

interface ApiError {
  response?: {
    data?: {
      detail?: string | Record<string, unknown>;
    };
  };
}

interface ProjectState {
  projects: Project[];
  currentProject: Project | null;
  isLoading: boolean;
  error: string | null;
  total: number;
  page: number;
  pageSize: number;

  // Actions
  listProjects: (tenantId: string, params?: { page?: number; page_size?: number; search?: string }) => Promise<void>;
  createProject: (tenantId: string, data: ProjectCreate) => Promise<void>;
  updateProject: (tenantId: string, projectId: string, data: ProjectUpdate) => Promise<void>;
  deleteProject: (tenantId: string, projectId: string) => Promise<void>;
  setCurrentProject: (project: Project | null) => void;
  getProject: (tenantId: string, projectId: string) => Promise<Project>;
  clearError: () => void;
}

function getErrorMessage(error: unknown): string {
  const apiError = error as ApiError;
  const detail = apiError.response?.data?.detail;
  return detail
    ? (typeof detail === 'string'
        ? detail
        : JSON.stringify(detail))
    : 'Failed to process request';
}

export const useProjectStore = create<ProjectState>((set, get) => ({
  projects: [],
  currentProject: null,
  isLoading: false,
  error: null,
  total: 0,
  page: 1,
  pageSize: 20,

  listProjects: async (tenantId: string, params = {}) => {
    set({ isLoading: true, error: null });
    try {
      const response: ProjectListResponse = await projectAPI.list(tenantId, params);
      set({
        projects: response.projects,
        total: response.total,
        page: response.page,
        pageSize: response.page_size,
        isLoading: false,
      });
    } catch (error: unknown) {
      set({
        error: getErrorMessage(error),
        isLoading: false
      });
      throw error;
    }
  },

  createProject: async (tenantId: string, data: ProjectCreate) => {
    set({ isLoading: true, error: null });
    try {
      const response: Project = await projectAPI.create(tenantId, data);
      const { projects } = get();
      set({
        projects: [...projects, response],
        isLoading: false,
      });
    } catch (error: unknown) {
      set({
        error: getErrorMessage(error),
        isLoading: false
      });
      throw error;
    }
  },

  updateProject: async (tenantId: string, projectId: string, data: ProjectUpdate) => {
    set({ isLoading: true, error: null });
    try {
      const response: Project = await projectAPI.update(tenantId, projectId, data);
      const { projects } = get();
      set({
        projects: projects.map(project => project.id === projectId ? response : project),
        currentProject: get().currentProject?.id === projectId ? response : get().currentProject,
        isLoading: false,
      });
    } catch (error: unknown) {
      set({
        error: getErrorMessage(error),
        isLoading: false
      });
      throw error;
    }
  },

  deleteProject: async (tenantId: string, projectId: string) => {
    set({ isLoading: true, error: null });
    try {
      await projectAPI.delete(tenantId, projectId);
      const { projects } = get();
      set({
        projects: projects.filter(project => project.id !== projectId),
        currentProject: get().currentProject?.id === projectId ? null : get().currentProject,
        isLoading: false,
      });
    } catch (error: unknown) {
      set({
        error: getErrorMessage(error),
        isLoading: false
      });
      throw error;
    }
  },

  setCurrentProject: (project: Project | null) => {
    set({ currentProject: project });
  },

  getProject: async (tenantId: string, projectId: string) => {
    set({ isLoading: true, error: null });
    try {
      const response: Project = await projectAPI.get(tenantId, projectId);
      set({ isLoading: false });
      return response;
    } catch (error: unknown) {
      set({
        error: getErrorMessage(error),
        isLoading: false
      });
      throw error;
    }
  },

  clearError: () => set({ error: null }),
}));

// ============================================================================
// SELECTORS - Fine-grained subscriptions for performance
// ============================================================================

// Project data selectors
export const useProjects = () => useProjectStore((state) => state.projects);
export const useCurrentProject = () => useProjectStore((state) => state.currentProject);
export const useProjectTotal = () => useProjectStore((state) => state.total);
export const useProjectPage = () => useProjectStore((state) => state.page);
export const useProjectPageSize = () => useProjectStore((state) => state.pageSize);

// Loading and error selectors
export const useProjectLoading = () => useProjectStore((state) => state.isLoading);
export const useProjectError = () => useProjectStore((state) => state.error);

// Action selectors
export const useProjectActions = () =>
  useProjectStore((state) => ({
    listProjects: state.listProjects,
    createProject: state.createProject,
    updateProject: state.updateProject,
    deleteProject: state.deleteProject,
    setCurrentProject: state.setCurrentProject,
    getProject: state.getProject,
    clearError: state.clearError,
  }));