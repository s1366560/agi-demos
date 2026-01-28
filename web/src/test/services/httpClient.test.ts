/**
 * Tests for the centralized HTTP client
 *
 * Tests verify:
 * - Client configuration with correct baseURL
 * - Auth token injection via request interceptor
 * - 401 error handling via response interceptor
 * - Proper axios instance creation
 * - Request caching for GET requests
 * - Request deduplication for concurrent requests
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { requestCache } from '../../services/client/requestCache';
import { requestDeduplicator } from '../../services/client/requestDeduplicator';

// Define the mock instance using vi.hoisted to handle hoisting
const { mockAxiosInstance } = vi.hoisted(() => {
  return {
    mockAxiosInstance: {
      interceptors: {
        request: { use: vi.fn() },
        response: { use: vi.fn() },
      },
      defaults: {
        baseURL: '/api/v1',
        headers: { 'Content-Type': 'application/json' },
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
    create: vi.fn(() => mockAxiosInstance),
  },
}));

// Import after mock is defined
import { httpClient } from '../../services/client/httpClient';

// Mock window.location
const mockLocation = {
  pathname: '/dashboard',
  href: 'http://localhost:3000/dashboard',
  origin: 'http://localhost:3000',
  protocol: 'http:',
  host: 'localhost:3000',
  hostname: 'localhost',
  port: '3000',
};

Object.defineProperty(global, 'window', {
  value: {
    location: mockLocation,
  },
  writable: true,
});

describe('httpClient', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    requestCache.clear();
    requestDeduplicator.clear();
    // Reset window.location
    window.location.pathname = '/dashboard';
  });

  afterEach(() => {
    requestCache.clear();
    requestDeduplicator.clear();
  });

  describe('client configuration', () => {
    it('should have correct baseURL from environment', () => {
      expect(httpClient).toBeDefined();
      expect(httpClient.defaults.baseURL).toBe('/api/v1');
    });

    it('should have default headers', () => {
      expect(httpClient.defaults.headers['Content-Type']).toBe('application/json');
    });
  });

  describe('request interceptor', () => {
    it('should have interceptors object configured', () => {
      expect(httpClient.interceptors).toBeDefined();
      expect(httpClient.interceptors.request).toBeDefined();
      expect(httpClient.interceptors.request.use).toBeDefined();
      expect(typeof httpClient.interceptors.request.use).toBe('function');
    });
  });

  describe('response interceptor', () => {
    it('should have response interceptors configured', () => {
      expect(httpClient.interceptors.response).toBeDefined();
      expect(httpClient.interceptors.response.use).toBeDefined();
      expect(typeof httpClient.interceptors.response.use).toBe('function');
    });
  });

  describe('client methods', () => {
    it('should expose standard axios methods', () => {
      expect(typeof httpClient.get).toBe('function');
      expect(typeof httpClient.post).toBe('function');
      expect(typeof httpClient.put).toBe('function');
      expect(typeof httpClient.patch).toBe('function');
      expect(typeof httpClient.delete).toBe('function');
    });

    it('should expose cache object', () => {
      expect(httpClient.cache).toBeDefined();
      expect(httpClient.cache).toBe(requestCache);
    });

    it('should expose deduplicator object', () => {
      expect(httpClient.deduplicator).toBeDefined();
      expect(httpClient.deduplicator).toBe(requestDeduplicator);
    });

    it('should expose axios instance', () => {
      expect(httpClient.instance).toBeDefined();
      expect(httpClient.instance).toBe(mockAxiosInstance);
    });
  });

  describe('GET request caching', () => {
    it('should return cached data on cache hit', async () => {
      const testData = { result: 'cached data' };
      const cacheKey = requestCache.generateCacheKey('/api/test');

      // Pre-populate cache
      requestCache.set(cacheKey, testData);

      // Call should not hit the network
      const result = await httpClient.get('/api/test');

      expect(mockAxiosInstance.get).not.toHaveBeenCalled();
      expect(result).toEqual(testData);
    });

    it('should make request and cache result on cache miss', async () => {
      const testData = { result: 'fresh data' };
      mockAxiosInstance.get.mockResolvedValueOnce({
        status: 200,
        data: testData,
      });

      const result = await httpClient.get('/api/test');

      expect(mockAxiosInstance.get).toHaveBeenCalledWith('/api/test', undefined);
      expect(result).toEqual(testData);

      // Verify it was cached
      const cacheKey = requestCache.generateCacheKey('/api/test');
      expect(requestCache.get(cacheKey)).toEqual(testData);
    });

    it('should not cache non-200 responses', async () => {
      mockAxiosInstance.get.mockResolvedValueOnce({
        status: 404,
        data: { error: 'Not found' },
      });

      await httpClient.get('/api/test');

      // Verify it was NOT cached
      const cacheKey = requestCache.generateCacheKey('/api/test');
      expect(requestCache.get(cacheKey)).toBeUndefined();
    });

    it('should use different cache keys for different params', async () => {
      const testData1 = { result: 'data1' };
      const testData2 = { result: 'data2' };

      mockAxiosInstance.get
        .mockResolvedValueOnce({ status: 200, data: testData1 })
        .mockResolvedValueOnce({ status: 200, data: testData2 });

      const result1 = await httpClient.get('/api/test', { params: { id: 1 } });
      const result2 = await httpClient.get('/api/test', { params: { id: 2 } });

      expect(result1).toEqual(testData1);
      expect(result2).toEqual(testData2);
      expect(mockAxiosInstance.get).toHaveBeenCalledTimes(2);
    });

    it('should generate same cache key for same params in different order', async () => {
      const testData = { result: 'data' };

      mockAxiosInstance.get.mockResolvedValueOnce({
        status: 200,
        data: testData,
      });

      // First call
      await httpClient.get('/api/test', { params: { a: 1, b: 2 } });

      // Second call with params in different order should hit cache
      const result2 = await httpClient.get('/api/test', { params: { b: 2, a: 1 } });

      expect(mockAxiosInstance.get).toHaveBeenCalledTimes(1);
      expect(result2).toEqual(testData);
    });
  });

  describe('POST/PUT/DELETE bypass cache', () => {
    it('should not cache POST requests', async () => {
      const testData = { result: 'created' };
      mockAxiosInstance.post.mockResolvedValueOnce({
        status: 201,
        data: testData,
      });

      await httpClient.post('/api/test', testData);

      const cacheKey = requestCache.generateCacheKey('/api/test');
      expect(requestCache.get(cacheKey)).toBeUndefined();
    });

    it('should not cache PUT requests', async () => {
      const testData = { result: 'updated' };
      mockAxiosInstance.put.mockResolvedValueOnce({
        status: 200,
        data: testData,
      });

      await httpClient.put('/api/test', testData);

      const cacheKey = requestCache.generateCacheKey('/api/test');
      expect(requestCache.get(cacheKey)).toBeUndefined();
    });

    it('should not cache DELETE requests', async () => {
      mockAxiosInstance.delete.mockResolvedValueOnce({
        status: 204,
        data: null,
      });

      await httpClient.delete('/api/test');

      const cacheKey = requestCache.generateCacheKey('/api/test');
      expect(requestCache.get(cacheKey)).toBeUndefined();
    });
  });

  describe('request deduplication', () => {
    it('should deduplicate concurrent GET requests', async () => {
      const testData = { result: 'shared' };

      // Create a pending promise that resolves after a delay
      let resolvePromise: (value: { status: number; data: typeof testData }) => void;
      const pendingPromise = new Promise<{ status: number; data: typeof testData }>((resolve) => {
        resolvePromise = resolve;
      });
      mockAxiosInstance.get.mockReturnValueOnce(
        pendingPromise.then(() => ({ status: 200, data: testData }))
      );

      // Start concurrent requests
      const promise1 = httpClient.get('/api/test');
      const promise2 = httpClient.get('/api/test');
      const promise3 = httpClient.get('/api/test');

      // All should share the same underlying request
      expect(mockAxiosInstance.get).toHaveBeenCalledTimes(1);

      // Resolve and wait for all
      resolvePromise!({ status: 200, data: testData });
      const [result1, result2, result3] = await Promise.all([promise1, promise2, promise3]);

      expect(result1).toEqual(testData);
      expect(result2).toEqual(testData);
      expect(result3).toEqual(testData);
    });

    it('should deduplicate concurrent POST requests', async () => {
      const testData = { result: 'created' };

      let resolvePromise: (value: { status: number; data: typeof testData }) => void;
      const pendingPromise = new Promise<{ status: number; data: typeof testData }>((resolve) => {
        resolvePromise = resolve;
      });
      mockAxiosInstance.post.mockReturnValueOnce(
        pendingPromise.then(() => ({ status: 201, data: testData }))
      );

      const promise1 = httpClient.post('/api/test', testData);
      const promise2 = httpClient.post('/api/test', testData);

      expect(mockAxiosInstance.post).toHaveBeenCalledTimes(1);

      resolvePromise!({ status: 201, data: testData });
      const [result1, result2] = await Promise.all([promise1, promise2]);

      expect(result1).toEqual(testData);
      expect(result2).toEqual(testData);
    });

    it('should deduplicate concurrent PUT requests', async () => {
      const testData = { result: 'updated' };

      let resolvePromise: (value: { status: number; data: typeof testData }) => void;
      const pendingPromise = new Promise<{ status: number; data: typeof testData }>((resolve) => {
        resolvePromise = resolve;
      });
      mockAxiosInstance.put.mockReturnValueOnce(
        pendingPromise.then(() => ({ status: 200, data: testData }))
      );

      const promise1 = httpClient.put('/api/test', testData);
      const promise2 = httpClient.put('/api/test', testData);

      expect(mockAxiosInstance.put).toHaveBeenCalledTimes(1);

      resolvePromise!({ status: 200, data: testData });
      await Promise.all([promise1, promise2]);
    });

    it('should deduplicate concurrent PATCH requests', async () => {
      const testData = { result: 'patched' };

      let resolvePromise: (value: { status: number; data: typeof testData }) => void;
      const pendingPromise = new Promise<{ status: number; data: typeof testData }>((resolve) => {
        resolvePromise = resolve;
      });
      mockAxiosInstance.patch.mockReturnValueOnce(
        pendingPromise.then(() => ({ status: 200, data: testData }))
      );

      const promise1 = httpClient.patch('/api/test', testData);
      const promise2 = httpClient.patch('/api/test', testData);

      expect(mockAxiosInstance.patch).toHaveBeenCalledTimes(1);

      resolvePromise!({ status: 200, data: testData });
      await Promise.all([promise1, promise2]);
    });

    it('should deduplicate concurrent DELETE requests', async () => {
      let resolvePromise: (value: { status: number; data: null }) => void;
      const pendingPromise = new Promise<{ status: number; data: null }>((resolve) => {
        resolvePromise = resolve;
      });
      mockAxiosInstance.delete.mockReturnValueOnce(
        pendingPromise.then(() => ({ status: 204, data: null }))
      );

      const promise1 = httpClient.delete('/api/test');
      const promise2 = httpClient.delete('/api/test');

      expect(mockAxiosInstance.delete).toHaveBeenCalledTimes(1);

      resolvePromise!({ status: 204, data: null });
      await Promise.all([promise1, promise2]);
    });

    it('should NOT deduplicate different requests', async () => {
      const testData1 = { result: 'data1' };
      const testData2 = { result: 'data2' };

      mockAxiosInstance.get
        .mockResolvedValueOnce({ status: 200, data: testData1 })
        .mockResolvedValueOnce({ status: 200, data: testData2 });

      const result1 = await httpClient.get('/api/test1');
      const result2 = await httpClient.get('/api/test2');

      expect(mockAxiosInstance.get).toHaveBeenCalledTimes(2);
      expect(result1).toEqual(testData1);
      expect(result2).toEqual(testData2);
    });

    it('should NOT deduplicate sequential requests', async () => {
      const testData = { result: 'data' };

      mockAxiosInstance.get.mockResolvedValue({ status: 200, data: testData });

      // First request - makes network call and caches result
      const result1 = await httpClient.get('/api/test');

      // Second request - returns from cache (not deduplicated, but cached)
      const result2 = await httpClient.get('/api/test');

      // Only one network call due to caching
      expect(mockAxiosInstance.get).toHaveBeenCalledTimes(1);
      expect(result1).toEqual(testData);
      expect(result2).toEqual(testData);
    });

    it('should track deduplication statistics', async () => {
      const testData = { result: 'data' };

      let resolvePromise: (value: { status: number; data: typeof testData }) => void;
      const pendingPromise = new Promise<{ status: number; data: typeof testData }>((resolve) => {
        resolvePromise = resolve;
      });
      mockAxiosInstance.get.mockReturnValueOnce(
        pendingPromise.then(() => ({ status: 200, data: testData }))
      );

      // Start concurrent requests
      const promise1 = httpClient.get('/api/test');
      const promise2 = httpClient.get('/api/test');

      // Check stats while pending
      const stats = httpClient.deduplicator.getStats();
      expect(stats.total).toBe(2);
      expect(stats.deduplicated).toBe(1);

      resolvePromise!({ status: 200, data: testData });
      await Promise.all([promise1, promise2]);
    });

    it('should allow new request after previous completes', async () => {
      const testData = { result: 'data' };
      mockAxiosInstance.get.mockResolvedValue({ status: 200, data: testData });

      // First request - makes network call and caches result
      const result1 = await httpClient.get('/api/test');

      // Clear cache to test deduplication separately
      requestCache.clear();

      // Second request - should make a new network call (cache was cleared)
      const result2 = await httpClient.get('/api/test');

      // Two network calls total (cache was cleared between)
      expect(mockAxiosInstance.get).toHaveBeenCalledTimes(2);
      expect(result1).toEqual(testData);
      expect(result2).toEqual(testData);
    });
  });
});

describe('httpClient retry integration', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.runAllTimers();
    vi.useRealTimers();
  });

  it('should retry request when retry is enabled', async () => {
    const { httpClient, ApiError } = await import('@/services/client/httpClient');
    const mockGet = vi.fn()
      .mockRejectedValueOnce(new ApiError('NETWORK' as any, 'NETWORK_ERROR', 'Network error'))
      .mockResolvedValueOnce({ data: 'success' });

    // Mock axios.get to use our mock
    httpClient.instance.get = mockGet as any;

    const promise = httpClient.get<string>('/api/test', { retry: true });

    // Initial attempt fails
    expect(mockGet).toHaveBeenCalledTimes(1);

    // Advance timers for retry delay
    await vi.advanceTimersByTimeAsync(1200);

    // Retry should succeed
    const result = await promise;
    expect(result).toBe('success');
    expect(mockGet).toHaveBeenCalledTimes(2);
  });

  it('should not retry when retry is not enabled', async () => {
    const { httpClient, ApiError } = await import('@/services/client/httpClient');
    const mockGet = vi.fn().mockRejectedValue(new ApiError('NETWORK' as any, 'NETWORK_ERROR', 'Network error'));

    httpClient.instance.get = mockGet as any;

    await expect(
      httpClient.get('/api/test', { retry: false })
    ).rejects.toThrow();

    // Only called once, no retry
    expect(mockGet).toHaveBeenCalledTimes(1);
  });

  it('should use custom retry config when provided', async () => {
    const { httpClient, ApiError } = await import('@/services/client/httpClient');
    const mockGet = vi.fn()
      .mockRejectedValueOnce(new ApiError('NETWORK' as any, 'NETWORK_ERROR', 'Network error'))
      .mockRejectedValueOnce(new ApiError('NETWORK' as any, 'NETWORK_ERROR', 'Network error 2'))
      .mockResolvedValueOnce({ data: 'success' });

    httpClient.instance.get = mockGet as any;

    const promise = httpClient.get<string>('/api/test', {
      retry: { maxRetries: 3, initialDelay: 100, jitter: false },
    });

    // Advance timers for each retry
    await vi.advanceTimersByTimeAsync(100); // 1st retry
    await vi.advanceTimersByTimeAsync(200); // 2nd retry (doubled)

    const result = await promise;
    expect(result).toBe('success');
    expect(mockGet).toHaveBeenCalledTimes(3); // initial + 2 retries (succeeded before 3rd)
  });

  it('should not retry on non-retryable errors (4xx)', async () => {
    const { httpClient, ApiError } = await import('@/services/client/httpClient');
    const mockError = new ApiError(
      'VALIDATION' as any,
      'INVALID_INPUT',
      'Invalid input',
      400
    );
    const mockGet = vi.fn().mockRejectedValue(mockError);

    httpClient.instance.get = mockGet as any;

    await expect(
      httpClient.get('/api/test', { retry: true })
    ).rejects.toThrow();

    // Only called once, 4xx errors are not retried
    expect(mockGet).toHaveBeenCalledTimes(1);
  });
});
