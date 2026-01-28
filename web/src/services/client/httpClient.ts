/**
 * Centralized HTTP Client
 *
 * Provides a single axios instance with:
 * - Consistent configuration
 * - Auth token injection
 * - ApiError-based error handling
 * - Request/response interceptors
 * - Request caching for GET requests
 * - Request deduplication for concurrent requests
 * - Automatic retry with exponential backoff
 *
 * All services should use this client instead of creating their own axios instances.
 */

import axios, { AxiosRequestConfig } from 'axios';
import { requestCache } from './requestCache';
import { requestDeduplicator } from './requestDeduplicator';
import { parseAxiosError, ApiError, ApiErrorType } from './ApiError';
import { retryWithBackoff, type RetryConfig, DEFAULT_RETRY_CONFIG } from './retry';

/**
 * HTTP request configuration interface
 * Extends AxiosRequestConfig for better type safety
 */
export interface HttpRequestConfig extends AxiosRequestConfig {
  skipCache?: boolean;
  /** Enable retry for this request (default: false) */
  retry?: RetryConfig | boolean;
}

/**
 * Default retry configuration for httpClient
 *
 * More conservative than defaults:
 * - Only 2 retries (vs 3)
 * - Only retry GET requests by default (idempotent)
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
 * Response interceptor to handle errors using ApiError
 *
 * Converts all axios errors to ApiError for consistent error handling.
 * Handles 401 authentication errors with redirect to login.
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

  post: <T = unknown>(url: string, data?: unknown, config?: HttpRequestConfig): Promise<T> => {
    const dedupeKey = requestDeduplicator.deduplicateKey('POST', url);

    return requestDeduplicator.deduplicate(dedupeKey, () =>
      withRetry(() =>
        client.post<T>(url, data, config).then((response) => response.data),
        config
      )
    );
  },

  put: <T = unknown>(url: string, data?: unknown, config?: HttpRequestConfig): Promise<T> => {
    const dedupeKey = requestDeduplicator.deduplicateKey('PUT', url);

    return requestDeduplicator.deduplicate(dedupeKey, () =>
      withRetry(() =>
        client.put<T>(url, data, config).then((response) => response.data),
        config
      )
    );
  },

  patch: <T = unknown>(url: string, data?: unknown, config?: HttpRequestConfig): Promise<T> => {
    const dedupeKey = requestDeduplicator.deduplicateKey('PATCH', url);

    return requestDeduplicator.deduplicate(dedupeKey, () =>
      withRetry(() =>
        client.patch<T>(url, data, config).then((response) => response.data),
        config
      )
    );
  },

  delete: <T = unknown>(url: string, config?: HttpRequestConfig): Promise<T> => {
    const dedupeKey = requestDeduplicator.deduplicateKey('DELETE', url);

    return requestDeduplicator.deduplicate(dedupeKey, () =>
      withRetry(() =>
        client.delete<T>(url, config).then((response) => response.data),
        config
      )
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
 * Re-export URL utilities and ApiError for convenience
 */
export * from './urlUtils';
export { ApiError, ApiErrorType } from './ApiError';

/**
 * Export retry types and utilities
 */
export { DEFAULT_RETRY_CONFIG };
export type { RetryConfig };
