/**
 * Centralized HTTP Client
 *
 * Provides a single axios instance with:
 * - Consistent configuration
 * - Auth token injection
 * - 401 error handling
 * - Request/response interceptors
 * - Request caching for GET requests
 * - Request deduplication for concurrent requests
 *
 * All services should use this client instead of creating their own axios instances.
 */

import axios, { AxiosRequestConfig, AxiosResponse } from 'axios';
import { requestCache } from './requestCache';
import { requestDeduplicator } from './requestDeduplicator';

/**
 * HTTP request configuration interface
 * Extends AxiosRequestConfig for better type safety
 */
export interface HttpRequestConfig extends AxiosRequestConfig {
  skipCache?: boolean;
}

/**
 * Create and configure the base HTTP client
 */
const client = axios.create({
  baseURL: import.meta.env.VITE_API_URL || '/api/v1',
  headers: {
    'Content-Type': 'application/json',
  },
});

/**
 * Request interceptor to inject auth token
 */
client.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

/**
 * Response interceptor to handle authentication errors
 */
client.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      // Clear token and user data
      localStorage.removeItem('token');
      localStorage.removeItem('user');
      // Redirect to login if not already there
      if (window.location.pathname !== '/login') {
        window.location.href = '/login';
      }
    }
    return Promise.reject(error);
  }
);

/**
 * Cached and deduplicated HTTP client wrapper
 *
 * Wraps axios methods with:
 * - Caching support for GET requests
 * - Deduplication for concurrent identical requests
 * - POST, PUT, PATCH, DELETE requests bypass cache but still use deduplication
 */
export const httpClient = {
  // Standard axios methods
  get: <T = unknown>(url: string, config?: HttpRequestConfig): Promise<T> => {
    const cacheKey = requestCache.generateCacheKey(url, config?.params);
    const dedupeKey = requestDeduplicator.deduplicateKey('GET', url, config?.params);

    // Check cache first for GET requests
    const cached = requestCache.get<T>(cacheKey);
    if (cached !== undefined) {
      return Promise.resolve(cached);
    }

    // Deduplicate concurrent requests
    return requestDeduplicator.deduplicate(dedupeKey, () =>
      client.get<T>(url, config).then((response) => {
        // Only cache successful responses
        if (response.status === 200) {
          requestCache.set(cacheKey, response.data);
        }
        return response.data;
      })
    );
  },

  post: <T = unknown>(url: string, data?: unknown, config?: HttpRequestConfig): Promise<T> => {
    const dedupeKey = requestDeduplicator.deduplicateKey('POST', url);

    return requestDeduplicator.deduplicate(dedupeKey, () =>
      client.post<T>(url, data, config).then((response) => response.data)
    );
  },

  put: <T = unknown>(url: string, data?: unknown, config?: HttpRequestConfig): Promise<T> => {
    const dedupeKey = requestDeduplicator.deduplicateKey('PUT', url);

    return requestDeduplicator.deduplicate(dedupeKey, () =>
      client.put<T>(url, data, config).then((response) => response.data)
    );
  },

  patch: <T = unknown>(url: string, data?: unknown, config?: HttpRequestConfig): Promise<T> => {
    const dedupeKey = requestDeduplicator.deduplicateKey('PATCH', url);

    return requestDeduplicator.deduplicate(dedupeKey, () =>
      client.patch<T>(url, data, config).then((response) => response.data)
    );
  },

  delete: <T = unknown>(url: string, config?: HttpRequestConfig): Promise<T> => {
    const dedupeKey = requestDeduplicator.deduplicateKey('DELETE', url);

    return requestDeduplicator.deduplicate(dedupeKey, () =>
      client.delete<T>(url, config).then((response) => response.data)
    );
  },

  // Pass-through axios instance for advanced usage
  instance: client,

  // Access to cache for manual invalidation
  cache: requestCache,

  // Access to deduplicator for monitoring
  deduplicator: requestDeduplicator,

  // Original axios methods (for compatibility)
  defaults: client.defaults,
  interceptors: client.interceptors,
};

/**
 * Export default for convenience
 */
export default client;

/**
 * Re-export URL utilities for convenience
 */
export * from './urlUtils';
