/**
 * Tests for API URL migration in components
 *
 * These tests verify that components use centralized URL utilities
 * instead of manually constructing URLs with /api/v1 prefix.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createApiUrl, createWebSocketUrl } from '../../services/client/urlUtils'

// Mock window.location for WebSocket URL tests
const mockLocation = {
  protocol: 'http:',
  host: 'localhost:3000',
  href: 'http://localhost:3000/',
  origin: 'http://localhost:3000',
  pathname: '/',
  search: '',
  hash: '',
  hostname: 'localhost',
  port: '3000',
  ancestorOrigins: {} as DOMStringList,
  assign: vi.fn(),
  reload: vi.fn(),
  replace: vi.fn(),
  toString: () => 'http://localhost:3000/',
}

describe('Component API URL Migration', () => {
  describe('createApiUrl', () => {
    it('should add /api/v1 prefix to relative paths', () => {
      expect(createApiUrl('/tasks/123/stream')).toBe('/api/v1/tasks/123/stream')
    })

    it('should handle paths without leading slash', () => {
      expect(createApiUrl('tasks/123/stream')).toBe('/api/v1/tasks/123/stream')
    })

    it('should handle root path', () => {
      expect(createApiUrl('')).toBe('/api/v1')
      expect(createApiUrl('/')).toBe('/api/v1')
    })

    it('should remove duplicate /api/v1 prefix', () => {
      expect(createApiUrl('/api/v1/tasks/123')).toBe('/api/v1/tasks/123')
      expect(createApiUrl('api/v1/tasks/123')).toBe('/api/v1/tasks/123')
    })
  })

  describe('createWebSocketUrl', () => {
    beforeEach(() => {
      // Mock window.location using vi.stubGlobal for proper typing
      vi.stubGlobal('location', { ...mockLocation })
    })

    afterEach(() => {
      // Restore original location
      vi.unstubAllGlobals()
    })

    it('should construct ws:// URL for http', () => {
      const result = createWebSocketUrl('/terminal/sandbox-123/ws')
      expect(result).toBe('ws://localhost:3000/api/v1/terminal/sandbox-123/ws')
    })

    it('should construct wss:// URL for https', () => {
      vi.stubGlobal('location', { ...mockLocation, protocol: 'https:', host: 'example.com' })

      const result = createWebSocketUrl('/terminal/sandbox-123/ws')
      expect(result).toBe('wss://example.com/api/v1/terminal/sandbox-123/ws')
    })

    it('should handle query parameters', () => {
      const result = createWebSocketUrl('/agent/ws', { token: 'abc123', session_id: 'sess-1' })
      expect(result).toBe('ws://localhost:3000/api/v1/agent/ws?token=abc123&session_id=sess-1')
    })

    it('should remove duplicate /api/v1 prefix from WebSocket URLs', () => {
      const result = createWebSocketUrl('/api/v1/terminal/sandbox-123/ws')
      expect(result).toBe('ws://localhost:3000/api/v1/terminal/sandbox-123/ws')
    })
  })
})
