/**
 * useBreadcrumbs Hook Tests
 */

import { renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useBreadcrumbs } from '@/hooks/useBreadcrumbs';

const mockParams: {
  tenantId?: string;
  projectId?: string;
} = { tenantId: 'tenant-123', projectId: 'proj-456' };

const mockLocation = {
  pathname: '/tenant/tenant-123/project/proj-456/memories',
  search: '',
  hash: '',
  state: null,
  key: 'test',
};

vi.mock('react-router-dom', () => ({
  useParams: () => mockParams,
  useLocation: () => mockLocation,
}));

let mockCurrentProject: { id: string; name: string } | null = {
  id: 'proj-456',
  name: 'Test Project',
};

vi.mock('@/stores/project', () => ({
  useProjectStore: (
    selector?: (state: { currentProject: typeof mockCurrentProject }) => unknown
  ) => {
    const state = { currentProject: mockCurrentProject };
    return selector ? selector(state) : state;
  },
}));

const mockCurrentConversation = { id: 'conv-123', title: 'Test Conversation' };

vi.mock('@business/agent/ui/web/stores/agent/conversationsStore', () => ({
  useConversationsStore: (
    selector?: (state: { currentConversation: typeof mockCurrentConversation }) => unknown
  ) => {
    const state = { currentConversation: mockCurrentConversation };
    return selector ? selector(state) : state;
  },
}));

describe('useBreadcrumbs', () => {
  beforeEach(() => {
    mockParams.tenantId = 'tenant-123';
    mockParams.projectId = 'proj-456';
    mockLocation.pathname = '/tenant/tenant-123/project/proj-456/memories';
    mockLocation.search = '';
    mockCurrentProject = { id: 'proj-456', name: 'Test Project' };
    mockCurrentConversation.id = 'conv-123';
    mockCurrentConversation.title = 'Test Conversation';
  });

  describe('tenant breadcrumbs', () => {
    it('should generate breadcrumbs for tenant overview', () => {
      mockLocation.pathname = '/tenant/tenant-123';
      const { result } = renderHook(() => useBreadcrumbs('tenant'));

      expect(result.current).toEqual([{ label: 'Home', path: '/tenant' }]);
    });

    it('should generate breadcrumbs for tenant sub-pages', () => {
      mockLocation.pathname = '/tenant/tenant-123/projects';
      const { result } = renderHook(() => useBreadcrumbs('tenant'));

      expect(result.current).toEqual([
        { label: 'Home', path: '/tenant' },
        { label: 'Projects', path: '/tenant/tenant-123/projects' },
      ]);
    });

    it('should return no breadcrumbs for the landing page', () => {
      mockLocation.pathname = '/tenant';
      mockParams.tenantId = undefined;

      const { result } = renderHook(() => useBreadcrumbs('tenant'));

      expect(result.current).toEqual([]);
    });

    it('should generate breadcrumbs for tenant agent workspace conversations', () => {
      mockLocation.pathname = '/tenant/tenant-123/agent-workspace/conv-123';
      const { result } = renderHook(() => useBreadcrumbs('tenant'));

      expect(result.current).toEqual([
        { label: 'Home', path: '/tenant' },
        {
          label: 'Test Conversation',
          path: '/tenant/tenant-123/agent-workspace/conv-123',
        },
      ]);
    });

    it('should fall back to Agent Workspace when the conversation has no title', () => {
      mockCurrentConversation.title = '';
      mockLocation.pathname = '/tenant/tenant-123/agent-workspace';

      const { result } = renderHook(() => useBreadcrumbs('tenant'));

      expect(result.current).toEqual([
        { label: 'Home', path: '/tenant' },
        {
          label: 'Agent Workspace',
          path: '/tenant/tenant-123/agent-workspace',
        },
      ]);
    });
  });

  describe('project breadcrumbs', () => {
    it('should generate breadcrumbs for project overview', () => {
      mockLocation.pathname = '/tenant/tenant-123/project/proj-456';
      const { result } = renderHook(() => useBreadcrumbs('project'));

      expect(result.current).toEqual([
        { label: 'Home', path: '/tenant' },
        { label: 'Projects', path: '/tenant/tenant-123/projects' },
        { label: 'Test Project', path: '/tenant/tenant-123/project/proj-456' },
      ]);
    });

    it('should generate breadcrumbs for project sub-pages', () => {
      mockLocation.pathname = '/tenant/tenant-123/project/proj-456/memories';
      const { result } = renderHook(() => useBreadcrumbs('project'));

      expect(result.current).toEqual([
        { label: 'Home', path: '/tenant' },
        { label: 'Projects', path: '/tenant/tenant-123/projects' },
        { label: 'Test Project', path: '/tenant/tenant-123/project/proj-456' },
        { label: 'Memories', path: '/tenant/tenant-123/project/proj-456/memories' },
      ]);
    });

    it('should format kebab-case labels correctly', () => {
      mockLocation.pathname = '/tenant/tenant-123/project/proj-456/advanced-search';
      const { result } = renderHook(() => useBreadcrumbs('project'));

      expect(result.current[result.current.length - 1].label).toBe('Advanced Search');
    });

    it('should keep the page-level breadcrumb on deeply nested paths', () => {
      mockLocation.pathname = '/tenant/tenant-123/project/proj-456/memories/abc-123';
      const { result } = renderHook(() => useBreadcrumbs('project'));

      expect(result.current[result.current.length - 1].label).toBe('Memories');
    });

    it('should fall back safely when project metadata is missing', () => {
      mockCurrentProject = null;
      mockLocation.pathname = '/tenant/tenant-123/project/proj-456/memories';

      const { result } = renderHook(() => useBreadcrumbs('project'));

      expect(result.current).toEqual([
        { label: 'Home', path: '/tenant' },
        { label: 'Projects', path: '/tenant/tenant-123/projects' },
        { label: 'Project', path: '/tenant/tenant-123/project/proj-456' },
        { label: 'Memories', path: '/tenant/tenant-123/project/proj-456/memories' },
      ]);
    });
  });

  describe('agent breadcrumbs', () => {
    it('should generate breadcrumbs for the agent dashboard', () => {
      mockLocation.pathname = '/tenant/tenant-123/project/proj-456/agent';
      const { result } = renderHook(() => useBreadcrumbs('agent'));

      expect(result.current).toEqual([
        { label: 'Home', path: '/tenant' },
        { label: 'Projects', path: '/tenant/tenant-123/projects' },
        { label: 'Test Project', path: '/tenant/tenant-123/project/proj-456' },
        { label: 'Agent', path: '/tenant/tenant-123/project/proj-456/agent' },
      ]);
    });

    it('should generate breadcrumbs for agent sub-pages', () => {
      mockLocation.pathname = '/tenant/tenant-123/project/proj-456/agent/logs';
      const { result } = renderHook(() => useBreadcrumbs('agent'));

      expect(result.current).toEqual([
        { label: 'Home', path: '/tenant' },
        { label: 'Projects', path: '/tenant/tenant-123/projects' },
        { label: 'Test Project', path: '/tenant/tenant-123/project/proj-456' },
        { label: 'Agent', path: '/tenant/tenant-123/project/proj-456/agent' },
        { label: 'Logs', path: '/tenant/tenant-123/project/proj-456/agent/logs' },
      ]);
    });
  });

  describe('schema breadcrumbs', () => {
    it('should generate breadcrumbs for schema pages', () => {
      mockLocation.pathname = '/tenant/tenant-123/project/proj-456/schema/entities';
      const { result } = renderHook(() => useBreadcrumbs('schema'));

      expect(result.current).toEqual([
        { label: 'Home', path: '/tenant' },
        { label: 'Projects', path: '/tenant/tenant-123/projects' },
        { label: 'Test Project', path: '/tenant/tenant-123/project/proj-456' },
        { label: 'Schema', path: '/tenant/tenant-123/project/proj-456/schema' },
        { label: 'Entities', path: '/tenant/tenant-123/project/proj-456/schema/entities' },
      ]);
    });
  });

  describe('options parameter', () => {
    it('should support custom labels via options', () => {
      mockLocation.pathname = '/tenant/tenant-123/project/proj-456/custom-page';
      const { result } = renderHook(() =>
        useBreadcrumbs('project', {
          labels: {
            'custom-page': 'Custom Label',
          },
        })
      );

      expect(result.current[result.current.length - 1].label).toBe('Custom Label');
    });

    it('should support maxDepth option', () => {
      mockLocation.pathname = '/tenant/tenant-123/project/proj-456/memories/abc-123/def-456';
      const { result } = renderHook(() =>
        useBreadcrumbs('project', {
          maxDepth: 3,
        })
      );

      expect(result.current.length).toBeLessThanOrEqual(3);
    });

    it('should support hideLast option', () => {
      mockLocation.pathname = '/tenant/tenant-123/project/proj-456/memories';
      const { result } = renderHook(() =>
        useBreadcrumbs('project', {
          hideLast: true,
        })
      );

      expect(result.current[result.current.length - 1].path).toBe('');
    });
  });
});
