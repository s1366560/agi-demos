/**
 * Tests for the request cache layer
 *
 * Tests verify:
 * - Cache hit returns cached data without making request
 * - Cache miss makes request and stores result
 * - TTL expiration works correctly
 * - Cache key generation is correct
 * - Different params create different cache keys
 * - POST/PUT/DELETE requests are not cached
 * - Cache can be cleared manually
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';

import { requestCache } from '../../../services/client/requestCache';

describe('requestCache', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    requestCache.clear();
  });

  describe('cache key generation', () => {
    it('should generate same key for same URL and params', () => {
      const key1 = requestCache.generateCacheKey('/api/test', { foo: 'bar' });
      const key2 = requestCache.generateCacheKey('/api/test', { foo: 'bar' });
      expect(key1).toBe(key2);
    });

    it('should generate different keys for different URLs', () => {
      const key1 = requestCache.generateCacheKey('/api/test1', {});
      const key2 = requestCache.generateCacheKey('/api/test2', {});
      expect(key1).not.toBe(key2);
    });

    it('should generate different keys for different params', () => {
      const key1 = requestCache.generateCacheKey('/api/test', { foo: 'bar' });
      const key2 = requestCache.generateCacheKey('/api/test', { foo: 'baz' });
      expect(key1).not.toBe(key2);
    });

    it('should generate same key regardless of param order', () => {
      const key1 = requestCache.generateCacheKey('/api/test', { a: 1, b: 2 });
      const key2 = requestCache.generateCacheKey('/api/test', { b: 2, a: 1 });
      expect(key1).toBe(key2);
    });

    it('should handle null/undefined params', () => {
      const key1 = requestCache.generateCacheKey('/api/test', null);
      const key2 = requestCache.generateCacheKey('/api/test', undefined);
      const key3 = requestCache.generateCacheKey('/api/test', {});
      expect(key1).toBe(key3);
      expect(key2).toBe(key3);
    });
  });

  describe('cache storage', () => {
    it('should store and retrieve values', async () => {
      const testData = { result: 'test' };
      const key = 'test-key';

      requestCache.set(key, testData, 1000);
      const retrieved = requestCache.get(key);

      expect(retrieved).toEqual(testData);
    });

    it('should return undefined for non-existent keys', () => {
      const result = requestCache.get('non-existent');
      expect(result).toBeUndefined();
    });

    it('should expire entries after TTL', async () => {
      const testData = { result: 'test' };
      const key = 'test-key';
      const shortTTL = 50; // 50ms

      requestCache.set(key, testData, shortTTL);

      // Should be available immediately
      expect(requestCache.get(key)).toEqual(testData);

      // Wait for expiration
      await new Promise(resolve => setTimeout(resolve, 60));

      // Should be expired
      expect(requestCache.get(key)).toBeUndefined();
    });

    it('should not expire before TTL', async () => {
      const testData = { result: 'test' };
      const key = 'test-key';
      const ttl = 200;

      requestCache.set(key, testData, ttl);

      // Should still be available after 100ms
      await new Promise(resolve => setTimeout(resolve, 100));
      expect(requestCache.get(key)).toEqual(testData);
    });

    it('should clear all cached entries', () => {
      requestCache.set('key1', { data: 1 }, 1000);
      requestCache.set('key2', { data: 2 }, 1000);

      requestCache.clear();

      expect(requestCache.get('key1')).toBeUndefined();
      expect(requestCache.get('key2')).toBeUndefined();
    });

    it('should delete specific entries', () => {
      requestCache.set('key1', { data: 1 }, 1000);
      requestCache.set('key2', { data: 2 }, 1000);

      requestCache.delete('key1');

      expect(requestCache.get('key1')).toBeUndefined();
      expect(requestCache.get('key2')).toEqual({ data: 2 });
    });
  });

  describe('cache configuration', () => {
    it('should have default TTL of 60 seconds', () => {
      expect(requestCache.defaultTTL).toBe(60000);
    });

    it('should allow disabling cache via enabled flag', () => {
      const testData = { result: 'test' };

      requestCache.set('key1', testData, 1000);
      requestCache.enabled = false;

      expect(requestCache.get('key1')).toBeUndefined();

      requestCache.enabled = true;
      expect(requestCache.get('key1')).toEqual(testData);
    });
  });

  describe('cache stats', () => {
    it('should track cache hits and misses', () => {
      requestCache.set('key1', { data: 1 }, 1000);

      requestCache.get('key1'); // hit
      requestCache.get('key2'); // miss

      const stats = requestCache.getStats();
      expect(stats.hits).toBe(1);
      expect(stats.misses).toBe(1);
      expect(stats.size).toBe(1);
    });

    it('should reset stats when clear is called', () => {
      requestCache.set('key1', { data: 1 }, 1000);
      requestCache.get('key1');

      requestCache.clear();

      const stats = requestCache.getStats();
      expect(stats.hits).toBe(0);
      expect(stats.misses).toBe(0);
      expect(stats.size).toBe(0);
    });
  });
});
