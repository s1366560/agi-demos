/**
 * useBreadcrumbs Hook Tests
 *
 * Tests for breadcrumb generation hook.
 */

import { describe, it, expect, vi } from 'vitest'
import { renderHook } from '@testing-library/react'
import { useBreadcrumbs } from '@/hooks/useBreadcrumbs'

// Mock react-router-dom
const mockParams = { tenantId: 'tenant-123', projectId: 'proj-456' }
const mockLocation = {
  pathname: '/project/proj-456/memories',
  search: '',
  hash: '',
  state: null,
  key: 'test',
}

vi.mock('react-router-dom', () => ({
  useParams: () => mockParams,
  useLocation: () => mockLocation,
}))

// Mock stores
let mockCurrentTenant = { id: 'tenant-123', name: 'Test Tenant' }
let mockCurrentProject = { id: 'proj-456', name: 'Test Project' }

vi.mock('@/stores/tenant', () => ({
  useTenantStore: (selector?: (state: { currentTenant: typeof mockCurrentTenant }) => unknown) => {
    const state = { currentTenant: mockCurrentTenant }
    return selector ? selector(state) : state
  },
}))

vi.mock('@/stores/project', () => ({
  useProjectStore: (selector?: (state: { currentProject: typeof mockCurrentProject }) => unknown) => {
    const state = { currentProject: mockCurrentProject }
    return selector ? selector(state) : state
  },
}))

describe('useBreadcrumbs', () => {
  describe('tenant breadcrumbs', () => {
    beforeEach(() => {
      mockLocation.pathname = '/tenant/tenant-123/projects'
      mockParams.tenantId = 'tenant-123'
    })

    it('should generate breadcrumbs for tenant overview', () => {
      mockLocation.pathname = '/tenant/tenant-123'
      const { result } = renderHook(() => useBreadcrumbs('tenant'))

      // For tenant overview, should have Home breadcrumb
      expect(result.current.length).toBeGreaterThanOrEqual(1)
      expect(result.current[0].label).toBe('Home')
    })

    it('should generate breadcrumbs for tenant sub-pages', () => {
      const { result } = renderHook(() => useBreadcrumbs('tenant'))

      expect(result.current).toEqual([
        { label: 'Home', path: '/tenant' },
        { label: 'Projects', path: '/tenant/tenant-123/projects' },
      ])
    })

    it('should handle generic tenant path', () => {
      mockLocation.pathname = '/tenant'
      mockParams.tenantId = undefined
      const { result } = renderHook(() => useBreadcrumbs('tenant'))

      // For generic /tenant path, should return empty breadcrumbs
      // (it's the entry point, no need for breadcrumbs)
      expect(result.current.length).toBe(0)
    })
  })

  describe('project breadcrumbs', () => {
    beforeEach(() => {
      mockParams.projectId = 'proj-456'
    })

    it('should generate breadcrumbs for project overview', () => {
      mockLocation.pathname = '/project/proj-456'
      const { result } = renderHook(() => useBreadcrumbs('project'))

      expect(result.current).toEqual([
        { label: 'Home', path: '/tenant' },
        { label: 'Projects', path: '/tenant/projects' },
        { label: 'Test Project', path: '/project/proj-456' },
      ])
    })

    it('should generate breadcrumbs for project sub-pages', () => {
      mockLocation.pathname = '/project/proj-456/memories'
      const { result } = renderHook(() => useBreadcrumbs('project'))

      expect(result.current).toEqual([
        { label: 'Home', path: '/tenant' },
        { label: 'Projects', path: '/tenant/projects' },
        { label: 'Test Project', path: '/project/proj-456' },
        { label: 'Memories', path: '/project/proj-456/memories' },
      ])
    })

    it('should format kebab-case labels correctly', () => {
      mockLocation.pathname = '/project/proj-456/advanced-search'
      const { result } = renderHook(() => useBreadcrumbs('project'))

      expect(result.current[result.current.length - 1].label).toBe('Advanced Search')
    })

    it('should handle deeply nested paths', () => {
      mockLocation.pathname = '/project/proj-456/memories/abc-123'
      const { result } = renderHook(() => useBreadcrumbs('project'))

      // Should include the nested resource
      expect(result.current.length).toBeGreaterThanOrEqual(4)
      // Last item should be the formatted page name
      expect(result.current[result.current.length - 1].label).toBe('Memories')
    })
  })

  describe('agent breadcrumbs', () => {
    beforeEach(() => {
      mockParams.projectId = 'proj-456'
    })

    it('should generate breadcrumbs for agent workspace', () => {
      mockLocation.pathname = '/project/proj-456/agent'
      const { result } = renderHook(() => useBreadcrumbs('agent'))

      expect(result.current.length).toBeGreaterThanOrEqual(3)
      expect(result.current[result.current.length - 1].label).toBe('Agent')
    })

    it('should generate breadcrumbs for agent sub-pages', () => {
      mockLocation.pathname = '/project/proj-456/agent/logs'
      const { result } = renderHook(() => useBreadcrumbs('agent'))

      expect(result.current.length).toBeGreaterThanOrEqual(4)
      expect(result.current[result.current.length - 1].label).toBe('Logs')
    })
  })

  describe('schema breadcrumbs', () => {
    beforeEach(() => {
      mockParams.projectId = 'proj-456'
    })

    it('should generate breadcrumbs for schema pages', () => {
      mockLocation.pathname = '/project/proj-456/schema/entities'
      const { result } = renderHook(() => useBreadcrumbs('schema'))

      expect(result.current.length).toBeGreaterThanOrEqual(4)
      expect(result.current[result.current.length - 1].label).toBe('Entities')
    })
  })

  describe('edge cases', () => {
    it('should handle root path', () => {
      mockLocation.pathname = '/'
      const { result } = renderHook(() => useBreadcrumbs('tenant'))

      expect(result.current).toEqual([])
    })

    it('should handle missing project name', () => {
      // Set project to null to test fallback behavior
      mockCurrentProject = null
      mockLocation.pathname = '/project/proj-456/memories'
      const { result } = renderHook(() => useBreadcrumbs('project'))

      // Should still generate breadcrumbs, even if project name is missing
      expect(result.current.length).toBeGreaterThan(0)
      // Should use "Project" as fallback label
      const projectBreadcrumb = result.current.find(b => b.path === '/project/proj-456')
      expect(projectBreadcrumb?.label).toBe('Project')

      // Reset for other tests
      mockCurrentProject = { id: 'proj-456', name: 'Test Project' }
    })

    it('should handle path with trailing slash', () => {
      mockLocation.pathname = '/project/proj-456/memories/'
      const { result } = renderHook(() => useBreadcrumbs('project'))

      // Should work the same as without trailing slash
      expect(result.current[result.current.length - 1].label).toBe('Memories')
    })
  })

  describe('options parameter', () => {
    beforeEach(() => {
      mockParams.projectId = 'proj-456'
    })

    it('should support custom labels via options', () => {
      mockLocation.pathname = '/project/proj-456/custom-page'
      const { result } = renderHook(() =>
        useBreadcrumbs('project', {
          labels: {
            'custom-page': 'Custom Label',
          },
        })
      )

      expect(result.current[result.current.length - 1].label).toBe('Custom Label')
    })

    it('should support maxDepth option', () => {
      mockLocation.pathname = '/project/proj-456/memories/abc-123/def-456'
      const { result } = renderHook(() =>
        useBreadcrumbs('project', {
          maxDepth: 3,
        })
      )

      // Should limit to 3 breadcrumbs
      expect(result.current.length).toBeLessThanOrEqual(3)
    })

    it('should support hideLast option', () => {
      mockLocation.pathname = '/project/proj-456/memories'
      const { result } = renderHook(() =>
        useBreadcrumbs('project', {
          hideLast: true,
        })
      )

      // Last breadcrumb should have empty path (not clickable)
      expect(result.current[result.current.length - 1].path).toBe('')
    })
  })
})
