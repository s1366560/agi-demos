/**
 * HTTP Client - Simplified Axios wrapper
 *
 * Basic axios instance with auth token injection.
 * All caching, deduplication, and retry logic removed for debugging.
 */

import axios, { AxiosRequestConfig } from 'axios';
import { getAuthToken } from '@/utils/tokenResolver';
import { ApiError } from './ApiError';

/**
 * HTTP request configuration interface
 */
export interface HttpRequestConfig extends AxiosRequestConfig {
  /** Skip cache for this request (GET only) - DEPRECATED, ignored */
  skipCache?: boolean;
  /** Enable retry - DEPRECATED, ignored */
  retry?: boolean;
}

/**
 * Create axios client with relative baseURL (goes through Vite proxy)
 */
const client = axios.create({
  baseURL: '/api/v1',
  headers: {
    'Content-Type': 'application/json',
  },
  // Add timeout to prevent hanging requests
  timeout: 30000,
});

/**
 * Endpoints that don't require authentication
 */
const NO_AUTH_ENDPOINTS = ['/auth/token', '/auth/register', '/public'];

/**
 * Request interceptor to inject auth token
 */
client.interceptors.request.use(
  (config) => {
    // Check if this is a public endpoint that doesn't require auth
    const url = config.url || '';
    const isNoAuthEndpoint = NO_AUTH_ENDPOINTS.some(endpoint =>
      url.endsWith(endpoint) || url.startsWith(endpoint)
    );

    if (isNoAuthEndpoint) {
      // Public endpoint - proceed without token check
      return config;
    }

    // If request already has Authorization header (set manually), proceed
    if (config.headers.Authorization) {
      return config;
    }

    const token = getAuthToken();
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    } else {
      // No token - reject and redirect to login
      if (window.location.pathname !== '/login') {
        console.warn('[httpClient] No auth token, redirecting to login');
        window.location.href = '/login';
      }
      return Promise.reject(new Error('No authentication token'));
    }
    return config;
  },
  (error) => Promise.reject(error)
);

/**
 * Response interceptor to convert errors to ApiError
 */
client.interceptors.response.use(
  (response) => response,
  (error) => {
    // Convert to ApiError
    if (error.response) {
      const apiError = new ApiError(
        error.response.status,
        error.response.data?.code || 'UNKNOWN_ERROR',
        error.response.data?.message || error.message
      );
      
      // Handle 401 - redirect to login
      if (apiError.isAuthError()) {
        localStorage.removeItem('memstack-auth-storage');
        localStorage.removeItem('token');
        localStorage.removeItem('user');
        if (window.location.pathname !== '/login') {
          window.location.href = '/login';
        }
      }
      
      return Promise.reject(apiError);
    }
    
    // Network errors
    return Promise.reject(new ApiError('NETWORK', 'NETWORK_ERROR', error.message));
  }
);

// Global request lock to prevent duplicate concurrent requests
const pendingRequests = new Map<string, Promise<unknown>>();

function getRequestKey(method: string, url: string, params?: unknown): string {
  return `${method}-${url}-${JSON.stringify(params || {})}`;
}

// Deduplication timeout - clear pending requests after this time to prevent stalls
const DEDUP_TIMEOUT = 10000; // 10 seconds

/**
 * Simple HTTP client - direct axios calls with global deduplication
 */
export const httpClient = {
  /**
   * GET request with global deduplication and timeout protection
   */
  get: <T = unknown>(url: string, config?: HttpRequestConfig): Promise<T> => {
    const key = getRequestKey('GET', url, config?.params);

    // Return existing pending request if exists AND hasn't timed out
    const existing = pendingRequests.get(key);
    if (existing) {
      console.log(`[httpClient] Deduplicating request: ${url}`);
      return existing as Promise<T>;
    }

    // Create new request with timeout protection
    const promise = client.get<T>(url, config)
      .then((response) => response.data)
      .finally(() => {
        // Cleanup on completion or error
        pendingRequests.delete(key);
      });

    // Track with timeout protection
    pendingRequests.set(key, promise);

    // Failsafe: remove from pending map after timeout to prevent permanent stalls
    setTimeout(() => {
      if (pendingRequests.has(key)) {
        console.warn(`[httpClient] Request timeout after ${DEDUP_TIMEOUT}ms, removing from pending: ${url}`);
        pendingRequests.delete(key);
      }
    }, DEDUP_TIMEOUT);

    return promise;
  },

  /**
   * POST request
   */
  post: <T = unknown>(url: string, data?: unknown, config?: HttpRequestConfig): Promise<T> => {
    return client.post<T>(url, data, config).then((response) => response.data);
  },

  /**
   * PATCH request
   */
  patch: <T = unknown>(url: string, data?: unknown, config?: HttpRequestConfig): Promise<T> => {
    return client.patch<T>(url, data, config).then((response) => response.data);
  },

  /**
   * PUT request
   */
  put: <T = unknown>(url: string, data?: unknown, config?: HttpRequestConfig): Promise<T> => {
    return client.put<T>(url, data, config).then((response) => response.data);
  },

  /**
   * DELETE request
   */
  delete: <T = unknown>(url: string, config?: HttpRequestConfig): Promise<T> => {
    return client.delete<T>(url, config).then((response) => response.data);
  },

  /**
   * Upload file with multipart/form-data
   */
  upload: <T = unknown>(
    url: string,
    formData: FormData,
    onProgress?: (progress: number) => void
  ): Promise<T> => {
    return client
      .post<T>(url, formData, {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
        onUploadProgress: (progressEvent) => {
          if (onProgress && progressEvent.total) {
            const progress = Math.round((progressEvent.loaded * 100) / progressEvent.total);
            onProgress(progress);
          }
        },
      })
      .then((response) => response.data);
  },
};
