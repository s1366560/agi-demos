/**
 * Tests for Request Deduplicator
 *
 * Tests request deduplication to prevent duplicate concurrent requests.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';

import { requestDeduplicator } from '../../../services/client/requestDeduplicator';

describe('requestDeduplicator', () => {
  beforeEach(() => {
    requestDeduplicator.clear();
  });

  describe('deduplicateKey', () => {
    it('generates consistent keys for same method, url, and params', () => {
      const key1 = requestDeduplicator.deduplicateKey('GET', '/api/test', { id: '1' });
      const key2 = requestDeduplicator.deduplicateKey('GET', '/api/test', { id: '1' });
      expect(key1).toBe(key2);
    });

    it('generates different keys for different methods', () => {
      const key1 = requestDeduplicator.deduplicateKey('GET', '/api/test');
      const key2 = requestDeduplicator.deduplicateKey('POST', '/api/test');
      expect(key1).not.toBe(key2);
    });

    it('generates different keys for different URLs', () => {
      const key1 = requestDeduplicator.deduplicateKey('GET', '/api/test1');
      const key2 = requestDeduplicator.deduplicateKey('GET', '/api/test2');
      expect(key1).not.toBe(key2);
    });

    it('generates same key regardless of param order', () => {
      const key1 = requestDeduplicator.deduplicateKey('GET', '/api/test', { a: '1', b: '2' });
      const key2 = requestDeduplicator.deduplicateKey('GET', '/api/test', { b: '2', a: '1' });
      expect(key1).toBe(key2);
    });

    it('generates different keys for different params', () => {
      const key1 = requestDeduplicator.deduplicateKey('GET', '/api/test', { id: '1' });
      const key2 = requestDeduplicator.deduplicateKey('GET', '/api/test', { id: '2' });
      expect(key1).not.toBe(key2);
    });

    it('handles empty params correctly', () => {
      const key1 = requestDeduplicator.deduplicateKey('GET', '/api/test', {});
      const key2 = requestDeduplicator.deduplicateKey('GET', '/api/test');
      expect(key1).toBe(key2);
    });

    it('handles null params correctly', () => {
      const key1 = requestDeduplicator.deduplicateKey('GET', '/api/test', null);
      const key2 = requestDeduplicator.deduplicateKey('GET', '/api/test');
      expect(key1).toBe(key2);
    });

    it('handles undefined params correctly', () => {
      const key1 = requestDeduplicator.deduplicateKey('GET', '/api/test', undefined);
      const key2 = requestDeduplicator.deduplicateKey('GET', '/api/test');
      expect(key1).toBe(key2);
    });
  });

  describe('track and getPromise', () => {
    it('stores and retrieves a promise by key', () => {
      const key = 'GET-/api/test';
      const promise = Promise.resolve({ data: 'test' });

      requestDeduplicator.track(key, promise);
      const retrieved = requestDeduplicator.getPromise(key);

      expect(retrieved).toBe(promise);
    });

    it('returns undefined for non-existent key', () => {
      const retrieved = requestDeduplicator.getPromise('non-existent');
      expect(retrieved).toBeUndefined();
    });
  });

  describe('deduplicate - concurrent requests', () => {
    it('returns existing promise for identical concurrent request', async () => {
      const key = 'GET-/api/test';
      const originalPromise = Promise.resolve({ data: 'test' });

      requestDeduplicator.track(key, originalPromise);

      const mockExecutor = vi.fn().mockResolvedValue({ data: 'should not execute' });
      const result = await requestDeduplicator.deduplicate(key, mockExecutor);

      expect(result).toEqual({ data: 'test' });
      expect(mockExecutor).not.toHaveBeenCalled();
    });

    it('executes new function when no existing promise', async () => {
      const key = 'GET-/api/test';
      const mockExecutor = vi.fn().mockResolvedValue({ data: 'new result' });

      const result = await requestDeduplicator.deduplicate(key, mockExecutor);

      expect(result).toEqual({ data: 'new result' });
      expect(mockExecutor).toHaveBeenCalledTimes(1);
    });

    it('removes promise after successful completion', async () => {
      const key = 'GET-/api/test';
      const mockExecutor = vi.fn().mockResolvedValue({ data: 'test' });

      await requestDeduplicator.deduplicate(key, mockExecutor);

      const retrieved = requestDeduplicator.getPromise(key);
      expect(retrieved).toBeUndefined();
    });

    it('removes promise after failure', async () => {
      const key = 'GET-/api/test';
      const mockExecutor = vi.fn().mockRejectedValue(new Error('Request failed'));

      await expect(requestDeduplicator.deduplicate(key, mockExecutor)).rejects.toThrow(
        'Request failed'
      );

      const retrieved = requestDeduplicator.getPromise(key);
      expect(retrieved).toBeUndefined();
    });

    it('allows new request after previous one completes', async () => {
      const key = 'GET-/api/test';
      const mockExecutor1 = vi.fn().mockResolvedValue({ data: 'first' });
      const mockExecutor2 = vi.fn().mockResolvedValue({ data: 'second' });

      const result1 = await requestDeduplicator.deduplicate(key, mockExecutor1);
      const result2 = await requestDeduplicator.deduplicate(key, mockExecutor2);

      expect(result1).toEqual({ data: 'first' });
      expect(result2).toEqual({ data: 'second' });
      expect(mockExecutor1).toHaveBeenCalledTimes(1);
      expect(mockExecutor2).toHaveBeenCalledTimes(1);
    });

    it('handles multiple concurrent identical requests', async () => {
      const key = 'GET-/api/test';
      const mockExecutor = vi.fn().mockResolvedValue({ data: 'shared' });

      const promises = [
        requestDeduplicator.deduplicate(key, mockExecutor),
        requestDeduplicator.deduplicate(key, mockExecutor),
        requestDeduplicator.deduplicate(key, mockExecutor),
      ];

      const results = await Promise.all(promises);

      expect(results).toEqual([{ data: 'shared' }, { data: 'shared' }, { data: 'shared' }]);
      expect(mockExecutor).toHaveBeenCalledTimes(1);
    });
  });

  describe('statistics', () => {
    it('tracks deduplication statistics', async () => {
      const key = 'GET-/api/test';
      let resolveExecutor: (value: { data: string }) => void;
      const mockExecutor = vi.fn(
        () =>
          new Promise<{ data: string }>((resolve) => {
            resolveExecutor = resolve;
          })
      );

      // Start first request - not deduplicated, promise stays pending
      const firstPromise = requestDeduplicator.deduplicate(key, mockExecutor);

      // Start concurrent second request - should be deduplicated
      const secondPromise = requestDeduplicator.deduplicate(key, mockExecutor);

      // Check stats while both are pending
      const activeStats = requestDeduplicator.getStats();
      expect(activeStats.total).toBe(2);
      expect(activeStats.deduplicated).toBe(1);
      expect(activeStats.active).toBe(1);

      // Resolve the promise
      resolveExecutor!({ data: 'test' });

      // Wait for both to complete
      await firstPromise;
      await secondPromise;

      // After completion, active should be 0
      const stats = requestDeduplicator.getStats();
      expect(stats.total).toBe(2);
      expect(stats.deduplicated).toBe(1);
      expect(stats.active).toBe(0);
    });

    it('returns zero stats initially', () => {
      const stats = requestDeduplicator.getStats();
      expect(stats.total).toBe(0);
      expect(stats.deduplicated).toBe(0);
      expect(stats.active).toBe(0);
    });
  });

  describe('clear', () => {
    it('clears all tracked promises', () => {
      const key = 'GET-/api/test';
      const promise = Promise.resolve({ data: 'test' });

      requestDeduplicator.track(key, promise);
      requestDeduplicator.clear();

      const retrieved = requestDeduplicator.getPromise(key);
      expect(retrieved).toBeUndefined();
    });

    it('resets statistics', async () => {
      const key = 'GET-/api/test';
      const mockExecutor = vi.fn().mockResolvedValue({ data: 'test' });

      await requestDeduplicator.deduplicate(key, mockExecutor);
      requestDeduplicator.clear();

      const stats = requestDeduplicator.getStats();
      expect(stats.total).toBe(0);
      expect(stats.deduplicated).toBe(0);
      expect(stats.active).toBe(0);
    });
  });

  describe('delete', () => {
    it('removes specific tracked promise', () => {
      const key1 = 'GET-/api/test1';
      const key2 = 'GET-/api/test2';

      requestDeduplicator.track(key1, Promise.resolve({ data: 'test1' }));
      requestDeduplicator.track(key2, Promise.resolve({ data: 'test2' }));

      requestDeduplicator.delete(key1);

      expect(requestDeduplicator.getPromise(key1)).toBeUndefined();
      expect(requestDeduplicator.getPromise(key2)).toBeDefined();
    });
  });

  describe('keys', () => {
    it('returns all tracked keys', () => {
      const key1 = 'GET-/api/test1';
      const key2 = 'GET-/api/test2';

      requestDeduplicator.track(key1, Promise.resolve({ data: 'test1' }));
      requestDeduplicator.track(key2, Promise.resolve({ data: 'test2' }));

      const keys = requestDeduplicator.keys();
      expect(keys).toContain(key1);
      expect(keys).toContain(key2);
      expect(keys).toHaveLength(2);
    });
  });
});
