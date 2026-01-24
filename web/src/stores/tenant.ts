import { create } from 'zustand';
import { tenantAPI } from '../services/api';
import type { Tenant, TenantCreate, TenantUpdate } from '../types/memory';

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
  listMembers: (tenantId: string) => Promise<any>;
  clearError: () => void;
}

export const useTenantStore = create<TenantState>((set, get) => ({
  tenants: [],
  currentTenant: null,
  isLoading: false,
  error: null,
  total: 0,
  page: 1,
  pageSize: 20,

  listTenants: async (params = {}) => {
    set({ isLoading: true, error: null });
    try {
      const response = await tenantAPI.list(params);
      set({
        tenants: response.tenants,
        total: response.total,
        page: response.page,
        pageSize: response.page_size,
        isLoading: false,
      });
    } catch (error: any) {
      const errorMessage = error.response?.data?.detail 
        ? (typeof error.response.data.detail === 'string' 
            ? error.response.data.detail 
            : JSON.stringify(error.response.data.detail))
        : 'Failed to list tenants';
      set({ 
        error: errorMessage, 
        isLoading: false 
      });
      throw error;
    }
  },

  getTenant: async (id: string) => {
    set({ isLoading: true, error: null });
    try {
      const response = await tenantAPI.get(id);
      set({
        currentTenant: response,
        isLoading: false,
      });
    } catch (error: any) {
      const errorMessage = error.response?.data?.detail 
        ? (typeof error.response.data.detail === 'string' 
            ? error.response.data.detail 
            : JSON.stringify(error.response.data.detail))
        : 'Failed to get tenant';
      set({ 
        error: errorMessage, 
        isLoading: false 
      });
      throw error;
    }
  },

  createTenant: async (data: TenantCreate) => {
    set({ isLoading: true, error: null });
    try {
      const response = await tenantAPI.create(data);
      const { tenants } = get();
      set({
        tenants: [...tenants, response],
        isLoading: false,
      });
    } catch (error: any) {
      const errorMessage = error.response?.data?.detail 
        ? (typeof error.response.data.detail === 'string' 
            ? error.response.data.detail 
            : JSON.stringify(error.response.data.detail))
        : 'Failed to create tenant';
      set({ 
        error: errorMessage, 
        isLoading: false 
      });
      throw error;
    }
  },

  updateTenant: async (id: string, data: TenantUpdate) => {
    set({ isLoading: true, error: null });
    try {
      const response = await tenantAPI.update(id, data);
      const { tenants } = get();
      set({
        tenants: tenants.map(tenant => tenant.id === id ? response : tenant),
        currentTenant: get().currentTenant?.id === id ? response : get().currentTenant,
        isLoading: false,
      });
    } catch (error: any) {
      const errorMessage = error.response?.data?.detail 
        ? (typeof error.response.data.detail === 'string' 
            ? error.response.data.detail 
            : JSON.stringify(error.response.data.detail))
        : 'Failed to update tenant';
      set({ 
        error: errorMessage, 
        isLoading: false 
      });
      throw error;
    }
  },

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
    } catch (error: any) {
      const errorMessage = error.response?.data?.detail 
        ? (typeof error.response.data.detail === 'string' 
            ? error.response.data.detail 
            : JSON.stringify(error.response.data.detail))
        : 'Failed to delete tenant';
      set({ 
        error: errorMessage, 
        isLoading: false 
      });
      throw error;
    }
  },

  setCurrentTenant: (tenant: Tenant | null) => {
    set({ currentTenant: tenant });
    // If tenant is cleared (logout), also clear the list
    if (tenant === null) {
      set({ tenants: [] });
    }
  },

  addMember: async (tenantId: string, userId: string, role: string) => {
    set({ isLoading: true, error: null });
    try {
      await tenantAPI.addMember(tenantId, userId, role);
      set({ isLoading: false });
    } catch (error: any) {
      const errorMessage = error.response?.data?.detail 
        ? (typeof error.response.data.detail === 'string' 
            ? error.response.data.detail 
            : JSON.stringify(error.response.data.detail))
        : 'Failed to add member';
      set({ 
        error: errorMessage, 
        isLoading: false 
      });
      throw error;
    }
  },

  removeMember: async (tenantId: string, userId: string) => {
    set({ isLoading: true, error: null });
    try {
      await tenantAPI.removeMember(tenantId, userId);
      set({ isLoading: false });
    } catch (error: any) {
      const errorMessage = error.response?.data?.detail 
        ? (typeof error.response.data.detail === 'string' 
            ? error.response.data.detail 
            : JSON.stringify(error.response.data.detail))
        : 'Failed to remove member';
      set({ 
        error: errorMessage, 
        isLoading: false 
      });
      throw error;
    }
  },

  listMembers: async (tenantId: string) => {
    set({ isLoading: true, error: null });
    try {
      const response = await tenantAPI.listMembers(tenantId);
      set({ isLoading: false });
      return response;
    } catch (error: any) {
      const errorMessage = error.response?.data?.detail 
        ? (typeof error.response.data.detail === 'string' 
            ? error.response.data.detail 
            : JSON.stringify(error.response.data.detail))
        : 'Failed to list members';
      set({ 
        error: errorMessage, 
        isLoading: false 
      });
      throw error;
    }
  },

  clearError: () => set({ error: null }),
}));