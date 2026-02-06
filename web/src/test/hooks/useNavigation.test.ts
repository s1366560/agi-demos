/**
 * useNavigation Hook Tests
 *
 * Tests for navigation utility hook.
 */

import { renderHook } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';

import { useNavigation } from '@/hooks/useNavigation';

// Mock react-router-dom
const mockNavigate = vi.fn();
const mockLocation = {
  pathname: '/tenant/test-tenant/projects',
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
    it('should return true for partial path match', () => {
      const { result } = renderHook(() => useNavigation('/tenant/test-tenant'));

      expect(result.current.isActive('/projects')).toBe(true);
    });

    it('should return false for non-matching paths', () => {
      const { result } = renderHook(() => useNavigation('/tenant/test-tenant'));

      expect(result.current.isActive('/users')).toBe(false);
    });

    it('should handle exact path matching', () => {
      const { result } = renderHook(() => useNavigation('/tenant/test-tenant'));

      // Current path is /tenant/test-tenant/projects
      // Empty path with exact should only match /tenant/test-tenant
      expect(result.current.isActive('', true)).toBe(false);
      expect(result.current.isActive('/projects', true)).toBe(true);
    });

    it('should handle empty path for exact base match', () => {
      // Override mock location for this test
      mockLocation.pathname = '/tenant/test-tenant';
      const { result } = renderHook(() => useNavigation('/tenant/test-tenant'));

      expect(result.current.isActive('', true)).toBe(true);

      // Reset
      mockLocation.pathname = '/tenant/test-tenant/projects';
    });
  });

  describe('getLink', () => {
    it('should prepend base path to relative path', () => {
      const { result } = renderHook(() => useNavigation('/tenant/test-tenant'));

      expect(result.current.getLink('/projects')).toBe('/tenant/test-tenant/projects');
    });

    it('should handle empty path', () => {
      const { result } = renderHook(() => useNavigation('/tenant/test-tenant'));

      expect(result.current.getLink('')).toBe('/tenant/test-tenant');
    });

    it('should handle paths starting with /', () => {
      const { result } = renderHook(() => useNavigation('/project/proj-123'));

      expect(result.current.getLink('/memories')).toBe('/project/proj-123/memories');
    });

    it('should handle paths without leading /', () => {
      const { result } = renderHook(() => useNavigation('/project/proj-123'));

      expect(result.current.getLink('memories')).toBe('/project/proj-123/memories');
    });
  });

  describe('navigate wrapper', () => {
    it('should expose navigate function', () => {
      const { result } = renderHook(() => useNavigation('/tenant/test-tenant'));

      expect(typeof result.current.navigate).toBe('function');
    });

    it('should expose location', () => {
      const { result } = renderHook(() => useNavigation('/tenant/test-tenant'));

      expect(result.current.location).toBeDefined();
      expect(result.current.location.pathname).toBe('/tenant/test-tenant/projects');
    });
  });

  describe('edge cases', () => {
    it('should handle trailing slashes correctly', () => {
      mockLocation.pathname = '/project/proj-123/';
      const { result } = renderHook(() => useNavigation('/project/proj-123'));

      expect(result.current.isActive('', true)).toBe(true);
      expect(result.current.isActive('', false)).toBe(true);

      // Reset
      mockLocation.pathname = '/tenant/test-tenant/projects';
    });

    it('should handle deeply nested paths', () => {
      mockLocation.pathname = '/project/proj-123/memories/123';
      const { result } = renderHook(() => useNavigation('/project/proj-123'));

      expect(result.current.isActive('/memories')).toBe(true);
      expect(result.current.isActive('/memories', true)).toBe(false);

      // Reset
      mockLocation.pathname = '/tenant/test-tenant/projects';
    });

    it('should handle query parameters in location', () => {
      mockLocation.pathname = '/project/proj-123/memories';
      mockLocation.search = '?filter=recent';
      const { result } = renderHook(() => useNavigation('/project/proj-123'));

      expect(result.current.isActive('/memories')).toBe(true);

      // Reset
      mockLocation.pathname = '/tenant/test-tenant/projects';
      mockLocation.search = '';
    });
  });
});
