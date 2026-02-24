/**
 * Project Store - Project state management
 *
 * Manages project CRUD operations and state within a tenant context.
 * Projects are tenant-scoped entities for multi-tenant isolation.
 *
 * @module stores/project
 *
 * @example
 * const { projects, currentProject, listProjects, createProject } = useProjectStore();
 */

import { create } from 'zustand';
import { devtools } from 'zustand/middleware';
import { useShallow } from 'zustand/react/shallow';

import { projectAPI } from '../services/api';

import type { Project, ProjectCreate, ProjectUpdate, ProjectListResponse } from '../types/memory';

interface ApiError {
  response?: {
    data?: {
      detail?: string | Record<string, unknown> | undefined;
    } | undefined;
  } | undefined;
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
  listProjects: (
    tenantId: string,
    params?: { page?: number | undefined; page_size?: number | undefined; search?: string | undefined }
  ) => Promise<void>;
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
    ? typeof detail === 'string'
      ? detail
      : JSON.stringify(detail)
    : 'Failed to process request';
}

export const useProjectStore = create<ProjectState>()(
  devtools(
    (set, get) => ({
      projects: [],
      currentProject: null,
      isLoading: false,
      error: null,
      total: 0,
      page: 1,
      pageSize: 20,

      /**
       * List projects for a tenant
       *
       * @param tenantId - Tenant ID
       * @param params - Query params (page, page_size, search)
       * @throws {ApiError} API failure
       * @example
       * await listProjects('tenant-1', { page: 1, page_size: 20 });
       */
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
            isLoading: false,
          });
          throw error;
        }
      },

      /**
       * Create a new project
       *
       * @param tenantId - Tenant ID
       * @param data - Project creation data
       * @throws {ApiError} API failure
       * @example
       * await createProject('tenant-1', { name: 'My Project', description: '...' });
       */
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
            isLoading: false,
          });
          throw error;
        }
      },

      /**
       * Update an existing project
       *
       * @param tenantId - Tenant ID
       * @param projectId - Project ID
       * @param data - Project update data
       * @throws {ApiError} API failure
       * @example
       * await updateProject('tenant-1', 'proj-1', { name: 'Updated Name' });
       */
      updateProject: async (tenantId: string, projectId: string, data: ProjectUpdate) => {
        set({ isLoading: true, error: null });
        try {
          const response: Project = await projectAPI.update(tenantId, projectId, data);
          const { projects } = get();
          set({
            projects: projects.map((project) => (project.id === projectId ? response : project)),
            currentProject:
              get().currentProject?.id === projectId ? response : get().currentProject,
            isLoading: false,
          });
        } catch (error: unknown) {
          set({
            error: getErrorMessage(error),
            isLoading: false,
          });
          throw error;
        }
      },

      /**
       * Delete a project
       *
       * @param tenantId - Tenant ID
       * @param projectId - Project ID
       * @throws {ApiError} API failure
       * @example
       * await deleteProject('tenant-1', 'proj-1');
       */
      deleteProject: async (tenantId: string, projectId: string) => {
        set({ isLoading: true, error: null });
        try {
          await projectAPI.delete(tenantId, projectId);
          const { projects } = get();
          set({
            projects: projects.filter((project) => project.id !== projectId),
            currentProject: get().currentProject?.id === projectId ? null : get().currentProject,
            isLoading: false,
          });
        } catch (error: unknown) {
          set({
            error: getErrorMessage(error),
            isLoading: false,
          });
          throw error;
        }
      },

      /**
       * Set the current active project
       *
       * @param project - Project to set as current, or null to clear
       * @example
       * setCurrentProject(selectedProject);
       */
      setCurrentProject: (project: Project | null) => {
        set({ currentProject: project });
      },

      /**
       * Fetch a single project by ID
       *
       * @param tenantId - Tenant ID
       * @param projectId - Project ID
       * @returns The project data
       * @throws {ApiError} API failure
       * @example
       * const project = await getProject('tenant-1', 'proj-1');
       */
      getProject: async (tenantId: string, projectId: string) => {
        set({ isLoading: true, error: null });
        try {
          const response: Project = await projectAPI.get(tenantId, projectId);
          set({ isLoading: false });
          return response;
        } catch (error: unknown) {
          set({
            error: getErrorMessage(error),
            isLoading: false,
          });
          throw error;
        }
      },

      clearError: () => { set({ error: null }); },
    }),
    {
      name: 'ProjectStore',
      enabled: import.meta.env.DEV,
    }
  )
);

// ============================================================================
// SELECTORS - Fine-grained subscriptions for performance
// ============================================================================

// Project data selectors

/**
 * Get all projects
 *
 * @returns Array of projects
 * @example
 * const projects = useProjects();
 */
export const useProjects = () => useProjectStore((state) => state.projects);

/**
 * Get current active project
 *
 * @returns Current project or null
 * @example
 * const project = useCurrentProject();
 */
export const useCurrentProject = () => useProjectStore((state) => state.currentProject);

/**
 * Get total project count
 *
 * @returns Total number of projects
 * @example
 * const total = useProjectTotal();
 */
export const useProjectTotal = () => useProjectStore((state) => state.total);

/**
 * Get current page number
 *
 * @returns Current page
 * @example
 * const page = useProjectPage();
 */
export const useProjectPage = () => useProjectStore((state) => state.page);

/**
 * Get current page size
 *
 * @returns Number of items per page
 * @example
 * const pageSize = useProjectPageSize();
 */
export const useProjectPageSize = () => useProjectStore((state) => state.pageSize);

// Loading and error selectors

/**
 * Get project loading state
 *
 * @returns True if projects are loading
 * @example
 * const isLoading = useProjectLoading();
 */
export const useProjectLoading = () => useProjectStore((state) => state.isLoading);

/**
 * Get project error message
 *
 * @returns Error message or null
 * @example
 * const error = useProjectError();
 */
export const useProjectError = () => useProjectStore((state) => state.error);

// Action selectors

/**
 * Get all project actions
 *
 * @returns Object containing all project actions
 * @example
 * const { listProjects, createProject, updateProject } = useProjectActions();
 */
export const useProjectActions = () =>
  useProjectStore(
    useShallow((state) => ({
      listProjects: state.listProjects,
      createProject: state.createProject,
      updateProject: state.updateProject,
      deleteProject: state.deleteProject,
      setCurrentProject: state.setCurrentProject,
      getProject: state.getProject,
      clearError: state.clearError,
    }))
  );
