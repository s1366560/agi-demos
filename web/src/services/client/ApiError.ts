/**
 * Unified API Error Handling
 *
 * Provides a consistent error handling system for API operations.
 *
 * Features:
 * - Structured error types (network, auth, validation, etc.)
 * - User-friendly error messages
 * - Error code mapping for internationalization
 * - Integration with fetch and axios
 */

/**
 * API Error Types
 *
 * Categorizes errors for appropriate handling and user messaging.
 */
export enum ApiErrorType {
  /** Network connectivity issues (timeout, connection refused, etc.) */
  NETWORK = 'NETWORK',

  /** Authentication failures (not logged in, invalid token, etc.) */
  AUTHENTICATION = 'AUTHENTICATION',

  /** Authorization failures (insufficient permissions) */
  AUTHORIZATION = 'AUTHORIZATION',

  /** Input validation failures (invalid data format, missing fields, etc.) */
  VALIDATION = 'VALIDATION',

  /** Resource not found */
  NOT_FOUND = 'NOT_FOUND',

  /** Resource conflicts (duplicate, version mismatch, etc.) */
  CONFLICT = 'CONFLICT',

  /** Server-side errors (5xx) */
  SERVER = 'SERVER',

  /** Unknown or unexpected errors */
  UNKNOWN = 'UNKNOWN',
}

/**
 * User-friendly error message mapping
 *
 * Maps error codes to user-friendly messages.
 * These messages can be extracted for i18n.
 */
const ERROR_MESSAGES: Record<string, string> = {
  // Authentication errors
  INVALID_CREDENTIALS: 'Invalid email or password. Please try again.',
  INVALID_TOKEN: 'Your session has expired. Please login again.',
  UNAUTHORIZED: 'Please login to continue.',
  TOKEN_EXPIRED: 'Your session has expired. Please login again.',

  // Authorization errors
  INSUFFICIENT_PERMISSIONS: "You don't have permission to perform this action.",
  FORBIDDEN: "You don't have permission to access this resource.",

  // Validation errors
  INVALID_EMAIL: 'Please enter a valid email address.',
  INVALID_PASSWORD: 'Password must be at least 8 characters long.',
  INVALID_INPUT: 'Please check your input and try again.',
  REQUIRED_FIELD: 'This field is required.',
  VALIDATION_FAILED: 'Please check your input and try again.',

  // Not found errors
  TENANT_NOT_FOUND: 'The requested tenant could not be found.',
  PROJECT_NOT_FOUND: 'The requested project could not be found.',
  RESOURCE_NOT_FOUND: 'The requested resource could not be found.',
  USER_NOT_FOUND: 'User not found.',

  // Conflict errors
  DUPLICATE_RESOURCE: 'This resource already exists.',
  VERSION_CONFLICT: 'This resource was modified by another user. Please refresh and try again.',

  // Network errors
  NETWORK_ERROR: 'Network connection failed. Please check your internet connection.',
  TIMEOUT: 'The request timed out. Please try again.',
  CONNECTION_FAILED: 'Could not connect to the server. Please try again.',

  // Server errors
  INTERNAL_ERROR: 'An unexpected error occurred. Please try again later.',
  SERVICE_UNAVAILABLE: 'The service is temporarily unavailable. Please try again later.',
};

/**
 * User-friendly default messages by error type
 */
const DEFAULT_MESSAGES: Record<ApiErrorType, string> = {
  [ApiErrorType.AUTHENTICATION]: 'Please login to continue.',
  [ApiErrorType.AUTHORIZATION]: "You don't have permission to perform this action.",
  [ApiErrorType.VALIDATION]: 'Please check your input and try again.',
  [ApiErrorType.NOT_FOUND]: 'The requested resource could not be found.',
  [ApiErrorType.CONFLICT]: 'This resource already exists.',
  [ApiErrorType.NETWORK]: 'Network connection failed. Please check your internet connection.',
  [ApiErrorType.SERVER]: 'An unexpected error occurred. Please try again later.',
  [ApiErrorType.UNKNOWN]: 'An unexpected error occurred. Please try again.',
};

/**
 * Unified API Error Class
 *
 * Extends Error to provide structured error information for API operations.
 *
 * @example
 * try {
 *   await apiFetch.get('/tenants/123');
 * } catch (error) {
 *   if (error instanceof ApiError) {
 *     if (error.isType(ApiErrorType.AUTHENTICATION)) {
 *       // Redirect to login
 *     }
 *     console.log(error.getUserMessage());
 *   }
 * }
 */
export class ApiError extends Error {
  /**
   * Creates a new API error
   *
   * @param type - The category of error
   * @param code - Application-specific error code
   * @param message - Technical error message
   * @param statusCode - HTTP status code (if applicable)
   * @param details - Additional error details
   */
  constructor(
    public type: ApiErrorType,
    public code: string,
    message: string,
    public statusCode?: number,
    public details?: unknown
  ) {
    super(message);
    this.name = 'ApiError';

    // Maintains proper stack trace for where our error was thrown (only available on V8)
    if (Error.captureStackTrace) {
      Error.captureStackTrace(this, ApiError);
    }
  }

  /**
   * Get a user-friendly error message
   *
   * Returns a localized, user-friendly message based on the error code.
   * Falls back to the default message for the error type.
   *
   * @returns User-friendly error message
   */
  getUserMessage(): string {
    // Check for code-specific message first
    if (this.code && ERROR_MESSAGES[this.code]) {
      return ERROR_MESSAGES[this.code] ?? this.message;
    }

    // Fall back to type-specific default
    return DEFAULT_MESSAGES[this.type];
  }

  /**
   * Check if this error is of a specific type
   *
   * @param type - The error type to check
   * @returns True if this error matches the type
   *
   * @example
   * if (error.isType(ApiErrorType.AUTHENTICATION)) {
   *   // Handle auth error
   * }
   */
  isType(type: ApiErrorType): boolean {
    return this.type === type;
  }

  /**
   * Check if this is a network-related error
   */
  isNetworkError(): boolean {
    return this.type === ApiErrorType.NETWORK;
  }

  /**
   * Check if this is an authentication error
   */
  isAuthError(): boolean {
    return this.type === ApiErrorType.AUTHENTICATION;
  }

  /**
   * Check if user can retry the operation
   */
  isRetryable(): boolean {
    return (
      this.type === ApiErrorType.NETWORK ||
      this.type === ApiErrorType.SERVER ||
      this.code === 'TIMEOUT' ||
      this.code === 'SERVICE_UNAVAILABLE'
    );
  }

  /**
   * Convert to plain object for serialization
   */
  toJSON(): {
    type: ApiErrorType;
    code: string;
    message: string;
    statusCode?: number | undefined;
    details?: unknown | undefined;
    userMessage: string;
  } {
    return {
      type: this.type,
      code: this.code,
      message: this.message,
      statusCode: this.statusCode,
      details: this.details,
      userMessage: this.getUserMessage(),
    };
  }

  /**
   * Create ApiError from a plain object
   */
  static fromJSON(data: {
    type: ApiErrorType;
    code: string;
    message: string;
    statusCode?: number | undefined;
    details?: unknown | undefined;
  }): ApiError {
    return new ApiError(data.type, data.code, data.message, data.statusCode, data.details);
  }
}

/**
 * Parse error from Response object
 *
 * Used for fetch-based API calls (apiFetch).
 *
 * @param response - The failed Response object
 * @returns Parsed ApiError
 */
export async function parseResponseError(response: Response): Promise<ApiError> {
  let code = 'UNKNOWN_ERROR';
  let message = response.statusText || 'Request failed';
  let details: unknown;

  // Try to extract error details from response body
  try {
    const data = await response.json();
    if (data) {
      if (data.code) code = data.code;
      if (data.detail) message = data.detail;
      if (data.message) message = data.message;
      if (data.error) message = data.error;
      details = data;
    }
  } catch {
    // Response body is not JSON or empty, use status text
    message = response.statusText || `HTTP ${response.status}`;
  }

  // Determine error type and code from status code
  const { type, statusCode } = getErrorTypeFromStatus(response.status);

  // Use derived code if none provided
  if (code === 'UNKNOWN_ERROR') {
    code = getDefaultCodeForStatus(response.status);
  }

  return new ApiError(type, code, message, statusCode, details);
}

/**
 * Parse error from axios error object
 *
 * Used for httpClient (axios-based) API calls.
 *
 * @param error - The axios error
 * @returns Parsed ApiError
 */
export function parseAxiosError(error: unknown): ApiError {
  // If already an ApiError, return as-is
  if (error instanceof ApiError) {
    return error;
  }

  // Extract error information
  let type = ApiErrorType.UNKNOWN;
  let code = 'UNKNOWN_ERROR';
  let message = 'An unknown error occurred';
  let statusCode: number | undefined;
  let details: unknown;

  const err = error as {
    response?: {
      status?: number | undefined;
      data?: {
        detail?: string | undefined;
        code?: string | undefined;
        message?: string | undefined;
        error?: string | undefined;
      } | undefined;
    } | undefined;
    message?: string | undefined;
    code?: string | undefined;
  };

  // Handle axios response errors
  if (err.response) {
    const { type: responseType, statusCode: status } = getErrorTypeFromStatus(
      err.response.status || 0
    );
    type = responseType;
    statusCode = status;

    if (err.response.data) {
      if (err.response.data.code) code = err.response.data.code;
      if (err.response.data.detail) message = err.response.data.detail;
      if (err.response.data.message) message = err.response.data.message;
      if (err.response.data.error) message = err.response.data.error;
      details = err.response.data;
    } else {
      message = err.response.status ? `HTTP ${err.response.status}` : 'Request failed';
    }
  }
  // Handle network/timeout errors
  else if (err.message) {
    if (err.message.includes('timeout') || err.code === 'ECONNABORTED') {
      type = ApiErrorType.NETWORK;
      code = 'TIMEOUT';
      message = 'Request timeout. Please try again.';
    } else if (err.message.includes('Network') || err.code === 'ERR_NETWORK') {
      type = ApiErrorType.NETWORK;
      code = 'NETWORK_ERROR';
      message = 'Network connection failed. Please check your internet connection.';
    } else {
      message = err.message;
    }
  }

  return new ApiError(type, code, message, statusCode, details);
}

/**
 * Parse any error into ApiError
 *
 * Generic error parser that handles:
 * - ApiError instances (passthrough)
 * - Error instances
 * - Strings
 * - Unknown types
 *
 * @param error - The error to parse
 * @returns ApiError instance
 */
export function parseError(error: unknown): ApiError {
  // Already an ApiError
  if (error instanceof ApiError) {
    return error;
  }

  // Standard Error
  if (error instanceof Error) {
    return new ApiError(ApiErrorType.UNKNOWN, 'STANDARD_ERROR', error.message, undefined, {
      originalError: error.name,
    });
  }

  // String error
  if (typeof error === 'string') {
    return new ApiError(ApiErrorType.UNKNOWN, 'STRING_ERROR', error);
  }

  // Unknown type
  return new ApiError(ApiErrorType.UNKNOWN, 'UNKNOWN_ERROR', 'An unknown error occurred');
}

/**
 * Get error type from HTTP status code
 */
function getErrorTypeFromStatus(status: number): {
  type: ApiErrorType;
  statusCode: number;
} {
  if (status === 401) {
    return { type: ApiErrorType.AUTHENTICATION, statusCode: status };
  }
  if (status === 403) {
    return { type: ApiErrorType.AUTHORIZATION, statusCode: status };
  }
  if (status === 404) {
    return { type: ApiErrorType.NOT_FOUND, statusCode: status };
  }
  if (status === 409 || status === 409) {
    return { type: ApiErrorType.CONFLICT, statusCode: status };
  }
  if (status === 422 || status === 400) {
    return { type: ApiErrorType.VALIDATION, statusCode: status };
  }
  if (status >= 500) {
    return { type: ApiErrorType.SERVER, statusCode: status };
  }
  if (status === 0) {
    return { type: ApiErrorType.NETWORK, statusCode: status };
  }
  return { type: ApiErrorType.UNKNOWN, statusCode: status };
}

/**
 * Get default error code for HTTP status code
 */
function getDefaultCodeForStatus(status: number): string {
  const codes: Record<number, string> = {
    400: 'BAD_REQUEST',
    401: 'UNAUTHORIZED',
    403: 'FORBIDDEN',
    404: 'NOT_FOUND',
    409: 'CONFLICT',
    422: 'UNPROCESSABLE_ENTITY',
    500: 'INTERNAL_ERROR',
    502: 'BAD_GATEWAY',
    503: 'SERVICE_UNAVAILABLE',
    504: 'GATEWAY_TIMEOUT',
    0: 'NETWORK_ERROR',
  };
  return codes[status] || 'HTTP_ERROR';
}
