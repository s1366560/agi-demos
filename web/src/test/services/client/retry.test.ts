/**
 * Tests for retry module using TDD
 *
 * Tests written first (RED), then implementation (GREEN)
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  calculateDelay,
  isRetryableError,
  retryWithBackoff,
  DEFAULT_RETRY_CONFIG,
  type RetryConfig,
} from '@/services/client/retry';
import { ApiError, ApiErrorType } from '@/services/client/ApiError';

describe('calculateDelay', () => {
  it('should return initial delay for first retry (attempt 0)', () => {
    const delay = calculateDelay(0);
    expect(delay).toBeGreaterThanOrEqual(750); // 1000 - 25% jitter
    expect(delay).toBeLessThanOrEqual(1250);  // 1000 + 25% jitter
  });

  it('should double delay for each attempt with exponential backoff', () => {
    // With jitter disabled for predictable testing
    const config: RetryConfig = { jitter: false };

    const delay0 = calculateDelay(0, config);
    const delay1 = calculateDelay(1, config);
    const delay2 = calculateDelay(2, config);

    expect(delay1).toBe(delay0 * 2);
    expect(delay2).toBe(delay1 * 2);
  });

  it('should clamp delay to maxDelay', () => {
    const config: RetryConfig = {
      initialDelay: 1000,
      maxDelay: 3000,
      backoffMultiplier: 10,
      jitter: false,
    };

    // With multiplier of 10, delay would exceed maxDelay quickly
    const delay0 = calculateDelay(0, config);
    const delay1 = calculateDelay(1, config);

    expect(delay0).toBe(1000);
    expect(delay1).toBe(3000); // Clamped to maxDelay
  });

  it('should use custom initialDelay', () => {
    const config: RetryConfig = {
      initialDelay: 500,
      jitter: false,
    };

    const delay = calculateDelay(0, config);
    expect(delay).toBe(500);
  });

  it('should use custom backoffMultiplier', () => {
    const config: RetryConfig = {
      initialDelay: 1000,
      backoffMultiplier: 3,
      jitter: false,
    };

    const delay0 = calculateDelay(0, config);
    const delay1 = calculateDelay(1, config);

    expect(delay1).toBe(1000 * 3);
  });

  it('should add jitter when enabled (default)', () => {
    // Run multiple times to check randomness
    const delays = new Set<number>();
    for (let i = 0; i < 10; i++) {
      delays.add(calculateDelay(2));
    }

    // With jitter, we should get different values
    expect(delays.size).toBeGreaterThan(1);
  });

  it('should not add jitter when disabled', () => {
    const config: RetryConfig = { jitter: false };

    const delay0 = calculateDelay(0, config);
    const delay1 = calculateDelay(0, config);

    expect(delay0).toBe(delay1);
  });
});

describe('isRetryableError', () => {
  it('should return true for NETWORK type errors', () => {
    const error = new ApiError(
      ApiErrorType.NETWORK,
      'NETWORK_ERROR',
      'Connection failed'
    );

    expect(isRetryableError(error)).toBe(true);
  });

  it('should return true for SERVER type errors (5xx)', () => {
    const error = new ApiError(
      ApiErrorType.SERVER,
      'INTERNAL_ERROR',
      'Server error',
      500
    );

    expect(isRetryableError(error)).toBe(true);
  });

  it('should return true for TIMEOUT code errors', () => {
    const error = new ApiError(
      ApiErrorType.NETWORK,
      'TIMEOUT',
      'Request timeout'
    );

    expect(isRetryableError(error)).toBe(true);
  });

  it('should return true for SERVICE_UNAVAILABLE code errors', () => {
    const error = new ApiError(
      ApiErrorType.SERVER,
      'SERVICE_UNAVAILABLE',
      'Service unavailable'
    );

    expect(isRetryableError(error)).toBe(true);
  });

  it('should return false for AUTHENTICATION errors (4xx)', () => {
    const error = new ApiError(
      ApiErrorType.AUTHENTICATION,
      'UNAUTHORIZED',
      'Not authenticated',
      401
    );

    expect(isRetryableError(error)).toBe(false);
  });

  it('should return false for VALIDATION errors (4xx)', () => {
    const error = new ApiError(
      ApiErrorType.VALIDATION,
      'INVALID_INPUT',
      'Invalid input',
      400
    );

    expect(isRetryableError(error)).toBe(false);
  });

  it('should return false for NOT_FOUND errors', () => {
    const error = new ApiError(
      ApiErrorType.NOT_FOUND,
      'NOT_FOUND',
      'Resource not found',
      404
    );

    expect(isRetryableError(error)).toBe(false);
  });

  it('should return true for status code 408 (Request Timeout)', () => {
    const error = new ApiError(
      ApiErrorType.UNKNOWN,
      'REQUEST_TIMEOUT',
      'Request timeout',
      408
    );

    expect(isRetryableError(error)).toBe(true);
  });

  it('should return true for status code 429 (Too Many Requests)', () => {
    const error = new ApiError(
      ApiErrorType.UNKNOWN,
      'TOO_MANY_REQUESTS',
      'Rate limited',
      429
    );

    expect(isRetryableError(error)).toBe(true);
  });

  it('should return true for status code 502 (Bad Gateway)', () => {
    const error = new ApiError(
      ApiErrorType.SERVER,
      'BAD_GATEWAY',
      'Bad gateway',
      502
    );

    expect(isRetryableError(error)).toBe(true);
  });

  it('should return true for status code 503 (Service Unavailable)', () => {
    const error = new ApiError(
      ApiErrorType.SERVER,
      'SERVICE_UNAVAILABLE',
      'Service unavailable',
      503
    );

    expect(isRetryableError(error)).toBe(true);
  });

  it('should return true for status code 504 (Gateway Timeout)', () => {
    const error = new ApiError(
      ApiErrorType.SERVER,
      'GATEWAY_TIMEOUT',
      'Gateway timeout',
      504
    );

    expect(isRetryableError(error)).toBe(true);
  });

  it('should use custom isRetryable function when provided', () => {
    const error = new ApiError(
      ApiErrorType.NOT_FOUND,
      'NOT_FOUND',
      'Not found',
      404
    );

    // Normally NOT_FOUND is not retryable
    expect(isRetryableError(error)).toBe(false);

    // But with custom function, we can make it retryable
    const customConfig: RetryConfig = {
      isRetryable: () => true,
    };

    expect(isRetryableError(error, customConfig)).toBe(true);
  });

  it('should use custom retryableStatusCodes when provided', () => {
    const error = new ApiError(
      ApiErrorType.VALIDATION,
      'VALIDATION_ERROR',
      'Validation failed',
      422
    );

    // Default behavior
    expect(isRetryableError(error)).toBe(false);

    // With custom status codes
    const customConfig: RetryConfig = {
      retryableStatusCodes: new Set([422]),
    };

    expect(isRetryableError(error, customConfig)).toBe(true);
  });
});

describe('retryWithBackoff', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.runAllTimers(); // Complete any pending timers
    vi.useRealTimers();
  });

  it('should return result on first successful attempt', async () => {
    const fn = vi.fn().mockResolvedValue('success');

    const result = await retryWithBackoff(fn);

    expect(result).toBe('success');
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it('should retry on retryable errors', async () => {
    const fn = vi.fn()
      .mockRejectedValueOnce(new ApiError(
        ApiErrorType.NETWORK,
        'NETWORK_ERROR',
        'Connection failed'
      ))
      .mockResolvedValue('success');

    const config: RetryConfig = {
      maxRetries: 3,
      initialDelay: 100,
      jitter: false,
    };

    // Start the promise but don't await
    const promise = retryWithBackoff(fn, config);

    // First attempt fails immediately
    expect(fn).toHaveBeenCalledTimes(1);

    // Advance timer past first retry delay
    await vi.advanceTimersByTimeAsync(100);

    // Second attempt should succeed
    expect(fn).toHaveBeenCalledTimes(2);

    const result = await promise;
    expect(result).toBe('success');
  });

  it('should not retry on non-retryable errors', async () => {
    const fn = vi.fn().mockRejectedValue(
      new ApiError(
        ApiErrorType.VALIDATION,
        'INVALID_INPUT',
        'Invalid input',
        400
      )
    );

    const config: RetryConfig = {
      maxRetries: 3,
      initialDelay: 100,
    };

    await expect(retryWithBackoff(fn, config)).rejects.toThrow();
    expect(fn).toHaveBeenCalledTimes(1); // Only called once, no retries
  });

  it('should respect maxRetries limit', async () => {
    const fn = vi.fn().mockRejectedValue(
      new ApiError(
        ApiErrorType.NETWORK,
        'NETWORK_ERROR',
        'Connection failed'
      )
    );

    const config: RetryConfig = {
      maxRetries: 2,
      initialDelay: 50,
      jitter: false,
    };

    const promise = retryWithBackoff(fn, config);

    // Initial attempt
    expect(fn).toHaveBeenCalledTimes(1);

    // First retry
    await vi.advanceTimersByTimeAsync(50);
    expect(fn).toHaveBeenCalledTimes(2);

    // Second retry
    await vi.advanceTimersByTimeAsync(100); // 50 * 2
    expect(fn).toHaveBeenCalledTimes(3);

    // No more retries - should reject now
    await expect(promise).rejects.toThrow();
  });

  it('should use exponential backoff between retries', async () => {
    const fn = vi.fn()
      .mockRejectedValueOnce(new ApiError(
        ApiErrorType.NETWORK,
        'NETWORK_ERROR',
        'Connection failed'
      ))
      .mockRejectedValueOnce(new ApiError(
        ApiErrorType.NETWORK,
        'NETWORK_ERROR',
        'Connection failed'
      ))
      .mockResolvedValue('success');

    const config: RetryConfig = {
      maxRetries: 3,
      initialDelay: 100,
      backoffMultiplier: 2,
      jitter: false,
    };

    // const startTime = Date.now();
    const promise = retryWithBackoff(fn, config);

    // First attempt (fails)
    expect(fn).toHaveBeenCalledTimes(1);

    // Wait less than initial delay - no retry yet
    await vi.advanceTimersByTimeAsync(50);
    expect(fn).toHaveBeenCalledTimes(1);

    // Wait for initial delay - first retry
    await vi.advanceTimersByTimeAsync(50);
    expect(fn).toHaveBeenCalledTimes(2);

    // Wait for doubled delay (200ms) - second retry
    await vi.advanceTimersByTimeAsync(200);
    expect(fn).toHaveBeenCalledTimes(3);

    const result = await promise;
    expect(result).toBe('success');
  });

  it('should reject with last error after all retries exhausted', async () => {
    const fn = vi.fn().mockRejectedValue(
      new ApiError(
        ApiErrorType.NETWORK,
        'NETWORK_ERROR',
        'Connection failed'
      )
    );

    const config: RetryConfig = {
      maxRetries: 1,
      initialDelay: 10,
      jitter: false,
    };

    // Start the retry operation
    const promise = retryWithBackoff(fn, config);

    // Wait for all retries to complete
    await vi.advanceTimersByTimeAsync(30); // 10ms (initial) + 20ms (doubled) + buffer

    await expect(promise).rejects.toThrow('Connection failed');
  });

  it('should handle non-ApiError errors', async () => {
    const fn = vi.fn()
      .mockRejectedValueOnce(new Error('Network error'))
      .mockResolvedValue('success');

    const config: RetryConfig = {
      maxRetries: 2,
      initialDelay: 50,
      jitter: false,
    };

    const promise = retryWithBackoff(fn, config);

    await vi.advanceTimersByTimeAsync(50);

    const result = await promise;
    expect(result).toBe('success');
  });
});

describe('DEFAULT_RETRY_CONFIG', () => {
  it('should have correct default values', () => {
    expect(DEFAULT_RETRY_CONFIG.maxRetries).toBe(3);
    expect(DEFAULT_RETRY_CONFIG.initialDelay).toBe(1000);
    expect(DEFAULT_RETRY_CONFIG.maxDelay).toBe(10000);
    expect(DEFAULT_RETRY_CONFIG.backoffMultiplier).toBe(2);
    expect(DEFAULT_RETRY_CONFIG.jitter).toBe(true);
    expect(DEFAULT_RETRY_CONFIG.retryableStatusCodes).toBeInstanceOf(Set);
    expect(DEFAULT_RETRY_CONFIG.retryableStatusCodes).toContain(408);
    expect(DEFAULT_RETRY_CONFIG.retryableStatusCodes).toContain(429);
    expect(DEFAULT_RETRY_CONFIG.retryableStatusCodes).toContain(500);
    expect(DEFAULT_RETRY_CONFIG.retryableStatusCodes).toContain(502);
    expect(DEFAULT_RETRY_CONFIG.retryableStatusCodes).toContain(503);
    expect(DEFAULT_RETRY_CONFIG.retryableStatusCodes).toContain(504);
  });
});
