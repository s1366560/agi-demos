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

import { getAuthToken, clearAuthState } from '@/utils/tokenResolver';

import { parseResponseError } from './ApiError';

/**
 * Retry configuration for apiFetch
 *
 * Controls retry behavior for fetch-based requests.
 */
export interface FetchRetryConfig {
  /** Maximum number of retry attempts (default: 2) */
  maxRetries?: number | undefined;
  /** Initial delay in milliseconds (default: 1000) */
  initialDelay?: number | undefined;
  /** Maximum delay between retries (default: 10000) */
  maxDelay?: number | undefined;
  /** Backoff multiplier (default: 2) */
  backoffMultiplier?: number | undefined;
  /** Whether to add jitter (default: true) */
  jitter?: boolean | undefined;
  /** Custom function to determine if an error is retryable */
  isRetryable?: ((error: unknown) => boolean) | undefined;
}

const DEFAULT_FETCH_RETRY: {
  maxRetries: number;
  initialDelay: number;
  maxDelay: number;
  backoffMultiplier: number;
  jitter: boolean;
} = {
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
async function fetchWithRetry<T>(fn: () => Promise<T>, config: FetchRetryConfig = {}): Promise<T> {
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
        const delay = Math.min(initialDelay * Math.pow(backoffMultiplier, attempt), maxDelay);
        await delayWithJitter(delay);
      } else {
        throw error;
      }
    }
  }

  throw lastError;
}

/**
 * Get the base API URL - always use relative path for Vite proxy
 *
 * @returns Empty string for relative URLs (ensures requests go through Vite proxy)
 *
 * NOTE: VITE_API_URL is intentionally NOT used here to ensure all HTTP requests
 * go through the Vite dev server proxy. This avoids CORS issues and ensures
 * consistent behavior between development and production.
 */
function getBaseUrl(): string {
  return '';
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

  const token = getAuthToken();
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }

  return headers;
}

function normalizeHeaders(headers: HeadersInit | undefined): Record<string, string> {
  if (headers === undefined) {
    return {};
  }

  if (headers instanceof Headers) {
    return Object.fromEntries(headers.entries());
  }

  if (Array.isArray(headers)) {
    return Object.fromEntries(headers);
  }

  return headers;
}

function mergeHeaders(headers: HeadersInit | undefined): Record<string, string> {
  return {
    ...getDefaultHeaders(),
    ...normalizeHeaders(headers),
  };
}

/**
 * Handle 401 unauthorized response
 *
 * Clears auth state via centralized clearAuthState().
 * React Router handles the redirect based on isAuthenticated becoming false.
 *
 * Exported for testing purposes
 */
export function handleUnauthorized(): void {
  clearAuthState();
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
 * createWebSocketUrl('/terminal/ws', { session_id: 'abc' }) // 'ws://localhost:3000/api/v1/terminal/ws?session_id=abc'
 */
export function createWebSocketUrl(path: string, params?: Record<string, string>): string {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const configuredApiUrl =
    typeof import.meta.env.VITE_API_URL === 'string' ? import.meta.env.VITE_API_URL : undefined;

  let host: string;
  if (configuredApiUrl) {
    // Extract host from VITE_API_URL
    host = new URL(configuredApiUrl).host;
  } else if (window.location.host.includes(':3000')) {
    // Development: Vite dev server on port 3000, backend on port 8000
    host = 'localhost:8000';
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

const WEBSOCKET_AUTH_SUBPROTOCOL = 'memstack.auth';

export function createWebSocketAuthProtocols(token: string): string[] {
  return [WEBSOCKET_AUTH_SUBPROTOCOL, token];
}

/**
 * Fetch request options with retry support
 */
export interface FetchOptions extends RequestInit {
  /** Enable retry for this request (default: false) */
  retry?: FetchRetryConfig | boolean | undefined;
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
  const retryConfig: FetchRetryConfig = typeof retryOption === 'boolean' ? {} : retryOption;

  // Execute with retry
  return fetchWithRetry(() => fetch(input, init), retryConfig);
}

export const apiFetch = {
  get: async (url: string, options: FetchOptions = {}): Promise<Response> => {
    const response = await fetchWithRetryWrapper(createApiUrl(url), {
      ...options,
      headers: mergeHeaders(options.headers),
    });
    return handleResponse(response);
  },

  post: async (url: string, data?: unknown, options: FetchOptions = {}): Promise<Response> => {
    const response = await fetchWithRetryWrapper(createApiUrl(url), {
      ...options,
      method: 'POST',
      headers: mergeHeaders(options.headers),
      body: data !== undefined ? JSON.stringify(data) : null,
    });
    return handleResponse(response);
  },

  put: async (url: string, data?: unknown, options: FetchOptions = {}): Promise<Response> => {
    const response = await fetchWithRetryWrapper(createApiUrl(url), {
      ...options,
      method: 'PUT',
      headers: mergeHeaders(options.headers),
      body: data !== undefined ? JSON.stringify(data) : null,
    });
    return handleResponse(response);
  },

  patch: async (url: string, data?: unknown, options: FetchOptions = {}): Promise<Response> => {
    const response = await fetchWithRetryWrapper(createApiUrl(url), {
      ...options,
      method: 'PATCH',
      headers: mergeHeaders(options.headers),
      body: data !== undefined ? JSON.stringify(data) : null,
    });
    return handleResponse(response);
  },

  delete: async (url: string, options: FetchOptions = {}): Promise<Response> => {
    const response = await fetchWithRetryWrapper(createApiUrl(url), {
      ...options,
      method: 'DELETE',
      headers: mergeHeaders(options.headers),
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
