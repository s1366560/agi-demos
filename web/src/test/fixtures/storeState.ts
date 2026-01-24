/**
 * Store state fixtures for testing Zustand stores.
 *
 * Provides initial state and reset functions for all application stores.
 * Use these fixtures to ensure stores start in a clean state for each test.
 */

import { vi } from 'vitest';

// Types for store states (adjust based on actual store implementations)
export interface AuthStoreState {
  user: {
    id: string;
    email: string;
    name: string;
  } | null;
  token: string | null;
  isAuthenticated: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  refreshToken: () => Promise<void>;
}

export const defaultAuthStoreState: AuthStoreState = {
  user: null,
  token: null,
  isAuthenticated: false,
  login: vi.fn(),
  logout: vi.fn(),
  refreshToken: vi.fn(),
};

export function resetAuthStore() {
  // Reset auth store to initial state
  // Implementation depends on actual store
  vi.clearAllMocks();
}

// Tenant Store State
export interface TenantStoreState {
  currentTenant: {
    id: string;
    name: string;
    slug: string;
  } | null;
  tenants: Array<{
    id: string;
    name: string;
    slug: string;
  }>;
  isLoading: boolean;
  error: string | null;
  setCurrentTenant: (tenantId: string) => void;
  loadTenants: () => Promise<void>;
}

export const defaultTenantStoreState: TenantStoreState = {
  currentTenant: null,
  tenants: [],
  isLoading: false,
  error: null,
  setCurrentTenant: vi.fn(),
  loadTenants: vi.fn(),
};

export function resetTenantStore() {
  vi.clearAllMocks();
}

// Memory Store State
export interface MemoryStoreState {
  memories: Array<{
    id: string;
    project_id: string;
    title: string;
    content: string;
    author_id: string;
    created_at: string;
  }>;
  loading: boolean;
  error: string | null;
  fetchMemories: (projectId?: string) => Promise<void>;
  createMemory: (memory: { title: string; content: string }) => Promise<void>;
  updateMemory: (id: string, memory: Partial<{ title: string; content: string }>) => Promise<void>;
  deleteMemory: (id: string) => Promise<void>;
}

export const defaultMemoryStoreState: MemoryStoreState = {
  memories: [],
  loading: false,
  error: null,
  fetchMemories: vi.fn(),
  createMemory: vi.fn(),
  updateMemory: vi.fn(),
  deleteMemory: vi.fn(),
};

export function resetMemoryStore() {
  vi.clearAllMocks();
}

// Project Store State
export interface ProjectStoreState {
  projects: Array<{
    id: string;
    tenant_id: string;
    name: string;
    description?: string;
    owner_id: string;
    created_at: string;
  }>;
  loading: boolean;
  error: string | null;
  fetchProjects: () => Promise<void>;
  createProject: (project: { name: string; description?: string }) => Promise<void>;
  updateProject: (id: string, project: Partial<{ name: string; description: string }>) => Promise<void>;
  deleteProject: (id: string) => Promise<void>;
}

export const defaultProjectStoreState: ProjectStoreState = {
  projects: [],
  loading: false,
  error: null,
  fetchProjects: vi.fn(),
  createProject: vi.fn(),
  updateProject: vi.fn(),
  deleteProject: vi.fn(),
};

export function resetProjectStore() {
  vi.clearAllMocks();
}

// Helper function to reset all stores
export function resetAllStores() {
  resetAuthStore();
  resetTenantStore();
  resetMemoryStore();
  resetProjectStore();
}

// Helper function to create a test user
export function createTestUser(overrides = {}) {
  return {
    id: 'user-123',
    email: 'test@example.com',
    name: 'Test User',
    ...overrides,
  };
}

// Helper function to create a test tenant
export function createTestTenant(overrides = {}) {
  return {
    id: 'tenant-123',
    name: 'Test Tenant',
    slug: 'test-tenant',
    ...overrides,
  };
}

// Helper function to create test memories
export function createTestMemories(count: number = 3) {
  return Array.from({ length: count }, (_, i) => ({
    id: `mem-${i + 1}`,
    project_id: 'proj-123',
    title: `Test Memory ${i + 1}`,
    content: `Test content ${i + 1}`,
    author_id: 'user-123',
    created_at: new Date().toISOString(),
  }));
}

// Helper function to create test projects
export function createTestProjects(count: number = 2) {
  return Array.from({ length: count }, (_, i) => ({
    id: `proj-${i + 1}`,
    tenant_id: 'tenant-123',
    name: `Test Project ${i + 1}`,
    description: `Test project ${i + 1}`,
    owner_id: 'user-123',
    created_at: new Date().toISOString(),
  }));
}
