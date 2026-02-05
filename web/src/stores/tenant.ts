/**
 * Tenant Store - Tenant (organization) state management
 *
 * Manages tenant CRUD operations, member management, and current tenant selection.
 * Tenants are the top-level organizational unit in the multi-tenant system.
 *
 * @module stores/tenant
 *
 * @example
 * const { tenants, currentTenant, listTenants, createTenant } = useTenantStore();
 */

import { create } from 'zustand';
import { devtools } from 'zustand/middleware';
import { useShallow } from 'zustand/react/shallow';

import { tenantAPI } from '../services/api';

import type { Tenant, TenantCreate, TenantUpdate, TenantListResponse, UserTenant } from '../types/memory';

interface ApiError {
  response?: {
    data?: {
      detail?: string | Record<string, unknown>;
    };
  };
}

interface TenantState {
  tenants: Tenant[];
  currentTenant: Tenant | null;
  isLoading: boolean;
  error: string | null;
  total: number;
  page: number;
  pageSize: number;

  // Actions
  listTenants: (params?: { page?: number; page_size?: number; search?: string }) => Promise<void>;
  getTenant: (id: string) => Promise<void>;
  createTenant: (data: TenantCreate) => Promise<void>;
  updateTenant: (id: string, data: TenantUpdate) => Promise<void>;
  deleteTenant: (id: string) => Promise<void>;
  setCurrentTenant: (tenant: Tenant | null) => void;
  addMember: (tenantId: string, userId: string, role: string) => Promise<void>;
  removeMember: (tenantId: string, userId: string) => Promise<void>;
  listMembers: (tenantId: string) => Promise<UserTenant[]>;
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

export const useTenantStore = create<TenantState>()(
  devtools((set, get) => ({
  tenants: [],
  currentTenant: null,
  isLoading: false,
  error: null,
  total: 0,
  page: 1,
  pageSize: 20,

  /**
   * List tenants
   *
   * @param params - Query params (page, page_size, search)
   * @throws {ApiError} API failure
   * @example
   * await listTenants({ page: 1, page_size: 20 });
   */
  listTenants: async (params = {}) => {
    set({ isLoading: true, error: null });
    try {
      const response: TenantListResponse = await tenantAPI.list(params);
      set({
        tenants: response.tenants,
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

  /**
   * Fetch a single tenant by ID
   *
   * @param id - Tenant ID
   * @throws {ApiError} API failure
   * @example
   * await getTenant('tenant-1');
   */
  getTenant: async (id: string) => {
    set({ isLoading: true, error: null });
    try {
      const response: Tenant = await tenantAPI.get(id);
      set({
        currentTenant: response,
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

  /**
   * Create a new tenant
   *
   * @param data - Tenant creation data
   * @throws {ApiError} API failure
   * @example
   * await createTenant({ name: 'My Organization', slug: 'my-org' });
   */
  createTenant: async (data: TenantCreate) => {
    set({ isLoading: true, error: null });
    try {
      const response: Tenant = await tenantAPI.create(data);
      const { tenants } = get();
      set({
        tenants: [...tenants, response],
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

  /**
   * Update an existing tenant
   *
   * @param id - Tenant ID
   * @param data - Tenant update data
   * @throws {ApiError} API failure
   * @example
   * await updateTenant('tenant-1', { name: 'Updated Name' });
   */
  updateTenant: async (id: string, data: TenantUpdate) => {
    set({ isLoading: true, error: null });
    try {
      const response: Tenant = await tenantAPI.update(id, data);
      const { tenants } = get();
      set({
        tenants: tenants.map(tenant => tenant.id === id ? response : tenant),
        currentTenant: get().currentTenant?.id === id ? response : get().currentTenant,
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

  /**
   * Delete a tenant
   *
   * @param id - Tenant ID
   * @throws {ApiError} API failure
   * @example
   * await deleteTenant('tenant-1');
   */
  deleteTenant: async (id: string) => {
    set({ isLoading: true, error: null });
    try {
      await tenantAPI.delete(id);
      const { tenants } = get();
      set({
        tenants: tenants.filter(tenant => tenant.id !== id),
        currentTenant: get().currentTenant?.id === id ? null : get().currentTenant,
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

  /**
   * Set the current active tenant
   *
   * @param tenant - Tenant to set as current, or null to clear
   * @example
   * setCurrentTenant(selectedTenant);
   */
  setCurrentTenant: (tenant: Tenant | null) => {
    set({ currentTenant: tenant });
    // If tenant is cleared (logout), also clear the list
    if (tenant === null) {
      set({ tenants: [] });
    }
  },

  /**
   * Add a member to a tenant
   *
   * @param tenantId - Tenant ID
   * @param userId - User ID to add
   * @param role - Member role (e.g., 'owner', 'admin', 'member')
   * @throws {ApiError} API failure
   * @example
   * await addMember('tenant-1', 'user-1', 'admin');
   */
  addMember: async (tenantId: string, userId: string, role: string) => {
    set({ isLoading: true, error: null });
    try {
      await tenantAPI.addMember(tenantId, userId, role);
      set({ isLoading: false });
    } catch (error: unknown) {
      set({
        error: getErrorMessage(error),
        isLoading: false
      });
      throw error;
    }
  },

  /**
   * Remove a member from a tenant
   *
   * @param tenantId - Tenant ID
   * @param userId - User ID to remove
   * @throws {ApiError} API failure
   * @example
   * await removeMember('tenant-1', 'user-1');
   */
  removeMember: async (tenantId: string, userId: string) => {
    set({ isLoading: true, error: null });
    try {
      await tenantAPI.removeMember(tenantId, userId);
      set({ isLoading: false });
    } catch (error: unknown) {
      set({
        error: getErrorMessage(error),
        isLoading: false
      });
      throw error;
    }
  },

  /**
   * List members of a tenant
   *
   * @param tenantId - Tenant ID
   * @returns Array of user-tenant relationships
   * @throws {ApiError} API failure
   * @example
   * const members = await listMembers('tenant-1');
   */
  listMembers: async (tenantId: string) => {
    set({ isLoading: true, error: null });
    try {
      const response: UserTenant[] = await tenantAPI.listMembers(tenantId);
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
}),
{
  name: 'TenantStore',
  enabled: import.meta.env.DEV,
}
)
);

// ============================================================================
// SELECTORS - Fine-grained subscriptions for performance
// ============================================================================

// Tenant data selectors

/**
 * Get all tenants
 *
 * @returns Array of tenants
 * @example
 * const tenants = useTenants();
 */
export const useTenants = () => useTenantStore((state) => state.tenants);

/**
 * Get current active tenant
 *
 * @returns Current tenant or null
 * @example
 * const tenant = useCurrentTenant();
 */
export const useCurrentTenant = () => useTenantStore((state) => state.currentTenant);

/**
 * Get total tenant count
 *
 * @returns Total number of tenants
 * @example
 * const total = useTenantTotal();
 */
export const useTenantTotal = () => useTenantStore((state) => state.total);

/**
 * Get current page number
 *
 * @returns Current page
 * @example
 * const page = useTenantPage();
 */
export const useTenantPage = () => useTenantStore((state) => state.page);

/**
 * Get current page size
 *
 * @returns Number of items per page
 * @example
 * const pageSize = useTenantPageSize();
 */
export const useTenantPageSize = () => useTenantStore((state) => state.pageSize);

// Loading and error selectors

/**
 * Get tenant loading state
 *
 * @returns True if tenants are loading
 * @example
 * const isLoading = useTenantLoading();
 */
export const useTenantLoading = () => useTenantStore((state) => state.isLoading);

/**
 * Get tenant error message
 *
 * @returns Error message or null
 * @example
 * const error = useTenantError();
 */
export const useTenantError = () => useTenantStore((state) => state.error);

// Action selectors

/**
 * Get all tenant actions
 *
 * @returns Object containing all tenant actions
 * @example
 * const { listTenants, createTenant, addMember } = useTenantActions();
 */
export const useTenantActions = () =>
  useTenantStore(useShallow((state) => ({
    listTenants: state.listTenants,
    getTenant: state.getTenant,
    createTenant: state.createTenant,
    updateTenant: state.updateTenant,
    deleteTenant: state.deleteTenant,
    setCurrentTenant: state.setCurrentTenant,
    addMember: state.addMember,
    removeMember: state.removeMember,
    listMembers: state.listMembers,
    clearError: state.clearError,
  })));