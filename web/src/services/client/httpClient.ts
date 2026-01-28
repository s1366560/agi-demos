/**
 * HTTP Client - Centralized HTTP client with caching and retry
 *
 * Provides a single axios instance with:
 * - Consistent configuration
 * - Auth token injection from localStorage
 * - ApiError-based error handling
 * - Request/response interceptors
 * - Request caching for GET requests
 * - Request deduplication for concurrent identical requests
 * - Automatic retry with exponential backoff
 *
 * All services should use this client instead of creating their own axios instances.
 *
 * @packageDocumentation
 *
 * @example
 * ```typescript
 * import { httpClient } from '@/services/client/httpClient';
 *
 * // Simple GET request with caching
 * const data = await httpClient.get('/projects');
 *
 * // POST request with retry
 * const result = await httpClient.post('/projects', {
 *   name: 'New Project'
 * }, { retry: true });
 *
 * // DELETE request
 * await httpClient.delete(`/projects/${projectId}`);
 *
 * // Clear cache for specific endpoint
 * httpClient.cache.invalidatePattern('/projects');
 * ```
 */

import axios, { AxiosRequestConfig } from 'axios';
import { requestCache } from './requestCache';
import { requestDeduplicator } from './requestDeduplicator';
import { parseAxiosError } from './ApiError';
import { retryWithBackoff, type RetryConfig, DEFAULT_RETRY_CONFIG } from './retry';

/**
 * HTTP request configuration interface
 *
 * Extends AxiosRequestConfig for better type safety and adds caching/retry options.
 *
 * @example
 * ```typescript
 * const config: HttpRequestConfig = {
 *   params: { page: 1 },
 *   retry: { maxRetries: 3 }
 * };
 * ```
 */
export interface HttpRequestConfig extends AxiosRequestConfig {
  /** Skip cache for this request (GET only) */
  skipCache?: boolean;
  /** Enable retry for this request (default: false) */
  retry?: RetryConfig | boolean;
}

/**
 * Default retry configuration for httpClient
 *
 * More conservative than generic defaults:
 * - Only 2 retries (vs 3)
 * - Only retry GET requests by default (idempotent)
 *
 * @example
 * ```typescript
 * // Override default retry config
 * await httpClient.get('/api/data', {
 *   retry: { maxRetries: 5, initialDelay: 2000 }
 * });
 * ```
 */
const HTTP_CLIENT_RETRY_CONFIG: RetryConfig = {
  maxRetries: 2,
  initialDelay: 1000,
  maxDelay: 10000,
  backoffMultiplier: 2,
  jitter: true,
};

/**
 * Create and configure the base HTTP client
 *
 * Initializes axios with base URL from environment and default headers.
 */
const client = axios.create({
  baseURL: import.meta.env.VITE_API_URL || '/api/v1',
  headers: {
    'Content-Type': 'application/json',
  },
});

/**
 * Request interceptor to inject auth token
 *
 * Automatically adds the Bearer token from localStorage to all requests.
 */
client.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

/**
 * Response interceptor to handle errors using ApiError
 *
 * Converts all axios errors to ApiError for consistent error handling.
 * Handles 401 authentication errors by clearing credentials and redirecting to login.
 */
client.interceptors.response.use(
  (response) => response,
  (error) => {
    // Convert to ApiError for consistent error handling
    const apiError = parseAxiosError(error);

    // Handle authentication errors
    if (apiError.isAuthError()) {
      // Clear token and user data
      localStorage.removeItem('token');
      localStorage.removeItem('user');
      // Redirect to login if not already there
      if (window.location.pathname !== '/login') {
        window.location.href = '/login';
      }
    }

    // Reject with ApiError
    return Promise.reject(apiError);
  }
);

/**
 * Wrap a request function with retry logic if enabled
 *
 * Checks if retry is enabled in config and wraps the request function
 * with exponential backoff retry logic.
 *
 * @param requestFn - The request function to potentially wrap
 * @param config - Optional request config with retry settings
 * @returns Promise with or without retry wrapper
 */
function withRetry<T>(
  requestFn: () => Promise<T>,
  config?: HttpRequestConfig
): Promise<T> {
  // Check if retry is enabled
  const retryOption = config?.retry;

  if (!retryOption) {
    return requestFn();
  }

  // Build retry config
  const retryConfig: RetryConfig =
    typeof retryOption === 'boolean'
      ? HTTP_CLIENT_RETRY_CONFIG
      : { ...HTTP_CLIENT_RETRY_CONFIG, ...retryOption };

  // Execute with retry
  return retryWithBackoff(requestFn, retryConfig);
}

/**
 * Cached and deduplicated HTTP client wrapper
 *
 * Wraps axios methods with:
 * - Caching support for GET requests
 * - Deduplication for concurrent identical requests
 * - Optional retry with exponential backoff
 * - POST, PUT, PATCH, DELETE requests bypass cache but still use deduplication
 *
 * @example
 * ```typescript
 * // GET with caching and retry
 * const projects = await httpClient.get('/projects', { retry: true });
 *
 * // POST without caching (but with deduplication)
 * const created = await httpClient.post('/projects', { name: 'New' });
 *
 * // PATCH with custom retry config
 * await httpClient.patch(`/projects/${id}`, { name: 'Updated' }, {
 *   retry: { maxRetries: 5, initialDelay: 2000 }
 * });
 * ```
 */
export const httpClient = {
  /**
   * GET request with caching and retry support
   *
   * Checks cache first before making network request. Concurrent identical
   * requests are deduplicated. Supports optional retry with exponential backoff.
   *
   * @param url - The URL path (relative to baseURL)
   * @param config - Optional request configuration
   * @returns Promise resolving to the response data
   *
   * @example
   * ```typescript
   * const projects = await httpClient.get('/projects');
   * const withRetry = await httpClient.get('/projects', { retry: true });
   * const noCache = await httpClient.get('/projects', { skipCache: true });
   * ```
   */
  get: <T = unknown>(url: string, config?: HttpRequestConfig): Promise<T> => {
    const cacheKey = requestCache.generateCacheKey(url, config?.params);
    const dedupeKey = requestDeduplicator.deduplicateKey('GET', url, config?.params);

    // Check cache first for GET requests
    const cached = requestCache.get<T>(cacheKey);
    if (cached !== undefined) {
      return Promise.resolve(cached);
    }

    // Deduplicate concurrent requests with retry support
    return requestDeduplicator.deduplicate(dedupeKey, () =>
      withRetry(() =>
        client.get<T>(url, config).then((response) => {
          // Only cache successful responses
          if (response.status === 200) {
            requestCache.set(cacheKey, response.data);
          }
          return response.data;
        }),
        config
      )
    );
  },

  /**
   * POST request with deduplication and retry support
   *
   * Bypasses cache but uses request deduplication for concurrent identical requests.
   * Supports optional retry with exponential backoff.
   *
   * @param url - The URL path (relative to baseURL)
   * @param data - The request body data
   * @param config - Optional request configuration
   * @returns Promise resolving to the response data
   *
   * @example
   * ```typescript
   * const created = await httpClient.post('/projects', { name: 'New Project' });
   * const withRetry = await httpClient.post('/projects', data, { retry: true });
   * ```
   */
  post: <T = unknown>(url: string, data?: unknown, config?: HttpRequestConfig): Promise<T> => {
    const dedupeKey = requestDeduplicator.deduplicateKey('POST', url);

    return requestDeduplicator.deduplicate(dedupeKey, () =>
      withRetry(() =>
        client.post<T>(url, data, config).then((response) => response.data),
        config
      )
    );
  },

  /**
   * PUT request with deduplication and retry support
   *
   * Bypasses cache but uses request deduplication for concurrent identical requests.
   * Supports optional retry with exponential backoff.
   *
   * @param url - The URL path (relative to baseURL)
   * @param data - The request body data
   * @param config - Optional request configuration
   * @returns Promise resolving to the response data
   *
   * @example
   * ```typescript
   * const updated = await httpClient.put(`/projects/${id}`, { name: 'Updated' });
   * ```
   */
  put: <T = unknown>(url: string, data?: unknown, config?: HttpRequestConfig): Promise<T> => {
    const dedupeKey = requestDeduplicator.deduplicateKey('PUT', url);

    return requestDeduplicator.deduplicate(dedupeKey, () =>
      withRetry(() =>
        client.put<T>(url, data, config).then((response) => response.data),
        config
      )
    );
  },

  /**
   * PATCH request with deduplication and retry support
   *
   * Bypasses cache but uses request deduplication for concurrent identical requests.
   * Supports optional retry with exponential backoff.
   *
   * @param url - The URL path (relative to baseURL)
   * @param data - The request body data
   * @param config - Optional request configuration
   * @returns Promise resolving to the response data
   *
   * @example
   * ```typescript
   * const patched = await httpClient.patch(`/projects/${id}`, { name: 'Patched' });
   * ```
   */
  patch: <T = unknown>(url: string, data?: unknown, config?: HttpRequestConfig): Promise<T> => {
    const dedupeKey = requestDeduplicator.deduplicateKey('PATCH', url);

    return requestDeduplicator.deduplicate(dedupeKey, () =>
      withRetry(() =>
        client.patch<T>(url, data, config).then((response) => response.data),
        config
      )
    );
  },

  /**
   * DELETE request with deduplication and retry support
   *
   * Bypasses cache but uses request deduplication for concurrent identical requests.
   * Supports optional retry with exponential backoff.
   *
   * @param url - The URL path (relative to baseURL)
   * @param config - Optional request configuration
   * @returns Promise resolving to the response data
   *
   * @example
   * ```typescript
   * await httpClient.delete(`/projects/${id}`);
   * ```
   */
  delete: <T = unknown>(url: string, config?: HttpRequestConfig): Promise<T> => {
    const dedupeKey = requestDeduplicator.deduplicateKey('DELETE', url);

    return requestDeduplicator.deduplicate(dedupeKey, () =>
      withRetry(() =>
        client.delete<T>(url, config).then((response) => response.data),
        config
      )
    );
  },

  /**
   * Pass-through axios instance for advanced usage
   *
   * Provides access to the underlying axios instance for advanced scenarios
   * not covered by the wrapper methods.
   */
  instance: client,

  /**
   * Access to cache for manual invalidation
   *
   * Provides access to the request cache for manual cache invalidation.
   *
   * @example
   * ```typescript
   * // Invalidate all project-related cache entries
   * httpClient.cache.invalidatePattern('/projects');
   * ```
   */
  cache: requestCache,

  /**
   * Access to deduplicator for monitoring
   *
   * Provides access to the request deduplicator for monitoring
   * pending requests.
   */
  deduplicator: requestDeduplicator,

  /**
   * Original axios defaults
   *
   * Access to axios default configuration.
   */
  defaults: client.defaults,

  /**
   * Original axios interceptors
   *
   * Access to axios interceptors for adding custom interceptors.
   */
  interceptors: client.interceptors,
};

/**
 * Export default for convenience
 */
export default client;

/**
 * Re-export URL utilities and ApiError for convenience
 */
export * from './urlUtils';
export { ApiError, ApiErrorType } from './ApiError';

/**
 * Export retry types and utilities
 */
export { DEFAULT_RETRY_CONFIG };
export type { RetryConfig };
