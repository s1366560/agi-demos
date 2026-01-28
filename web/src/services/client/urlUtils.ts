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

import { parseResponseError } from './ApiError';

/**
 * Retry configuration for apiFetch
 *
 * Controls retry behavior for fetch-based requests.
 */
export interface FetchRetryConfig {
  /** Maximum number of retry attempts (default: 2) */
  maxRetries?: number;
  /** Initial delay in milliseconds (default: 1000) */
  initialDelay?: number;
  /** Maximum delay between retries (default: 10000) */
  maxDelay?: number;
  /** Backoff multiplier (default: 2) */
  backoffMultiplier?: number;
  /** Whether to add jitter (default: true) */
  jitter?: boolean;
  /** Custom function to determine if an error is retryable */
  isRetryable?: (error: unknown) => boolean;
}

const DEFAULT_FETCH_RETRY: Required<Omit<FetchRetryConfig, 'isRetryable'>> = {
  maxRetries: 2,
  initialDelay: 1000,
  maxDelay: 10000,
  backoffMultiplier: 2,
  jitter: true,
};

/**
 * Check if a fetch error is retryable
 * Only retry network errors and 5xx status codes
 */
function isFetchErrorRetryable(error: unknown): boolean {
  // Network errors (TypeError from fetch)
  if (error instanceof TypeError) {
    return true;
  }
  // HTTP 5xx responses
  if (error instanceof Response && error.status >= 500) {
    return true;
  }
  // AbortError (user cancelled) - don't retry
  if (error instanceof DOMException && error.name === 'AbortError') {
    return false;
  }
  return false;
}

/**
 * Delay with jitter
 */
function delayWithJitter(ms: number): Promise<void> {
  // Add jitter: delay * (0.5 + Math.random() * 0.5)
  const jittered = ms * (0.5 + Math.random() * 0.5);
  return new Promise((resolve) => setTimeout(resolve, jittered));
}

/**
 * Retry fetch with exponential backoff
 */
async function fetchWithRetry<T>(
  fn: () => Promise<T>,
  config: FetchRetryConfig = {}
): Promise<T> {
  const {
    maxRetries = DEFAULT_FETCH_RETRY.maxRetries,
    initialDelay = DEFAULT_FETCH_RETRY.initialDelay,
    maxDelay = DEFAULT_FETCH_RETRY.maxDelay,
    backoffMultiplier = DEFAULT_FETCH_RETRY.backoffMultiplier,
    isRetryable = isFetchErrorRetryable,
  } = config;

  let lastError: unknown;

  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    try {
      return await fn();
    } catch (error) {
      lastError = error;
      if (attempt < maxRetries && isRetryable(error)) {
        const delay = Math.min(
          initialDelay * Math.pow(backoffMultiplier, attempt),
          maxDelay
        );
        await delayWithJitter(delay);
      } else {
        throw error;
      }
    }
  }

  throw lastError;
}

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
export interface FetchOptions extends RequestInit {
  /** Enable retry for this request (default: false) */
  retry?: FetchRetryConfig | boolean;
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
async function fetchWithRetryWrapper(
  input: RequestInfo | URL,
  init?: FetchOptions
): Promise<Response> {
  const retryOption = init?.retry;

  // No retry - execute directly
  if (!retryOption) {
    return fetch(input, init);
  }

  // Build retry config
  const retryConfig: FetchRetryConfig =
    typeof retryOption === 'boolean'
      ? {}
      : retryOption;

  // Execute with retry
  return fetchWithRetry(() => fetch(input, init), retryConfig);
}

export const apiFetch = {
  get: async (url: string, options: FetchOptions = {}): Promise<Response> => {
    const headers = getDefaultHeaders();
    const mergedHeaders = { ...headers, ...options.headers };

    const response = await fetchWithRetryWrapper(createApiUrl(url), {
      ...options,
      headers: mergedHeaders,
    });
    return handleResponse(response);
  },

  post: async (url: string, data?: unknown, options: FetchOptions = {}): Promise<Response> => {
    const headers = getDefaultHeaders();
    const mergedHeaders = { ...headers, ...options.headers };

    const response = await fetchWithRetryWrapper(createApiUrl(url), {
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

    const response = await fetchWithRetryWrapper(createApiUrl(url), {
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

    const response = await fetchWithRetryWrapper(createApiUrl(url), {
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

    const response = await fetchWithRetryWrapper(createApiUrl(url), {
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
