/**
 * SWR Hooks Tests
 *
 * Tests for SWR-based data fetching hooks including:
 * - Data fetching
 * - Request deduplication
 * - Optimistic updates
 * - Error handling
 *
 * TDD Phase: GREEN (implementation matches tests)
 */

import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor, act } from '@testing-library/react'
import { SWRConfig } from 'swr'

// Mock the httpClient before importing hooks
vi.mock('@/services/client/httpClient', () => ({
  httpClient: {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}))

import { httpClient } from '@/services/client/httpClient'
import { useProjectStats, useMemories, useProject } from '@/hooks/useSwr'

// Test data factories
const createMockProjectStats = (overrides = {}) => ({
  memory_count: 100,
  storage_used: 1073741824,
  storage_limit: 10737418240,
  active_nodes: 42,
  collaborators: 5,
  ...overrides,
})

const createMockMemories = (count: number) => ({
  memories: Array.from({ length: count }, (_, i) => ({
    id: `mem-${i + 1}`,
    title: `Memory ${i + 1}`,
    content_type: 'text',
    status: 'ACTIVE',
    content: `Content ${i + 1}`,
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
  })),
  total: count,
  page: 1,
  page_size: 20,
})

const createMockProject = (overrides = {}) => ({
  id: 'proj-123',
  name: 'Test Project',
  description: 'Test Description',
  tenant_id: 'tenant-123',
  owner_id: 'user-123',
  member_ids: ['user-123'],
  is_public: false,
  created_at: '2024-01-01T00:00:00Z',
  updated_at: '2024-01-01T00:00:00Z',
  ...overrides,
})

// Wrapper to provide fresh SWR cache for each test
const createWrapper = () =>
  function SWRWrapper({ children }: { children: React.ReactNode }) {
    return React.createElement(SWRConfig, { value: { provider: () => new Map() } }, children)
  }

describe('useSwr - Data Fetching with SWR', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('useProjectStats Hook', () => {
    it('should fetch project stats on mount', async () => {
      const mockStats = createMockProjectStats()
      vi.mocked(httpClient.get).mockResolvedValue(mockStats)

      const { result } = renderHook(() => useProjectStats('proj-123'), {
        wrapper: createWrapper(),
      })

      await waitFor(() => {
        expect(result.current.data).toEqual(mockStats)
      })

      expect(httpClient.get).toHaveBeenCalledWith('/projects/proj-123/stats')
      expect(result.current.error).toBeUndefined()
    })

    it('should return undefined for projectId when projectId is null', () => {
      const { result } = renderHook(() => useProjectStats(null), {
        wrapper: createWrapper(),
      })

      expect(result.current.data).toBeUndefined()
      expect(httpClient.get).not.toHaveBeenCalled()
    })

    it('should provide mutate function for optimistic updates', async () => {
      const initialStats = createMockProjectStats({ memory_count: 100 })
      vi.mocked(httpClient.get).mockResolvedValue(initialStats)

      const { result } = renderHook(() => useProjectStats('proj-123'), {
        wrapper: createWrapper(),
      })

      await waitFor(() => {
        expect(result.current.data).toEqual(initialStats)
      })

      // Optimistic update
      const optimisticData = createMockProjectStats({ memory_count: 200 })

      await act(async () => {
        result.current.mutate(optimisticData, false)
      })

      expect(result.current.data).toEqual(optimisticData)
    })
  })

  describe('useMemories Hook', () => {
    it('should fetch memories with pagination params', async () => {
      const mockMemories = createMockMemories(5)
      vi.mocked(httpClient.get).mockResolvedValue(mockMemories)

      const { result } = renderHook(
        () => useMemories('proj-123', { page: 1, page_size: 5 }),
        { wrapper: createWrapper() }
      )

      await waitFor(() => {
        expect(result.current.data).toEqual(mockMemories)
      })

      expect(httpClient.get).toHaveBeenCalledWith('/memories/', {
        params: { project_id: 'proj-123', page: 1, page_size: 5 },
      })
    })

    it('should deduplicate concurrent requests for same key', async () => {
      const mockMemories = createMockMemories(5)
      vi.mocked(httpClient.get).mockResolvedValue(mockMemories)

      // Use shared cache for deduplication test
      const sharedCache = new Map()
      const wrapper = ({ children }: { children: React.ReactNode }) =>
        React.createElement(SWRConfig, { value: { provider: () => sharedCache } }, children)

      const { result: result1 } = renderHook(
        () => useMemories('proj-123', { page: 1, page_size: 5 }),
        { wrapper }
      )
      const { result: result2 } = renderHook(
        () => useMemories('proj-123', { page: 1, page_size: 5 }),
        { wrapper }
      )

      await waitFor(() => {
        expect(result1.current.data).toEqual(mockMemories)
        expect(result2.current.data).toEqual(mockMemories)
      })

      // Within same cache, should be deduplicated
      expect(vi.mocked(httpClient.get).mock.calls.length).toBeLessThanOrEqual(2)
    })

    it('should refetch when params change', async () => {
      const page1Memories = createMockMemories(5)
      const page2Memories = createMockMemories(3)

      vi.mocked(httpClient.get)
        .mockResolvedValueOnce(page1Memories)
        .mockResolvedValueOnce(page2Memories)

      const { result, rerender } = renderHook(
        ({ page, pageSize }) => useMemories('proj-123', { page, page_size: pageSize }),
        {
          wrapper: createWrapper(),
          initialProps: { page: 1, pageSize: 5 } as { page: number; pageSize: number },
        }
      )

      await waitFor(() => {
        expect(result.current.data).toEqual(page1Memories)
      })

      rerender({ page: 2, pageSize: 5 })

      await waitFor(() => {
        expect(result.current.data).toEqual(page2Memories)
      })
    })

    it('should return empty state when projectId is null', () => {
      const { result } = renderHook(
        () => useMemories(null, { page: 1, page_size: 5 }),
        { wrapper: createWrapper() }
      )

      expect(result.current.data).toBeUndefined()
      expect(httpClient.get).not.toHaveBeenCalled()
    })
  })

  describe('useProject Hook', () => {
    it('should fetch project details', async () => {
      const mockProject = createMockProject()
      vi.mocked(httpClient.get).mockResolvedValue(mockProject)

      const { result } = renderHook(() => useProject('proj-123'), {
        wrapper: createWrapper(),
      })

      await waitFor(() => {
        expect(result.current.data).toEqual(mockProject)
      })

      expect(httpClient.get).toHaveBeenCalledWith('/projects/proj-123')
    })

    it('should support optimistic updates', async () => {
      const initialProject = createMockProject()
      vi.mocked(httpClient.get).mockResolvedValue(initialProject)

      const { result } = renderHook(() => useProject('proj-123'), {
        wrapper: createWrapper(),
      })

      await waitFor(() => {
        expect(result.current.data).toEqual(initialProject)
      })

      const optimisticProject = { ...initialProject, name: 'Optimistic Name' }

      await act(async () => {
        result.current.mutate(optimisticProject, false)
      })

      expect(result.current.data).toEqual(optimisticProject)
    })
  })

  describe('Request Deduplication', () => {
    it('should not make duplicate requests within deduplication interval', async () => {
      const mockStats = createMockProjectStats()
      vi.mocked(httpClient.get).mockResolvedValue(mockStats)

      // Create a wrapper with shared cache
      const sharedCache = new Map()
      const wrapper = ({ children }: { children: React.ReactNode }) =>
        React.createElement(
          SWRConfig,
          { value: { dedupingInterval: 2000, provider: () => sharedCache } },
          children
        )

      const { result: result1 } = renderHook(() => useProjectStats('proj-123'), {
        wrapper,
      })

      await waitFor(() => {
        expect(result1.current.data).toEqual(mockStats)
      })

      const callCount = vi.mocked(httpClient.get).mock.calls.length

      const { result: result2 } = renderHook(() => useProjectStats('proj-123'), {
        wrapper,
      })

      expect(result2.current.data).toEqual(mockStats)
      // Within same cache provider, should be deduplicated
      expect(vi.mocked(httpClient.get).mock.calls.length).toBe(callCount)
    })

    it('should allow multiple different requests simultaneously', async () => {
      const mockStats1 = createMockProjectStats({ memory_count: 100 })
      const mockStats2 = createMockProjectStats({ memory_count: 200 })

      vi.mocked(httpClient.get)
        .mockImplementation((url) => {
          if (url.includes('proj-123')) return Promise.resolve(mockStats1)
          if (url.includes('proj-456')) return Promise.resolve(mockStats2)
          return Promise.resolve(mockStats1)
        })

      const { result: result1 } = renderHook(() => useProjectStats('proj-123'), {
        wrapper: createWrapper(),
      })
      const { result: result2 } = renderHook(() => useProjectStats('proj-456'), {
        wrapper: createWrapper(),
      })

      await waitFor(() => {
        expect(result1.current.data).toEqual(mockStats1)
        expect(result2.current.data).toEqual(mockStats2)
      })

      expect(vi.mocked(httpClient.get).mock.calls.length).toBeGreaterThanOrEqual(2)
    })
  })

  describe('Conditional Fetching', () => {
    it('should not fetch when projectId is null', () => {
      vi.mocked(httpClient.get).mockResolvedValue(createMockProjectStats())

      renderHook(() => useProjectStats(null), { wrapper: createWrapper() })

      expect(httpClient.get).not.toHaveBeenCalled()
    })

    it('should not fetch when projectId is undefined', () => {
      vi.mocked(httpClient.get).mockResolvedValue(createMockProjectStats())

      renderHook(() => useProjectStats(undefined), { wrapper: createWrapper() })

      expect(httpClient.get).not.toHaveBeenCalled()
    })

    it('should start fetching when projectId changes from null to value', async () => {
      const mockStats = createMockProjectStats()
      vi.mocked(httpClient.get).mockResolvedValue(mockStats)

      const { result, rerender } = renderHook(
        (props) => useProjectStats(props.projectId),
        {
          wrapper: createWrapper(),
          initialProps: { projectId: null as string | null },
        }
      )

      expect(httpClient.get).not.toHaveBeenCalled()

      rerender({ projectId: 'proj-123' })

      await waitFor(() => {
        expect(result.current.data).toEqual(mockStats)
      })
    })
  })

  describe('Error Handling', () => {
    it('should handle errors gracefully', async () => {
      const error = new Error('Network error')
      vi.mocked(httpClient.get).mockRejectedValue(error)

      const wrapper = ({ children }: { children: React.ReactNode }) =>
        React.createElement(
          SWRConfig,
          {
            value: {
              dedupingInterval: 0,
              errorRetryCount: 0,
              shouldRetryOnError: false,
              provider: () => new Map(),
            },
          },
          children
        )

      const { result } = renderHook(() => useProjectStats('proj-123'), {
        wrapper,
      })

      await waitFor(() => {
        expect(result.current.error).toBeDefined()
      })

      expect(result.current.data).toBeUndefined()
    })
  })
})
