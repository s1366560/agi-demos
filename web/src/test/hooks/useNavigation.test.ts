/**
 * useNavigation Hook Tests
 */

import { renderHook } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { useNavigation } from '@/hooks/useNavigation';

const mockNavigate = vi.fn();
const mockLocation = {
  pathname: '/tenant/test-tenant/project/proj-123/memories',
  search: '',
  hash: '',
  state: null,
  key: 'test',
};

vi.mock('react-router-dom', () => ({
  useNavigate: () => mockNavigate,
  useLocation: () => mockLocation,
}));

describe('useNavigation', () => {
  describe('isActive', () => {
    it('should return true for canonical partial path matches', () => {
      const { result } = renderHook(() =>
        useNavigation('/tenant/test-tenant/project/proj-123')
      );

      expect(result.current.isActive('/memories')).toBe(true);
    });

    it('should return false for non-matching paths', () => {
      const { result } = renderHook(() =>
        useNavigation('/tenant/test-tenant/project/proj-123')
      );

      expect(result.current.isActive('/entities')).toBe(false);
    });

    it('should handle exact path matching', () => {
      const { result } = renderHook(() =>
        useNavigation('/tenant/test-tenant/project/proj-123')
      );

      expect(result.current.isActive('', true)).toBe(false);
      expect(result.current.isActive('/memories', true)).toBe(true);
    });

    it('should treat canonical absolute paths as pass-through targets', () => {
      const { result } = renderHook(() => useNavigation('/tenant/test-tenant'));

      expect(result.current.isActive('/tenant/test-tenant/project/proj-123/memories', true)).toBe(
        true
      );
    });

    it('should ignore query params in active-state checks for dynamic routes', () => {
      mockLocation.pathname = '/tenant/test-tenant/project/proj-123/blackboard';
      mockLocation.search = '?workspaceId=ws-1';

      const { result } = renderHook(() =>
        useNavigation('/tenant/test-tenant/project/proj-123')
      );

      expect(result.current.isActive('blackboard?workspaceId=ws-1')).toBe(true);

      mockLocation.pathname = '/tenant/test-tenant/project/proj-123/memories';
      mockLocation.search = '';
    });
  });

  describe('getLink', () => {
    it('should prepend the base path to relative paths', () => {
      const { result } = renderHook(() =>
        useNavigation('/tenant/test-tenant/project/proj-123')
      );

      expect(result.current.getLink('/entities')).toBe('/tenant/test-tenant/project/proj-123/entities');
    });

    it('should handle empty paths', () => {
      const { result } = renderHook(() =>
        useNavigation('/tenant/test-tenant/project/proj-123')
      );

      expect(result.current.getLink('')).toBe('/tenant/test-tenant/project/proj-123');
    });

    it('should handle relative paths without a leading slash', () => {
      const { result } = renderHook(() =>
        useNavigation('/tenant/test-tenant/project/proj-123/agent')
      );

      expect(result.current.getLink('logs')).toBe('/tenant/test-tenant/project/proj-123/agent/logs');
    });

    it('should preserve canonical absolute paths unchanged', () => {
      const { result } = renderHook(() => useNavigation('/tenant/test-tenant'));

      expect(result.current.getLink('/tenant/other-tenant/projects')).toBe('/tenant/other-tenant/projects');
    });
  });

  describe('exposed router values', () => {
    it('should expose navigate function', () => {
      const { result } = renderHook(() => useNavigation('/tenant/test-tenant'));

      expect(typeof result.current.navigate).toBe('function');
    });

    it('should expose location', () => {
      const { result } = renderHook(() => useNavigation('/tenant/test-tenant'));

      expect(result.current.location.pathname).toBe(
        '/tenant/test-tenant/project/proj-123/memories'
      );
    });
  });

  describe('edge cases', () => {
    it('should handle trailing slashes correctly', () => {
      mockLocation.pathname = '/tenant/test-tenant/project/proj-123/';
      const { result } = renderHook(() =>
        useNavigation('/tenant/test-tenant/project/proj-123')
      );

      expect(result.current.isActive('', true)).toBe(true);
      expect(result.current.isActive('', false)).toBe(true);

      mockLocation.pathname = '/tenant/test-tenant/project/proj-123/memories';
    });

    it('should handle deeply nested paths', () => {
      mockLocation.pathname = '/tenant/test-tenant/project/proj-123/memories/abc-123';
      const { result } = renderHook(() =>
        useNavigation('/tenant/test-tenant/project/proj-123')
      );

      expect(result.current.isActive('/memories')).toBe(true);
      expect(result.current.isActive('/memories', true)).toBe(false);

      mockLocation.pathname = '/tenant/test-tenant/project/proj-123/memories';
    });
  });
});
