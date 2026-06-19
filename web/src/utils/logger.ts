/**
 * Logger Utility
 *
 * Environment-aware logging with consistent prefixes.
 *
 * - `debug` and `info` are opt-in, even in development
 * - `warn` and `error` always output
 * - All messages have level prefixes: [DEBUG], [INFO], [WARN], [ERROR]
 */

/**
 * Logger method type accepting variable arguments
 */
type LogMethod = (...args: unknown[]) => void;

const VERBOSE_LOG_LIMIT_PER_WINDOW = 120;
const VERBOSE_LOG_WINDOW_MS = 1000;

let verboseLogWindowStartedAt = 0;
let verboseLogCount = 0;

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
 * Check whether verbose logs are explicitly enabled.
 *
 * Dev sessions can emit thousands of WebSocket/timeline events during tenant
 * switches. Keep verbose logs off by default and require a deliberate opt-in.
 */
function isTruthyFlag(value: unknown): boolean {
  return typeof value === 'string' && ['1', 'true', 'yes', 'on'].includes(value.toLowerCase());
}

const isVerboseLoggingEnabled = (): boolean => {
  if (
    isTruthyFlag(import.meta.env.VITE_ENABLE_DEBUG_LOGS) ||
    isTruthyFlag(import.meta.env.VITE_DEBUG_LOGS)
  ) {
    return true;
  }

  try {
    return (
      typeof localStorage !== 'undefined' &&
      isTruthyFlag(localStorage.getItem('memstack:debugLogs'))
    );
  } catch {
    return false;
  }
};

const shouldEmitVerboseLog = (): boolean => {
  const now = Date.now();

  if (now - verboseLogWindowStartedAt >= VERBOSE_LOG_WINDOW_MS) {
    verboseLogWindowStartedAt = now;
    verboseLogCount = 0;
  }

  if (verboseLogCount >= VERBOSE_LOG_LIMIT_PER_WINDOW) {
    return false;
  }

  verboseLogCount += 1;
  return true;
};

/**
 * Logger implementation
 */
export const logger: Logger = {
  /**
   * Debug level - opt-in only
   */
  debug: (...args: unknown[]): void => {
    if (isVerboseLoggingEnabled() && shouldEmitVerboseLog()) {
      console.log('[DEBUG]', ...args);
    }
  },

  /**
   * Info level - opt-in only
   */
  info: (...args: unknown[]): void => {
    if (isVerboseLoggingEnabled() && shouldEmitVerboseLog()) {
      console.info('[INFO]', ...args);
    }
  },

  /**
   * Warn level - always enabled
   */
  warn: (...args: unknown[]): void => {
    console.warn('[WARN]', ...args);
  },

  /**
   * Error level - always enabled
   */
  error: (...args: unknown[]): void => {
    console.error('[ERROR]', ...args);
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
