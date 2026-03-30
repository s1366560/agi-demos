/**
 * Instance Zustand Store
 *
 * State management for Instance CRUD operations, scaling, restart,
 * config management, and member management.
 */

import { create } from 'zustand';
import { devtools } from 'zustand/middleware';
import { useShallow } from 'zustand/react/shallow';

import { instanceService } from '../services/instanceService';

import type {
  InstanceResponse,
  InstanceCreate,
  InstanceUpdate,
  InstanceMemberResponse,
  InstanceMemberCreate,
  InstanceMemberUpdate,
  InstanceConfigResponse,
  UserSearchResult,
} from '../services/instanceService';

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

interface InstanceState {
  // Data
  instances: InstanceResponse[];
  currentInstance: InstanceResponse | null;
  members: InstanceMemberResponse[];
  instanceConfig: InstanceConfigResponse | null;

  // Pagination
  total: number;
  page: number;
  pageSize: number;

  // Loading states
  isLoading: boolean;
  isSubmitting: boolean;

  // Error
  error: string | null;

  // Actions - Instance CRUD
  listInstances: (params?: Record<string, unknown>) => Promise<void>;
  getInstance: (id: string) => Promise<InstanceResponse>;
  createInstance: (data: InstanceCreate) => Promise<InstanceResponse>;
  updateInstance: (id: string, data: InstanceUpdate) => Promise<InstanceResponse>;
  deleteInstance: (id: string) => Promise<void>;

  // Actions - Lifecycle
  scaleInstance: (id: string, replicas: number) => Promise<InstanceResponse>;
  restartInstance: (id: string) => Promise<InstanceResponse>;

  // Actions - Config
  getConfig: (id: string) => Promise<InstanceConfigResponse>;
  updateConfig: (id: string, data: InstanceConfigResponse) => Promise<InstanceConfigResponse>;

  // Actions - Members
  listMembers: (id: string) => Promise<void>;
  addMember: (id: string, data: InstanceMemberCreate) => Promise<InstanceMemberResponse>;
  removeMember: (id: string, memberId: string) => Promise<void>;
  updateMemberRole: (
    id: string,
    userId: string,
    data: InstanceMemberUpdate
  ) => Promise<InstanceMemberResponse>;
  searchUsers: (id: string, query: string) => Promise<UserSearchResult[]>;

  // Actions - UI
  setCurrentInstance: (instance: InstanceResponse | null) => void;
  clearError: () => void;
  reset: () => void;
}

// ============================================================================
// INITIAL STATE
// ============================================================================

const initialState = {
  instances: [] as InstanceResponse[],
  currentInstance: null as InstanceResponse | null,
  members: [] as InstanceMemberResponse[],
  instanceConfig: null as InstanceConfigResponse | null,
  total: 0,
  page: 1,
  pageSize: 20,
  isLoading: false,
  isSubmitting: false,
  error: null as string | null,
};

// ============================================================================
// STORE
// ============================================================================

export const useInstanceStore = create<InstanceState>()(
  devtools(
    (set, get) => ({
      ...initialState,

      // ========== Instance CRUD ==========

      listInstances: async (params = {}) => {
        set({ isLoading: true, error: null });
        try {
          const response = await instanceService.list(
            params as { page?: number; page_size?: number; status?: string; search?: string }
          );
          set({
            instances: response.instances,
            total: response.total,
            page: response.page,
            pageSize: response.page_size,
            isLoading: false,
          });
        } catch (error: unknown) {
          set({ error: getErrorMessage(error, 'Failed to list instances'), isLoading: false });
          throw error;
        }
      },

      getInstance: async (id: string) => {
        set({ isLoading: true, error: null });
        try {
          const response = await instanceService.getById(id);
          set({ currentInstance: response, isLoading: false });
          return response;
        } catch (error: unknown) {
          set({ error: getErrorMessage(error, 'Failed to get instance'), isLoading: false });
          throw error;
        }
      },

      createInstance: async (data: InstanceCreate) => {
        set({ isSubmitting: true, error: null });
        try {
          const response = await instanceService.create(data);
          const { instances } = get();
          set({
            instances: [response, ...instances],
            total: get().total + 1,
            isSubmitting: false,
          });
          return response;
        } catch (error: unknown) {
          set({ error: getErrorMessage(error, 'Failed to create instance'), isSubmitting: false });
          throw error;
        }
      },

      updateInstance: async (id: string, data: InstanceUpdate) => {
        set({ isSubmitting: true, error: null });
        try {
          const response = await instanceService.update(id, data);
          const { instances } = get();
          set({
            instances: instances.map((i) => (i.id === id ? response : i)),
            currentInstance: get().currentInstance?.id === id ? response : get().currentInstance,
            isSubmitting: false,
          });
          return response;
        } catch (error: unknown) {
          set({ error: getErrorMessage(error, 'Failed to update instance'), isSubmitting: false });
          throw error;
        }
      },

      deleteInstance: async (id: string) => {
        set({ isSubmitting: true, error: null });
        try {
          await instanceService.delete(id);
          const { instances } = get();
          set({
            instances: instances.filter((i) => i.id !== id),
            currentInstance: get().currentInstance?.id === id ? null : get().currentInstance,
            total: get().total - 1,
            isSubmitting: false,
          });
        } catch (error: unknown) {
          set({ error: getErrorMessage(error, 'Failed to delete instance'), isSubmitting: false });
          throw error;
        }
      },

      // ========== Lifecycle ==========

      scaleInstance: async (id: string, replicas: number) => {
        set({ isSubmitting: true, error: null });
        try {
          const response = await instanceService.scale(id, replicas);
          const { instances } = get();
          set({
            instances: instances.map((i) => (i.id === id ? response : i)),
            currentInstance: get().currentInstance?.id === id ? response : get().currentInstance,
            isSubmitting: false,
          });
          return response;
        } catch (error: unknown) {
          set({ error: getErrorMessage(error, 'Failed to scale instance'), isSubmitting: false });
          throw error;
        }
      },

      restartInstance: async (id: string) => {
        set({ isSubmitting: true, error: null });
        try {
          const response = await instanceService.restart(id);
          const { instances } = get();
          set({
            instances: instances.map((i) => (i.id === id ? response : i)),
            currentInstance: get().currentInstance?.id === id ? response : get().currentInstance,
            isSubmitting: false,
          });
          return response;
        } catch (error: unknown) {
          set({
            error: getErrorMessage(error, 'Failed to restart instance'),
            isSubmitting: false,
          });
          throw error;
        }
      },

      // ========== Config ==========

      getConfig: async (id: string) => {
        set({ isLoading: true, error: null });
        try {
          const response = await instanceService.getConfig(id);
          set({ instanceConfig: response, isLoading: false });
          return response;
        } catch (error: unknown) {
          set({
            error: getErrorMessage(error, 'Failed to get instance config'),
            isLoading: false,
          });
          throw error;
        }
      },

      updateConfig: async (id: string, data: InstanceConfigResponse) => {
        set({ isSubmitting: true, error: null });
        try {
          const response = await instanceService.updateConfig(id, data);
          set({ instanceConfig: response, isSubmitting: false });
          return response;
        } catch (error: unknown) {
          set({
            error: getErrorMessage(error, 'Failed to update instance config'),
            isSubmitting: false,
          });
          throw error;
        }
      },

      // ========== Members ==========

      listMembers: async (id: string) => {
        set({ isLoading: true, error: null });
        try {
          const response = await instanceService.listMembers(id);
          set({ members: response, isLoading: false });
        } catch (error: unknown) {
          set({
            error: getErrorMessage(error, 'Failed to list instance members'),
            isLoading: false,
          });
          throw error;
        }
      },

      addMember: async (id: string, data: InstanceMemberCreate) => {
        set({ isSubmitting: true, error: null });
        try {
          const response = await instanceService.addMember(id, data);
          const { members } = get();
          set({ members: [...members, response], isSubmitting: false });
          return response;
        } catch (error: unknown) {
          set({ error: getErrorMessage(error, 'Failed to add member'), isSubmitting: false });
          throw error;
        }
      },

      removeMember: async (id: string, memberId: string) => {
        set({ isSubmitting: true, error: null });
        try {
          await instanceService.removeMember(id, memberId);
          const { members } = get();
          set({ members: members.filter((m) => m.id !== memberId), isSubmitting: false });
        } catch (error: unknown) {
          set({ error: getErrorMessage(error, 'Failed to remove member'), isSubmitting: false });
          throw error;
        }
      },

      updateMemberRole: async (id: string, userId: string, data: InstanceMemberUpdate) => {
        set({ isSubmitting: true, error: null });
        try {
          const response = await instanceService.updateMemberRole(id, userId, data);
          const { members } = get();
          set({
            members: members.map((m) => (m.user_id === userId ? response : m)),
            isSubmitting: false,
          });
          return response;
        } catch (error: unknown) {
          set({
            error: getErrorMessage(error, 'Failed to update member role'),
            isSubmitting: false,
          });
          throw error;
        }
      },

      searchUsers: async (id: string, query: string) => {
        try {
          return await instanceService.searchUsers(id, query);
        } catch (error: unknown) {
          set({ error: getErrorMessage(error, 'Failed to search users') });
          throw error;
        }
      },

      // ========== UI ==========

      setCurrentInstance: (instance: InstanceResponse | null) => {
        set({ currentInstance: instance });
      },

      clearError: () => {
        set({ error: null });
      },

      reset: () => {
        set(initialState);
      },
    }),
    {
      name: 'InstanceStore',
      enabled: import.meta.env.DEV,
    }
  )
);

// ============================================================================
// SELECTOR HOOKS
// ============================================================================

export const useInstances = () => useInstanceStore((s) => s.instances);
export const useCurrentInstance = () => useInstanceStore((s) => s.currentInstance);
export const useInstanceMembers = () => useInstanceStore((s) => s.members);
export const useInstanceConfig = () => useInstanceStore((s) => s.instanceConfig);
export const useInstanceLoading = () => useInstanceStore((s) => s.isLoading);
export const useInstanceSubmitting = () => useInstanceStore((s) => s.isSubmitting);
export const useInstanceError = () => useInstanceStore((s) => s.error);
export const useInstanceTotal = () => useInstanceStore((s) => s.total);

export const useInstanceActions = () =>
  useInstanceStore(
    useShallow((s) => ({
      listInstances: s.listInstances,
      getInstance: s.getInstance,
      createInstance: s.createInstance,
      updateInstance: s.updateInstance,
      deleteInstance: s.deleteInstance,
      scaleInstance: s.scaleInstance,
      restartInstance: s.restartInstance,
      listMembers: s.listMembers,
      addMember: s.addMember,
      removeMember: s.removeMember,
      updateMemberRole: s.updateMemberRole,
      searchUsers: s.searchUsers,
      getConfig: s.getConfig,
      updateConfig: s.updateConfig,
      setCurrentInstance: s.setCurrentInstance,
      clearError: s.clearError,
      reset: s.reset,
    }))
  );
