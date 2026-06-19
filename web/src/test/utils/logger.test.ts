/**
 * Logger utility tests
 *
 * TDD Approach:
 * 1. Write tests first (RED)
 * 2. Run tests - they should fail
 * 3. Implement logger (GREEN)
 * 4. Refactor if needed
 * 5. Run tests to verify
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

import { logger } from '../../utils/logger';

describe('logger', () => {
  // Store original console methods
  const originalConsole = {
    log: console.log,
    info: console.info,
    warn: console.warn,
    error: console.error,
  };

  // Track calls
  const mockCalls = {
    log: [] as unknown[][],
    info: [] as unknown[][],
    warn: [] as unknown[][],
    error: [] as unknown[][],
  };

  beforeEach(() => {
    // Clear call tracking
    mockCalls.log = [];
    mockCalls.info = [];
    mockCalls.warn = [];
    mockCalls.error = [];

    // Replace console methods with tracking functions
    console.log = (...args: unknown[]) => mockCalls.log.push(args);
    console.info = (...args: unknown[]) => mockCalls.info.push(args);
    console.warn = (...args: unknown[]) => mockCalls.warn.push(args);
    console.error = (...args: unknown[]) => mockCalls.error.push(args);
  });

  afterEach(() => {
    // Restore original console methods
    console.log = originalConsole.log;
    console.info = originalConsole.info;
    console.warn = originalConsole.warn;
    console.error = originalConsole.error;
    vi.useRealTimers();
  });

  describe('logger types', () => {
    it('should have correct method signatures', () => {
      expect(typeof logger.debug).toBe('function');
      expect(typeof logger.info).toBe('function');
      expect(typeof logger.warn).toBe('function');
      expect(typeof logger.error).toBe('function');
    });
  });

  describe('verbose logs', () => {
    beforeEach(() => {
      localStorage.removeItem('memstack:debugLogs');
    });

    it('should not output debug or info messages by default', () => {
      logger.debug('test debug message');
      logger.info('test info message');

      expect(mockCalls.log).toHaveLength(0);
      expect(mockCalls.info).toHaveLength(0);
    });

    it('should output debug messages with [DEBUG] prefix when explicitly enabled', () => {
      localStorage.setItem('memstack:debugLogs', 'true');

      logger.debug('test debug message');
      logger.debug('test with param', 42, { key: 'value' });

      expect(mockCalls.log).toHaveLength(2);
      expect(mockCalls.log[0]).toContain('[DEBUG]');
      expect(mockCalls.log[0]).toContain('test debug message');
    });

    it('should output info messages with [INFO] prefix when explicitly enabled', () => {
      localStorage.setItem('memstack:debugLogs', '1');

      logger.info('test info message');

      expect(mockCalls.info).toHaveLength(1);
      expect(mockCalls.info[0]).toContain('[INFO]');
      expect(mockCalls.info[0]).toContain('test info message');
    });

    it('should rate limit verbose logs to keep browser consoles responsive', () => {
      vi.useFakeTimers();
      vi.setSystemTime(2_000_000_000_000);
      localStorage.setItem('memstack:debugLogs', 'true');

      for (let index = 0; index < 130; index += 1) {
        logger.debug('burst debug message', index);
      }

      expect(mockCalls.log).toHaveLength(120);

      vi.advanceTimersByTime(1000);
      logger.debug('next window debug message');

      expect(mockCalls.log).toHaveLength(121);
    });

    it('should output warn messages with [WARN] prefix', () => {
      logger.warn('test warn message');

      expect(mockCalls.warn.length).toBe(1);
      expect(mockCalls.warn[0]).toContain('[WARN]');
      expect(mockCalls.warn[0]).toContain('test warn message');
    });

    it('should output error messages with [ERROR] prefix', () => {
      logger.error('test error message');

      expect(mockCalls.error.length).toBe(1);
      expect(mockCalls.error[0]).toContain('[ERROR]');
      expect(mockCalls.error[0]).toContain('test error message');
    });

    it('should pass multiple arguments correctly', () => {
      const error = new Error('test error');
      logger.error('Something went wrong', error, { context: 'test' });

      expect(mockCalls.error.length).toBe(1);
      expect(mockCalls.error[0]).toContain('[ERROR]');
      expect(mockCalls.error[0]).toContain('Something went wrong');
      expect(mockCalls.error[0]).toContain(error);
    });

    it('should accept any number of arguments', () => {
      expect(() => logger.debug()).not.toThrow();
      expect(() => logger.debug('one')).not.toThrow();
      expect(() => logger.debug('one', 'two')).not.toThrow();
      expect(() => logger.debug('one', 'two', 'three')).not.toThrow();
      expect(() => logger.debug('one', 'two', 'three', 'four')).not.toThrow();
    });
  });

  describe('warn and error always work', () => {
    it('should always output warn messages regardless of environment', () => {
      logger.warn('warning message');

      expect(mockCalls.warn.length).toBe(1);
      expect(mockCalls.warn[0][0]).toBe('[WARN]');
      expect(mockCalls.warn[0][1]).toBe('warning message');
    });

    it('should always output error messages regardless of environment', () => {
      logger.error('error message');

      expect(mockCalls.error.length).toBe(1);
      expect(mockCalls.error[0][0]).toBe('[ERROR]');
      expect(mockCalls.error[0][1]).toBe('error message');
    });

    it('should handle complex error objects', () => {
      const err = new Error('test error');
      logger.error('Failed to load data', err);

      expect(mockCalls.error.length).toBe(1);
      expect(mockCalls.error[0][0]).toBe('[ERROR]');
      expect(mockCalls.error[0][1]).toBe('Failed to load data');
      expect(mockCalls.error[0][2]).toBe(err);
    });
  });
});
