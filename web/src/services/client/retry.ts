/**
 * Retry Strategy Module
 *
 * Provides intelligent retry logic for HTTP requests with:
 * - Exponential backoff
 * - Jitter to avoid thundering herd
 * - Configurable retry conditions
 * - Integration with ApiError.isRetryable()
 */

import { ApiError } from './ApiError';

/**
 * Retry configuration options
 */
export interface RetryConfig {
  /** Maximum number of retry attempts (default: 3) */
  maxRetries?: number | undefined;

  /** Initial delay in milliseconds before first retry (default: 1000) */
  initialDelay?: number | undefined;

  /** Maximum delay between retries in milliseconds (default: 10000) */
  maxDelay?: number | undefined;

  /** Multiplier for exponential backoff (default: 2) */
  backoffMultiplier?: number | undefined;

  /** Whether to add jitter to delay (default: true) */
  jitter?: boolean | undefined;

  /** HTTP status codes that should trigger retry (default: 408, 429, 500+) */
  retryableStatusCodes?: Set<number> | undefined;

  /** Custom function to determine if an error is retryable */
  isRetryable?: ((error: ApiError) => boolean) | undefined;
}

/**
 * Default retry configuration
 */
export const DEFAULT_RETRY_CONFIG: {
  maxRetries: number;
  initialDelay: number;
  maxDelay: number;
  backoffMultiplier: number;
  jitter: boolean;
  retryableStatusCodes: Set<number>;
  isRetryable?: RetryConfig['isRetryable'] | undefined;
} = {
  maxRetries: 3,
  initialDelay: 1000,
  maxDelay: 10000,
  backoffMultiplier: 2,
  jitter: true,
  retryableStatusCodes: new Set([408, 429, 500, 502, 503, 504]),
};

/**
 * Calculate delay with exponential backoff and optional jitter
 *
 * @param attempt - The retry attempt number (0-based)
 * @param config - Retry configuration
 * @returns Delay in milliseconds
 */
export function calculateDelay(attempt: number, config: RetryConfig = {}): number {
  const {
    initialDelay: _initialDelay = DEFAULT_RETRY_CONFIG.initialDelay,
    maxDelay: _maxDelay = DEFAULT_RETRY_CONFIG.maxDelay,
    backoffMultiplier: _backoffMultiplier = DEFAULT_RETRY_CONFIG.backoffMultiplier,
    jitter = DEFAULT_RETRY_CONFIG.jitter,
  } = config;
  const initialDelay = _initialDelay ?? DEFAULT_RETRY_CONFIG.initialDelay;
  const maxDelay = _maxDelay ?? DEFAULT_RETRY_CONFIG.maxDelay;
  const backoffMultiplier = _backoffMultiplier ?? DEFAULT_RETRY_CONFIG.backoffMultiplier;

  // Calculate exponential backoff: initialDelay * (multiplier ^ attempt)
  const exponentialDelay = initialDelay * Math.pow(backoffMultiplier, attempt);

  // Clamp to maximum delay
  const clampedDelay = Math.min(exponentialDelay, maxDelay);

  // Add jitter to prevent thundering herd problem
  if (jitter) {
    // Add random +/- 25% jitter
    const jitterAmount = clampedDelay * 0.25;
    return clampedDelay - jitterAmount + Math.random() * jitterAmount * 2;
  }

  return clampedDelay;
}

/**
 * Check if an error is retryable based on its type and status code
 *
 * @param error - The ApiError to check
 * @param config - Retry configuration with custom isRetryable function
 * @returns True if the error should trigger a retry
 */
export function isRetryableError(error: ApiError, config: RetryConfig = {}): boolean {
  // Use custom retryable check if provided
  if (config.isRetryable) {
    return config.isRetryable(error);
  }

  // Use ApiError's built-in isRetryable method
  if (error.isRetryable()) {
    return true;
  }

  // Check if status code is in retryable list
  const { retryableStatusCodes = DEFAULT_RETRY_CONFIG.retryableStatusCodes } = config;
  const codes = retryableStatusCodes ?? DEFAULT_RETRY_CONFIG.retryableStatusCodes;
  if (error.statusCode && codes.has(error.statusCode)) {
    return true;
  }

  return false;
}

/**
 * Retry an async function with exponential backoff
 *
 * @param fn - The async function to retry
 * @param config - Retry configuration
 * @returns Promise that resolves with the function result or rejects after all retries
 */
export async function retryWithBackoff<T>(
  fn: () => Promise<T>,
  config: RetryConfig = {}
): Promise<T> {
  const { maxRetries: _maxRetries = DEFAULT_RETRY_CONFIG.maxRetries } = config;
  const maxRetries = _maxRetries ?? DEFAULT_RETRY_CONFIG.maxRetries;

  let lastError: Error | undefined;

  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    try {
      return await fn();
    } catch (error) {
      lastError = error as Error;

      // Check if we should retry
      const apiError = error instanceof ApiError ? error : parseErrorAsApiError(error);

      if (!isRetryableError(apiError, config)) {
        throw error; // Not retryable, fail immediately
      }

      // Don't delay after the last attempt
      if (attempt < maxRetries) {
        const delay = calculateDelay(attempt, config);
        await sleep(delay);
      }
    }
  }

  throw lastError;
}

/**
 * Sleep for a specified number of milliseconds
 *
 * @param ms - Milliseconds to sleep
 * @returns Promise that resolves after the delay
 */
function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Parse a generic error as ApiError for retry determination
 *
 * @param error - The error to parse
 * @returns ApiError instance
 */
function parseErrorAsApiError(error: unknown): ApiError {
  if (error instanceof ApiError) {
    return error;
  }

  // For non-ApiError errors, create a generic one
  // Import parseError dynamically to avoid circular dependency
  if (error instanceof Error) {
    return new ApiError('NETWORK' as any, 'UNKNOWN_ERROR', error.message);
  }

  return new ApiError('NETWORK' as any, 'UNKNOWN_ERROR', String(error));
}
