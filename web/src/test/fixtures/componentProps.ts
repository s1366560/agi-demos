/**
 * Component test props fixtures for testing React components.
 *
 * Provides default props for common components to simplify test setup.
 * Each fixture includes sensible defaults that can be overridden in specific tests.
 */

import { vi } from 'vitest';

// Memory Manager Props
export interface MemoryManagerProps {
  memories: Array<{
    id: string;
    title: string;
    content: string;
    author_id: string;
    created_at: string;
    updated_at?: string;
  }>;
  loading: boolean;
  error: string | null;
  onCreate: (memory: Partial<{ title: string; content: string }>) => Promise<void>;
  onUpdate: (id: string, memory: Partial<{ title: string; content: string }>) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
}

export const defaultMemoryManagerProps: MemoryManagerProps = {
  memories: [],
  loading: false,
  error: null,
  onCreate: vi.fn(),
  onUpdate: vi.fn(),
  onDelete: vi.fn(),
};

// Project Manager Props
export interface ProjectManagerProps {
  projects: Array<{
    id: string;
    tenant_id: string;
    name: string;
    description?: string;
    owner_id: string;
    created_at: string;
    updated_at?: string;
  }>;
  loading: boolean;
  error: string | null;
  onCreate: (project: Partial<{ name: string; description: string }>) => Promise<void>;
  onUpdate: (id: string, project: Partial<{ name: string; description: string }>) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
}

export const defaultProjectManagerProps: ProjectManagerProps = {
  projects: [],
  loading: false,
  error: null,
  onCreate: vi.fn(),
  onUpdate: vi.fn(),
  onDelete: vi.fn(),
};

// Tenant Selector Props
export interface TenantSelectorProps {
  tenants: Array<{
    id: string;
    name: string;
    slug: string;
    owner_id: string;
  }>;
  currentTenant: string | null;
  loading: boolean;
  onTenantChange: (tenantId: string) => void;
}

export const defaultTenantSelectorProps: TenantSelectorProps = {
  tenants: [],
  currentTenant: null,
  loading: false,
  onTenantChange: vi.fn(),
};

// Memory Form Props
export interface MemoryFormProps {
  onSubmit: (data: { title: string; content: string; tags: string[] }) => Promise<void>;
  onCancel?: () => void;
  initialValues?: {
    title: string;
    content: string;
    tags: string[];
  };
  loading?: boolean;
}

export const defaultMemoryFormProps: MemoryFormProps = {
  onSubmit: vi.fn(),
};

// Project Form Props
export interface ProjectFormProps {
  onSubmit: (data: { name: string; description?: string }) => Promise<void>;
  onCancel?: () => void;
  initialValues?: {
    name: string;
    description?: string;
  };
  loading?: boolean;
}

export const defaultProjectFormProps: ProjectFormProps = {
  onSubmit: vi.fn(),
};

// Helper function to create test memories
export function createTestMemory(overrides: Partial<MemoryManagerProps['memories'][0]> = {}) {
  return {
    id: 'mem-123',
    title: 'Test Memory',
    content: 'Test content',
    author_id: 'user-123',
    created_at: new Date().toISOString(),
    ...overrides,
  };
}

// Helper function to create test projects
export function createTestProject(overrides: Partial<ProjectManagerProps['projects'][0]> = {}) {
  return {
    id: 'proj-123',
    tenant_id: 'tenant-123',
    name: 'Test Project',
    owner_id: 'user-123',
    created_at: new Date().toISOString(),
    ...overrides,
  };
}
