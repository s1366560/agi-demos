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

let latestListProjectsRequest = 0;
let projectStateGeneration = 0;
const pendingListProjectRequests = new Map<string, Promise<ProjectListResponse>>();
const pendingGetProjectRequests = new Map<string, Promise<Project>>();
const recentGetProjectResponses = new Map<string, { project: Project; fetchedAt: number }>();
const PROJECT_DETAIL_CACHE_TTL_MS = 10_000;

function isSameCurrentProject(left: Project | null, right: Project | null): boolean {
  if (left === right) {
    return true;
  }
  if (!left || !right) {
    return false;
  }
  return (
    left.id === right.id &&
    left.tenant_id === right.tenant_id &&
    left.name === right.name &&
    (left.description ?? '') === (right.description ?? '') &&
    (left.updated_at ?? '') === (right.updated_at ?? '')
  );
}

function getProjectRequestKey(tenantId: string, projectId: string): string {
  return `${tenantId}:${projectId}`;
}

function getProjectListRequestKey(
  tenantId: string,
  params: {
    page?: number | undefined;
    page_size?: number | undefined;
    search?: string | undefined;
    visibility?: 'all' | 'public' | 'private' | undefined;
    owner_id?: string | undefined;
  }
): string {
  return JSON.stringify({
    tenantId,
    page: params.page ?? null,
    page_size: params.page_size ?? null,
    search: params.search ?? null,
    visibility: params.visibility ?? null,
    owner_id: params.owner_id ?? null,
  });
}

function listProjectsRequest(
  tenantId: string,
  params: {
    page?: number | undefined;
    page_size?: number | undefined;
    search?: string | undefined;
    visibility?: 'all' | 'public' | 'private' | undefined;
    owner_id?: string | undefined;
  }
): Promise<ProjectListResponse> {
  const requestKey = getProjectListRequestKey(tenantId, params);
  const pendingRequest = pendingListProjectRequests.get(requestKey);
  if (pendingRequest) {
    return pendingRequest;
  }

  const request = projectAPI.list(tenantId, params).finally(() => {
    if (pendingListProjectRequests.get(requestKey) === request) {
      pendingListProjectRequests.delete(requestKey);
    }
  });
  pendingListProjectRequests.set(requestKey, request);
  return request;
}

function getRecentProjectResponse(requestKey: string): Project | null {
  const cached = recentGetProjectResponses.get(requestKey);
  if (!cached) {
    return null;
  }
  if (Date.now() - cached.fetchedAt > PROJECT_DETAIL_CACHE_TTL_MS) {
    recentGetProjectResponses.delete(requestKey);
    return null;
  }
  return cached.project;
}

function cacheProjectResponse(requestKey: string, project: Project): void {
  recentGetProjectResponses.set(requestKey, {
    project,
    fetchedAt: Date.now(),
  });
}

function deleteCachedProjectResponses(projectId: string): void {
  for (const [requestKey, cached] of recentGetProjectResponses) {
    if (cached.project.id === projectId || requestKey.endsWith(`:${projectId}`)) {
      recentGetProjectResponses.delete(requestKey);
    }
  }
}

interface ApiError {
  response?:
    | {
        data?:
          | {
              detail?: string | Record<string, unknown> | undefined;
            }
          | undefined;
      }
    | undefined;
}

interface ProjectState {
  projects: Project[];
  currentProject: Project | null;
  isLoading: boolean;
  error: string | null;
  total: number;
  page: number;
  pageSize: number;
  ownerIds: string[];

  // Actions
  listProjects: (
    tenantId: string,
    params?: {
      page?: number | undefined;
      page_size?: number | undefined;
      search?: string | undefined;
      visibility?: 'all' | 'public' | 'private' | undefined;
      owner_id?: string | undefined;
    }
  ) => Promise<void>;
  createProject: (tenantId: string, data: ProjectCreate) => Promise<void>;
  updateProject: (tenantId: string, projectId: string, data: ProjectUpdate) => Promise<void>;
  deleteProject: (tenantId: string, projectId: string) => Promise<void>;
  setCurrentProject: (project: Project | null) => void;
  getProject: (tenantId: string, projectId: string) => Promise<Project>;
  clearProjects: () => void;
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
      ownerIds: [],

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
        const requestId = latestListProjectsRequest + 1;
        latestListProjectsRequest = requestId;
        set({ isLoading: true, error: null });
        try {
          const response: ProjectListResponse = await listProjectsRequest(tenantId, params);
          if (requestId !== latestListProjectsRequest) return;
          set({
            projects: response.projects,
            total: response.total,
            page: response.page,
            pageSize: response.page_size,
            ownerIds: response.owner_ids ?? [],
            isLoading: false,
          });
        } catch (error: unknown) {
          if (requestId !== latestListProjectsRequest) return;
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
          cacheProjectResponse(getProjectRequestKey(tenantId, response.id), response);
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
          cacheProjectResponse(getProjectRequestKey(tenantId, projectId), response);
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
          deleteCachedProjectResponses(projectId);
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
        if (isSameCurrentProject(get().currentProject, project)) {
          return;
        }
        set({ currentProject: project });
      },

      /**
       * Clear tenant-scoped project state and invalidate in-flight list requests.
       *
       * @example
       * clearProjects();
       */
      clearProjects: () => {
        latestListProjectsRequest += 1;
        projectStateGeneration += 1;
        pendingListProjectRequests.clear();
        pendingGetProjectRequests.clear();
        recentGetProjectResponses.clear();
        set({
          projects: [],
          currentProject: null,
          isLoading: false,
          error: null,
          total: 0,
          page: 1,
          pageSize: 20,
          ownerIds: [],
        });
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
        const { currentProject, projects } = get();
        if (currentProject?.id === projectId && currentProject.tenant_id === tenantId) {
          return currentProject;
        }

        const existingProject = projects.find(
          (project) => project.id === projectId && project.tenant_id === tenantId
        );
        if (existingProject) {
          return existingProject;
        }

        const requestKey = getProjectRequestKey(tenantId, projectId);
        const recentResponse = getRecentProjectResponse(requestKey);
        if (recentResponse) {
          return recentResponse;
        }

        const pendingRequest = pendingGetProjectRequests.get(requestKey);
        if (pendingRequest) {
          return pendingRequest;
        }

        const requestGeneration = projectStateGeneration;
        set({ isLoading: true, error: null });

        const request = projectAPI
          .get(tenantId, projectId)
          .then((response: Project) => {
            if (requestGeneration === projectStateGeneration) {
              cacheProjectResponse(requestKey, response);
              const { currentProject: latestCurrentProject, projects: latestProjects } = get();
              const projectExists = latestProjects.some((project) => project.id === response.id);

              set({
                projects: projectExists
                  ? latestProjects.map((project) =>
                      project.id === response.id ? response : project
                    )
                  : [...latestProjects, response],
                currentProject:
                  latestCurrentProject?.id === response.id ? response : latestCurrentProject,
                isLoading: false,
              });
            }

            return response;
          })
          .catch((error: unknown) => {
            if (requestGeneration === projectStateGeneration) {
              set({
                error: getErrorMessage(error),
                isLoading: false,
              });
            }
            throw error;
          })
          .finally(() => {
            if (pendingGetProjectRequests.get(requestKey) === request) {
              pendingGetProjectRequests.delete(requestKey);
            }
          });

        pendingGetProjectRequests.set(requestKey, request);

        return request;
      },

      clearError: () => {
        set({ error: null });
      },
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

/**
 * Get owner IDs available for the current project list query
 *
 * @returns Array of owner IDs
 */
export const useProjectOwnerIds = () => useProjectStore((state) => state.ownerIds);

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
      clearProjects: state.clearProjects,
      clearError: state.clearError,
    }))
  );
