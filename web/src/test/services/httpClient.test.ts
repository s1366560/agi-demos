import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

import { requestCache } from '../../services/client/requestCache';
import { requestDeduplicator } from '../../services/client/requestDeduplicator';

let capturedRequestInterceptor: ((config: Record<string, unknown>) => unknown) | null = null;
let capturedResponseInterceptor: ((response: unknown) => unknown) | null = null;

const { mockAxiosInstance } = vi.hoisted(() => {
  return {
    mockAxiosInstance: {
      interceptors: {
        request: {
          use: vi.fn(),
        },
        response: {
          use: vi.fn(),
        },
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

vi.mock('axios', () => ({
  default: {
    create: vi.fn(() => mockAxiosInstance),
  },
}));

vi.mock('@/utils/tokenResolver', () => ({
  getAuthToken: vi.fn(() => 'test-token'),
  clearAuthState: vi.fn(),
}));

vi.mock('../../services/client/ApiError', () => ({
  parseAxiosError: vi.fn((error: unknown) => error),
}));

import { httpClient, isNoAuthEndpoint } from '../../services/client/httpClient';
import { getAuthToken } from '@/utils/tokenResolver';

capturedRequestInterceptor = mockAxiosInstance.interceptors.request.use.mock.calls[0]?.[0] ?? null;
capturedResponseInterceptor =
  mockAxiosInstance.interceptors.response.use.mock.calls[0]?.[0] ?? null;

describe('httpClient', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    requestCache.clear();
    requestDeduplicator.clear();
  });

  afterEach(() => {
    requestCache.clear();
    requestDeduplicator.clear();
  });

  describe('client configuration', () => {
    it('should be defined with expected HTTP methods', () => {
      expect(httpClient).toBeDefined();
      expect(typeof httpClient.get).toBe('function');
      expect(typeof httpClient.post).toBe('function');
      expect(typeof httpClient.put).toBe('function');
      expect(typeof httpClient.patch).toBe('function');
      expect(typeof httpClient.delete).toBe('function');
    });

    it('should expose upload method', () => {
      expect(typeof httpClient.upload).toBe('function');
    });
  });

  describe('request interceptor', () => {
    it('should have captured the request interceptor function', () => {
      expect(capturedRequestInterceptor).toBeDefined();
      expect(typeof capturedRequestInterceptor).toBe('function');
    });

    it('should inject auth token into request headers', () => {
      expect(capturedRequestInterceptor).toBeDefined();
      if (capturedRequestInterceptor) {
        const config = { url: '/test', headers: {} as Record<string, string> };
        const result = capturedRequestInterceptor(config);
        expect((result as typeof config).headers.Authorization).toBe('Bearer test-token');
      }
    });

    it('should skip auth for public endpoints', () => {
      expect(capturedRequestInterceptor).toBeDefined();
      if (capturedRequestInterceptor) {
        const config = { url: '/auth/token', headers: {} as Record<string, string> };
        const result = capturedRequestInterceptor(config);
        expect((result as typeof config).headers.Authorization).toBeUndefined();
      }
    });

    it('should match no-auth endpoints only on exact or path segment boundaries', () => {
      expect(isNoAuthEndpoint('/auth/token')).toBe(true);
      expect(isNoAuthEndpoint('/api/v1/auth/token?grant=password')).toBe(true);
      expect(isNoAuthEndpoint('/public')).toBe(true);
      expect(isNoAuthEndpoint('/public/assets/logo.png')).toBe(true);
      expect(isNoAuthEndpoint('/publicly-visible')).toBe(false);
      expect(isNoAuthEndpoint('/public-resource')).toBe(false);
      expect(isNoAuthEndpoint('/auth/tokenized')).toBe(false);
    });

    it('should require auth for paths that only share a public prefix', async () => {
      vi.mocked(getAuthToken).mockReturnValueOnce(null);
      expect(capturedRequestInterceptor).toBeDefined();
      if (capturedRequestInterceptor) {
        const config = { url: '/public-resource', headers: {} as Record<string, string> };
        const result = capturedRequestInterceptor(config);
        expect(result).toBeInstanceOf(Promise);
        await expect(result).rejects.toThrow('No authentication token');
      }
    });

    it('should reject when no token is available for authenticated endpoints', async () => {
      vi.mocked(getAuthToken).mockReturnValueOnce(null);
      expect(capturedRequestInterceptor).toBeDefined();
      if (capturedRequestInterceptor) {
        const config = { url: '/test', headers: {} as Record<string, string> };
        const result = capturedRequestInterceptor(config);
        expect(result).toBeInstanceOf(Promise);
        await expect(result).rejects.toThrow('No authentication token');
      }
    });
  });

  describe('response interceptor', () => {
    it('should have captured the response interceptor functions', () => {
      expect(capturedResponseInterceptor).toBeDefined();
      expect(typeof capturedResponseInterceptor).toBe('function');
    });

    it('should pass through successful responses', () => {
      expect(capturedResponseInterceptor).toBeDefined();
      if (capturedResponseInterceptor) {
        const response = { status: 200, data: { result: 'ok' } };
        const result = capturedResponseInterceptor(response);
        expect(result).toBe(response);
      }
    });
  });

  describe('client methods', () => {
    it('should expose standard HTTP methods', () => {
      expect(typeof httpClient.get).toBe('function');
      expect(typeof httpClient.post).toBe('function');
      expect(typeof httpClient.put).toBe('function');
      expect(typeof httpClient.patch).toBe('function');
      expect(typeof httpClient.delete).toBe('function');
    });

    it('should return response.data from GET requests', async () => {
      const testData = { result: 'success' };
      mockAxiosInstance.get.mockResolvedValueOnce({ status: 200, data: testData });

      const result = await httpClient.get('/test');

      expect(mockAxiosInstance.get).toHaveBeenCalledWith('/test', undefined);
      expect(result).toEqual(testData);
    });

    it('should return response.data from POST requests', async () => {
      const testData = { result: 'created' };
      const postBody = { name: 'test' };
      mockAxiosInstance.post.mockResolvedValueOnce({ status: 201, data: testData });

      const result = await httpClient.post('/test', postBody);

      expect(mockAxiosInstance.post).toHaveBeenCalledWith('/test', postBody, undefined);
      expect(result).toEqual(testData);
    });

    it('should return response.data from PUT requests', async () => {
      const testData = { result: 'updated' };
      const putBody = { name: 'updated' };
      mockAxiosInstance.put.mockResolvedValueOnce({ status: 200, data: testData });

      const result = await httpClient.put('/test', putBody);

      expect(mockAxiosInstance.put).toHaveBeenCalledWith('/test', putBody, undefined);
      expect(result).toEqual(testData);
    });

    it('should return response.data from PATCH requests', async () => {
      const testData = { result: 'patched' };
      const patchBody = { name: 'patched' };
      mockAxiosInstance.patch.mockResolvedValueOnce({ status: 200, data: testData });

      const result = await httpClient.patch('/test', patchBody);

      expect(mockAxiosInstance.patch).toHaveBeenCalledWith('/test', patchBody, undefined);
      expect(result).toEqual(testData);
    });

    it('should return response.data from DELETE requests', async () => {
      const testData = null;
      mockAxiosInstance.delete.mockResolvedValueOnce({ status: 204, data: testData });

      const result = await httpClient.delete('/test');

      expect(mockAxiosInstance.delete).toHaveBeenCalledWith('/test', undefined);
      expect(result).toEqual(testData);
    });
  });

  describe('requestCache (standalone utility)', () => {
    it('should store and retrieve cached data', () => {
      const testData = { result: 'cached data' };
      const cacheKey = requestCache.generateCacheKey('/api/test');

      requestCache.set(cacheKey, testData);
      expect(requestCache.get(cacheKey)).toEqual(testData);
    });

    it('should return undefined on cache miss', () => {
      const cacheKey = requestCache.generateCacheKey('/api/test');
      expect(requestCache.get(cacheKey)).toBeUndefined();
    });

    it('should use different cache keys for different params', () => {
      const testData1 = { result: 'data1' };
      const testData2 = { result: 'data2' };

      const key1 = requestCache.generateCacheKey('/api/test', { id: 1 });
      const key2 = requestCache.generateCacheKey('/api/test', { id: 2 });

      requestCache.set(key1, testData1);
      requestCache.set(key2, testData2);

      expect(requestCache.get(key1)).toEqual(testData1);
      expect(requestCache.get(key2)).toEqual(testData2);
      expect(key1).not.toBe(key2);
    });

    it('should generate same cache key for same params in different order', () => {
      const key1 = requestCache.generateCacheKey('/api/test', { a: 1, b: 2 });
      const key2 = requestCache.generateCacheKey('/api/test', { b: 2, a: 1 });

      expect(key1).toBe(key2);
    });

    it('should clear all entries', () => {
      requestCache.set('key1', 'data1');
      requestCache.set('key2', 'data2');

      requestCache.clear();

      expect(requestCache.get('key1')).toBeUndefined();
      expect(requestCache.get('key2')).toBeUndefined();
    });

    it('should report cache statistics', () => {
      requestCache.set('key1', 'data');

      requestCache.get('key1');
      requestCache.get('missing');

      const stats = requestCache.getStats();
      expect(stats.hits).toBe(1);
      expect(stats.misses).toBe(1);
      expect(stats.size).toBe(1);
    });
  });

  describe('requestDeduplicator (standalone utility)', () => {
    it('should deduplicate concurrent requests with same key', async () => {
      let callCount = 0;
      const executor = () => {
        callCount++;
        return Promise.resolve('result');
      };

      const promise1 = requestDeduplicator.deduplicate('key1', executor);
      const promise2 = requestDeduplicator.deduplicate('key1', executor);

      const [result1, result2] = await Promise.all([promise1, promise2]);

      expect(callCount).toBe(1);
      expect(result1).toBe('result');
      expect(result2).toBe('result');
    });

    it('should NOT deduplicate requests with different keys', async () => {
      let callCount = 0;
      const executor = () => {
        callCount++;
        return Promise.resolve('result');
      };

      await Promise.all([
        requestDeduplicator.deduplicate('key1', executor),
        requestDeduplicator.deduplicate('key2', executor),
      ]);

      expect(callCount).toBe(2);
    });

    it('should track deduplication statistics', async () => {
      let resolvePromise: (value: string) => void;
      const pendingPromise = new Promise<string>((resolve) => {
        resolvePromise = resolve;
      });

      const promise1 = requestDeduplicator.deduplicate('key1', () => pendingPromise);
      const promise2 = requestDeduplicator.deduplicate('key1', () => pendingPromise);

      const stats = requestDeduplicator.getStats();
      expect(stats.total).toBe(2);
      expect(stats.deduplicated).toBe(1);

      resolvePromise!('done');
      await Promise.all([promise1, promise2]);
    });

    it('should allow new request after previous completes', async () => {
      let callCount = 0;
      const executor = () => {
        callCount++;
        return Promise.resolve('result');
      };

      await requestDeduplicator.deduplicate('key1', executor);
      await requestDeduplicator.deduplicate('key1', executor);

      expect(callCount).toBe(2);
    });

    it('should generate correct deduplication keys', () => {
      const key1 = requestDeduplicator.deduplicateKey('GET', '/api/test', { id: 1 });
      const key2 = requestDeduplicator.deduplicateKey('GET', '/api/test', { id: 2 });
      const key3 = requestDeduplicator.deduplicateKey('POST', '/api/test', { id: 1 });

      expect(key1).not.toBe(key2);
      expect(key1).not.toBe(key3);
    });

    it('should deduplicate concurrent POST requests', async () => {
      let callCount = 0;
      const executor = () => {
        callCount++;
        return Promise.resolve({ result: 'created' });
      };

      const key = requestDeduplicator.deduplicateKey('POST', '/api/test');
      const promise1 = requestDeduplicator.deduplicate(key, executor);
      const promise2 = requestDeduplicator.deduplicate(key, executor);

      const [result1, result2] = await Promise.all([promise1, promise2]);

      expect(callCount).toBe(1);
      expect(result1).toEqual({ result: 'created' });
      expect(result2).toEqual({ result: 'created' });
    });

    it('should deduplicate concurrent PUT requests', async () => {
      let callCount = 0;
      const executor = () => {
        callCount++;
        return Promise.resolve({ result: 'updated' });
      };

      const key = requestDeduplicator.deduplicateKey('PUT', '/api/test');
      const promise1 = requestDeduplicator.deduplicate(key, executor);
      const promise2 = requestDeduplicator.deduplicate(key, executor);

      await Promise.all([promise1, promise2]);
      expect(callCount).toBe(1);
    });

    it('should deduplicate concurrent PATCH requests', async () => {
      let callCount = 0;
      const executor = () => {
        callCount++;
        return Promise.resolve({ result: 'patched' });
      };

      const key = requestDeduplicator.deduplicateKey('PATCH', '/api/test');
      const promise1 = requestDeduplicator.deduplicate(key, executor);
      const promise2 = requestDeduplicator.deduplicate(key, executor);

      await Promise.all([promise1, promise2]);
      expect(callCount).toBe(1);
    });

    it('should deduplicate concurrent DELETE requests', async () => {
      let callCount = 0;
      const executor = () => {
        callCount++;
        return Promise.resolve(null);
      };

      const key = requestDeduplicator.deduplicateKey('DELETE', '/api/test');
      const promise1 = requestDeduplicator.deduplicate(key, executor);
      const promise2 = requestDeduplicator.deduplicate(key, executor);

      await Promise.all([promise1, promise2]);
      expect(callCount).toBe(1);
    });
  });
});

describe('httpClient error handling', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('should propagate errors from GET requests', async () => {
    const error = new Error('Network error');
    mockAxiosInstance.get.mockRejectedValueOnce(error);

    await expect(httpClient.get('/test')).rejects.toThrow('Network error');
  });

  it('should propagate errors from POST requests', async () => {
    const error = new Error('Server error');
    mockAxiosInstance.post.mockRejectedValueOnce(error);

    await expect(httpClient.post('/test', {})).rejects.toThrow('Server error');
  });

  it('should propagate errors from PUT requests', async () => {
    const error = new Error('Forbidden');
    mockAxiosInstance.put.mockRejectedValueOnce(error);

    await expect(httpClient.put('/test', {})).rejects.toThrow('Forbidden');
  });

  it('should propagate errors from DELETE requests', async () => {
    const error = new Error('Not found');
    mockAxiosInstance.delete.mockRejectedValueOnce(error);

    await expect(httpClient.delete('/test')).rejects.toThrow('Not found');
  });
});
