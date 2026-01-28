/**
 * Retry utility with exponential backoff strategy
 */

export interface RetryOptions {
  /**
   * Maximum number of retry attempts
   * @default 3
   */
  maxRetries?: number;

  /**
   * Initial delay before first retry in milliseconds
   * @default 1000
   */
  initialDelay?: number;

  /**
   * Maximum delay between retries in milliseconds
   * @default 10000
   */
  maxDelay?: number;

  /**
   * Multiplier for exponential backoff
   * @default 2
   */
  backoffMultiplier?: number;

  /**
   * Function to determine if an error is retryable
   * @default Retries network errors and 5xx status codes
   */
  retryable?: (error: unknown) => boolean;

  /**
   * Callback invoked before each retry attempt
   * @param attempt - The current attempt number (1-based)
   * @param error - The error that triggered the retry
   */
  onRetry?: (attempt: number, error: unknown) => void;
}

/**
 * Default retryable predicate that retries on network errors and 5xx status codes
 */
function isDefaultRetryable(error: unknown): boolean {
  if (error instanceof TypeError) {
    // Network errors (e.g., fetch failed, CORS issues)
    return true;
  }

  if (error instanceof Response) {
    // HTTP 5xx errors
    return error.status >= 500;
  }

  // Check for API-like error objects with status property
  const apiError = error as { status?: number; response?: { status?: number } };
  const status = apiError.status ?? apiError.response?.status;
  if (status && status >= 500) {
    return true;
  }

  // Check for AbortError (user cancelled, should not retry)
  if (error instanceof DOMException && error.name === 'AbortError') {
    return false;
  }

  return false;
}

/**
 * Delay function with jitter to prevent thundering herd
 * @param delay - Base delay in milliseconds
 * @returns Promise that resolves after the delayed time with jitter applied
 */
function delayWithJitter(delay: number): Promise<void> {
  // Add jitter: delay * (0.5 + Math.random() * 0.5)
  // This results in a value between 0.5x and 1.0x of the base delay
  const jitteredDelay = delay * (0.5 + Math.random() * 0.5);
  return new Promise((resolve) => setTimeout(resolve, jitteredDelay));
}

/**
 * Retry an async function with exponential backoff strategy
 *
 * @param fn - Async function to retry
 * @param options - Retry configuration options
 * @returns Promise that resolves with the result or rejects with the last error
 *
 * @example
 * ```ts
 * const result = await retryWithBackoff(
 *   () => fetch('/api/data').then(r => r.json()),
 *   { maxRetries: 5, initialDelay: 2000 }
 * );
 * ```
 *
 * @example
 * ```ts
 * const result = await retryWithBackoff(
 *   async () => {
 *     const response = await fetch('/api/data');
 *     if (!response.ok) throw response;
 *     return response.json();
 *   },
 *   {
 *     maxRetries: 3,
 *     retryable: (error) => error instanceof Response && error.status >= 500,
 *     onRetry: (attempt, error) => console.log(`Retry ${attempt}:`, error)
 *   }
 * );
 * ```
 */
export async function retryWithBackoff<T>(
  fn: () => Promise<T>,
  options: RetryOptions = {}
): Promise<T> {
  const {
    maxRetries = 3,
    initialDelay = 1000,
    maxDelay = 10000,
    backoffMultiplier = 2,
    retryable = isDefaultRetryable,
    onRetry,
  } = options;

  let lastError: unknown;

  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    try {
      return await fn();
    } catch (error) {
      lastError = error;

      // Check if we should retry and haven't exhausted attempts
      if (attempt < maxRetries && retryable(error)) {
        // Calculate delay: min(initialDelay * multiplier^attempt, maxDelay)
        const delay = Math.min(
          initialDelay * Math.pow(backoffMultiplier, attempt),
          maxDelay
        );

        // Call onRetry callback if provided
        onRetry?.(attempt + 1, error);

        // Wait with jitter before retrying
        await delayWithJitter(delay);
      } else {
        // Not retryable or exhausted retries, throw the error
        throw error;
      }
    }
  }

  // TypeScript unreachable, but keeps the type checker happy
  throw lastError;
}
