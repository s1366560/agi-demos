/**
 * API URL Utilities
 *
 * Centralized utilities for constructing API URLs and WebSocket URLs.
 * Ensures consistent /api/v1 prefix handling across the application.
 *
 * Rules:
 * 1. All API paths should use /api/v1 prefix
 * 2. Use createApiUrl() for HTTP requests
 * 3. Use createWebSocketUrl() for WebSocket connections
 * 4. Use apiFetch for fetch-based requests (SSE, etc.)
 */

import { parseResponseError, ApiError, ApiErrorType } from './ApiError';
import { retryWithBackoff, type RetryConfig } from './retry';

/**
 * Get the base API URL from environment or use relative path
 *
 * @returns The base URL (e.g., 'http://api.example.com' or '' for relative)
 */
function getBaseUrl(): string {
  return import.meta.env.VITE_API_URL || '';
}

/**
 * Create a full API URL with /api/v1 prefix
 *
 * @param path - The API path (e.g., '/agent/conversations' or 'agent/conversations')
 * @returns Full URL with /api/v1 prefix
 *
 * @example
 * createApiUrl('/agent/conversations') // '/api/v1/agent/conversations'
 * createApiUrl('agent/conversations')  // '/api/v1/agent/conversations'
 * createApiUrl('/api/v1/agent/...')    // '/api/v1/agent/...' (normalized)
 */
export function createApiUrl(path: string): string {
  const baseUrl = getBaseUrl();
  const normalizedPath = path.startsWith('/') ? path : `/${path}`;

  // Remove /api/v1 prefix if already present to avoid duplication
  const cleanPath = normalizedPath.replace(/^\/api\/v1/, '');

  // Handle empty path - don't add trailing slash
  if (cleanPath === '' || cleanPath === '/') {
    return `${baseUrl}/api/v1`;
  }

  return `${baseUrl}/api/v1${cleanPath}`;
}

/**
 * Get default headers for API requests
 *
 * @returns Headers object with auth token and content type
 */
function getDefaultHeaders(): Record<string, string> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  };

  const token = localStorage.getItem('token');
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }

  return headers;
}

/**
 * Handle 401 unauthorized response
 *
 * Clears token and redirects to login page
 *
 * Exported for testing purposes
 */
export function handleUnauthorized(): void {
  localStorage.removeItem('token');
  localStorage.removeItem('user');

  if (window.location.pathname !== '/login') {
    window.location.href = '/login';
  }
}

/**
 * Create a WebSocket URL with /api/v1 prefix
 *
 * Automatically uses ws:// or wss:// protocol based on current page protocol.
 *
 * @param path - The WebSocket path (e.g., '/agent/ws')
 * @param params - Optional query parameters
 * @returns Full WebSocket URL
 *
 * @example
 * createWebSocketUrl('/agent/ws') // 'ws://localhost:3000/api/v1/agent/ws'
 * createWebSocketUrl('/agent/ws', { token: 'abc' }) // 'ws://localhost:3000/api/v1/agent/ws?token=abc'
 */
export function createWebSocketUrl(
  path: string,
  params?: Record<string, string>
): string {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';

  let host: string;
  if (import.meta.env.VITE_API_URL) {
    // Extract host from VITE_API_URL
    host = new URL(import.meta.env.VITE_API_URL).host;
  } else {
    host = window.location.host;
  }

  const normalizedPath = path.startsWith('/') ? path : `/${path}`;
  const cleanPath = normalizedPath.replace(/^\/api\/v1/, '');
  let wsUrl = `${protocol}//${host}/api/v1${cleanPath}`;

  // Add query parameters
  if (params) {
    const searchParams = new URLSearchParams(params);
    wsUrl += `?${searchParams.toString()}`;
  }

  return wsUrl;
}

/**
 * Fetch request options with retry support
 */
interface FetchOptions extends RequestInit {
  /** Enable retry for this request (default: false) */
  retry?: RetryConfig | boolean;
}

/**
 * Fetch wrapper with automatic /api/v1 prefix and auth headers
 *
 * Use this for fetch-based requests (SSE, file uploads, etc.) where
 * httpClient cannot be used.
 *
 * Throws ApiError on any error for consistent error handling.
 */

async function handleResponse(response: Response): Promise<Response> {
  if (response.status === 401) {
    handleUnauthorized();
  }
  // Throw ApiError for non-success responses
  if (!response.ok) {
    throw await parseResponseError(response);
  }
  return response;
}

/**
 * Wrap fetch with retry logic if enabled
 */
async function fetchWithRetry(
  input: RequestInfo | URL,
  init?: FetchOptions
): Promise<Response> {
  const retryOption = init?.retry;

  // No retry - execute directly
  if (!retryOption) {
    return fetch(input, init);
  }

  // Build retry config (more conservative for fetch)
  const retryConfig: RetryConfig =
    typeof retryOption === 'boolean'
      ? { maxRetries: 2, initialDelay: 1000 }
      : { maxRetries: 2, initialDelay: 1000, ...retryOption };

  // Execute with retry
  return retryWithBackoff(() => fetch(input, init), retryConfig);
}

export const apiFetch = {
  get: async (url: string, options: FetchOptions = {}): Promise<Response> => {
    const headers = getDefaultHeaders();
    // Merge headers, with options.headers taking precedence
    const mergedHeaders = { ...headers, ...options.headers };

    const response = await fetchWithRetry(createApiUrl(url), {
      ...options,
      headers: mergedHeaders,
    });
    return handleResponse(response);
  },

  post: async (url: string, data?: unknown, options: FetchOptions = {}): Promise<Response> => {
    const headers = getDefaultHeaders();
    const mergedHeaders = { ...headers, ...options.headers };

    const response = await fetchWithRetry(createApiUrl(url), {
      ...options,
      method: 'POST',
      headers: mergedHeaders,
      body: data !== undefined ? JSON.stringify(data) : undefined,
    });
    return handleResponse(response);
  },

  put: async (url: string, data?: unknown, options: FetchOptions = {}): Promise<Response> => {
    const headers = getDefaultHeaders();
    const mergedHeaders = { ...headers, ...options.headers };

    const response = await fetchWithRetry(createApiUrl(url), {
      ...options,
      method: 'PUT',
      headers: mergedHeaders,
      body: data !== undefined ? JSON.stringify(data) : undefined,
    });
    return handleResponse(response);
  },

  patch: async (url: string, data?: unknown, options: FetchOptions = {}): Promise<Response> => {
    const headers = getDefaultHeaders();
    const mergedHeaders = { ...headers, ...options.headers };

    const response = await fetchWithRetry(createApiUrl(url), {
      ...options,
      method: 'PATCH',
      headers: mergedHeaders,
      body: data !== undefined ? JSON.stringify(data) : undefined,
    });
    return handleResponse(response);
  },

  delete: async (url: string, options: FetchOptions = {}): Promise<Response> => {
    const headers = getDefaultHeaders();
    const mergedHeaders = { ...headers, ...options.headers };

    const response = await fetchWithRetry(createApiUrl(url), {
      ...options,
      method: 'DELETE',
      headers: mergedHeaders,
    });
    return handleResponse(response);
  },
};

/**
 * Re-export ApiError for convenience
 *
 * Services can import ApiError from either urlUtils or ApiError.
 */
export { ApiError, ApiErrorType } from './ApiError';

/**
 * Export retry types for convenience
 */
export type { RetryConfig };
