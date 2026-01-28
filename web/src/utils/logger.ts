/**
 * Logger Utility
 *
 * Environment-aware logging with consistent prefixes.
 *
 * - `debug` and `info` only output in development
 * - `warn` and `error` always output
 * - All messages have level prefixes: [DEBUG], [INFO], [WARN], [ERROR]
 */

/**
 * Logger method type accepting variable arguments
 */
type LogMethod = (...args: unknown[]) => void;

/**
 * Logger interface with all log levels
 */
export interface Logger {
  debug: LogMethod;
  info: LogMethod;
  warn: LogMethod;
  error: LogMethod;
}

/**
 * Check if we are in development mode
 *
 * Uses Vite's MODE env var which is set to 'development' in dev
 * and 'production' in build. Also enables debug in test mode.
 * Falls back to NODE_ENV for compatibility.
 */
const isDevelopment = (): boolean => {
  // Vite sets MODE automatically
  if (import.meta.env) {
    return import.meta.env.MODE === "development" || import.meta.env.MODE === "test";
  }
  // Fallback to NODE_ENV for Node.js environments
  if (typeof process !== "undefined" && process.env?.NODE_ENV) {
    return ["development", "test"].includes(process.env.NODE_ENV);
  }
  return false;
};

const dev = isDevelopment();

/**
 * No-op function for disabled logging
 */
const noop = (): void => {};

/**
 * Logger implementation
 */
export const logger: Logger = {
  /**
   * Debug level - only in development
   */
  debug: dev
    ? (...args: unknown[]): void => {
        console.log("[DEBUG]", ...args);
      }
    : noop,

  /**
   * Info level - only in development
   */
  info: dev
    ? (...args: unknown[]): void => {
        console.info("[INFO]", ...args);
      }
    : noop,

  /**
   * Warn level - always enabled
   */
  warn: (...args: unknown[]): void => {
    console.warn("[WARN]", ...args);
  },

  /**
   * Error level - always enabled
   */
  error: (...args: unknown[]): void => {
    console.error("[ERROR]", ...args);
  },
};

/**
 * Export types for external use
 */
export type { LogMethod };

/**
 * Default export
 */
export default logger;
