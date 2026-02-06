/**
 * SWR Schema Hooks Tests
 *
 * Basic tests for SWR-based schema data fetching hooks.
 * Full async testing requires more complex setup - these tests verify the hooks are properly defined.
 */

import { renderHook } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';

import { schemaAPI } from '@/services/api';

import { useEntityTypes, useEdgeTypes, useEdgeMaps, useSchemaData } from '@/hooks/useSwr';

// Mock the API service
vi.mock('@/services/api', () => ({
  schemaAPI: {
    listEntityTypes: vi.fn(),
    listEdgeTypes: vi.fn(),
    listEdgeMaps: vi.fn(),
  },
}));

describe('useEntityTypes', () => {
  it('should return initial loading state', () => {
    vi.mocked(schemaAPI.listEntityTypes).mockResolvedValue([]);

    const { result } = renderHook(() => useEntityTypes('proj-123'));

    expect(result.current.isLoading).toBe(true);
    expect(result.current.data).toBeUndefined();
    expect(typeof result.current.mutate).toBe('function');
  });

  it('should not fetch when projectId is null', () => {
    const { result } = renderHook(() => useEntityTypes(null));

    expect(result.current.isLoading).toBe(false);
    expect(schemaAPI.listEntityTypes).not.toHaveBeenCalled();
  });
});

describe('useEdgeTypes', () => {
  it('should return initial loading state', () => {
    vi.mocked(schemaAPI.listEdgeTypes).mockResolvedValue([]);

    const { result } = renderHook(() => useEdgeTypes('proj-123'));

    expect(result.current.isLoading).toBe(true);
    expect(typeof result.current.mutate).toBe('function');
  });
});

describe('useEdgeMaps', () => {
  it('should return initial loading state', () => {
    vi.mocked(schemaAPI.listEdgeMaps).mockResolvedValue([]);

    const { result } = renderHook(() => useEdgeMaps('proj-123'));

    expect(result.current.isLoading).toBe(true);
    expect(typeof result.current.mutate).toBe('function');
  });
});

describe('useSchemaData', () => {
  it('should provide mutate functions for all data types', () => {
    vi.mocked(schemaAPI.listEntityTypes).mockResolvedValue([]);
    vi.mocked(schemaAPI.listEdgeTypes).mockResolvedValue([]);
    vi.mocked(schemaAPI.listEdgeMaps).mockResolvedValue([]);

    const { result } = renderHook(() => useSchemaData('proj-123'));

    expect(typeof result.current.mutate.entities).toBe('function');
    expect(typeof result.current.mutate.edges).toBe('function');
    expect(typeof result.current.mutate.mappings).toBe('function');
  });
});
