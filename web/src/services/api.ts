/// <reference types="vite/client" />
import axios from 'axios';
import {
    ProjectCreate,
    ProjectUpdate,
    MemoryCreate,
    MemoryUpdate,
    MemoryQuery,
    TenantCreate,
    TenantUpdate,
    ProviderCreate,
    ProviderUpdate
} from '../types/memory';

const api = axios.create({
    baseURL: import.meta.env.VITE_API_URL || '/api/v1',
    headers: {
        'Content-Type': 'application/json',
    },
});

api.interceptors.request.use((config) => {
    const token = localStorage.getItem('token');
    if (token) {
        config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
});

// Response interceptor to handle errors
api.interceptors.response.use(
    (response) => response,
    (error) => {
        if (error.response?.status === 401) {
            // Clear token and redirect to login if unauthorized
            localStorage.removeItem('token');
            localStorage.removeItem('user');
            if (window.location.pathname !== '/login') {
                window.location.href = '/login';
            }
        }
        return Promise.reject(error);
    }
);

export const authAPI = {
    login: async (email: string, password: string) => {
        const formData = new FormData();
        formData.append('username', email);
        formData.append('password', password);
        const response = await api.post('/auth/token', formData, {
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
            },
        });
        // Backend returns { access_token, token_type } - user is fetched separately
        const token = response.data.access_token;

        // Fetch user details
        const userResponse = await api.get('/auth/me', {
            headers: { Authorization: `Bearer ${token}` }
        });

        return { token, user: userResponse.data };
    },
    verifyToken: async (_token: string) => {
        const response = await api.get('/auth/me');
        return response.data;
    },
    updateProfile: async (data: any) => {
        const response = await api.put('/users/me', data);
        return response.data;
    },
};

export const tenantAPI = {
    list: async (params = {}) => {
        const response = await api.get('/tenants/', { params });
        return response.data;
    },
    create: async (data: TenantCreate) => {
        const response = await api.post('/tenants/', data);
        return response.data;
    },
    update: async (id: string, data: TenantUpdate) => {
        const response = await api.put(`/tenants/${id}`, data);
        return response.data;
    },
    delete: async (id: string) => {
        await api.delete(`/tenants/${id}`);
    },
    addMember: async (tenantId: string, userId: string, role: string) => {
        await api.post(`/tenants/${tenantId}/members`, { user_id: userId, role });
    },
    removeMember: async (tenantId: string, userId: string) => {
        await api.delete(`/tenants/${tenantId}/members/${userId}`);
    },
    listMembers: async (tenantId: string) => {
        const response = await api.get(`/tenants/${tenantId}/members`);
        return response.data;
    },
    get: async (id: string) => {
        const response = await api.get(`/tenants/${id}`);
        return response.data;
    },
    getStats: async (id: string) => {
        const response = await api.get(`/tenants/${id}/stats`);
        return response.data;
    },
    getAnalytics: async (id: string) => {
        const response = await api.get(`/tenants/${id}/analytics`);
        return response.data;
    },
};

export const projectAPI = {
    list: async (tenantId: string, params = {}) => {
        const response = await api.get('/projects/', { params: { ...params, tenant_id: tenantId } });
        return response.data;
    },
    create: async (tenantId: string, data: ProjectCreate) => {
        const response = await api.post('/projects/', { ...data, tenant_id: tenantId });
        return response.data;
    },
    update: async (_tenantId: string, projectId: string, data: ProjectUpdate) => {
        const response = await api.put(`/projects/${projectId}`, data);
        return response.data;
    },
    delete: async (_tenantId: string, projectId: string) => {
        await api.delete(`/projects/${projectId}`);
    },
    get: async (_tenantId: string, projectId: string) => {
        const response = await api.get(`/projects/${projectId}`);
        return response.data;
    },
    getStats: async (projectId: string) => {
        const response = await api.get(`/projects/${projectId}/stats`);
        return response.data;
    },
};

export const memoryAPI = {
    list: async (projectId: string, params = {}) => {
        const response = await api.get('/memories/', { params: { ...params, project_id: projectId } });
        return response.data;
    },
    create: async (projectId: string, data: MemoryCreate) => {
        const response = await api.post('/memories/', { ...data, project_id: projectId });
        return response.data;
    },
    update: async (_projectId: string, memoryId: string, data: MemoryUpdate) => {
        const response = await api.patch(`/memories/${memoryId}`, data);
        return response.data;
    },
    delete: async (_projectId: string, memoryId: string) => {
        await api.delete(`/memories/${memoryId}`);
    },
    search: async (projectId: string, query: MemoryQuery) => {
        const response = await api.post('/memory/search', { ...query, project_id: projectId });
        return response.data;
    },
    get: async (_projectId: string, memoryId: string) => {
        const response = await api.get(`/memories/${memoryId}`);
        return response.data;
    },
    getGraphData: async (projectId: string, options = {}) => {
        const response = await api.get('/memory/graph', { params: { ...options, project_id: projectId } });
        return response.data;
    },
    extractEntities: async (projectId: string, text: string) => {
        const response = await api.post('/memories/extract-entities', { text, project_id: projectId });
        return response.data;
    },
    extractRelationships: async (projectId: string, text: string) => {
        const response = await api.post('/memories/extract-relationships', { text, project_id: projectId });
        return response.data;
    },
    listShares: async (memoryId: string) => {
        const response = await api.get(`/memories/${memoryId}/shares`);
        return response.data.shares;
    },
    createShare: async (memoryId: string, permissions: { view: boolean; edit: boolean }, expiresAt?: string) => {
        const response = await api.post(`/memories/${memoryId}/shares`, {
            permissions,
            expires_at: expiresAt
        });
        return response.data;
    },
    deleteShare: async (memoryId: string, shareId: string) => {
        await api.delete(`/memories/${memoryId}/shares/${shareId}`);
    },
    reprocess: async (_projectId: string, memoryId: string) => {
        const response = await api.post(`/memories/${memoryId}/reprocess`);
        return response.data;
    },
};

export const schemaAPI = {
    // Entity Types
    listEntityTypes: async (projectId: string) => {
        const response = await api.get(`/projects/${projectId}/schema/entities`);
        return response.data;
    },
    createEntityType: async (projectId: string, data: any) => {
        const response = await api.post(`/projects/${projectId}/schema/entities`, data);
        return response.data;
    },
    updateEntityType: async (projectId: string, entityId: string, data: any) => {
        const response = await api.put(`/projects/${projectId}/schema/entities/${entityId}`, data);
        return response.data;
    },
    deleteEntityType: async (projectId: string, entityId: string) => {
        await api.delete(`/projects/${projectId}/schema/entities/${entityId}`);
    },

    // Edge Types
    listEdgeTypes: async (projectId: string) => {
        const response = await api.get(`/projects/${projectId}/schema/edges`);
        return response.data;
    },
    createEdgeType: async (projectId: string, data: any) => {
        const response = await api.post(`/projects/${projectId}/schema/edges`, data);
        return response.data;
    },
    updateEdgeType: async (projectId: string, edgeId: string, data: any) => {
        const response = await api.put(`/projects/${projectId}/schema/edges/${edgeId}`, data);
        return response.data;
    },
    deleteEdgeType: async (projectId: string, edgeId: string) => {
        await api.delete(`/projects/${projectId}/schema/edges/${edgeId}`);
    },

    // Edge Mappings
    listEdgeMaps: async (projectId: string) => {
        const response = await api.get(`/projects/${projectId}/schema/mappings`);
        return response.data;
    },
    createEdgeMap: async (projectId: string, data: any) => {
        const response = await api.post(`/projects/${projectId}/schema/mappings`, data);
        return response.data;
    },
    deleteEdgeMap: async (projectId: string, mapId: string) => {
        await api.delete(`/projects/${projectId}/schema/mappings/${mapId}`);
    },
};

export const taskAPI = {
    getStats: async () => {
        const response = await api.get('/tasks/stats');
        return response.data;
    },
    getQueueDepth: async () => {
        const response = await api.get('/tasks/queue-depth');
        return response.data;
    },
    getRecentTasks: async (params: {
        limit?: number;
        offset?: number;
        status?: string;
        task_type?: string;
        search?: string;
    } = {}) => {
        const response = await api.get('/tasks/recent', { params });
        return response.data;
    },
    getStatusBreakdown: async () => {
        const response = await api.get('/tasks/status-breakdown');
        return response.data;
    },
    retryTask: async (taskId: string) => {
        const response = await api.post(`/tasks/${taskId}/retry`);
        return response.data;
    },
    stopTask: async (taskId: string) => {
        const response = await api.post(`/tasks/${taskId}/stop`);
        return response.data;
    },
};

export const providerAPI = {
    list: async (params: { is_active?: boolean; provider_type?: string } = {}) => {
        const response = await api.get('/llm-providers/', { params });
        return response.data;
    },
    get: async (id: string) => {
        const response = await api.get(`/llm-providers/${id}`);
        return response.data;
    },
    create: async (data: ProviderCreate) => {
        const response = await api.post('/llm-providers/', data);
        return response.data;
    },
    update: async (id: string, data: ProviderUpdate) => {
        const response = await api.put(`/llm-providers/${id}`, data);
        return response.data;
    },
    delete: async (id: string) => {
        await api.delete(`/llm-providers/${id}`);
    },
    checkHealth: async (id: string) => {
        const response = await api.post(`/llm-providers/${id}/health-check`);
        return response.data;
    },
    getUsage: async (id: string, params: { start_date?: string; end_date?: string; tenant_id?: string } = {}) => {
        const response = await api.get(`/llm-providers/${id}/usage`, { params });
        return response.data;
    },
    assignToTenant: async (id: string, tenantId: string, priority: number = 0) => {
        const response = await api.post(`/llm-providers/${id}/assign`, { tenant_id: tenantId, priority });
        return response.data;
    },
    unassignFromTenant: async (id: string, tenantId: string) => {
        await api.delete(`/llm-providers/${id}/assign/${tenantId}`);
    },
};

export default api;
