/**
 * HTTP Client - Simplified Axios wrapper
 *
 * Basic axios instance with auth token injection.
 * All caching, deduplication, and retry logic removed for debugging.
 */

import axios, { AxiosRequestConfig } from 'axios';

import { getAuthToken } from '@/utils/tokenResolver';
import { clearAuthState } from '@/utils/tokenResolver';

import { parseAxiosError } from './ApiError';

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
  timeout: 30000, // 30 seconds (default; individual calls can override)
  maxContentLength: 200 * 1024 * 1024, // 200MB (base64 inflates ~33%)
  maxBodyLength: 200 * 1024 * 1024,
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
    const isNoAuthEndpoint = NO_AUTH_ENDPOINTS.some(
      (endpoint) => url.endsWith(endpoint) || url.startsWith(endpoint)
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
      // No token available for an authenticated endpoint - reject immediately.
      // React Router will redirect to /login based on isAuthenticated state.
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
    // Convert to properly typed ApiError using the parser
    const apiError = parseAxiosError(error);

    // Handle 401 - clear auth state; React routing will redirect to /login
    if (apiError.isAuthError()) {
      clearAuthState();
    }

    return Promise.reject(apiError);
  }
);

/**
 * Simple HTTP client - direct axios calls without request deduplication
 *
 * Note: Request deduplication is intentionally removed from the HTTP client layer.
 * It should be handled at the application/store layer where the context is better
 * understood. HTTP-level deduplication can cause requests to hang indefinitely
 * if the original request never completes.
 */
export const httpClient = {
  /**
   * GET request - simple wrapper around axios
   */
  get: <T = unknown>(url: string, config?: HttpRequestConfig): Promise<T> => {
    return client.get<T>(url, config).then((response) => response.data);
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
