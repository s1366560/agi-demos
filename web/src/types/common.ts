/**
 * Common utility types used across the application
 */

/**
 * API Error response structure
 */
export interface ApiErrorResponse {
  detail?: string | Record<string, unknown>;
  message?: string;
  status_code?: number;
}

/**
 * Unknown error type with optional response data
 * Used for catch blocks where the error type is not guaranteed
 */
export interface UnknownError extends Error {
  response?: {
    data?: ApiErrorResponse;
    status?: number;
  };
  code?: string;
}

/**
 * Type guard to check if an object is an UnknownError
 */
export function isUnknownError(error: unknown): error is UnknownError {
  return (
    error instanceof Error || (typeof error === 'object' && error !== null && 'message' in error)
  );
}

/**
 * Extract error message from an unknown error
 */
export function getErrorMessage(error: unknown): string {
  if (isUnknownError(error)) {
    if (error.response?.data?.detail) {
      const detail = error.response.data.detail;
      return typeof detail === 'string' ? detail : JSON.stringify(detail);
    }
    if (error.message) {
      return error.message;
    }
  }
  return 'An unknown error occurred';
}
