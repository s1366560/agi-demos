import { describe, it, expect, vi, beforeEach } from 'vitest';

import { authAPI, tenantAPI, projectAPI, memoryAPI, taskAPI } from '../services/api';

import type { MemoryCreate, MemoryUpdate, Entity, Relationship } from '../types/memory';

// Define the mock instance using vi.hoisted to handle hoisting
const { mockApiInstance } = vi.hoisted(() => {
  return {
    mockApiInstance: {
      interceptors: {
        request: { use: vi.fn() },
        response: { use: vi.fn() },
      },
      get: vi.fn(),
      post: vi.fn(),
      put: vi.fn(),
      patch: vi.fn(),
      delete: vi.fn(),
    },
  };
});

// Mock axios
vi.mock('axios', () => ({
  default: {
    create: vi.fn(() => mockApiInstance),
  },
}));

describe('API Services', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
  });

  describe('authAPI', () => {
    it('login should return token and user', async () => {
      const mockTokenResponse = {
        access_token: 'test-token',
        token_type: 'bearer',
      };
      const mockBackendUser = {
        user_id: 'user-1',
        email: 'test@example.com',
        name: 'Test User',
        roles: ['user'],
        is_active: true,
        created_at: '2024-01-01T00:00:00Z',
      };

      mockApiInstance.post.mockResolvedValueOnce({ data: mockTokenResponse });
      mockApiInstance.get.mockResolvedValueOnce({ data: mockBackendUser });

      const result = await authAPI.login('test@example.com', 'password');

      expect(mockApiInstance.post).toHaveBeenCalledWith(
        '/auth/token',
        expect.any(FormData),
        expect.any(Object)
      );
      expect(mockApiInstance.get).toHaveBeenCalledWith('/auth/me', expect.any(Object));
      expect(result).toEqual({
        token: 'test-token',
        user: {
          id: 'user-1',
          email: 'test@example.com',
          name: 'Test User',
          roles: ['user'],
          is_active: true,
          created_at: '2024-01-01T00:00:00Z',
          profile: undefined,
          must_change_password: undefined,
        },
        must_change_password: false,
      });
    });

    it('verifyToken should return user', async () => {
      const mockBackendUser = {
        user_id: '1',
        email: 'test@example.com',
        name: 'Test User',
        roles: ['user'],
        is_active: true,
        created_at: '2024-01-01T00:00:00Z',
      };
      mockApiInstance.get.mockResolvedValue({ data: mockBackendUser });
      const result = await authAPI.verifyToken('token');
      expect(mockApiInstance.get).toHaveBeenCalledWith('/auth/me', undefined);
      expect(result).toEqual({
        id: '1',
        email: 'test@example.com',
        name: 'Test User',
        roles: ['user'],
        is_active: true,
        created_at: '2024-01-01T00:00:00Z',
        profile: undefined,
      });
    });

    it('updateProfile should send user update payload and map the response', async () => {
      const payload = {
        name: 'Updated User',
        profile: {
          job_title: 'Staff Engineer',
          location: 'Remote',
        },
      };
      const mockBackendUser = {
        user_id: 'user-1',
        email: 'updated@example.com',
        name: 'Updated User',
        roles: ['user'],
        is_active: true,
        created_at: '2024-01-01T00:00:00Z',
        profile: payload.profile,
        preferred_language: 'en-US' as const,
      };

      mockApiInstance.put.mockResolvedValue({ data: mockBackendUser });

      const result = await authAPI.updateProfile(payload);

      expect(mockApiInstance.put).toHaveBeenCalledWith('/users/me', payload, undefined);
      expect(result).toEqual({
        id: 'user-1',
        email: 'updated@example.com',
        name: 'Updated User',
        roles: ['user'],
        is_active: true,
        created_at: '2024-01-01T00:00:00Z',
        profile: payload.profile,
        preferred_language: 'en-US',
      });
    });
  });

  describe('tenantAPI', () => {
    it('list should return tenants', async () => {
      const mockData = {
        tenants: [{ id: 't1', name: 'Tenant 1' }],
        total: 1,
      };
      mockApiInstance.get.mockResolvedValue({ data: mockData });

      const result = await tenantAPI.list();

      expect(mockApiInstance.get).toHaveBeenCalledWith('/tenants/', { params: {} });
      expect(result).toEqual(mockData);
    });

    it('create should create tenant', async () => {
      const mockData = { id: '1' };
      mockApiInstance.post.mockResolvedValue({ data: mockData });
      const result = await tenantAPI.create({ name: 'T1' } as any);
      expect(mockApiInstance.post).toHaveBeenCalledWith('/tenants/', { name: 'T1' }, undefined);
      expect(result).toEqual(mockData);
    });

    it('update should update tenant', async () => {
      const mockData = { id: '1' };
      mockApiInstance.put.mockResolvedValue({ data: mockData });
      const result = await tenantAPI.update('1', { name: 'T2' });
      expect(mockApiInstance.put).toHaveBeenCalledWith('/tenants/1', { name: 'T2' }, undefined);
      expect(result).toEqual(mockData);
    });

    it('delete should delete tenant', async () => {
      mockApiInstance.delete.mockResolvedValue({});
      await tenantAPI.delete('1');
      expect(mockApiInstance.delete).toHaveBeenCalledWith('/tenants/1', undefined);
    });

    it('get should get tenant', async () => {
      const mockData = { id: '1' };
      mockApiInstance.get.mockResolvedValue({ data: mockData });
      const result = await tenantAPI.get('1');
      expect(mockApiInstance.get).toHaveBeenCalledWith('/tenants/1', undefined);
      expect(result).toEqual(mockData);
    });

    it('addMember should add member', async () => {
      mockApiInstance.post.mockResolvedValue({});
      await tenantAPI.addMember('t1', 'u1', 'admin');
      expect(mockApiInstance.post).toHaveBeenCalledWith(
        '/tenants/t1/members',
        { user_id: 'u1', role: 'admin' },
        undefined
      );
    });

    it('removeMember should remove member', async () => {
      mockApiInstance.delete.mockResolvedValue({});
      await tenantAPI.removeMember('t1', 'u1');
      expect(mockApiInstance.delete).toHaveBeenCalledWith('/tenants/t1/members/u1', undefined);
    });

    it('listMembers should list members', async () => {
      const mockData = [{ user_id: 'u1' }];
      mockApiInstance.get.mockResolvedValue({ data: mockData });
      const result = await tenantAPI.listMembers('t1');
      expect(mockApiInstance.get).toHaveBeenCalledWith('/tenants/t1/members', undefined);
      expect(result).toEqual(mockData);
    });

    it('listMembers should normalize backend members envelope', async () => {
      const mockData = [{ user_id: 'u1' }];
      mockApiInstance.get.mockResolvedValue({ data: { members: mockData, total: 1 } });
      const result = await tenantAPI.listMembers('t1');
      expect(mockApiInstance.get).toHaveBeenCalledWith('/tenants/t1/members', undefined);
      expect(result).toEqual(mockData);
    });
  });

  describe('projectAPI', () => {
    it('list should return projects for tenant', async () => {
      const mockData = {
        projects: [{ id: 'p1', name: 'Project 1' }],
        total: 1,
      };
      mockApiInstance.get.mockResolvedValue({ data: mockData });

      const result = await projectAPI.list('tenant-1');

      expect(mockApiInstance.get).toHaveBeenCalledWith('/projects/', {
        params: { tenant_id: 'tenant-1' },
      });
      expect(result).toEqual(mockData);
    });

    it('create should create project', async () => {
      const mockData = { id: '1' };
      mockApiInstance.post.mockResolvedValue({ data: mockData });
      const result = await projectAPI.create('t1', { name: 'P1' } as any);
      expect(mockApiInstance.post).toHaveBeenCalledWith(
        '/projects/',
        { name: 'P1', tenant_id: 't1' },
        undefined
      );
      expect(result).toEqual(mockData);
    });

    it('update should update project', async () => {
      const mockData = { id: '1' };
      mockApiInstance.put.mockResolvedValue({ data: mockData });
      const result = await projectAPI.update('t1', 'p1', { name: 'P2' } as any);
      expect(mockApiInstance.put).toHaveBeenCalledWith('/projects/p1', { name: 'P2' }, undefined);
      expect(result).toEqual(mockData);
    });

    it('delete should delete project', async () => {
      mockApiInstance.delete.mockResolvedValue({});
      await projectAPI.delete('t1', 'p1');
      expect(mockApiInstance.delete).toHaveBeenCalledWith('/projects/p1', undefined);
    });

    it('get should get project', async () => {
      const mockData = { id: '1' };
      mockApiInstance.get.mockResolvedValue({ data: mockData });
      const result = await projectAPI.get('t1', 'p1');
      expect(mockApiInstance.get).toHaveBeenCalledWith('/projects/p1', undefined);
      expect(result).toEqual(mockData);
    });
  });

  describe('memoryAPI', () => {
    it('list should list memories', async () => {
      const mockData: unknown[] = [];
      mockApiInstance.get.mockResolvedValue({ data: mockData });
      await memoryAPI.list('p1');
      expect(mockApiInstance.get).toHaveBeenCalledWith('/memories/', {
        params: { project_id: 'p1' },
      });
    });

    it('create should create memory', async () => {
      const mockData = { id: '1' };
      mockApiInstance.post.mockResolvedValue({ data: mockData });
      await memoryAPI.create('p1', { title: 'M1' } as MemoryCreate);
      expect(mockApiInstance.post).toHaveBeenCalledWith(
        '/memories/',
        { title: 'M1', project_id: 'p1' },
        undefined
      );
    });

    it('update should update memory', async () => {
      const mockData = { id: '1' };
      mockApiInstance.patch.mockResolvedValue({ data: mockData });
      await memoryAPI.update('p1', 'm1', { title: 'M2' } as MemoryUpdate);
      expect(mockApiInstance.patch).toHaveBeenCalledWith(
        '/memories/m1',
        { title: 'M2' },
        undefined
      );
    });

    it('delete should delete memory', async () => {
      mockApiInstance.delete.mockResolvedValue({});
      await memoryAPI.delete('p1', 'm1');
      expect(mockApiInstance.delete).toHaveBeenCalledWith('/memories/m1', undefined);
    });

    it('get should get memory', async () => {
      const mockData = { id: '1' };
      mockApiInstance.get.mockResolvedValue({ data: mockData });
      await memoryAPI.get('p1', 'm1');
      expect(mockApiInstance.get).toHaveBeenCalledWith('/memories/m1', undefined);
    });

    it('search should return results', async () => {
      const mockData = {
        results: [{ id: 'm1', content: 'memory 1' }],
        total: 1,
      };
      mockApiInstance.post.mockResolvedValue({ data: mockData });

      const result = await memoryAPI.search('project-1', { query: 'test' });

      expect(mockApiInstance.post).toHaveBeenCalledWith(
        '/memory/search',
        { query: 'test', project_id: 'project-1' },
        undefined
      );
      expect(result).toEqual(mockData);
    });

    it('getGraphData should get graph', async () => {
      const mockData = {};
      mockApiInstance.get.mockResolvedValue({ data: mockData });
      await memoryAPI.getGraphData('p1');
      expect(mockApiInstance.get).toHaveBeenCalledWith('/graph/memory/graph', {
        params: { project_id: 'p1' },
      });
    });

    it('extractEntities should extract', async () => {
      const mockData: Entity[] = [];
      mockApiInstance.post.mockResolvedValue({ data: mockData });
      await memoryAPI.extractEntities('p1', 'text');
      expect(mockApiInstance.post).toHaveBeenCalledWith(
        '/memories/extract-entities',
        { text: 'text', project_id: 'p1' },
        undefined
      );
    });

    it('extractRelationships should extract', async () => {
      const mockData: Relationship[] = [];
      mockApiInstance.post.mockResolvedValue({ data: mockData });
      await memoryAPI.extractRelationships('p1', 'text');
      expect(mockApiInstance.post).toHaveBeenCalledWith(
        '/memories/extract-relationships',
        { text: 'text', project_id: 'p1' },
        undefined
      );
    });
  });

  describe('taskAPI', () => {
    it('getRecentTasks should pass filters and return list responses', async () => {
      const mockTasks = [
        { id: 'task-1', task_type: 'embedding', status: 'completed', created_at: 'now' },
      ];
      mockApiInstance.get.mockResolvedValue({ data: mockTasks });

      const result = await taskAPI.getRecentTasks({
        entity_id: 'entity-1',
        entity_type: 'memory',
        limit: 25,
      });

      expect(mockApiInstance.get).toHaveBeenCalledWith('/tasks/recent', {
        params: { entity_id: 'entity-1', entity_type: 'memory', limit: 25 },
      });
      expect(result).toEqual({
        tasks: mockTasks,
        total: mockTasks.length,
        limit: 25,
        offset: 0,
        has_more: false,
      });
    });

    it('getRecentTasks should normalize enveloped task responses', async () => {
      const mockTasks = [
        { id: 'task-1', task_type: 'embedding', status: 'completed', created_at: 'now' },
      ];
      mockApiInstance.get.mockResolvedValue({ data: { tasks: mockTasks, total: 1 } });

      const result = await taskAPI.getRecentTasks();

      expect(result).toEqual({
        tasks: mockTasks,
        total: 1,
        limit: mockTasks.length,
        offset: 0,
        has_more: false,
      });
    });

    it('retryPendingTasks should submit a bounded resume request', async () => {
      const response = { submitted: 2, skipped: 0, limit: 25, task_ids: ['t1', 't2'] };
      mockApiInstance.post.mockResolvedValue({ data: response });

      const result = await taskAPI.retryPendingTasks({
        limit: 25,
        task_type: 'add_episode',
        include_failed: true,
      });

      expect(mockApiInstance.post).toHaveBeenCalledWith('/tasks/retry-pending', undefined, {
        params: { limit: 25, task_type: 'add_episode', include_failed: true },
      });
      expect(result).toEqual(response);
    });
  });
});
