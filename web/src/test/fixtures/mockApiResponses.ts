/**
 * Mock API response fixtures for testing API service calls.
 *
 * Provides realistic mock responses for common API endpoints.
 * Use these with vi.mocked() or fetch-mock to simulate API responses.
 */

import { vi } from 'vitest';

// Memory API Responses
export interface MockMemoryResponse {
    data: {
        id: string;
        project_id: string;
        title: string;
        content: string;
        author_id: string;
        created_at: string;
        updated_at?: string;
    };
    meta: {
        tenant_id: string;
        project_id: string;
    };
}

export const mockMemoryResponse: MockMemoryResponse = {
    data: {
        id: 'mem-123',
        project_id: 'proj-123',
        title: 'Test Memory',
        content: 'Test memory content',
        author_id: 'user-123',
        created_at: '2024-01-01T00:00:00Z',
    },
    meta: {
        tenant_id: 'tenant-123',
        project_id: 'proj-123',
    },
};

export interface MockMemoriesListResponse {
    data: Array<{
        id: string;
        project_id: string;
        title: string;
        content: string;
        author_id: string;
        created_at: string;
    }>;
    meta: {
        total: number;
        page: number;
        per_page: number;
        tenant_id: string;
        project_id: string;
    };
}

export const mockMemoriesListResponse: MockMemoriesListResponse = {
    data: [
        {
            id: 'mem-123',
            project_id: 'proj-123',
            title: 'Memory 1',
            content: 'Test content 1',
            author_id: 'user-123',
            created_at: '2024-01-01T00:00:00Z',
        },
        {
            id: 'mem-456',
            project_id: 'proj-123',
            title: 'Memory 2',
            content: 'Test content 2',
            author_id: 'user-123',
            created_at: '2024-01-02T00:00:00Z',
        },
    ],
    meta: {
        total: 2,
        page: 1,
        per_page: 20,
        tenant_id: 'tenant-123',
        project_id: 'proj-123',
    },
};

// Project API Responses
export interface MockProjectResponse {
    data: {
        id: string;
        tenant_id: string;
        name: string;
        description?: string;
        owner_id: string;
        member_ids: string[];
        created_at: string;
        updated_at?: string;
    };
    meta: {
        tenant_id: string;
    };
}

export const mockProjectResponse: MockProjectResponse = {
    data: {
        id: 'proj-123',
        tenant_id: 'tenant-123',
        name: 'Test Project',
        description: 'A test project',
        owner_id: 'user-123',
        member_ids: ['user-123'],
        created_at: '2024-01-01T00:00:00Z',
    },
    meta: {
        tenant_id: 'tenant-123',
    },
};

export interface MockProjectsListResponse {
    data: Array<{
        id: string;
        tenant_id: string;
        name: string;
        description?: string;
        owner_id: string;
        created_at: string;
    }>;
    meta: {
        total: number;
        page: number;
        per_page: number;
        tenant_id: string;
    };
}

export const mockProjectsListResponse: MockProjectsListResponse = {
    data: [
        {
            id: 'proj-123',
            tenant_id: 'tenant-123',
            name: 'Project 1',
            description: 'First project',
            owner_id: 'user-123',
            created_at: '2024-01-01T00:00:00Z',
        },
        {
            id: 'proj-456',
            tenant_id: 'tenant-123',
            name: 'Project 2',
            description: 'Second project',
            owner_id: 'user-123',
            created_at: '2024-01-02T00:00:00Z',
        },
    ],
    meta: {
        total: 2,
        page: 1,
        per_page: 20,
        tenant_id: 'tenant-123',
    },
};

// Tenant API Responses
export interface MockTenantResponse {
    data: {
        id: string;
        name: string;
        slug: string;
        description?: string;
        owner_id: string;
        plan: string;
        created_at: string;
    };
    meta: Record<string, unknown>;
}

export const mockTenantResponse: MockTenantResponse = {
    data: {
        id: 'tenant-123',
        name: 'Test Tenant',
        slug: 'test-tenant',
        description: 'A test tenant',
        owner_id: 'user-123',
        plan: 'free',
        created_at: '2024-01-01T00:00:00Z',
    },
    meta: {},
};

// Authentication API Responses
export interface MockAuthResponse {
    data: {
        user: {
            id: string;
            email: string;
            name: string;
        };
        token: string;
    };
    meta: Record<string, unknown>;
}

export const mockLoginResponse: MockAuthResponse = {
    data: {
        user: {
            id: 'user-123',
            email: 'test@example.com',
            name: 'Test User',
        },
        token: 'ms_sk_test_token_123456789',
    },
    meta: {},
};

// Error Responses
export interface MockErrorResponse {
    error: {
        code: string;
        message: string;
        details?: Record<string, unknown>;
    };
}

export const mockNotFoundResponse: MockErrorResponse = {
    error: {
        code: 'NOT_FOUND',
        message: 'Resource not found',
    },
};

export const mockUnauthorizedResponse: MockErrorResponse = {
    error: {
        code: 'UNAUTHORIZED',
        message: 'Authentication required',
    },
};

export const mockValidationErrorResponse: MockErrorResponse = {
    error: {
        code: 'VALIDATION_ERROR',
        message: 'Invalid input data',
        details: {
            field: 'title',
            message: 'Title is required',
        },
    },
};

// Helper function to create a successful fetch mock
export function createMockFetchSuccess<T>(data: T) {
    return vi.fn().mockResolvedValue({
        ok: true,
        json: async () => data,
    } as Response);
}

// Helper function to create a failed fetch mock
export function createMockFetchError(response: MockErrorResponse) {
    return vi.fn().mockResolvedValue({
        ok: false,
        status: response.error.code === 'UNAUTHORIZED' ? 401 : response.error.code === 'NOT_FOUND' ? 404 : 400,
        json: async () => response,
    } as Response);
}
