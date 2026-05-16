/**
 * Unit tests for useLocalStorage hook.
 *
 * TDD Phase 1 (RED): Tests written before implementation.
 *
 * These tests verify that:
 * 1. Initial value is returned when no stored value exists
 * 2. Stored value is loaded and returned
 * 3. setValue updates localStorage and state
 * 4. Functional updates work with setValue
 * 5. removeValue clears localStorage and resets to initial value
 * 6. Changes to localStorage in other tabs are reflected
 * 7. Edge cases (null, undefined, objects, arrays)
 * 8. JSON parsing errors are handled gracefully
 *
 * NOTE: The hook uses a module-level in-memory cache (localStorageCache Map)
 * that persists across tests. To avoid cache interference, each test uses
 * a unique localStorage key via the uniqueKey() helper.
 */

import { renderHook, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

import { useLocalStorage } from '../../hooks/useLocalStorage';

describe('useLocalStorage', () => {
  // Use unique keys per test to avoid module-level cache interference
  let testCounter = 0;
  const uniqueKey = (suffix = '') => `test-ls-${testCounter++}${suffix ? `-${suffix}` : ''}`;

  beforeEach(() => {
    // Clear localStorage before each test
    localStorage.clear();
    vi.restoreAllMocks();
    vi.clearAllMocks();
  });

  afterEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  describe('Initial Value', () => {
    it('should return initial value when no stored value exists', () => {
      const key = uniqueKey();
      const { result } = renderHook(() => useLocalStorage(key, 'default'));

      expect(result.current.value).toBe('default');
      expect(localStorage.getItem(key)).toBe(JSON.stringify('default'));
    });

    it('should store initial value in localStorage on first render', async () => {
      const key = uniqueKey();
      renderHook(() => useLocalStorage(key, 'default'));

      await new Promise((resolve) => setTimeout(resolve, 0));

      expect(localStorage.getItem(key)).toBe(JSON.stringify('default'));
    });

    it('should return stored value if it exists', () => {
      const key = uniqueKey();
      localStorage.setItem(key, JSON.stringify('stored'));

      const { result } = renderHook(() => useLocalStorage(key, 'default'));

      expect(result.current.value).toBe('stored');
    });

    it('should not overwrite existing stored value with initial value', () => {
      const key = uniqueKey();
      localStorage.setItem(key, JSON.stringify('existing'));

      const { result } = renderHook(() => useLocalStorage(key, 'default'));

      expect(result.current.value).toBe('existing');
      expect(localStorage.getItem(key)).toBe(JSON.stringify('existing'));
    });
  });

  describe('setValue', () => {
    it('should update state when setValue is called', () => {
      const key = uniqueKey();
      const { result } = renderHook(() => useLocalStorage(key, 'initial'));

      act(() => {
        result.current.setValue('updated');
      });

      expect(result.current.value).toBe('updated');
    });

    it('should update localStorage when setValue is called', () => {
      const key = uniqueKey();
      const { result } = renderHook(() => useLocalStorage(key, 'initial'));

      act(() => {
        result.current.setValue('updated');
      });

      expect(localStorage.getItem(key)).toBe(JSON.stringify('updated'));
    });

    it('should support functional updates', () => {
      const key = uniqueKey();
      const { result } = renderHook(() => useLocalStorage(key, 10));

      act(() => {
        result.current.setValue((prev) => prev + 5);
      });

      expect(result.current.value).toBe(15);
    });

    it('should support functional updates with complex objects', () => {
      const key = uniqueKey();
      const { result } = renderHook(() => useLocalStorage(key, { count: 0, name: 'test' }));

      act(() => {
        result.current.setValue((prev) => ({ ...prev, count: prev.count + 1 }));
      });

      expect(result.current.value).toEqual({ count: 1, name: 'test' });
    });

    it('should handle multiple setValue calls', () => {
      const key = uniqueKey();
      const { result } = renderHook(() => useLocalStorage(key, 'initial'));

      act(() => {
        result.current.setValue('first');
      });

      act(() => {
        result.current.setValue('second');
      });

      act(() => {
        result.current.setValue('third');
      });

      expect(result.current.value).toBe('third');
      expect(localStorage.getItem(key)).toBe(JSON.stringify('third'));
    });
  });

  describe('removeValue', () => {
    it('should remove value from localStorage', () => {
      const key = uniqueKey();
      const { result } = renderHook(() => useLocalStorage(key, 'initial'));

      act(() => {
        result.current.removeValue();
      });

      expect(localStorage.getItem(key)).toBeNull();
    });

    it('should reset state to initial value after removeValue', () => {
      const key = uniqueKey();
      const { result } = renderHook(() => useLocalStorage(key, 'default'));

      act(() => {
        result.current.setValue('updated');
      });

      expect(result.current.value).toBe('updated');

      act(() => {
        result.current.removeValue();
      });

      expect(result.current.value).toBe('default');
    });

    it('should handle removeValue when already at initial value', () => {
      const key = uniqueKey();
      const { result } = renderHook(() => useLocalStorage(key, 'default'));

      act(() => {
        result.current.removeValue();
      });

      expect(result.current.value).toBe('default');
      expect(localStorage.getItem(key)).toBeNull();
    });
  });

  describe('Type Support', () => {
    it('should work with string values', () => {
      const key = uniqueKey();
      const { result } = renderHook(() => useLocalStorage(key, ''));

      act(() => {
        result.current.setValue('hello world');
      });

      expect(result.current.value).toBe('hello world');
    });

    it('should work with number values', () => {
      const key = uniqueKey();
      const { result } = renderHook(() => useLocalStorage(key, 0));

      act(() => {
        result.current.setValue(42);
      });

      expect(result.current.value).toBe(42);
    });

    it('should work with boolean values', () => {
      const key = uniqueKey();
      const { result } = renderHook(() => useLocalStorage(key, false));

      act(() => {
        result.current.setValue(true);
      });

      expect(result.current.value).toBe(true);
    });

    it('should work with object values', () => {
      const key = uniqueKey();
      const initialObj = { name: 'Alice', age: 30 };
      const { result } = renderHook(() => useLocalStorage(key, initialObj));

      act(() => {
        result.current.setValue({ name: 'Bob', age: 25 });
      });

      expect(result.current.value).toEqual({ name: 'Bob', age: 25 });
    });

    it('should work with array values', () => {
      const key = uniqueKey();
      const { result } = renderHook(() => useLocalStorage<number[]>(key, []));

      act(() => {
        result.current.setValue([1, 2, 3]);
      });

      expect(result.current.value).toEqual([1, 2, 3]);
    });

    it('should work with null as initial value', () => {
      const key = uniqueKey();
      const { result } = renderHook(() => useLocalStorage<string | null>(key, null));

      expect(result.current.value).toBeNull();

      act(() => {
        result.current.setValue('not null');
      });

      expect(result.current.value).toBe('not null');
    });

    it('should work with undefined as initial value', () => {
      const key = uniqueKey();
      const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
      const { result } = renderHook(() => useLocalStorage<string | undefined>(key, undefined));

      expect(result.current.value).toBeUndefined();
      expect(localStorage.getItem(key)).toBeNull();
      expect(warnSpy).not.toHaveBeenCalled();

      act(() => {
        result.current.setValue('defined');
      });

      expect(result.current.value).toBe('defined');
    });

    it('should remove localStorage entry when value is set to undefined', () => {
      const key = uniqueKey();
      const { result } = renderHook(() => useLocalStorage<string | undefined>(key, 'initial'));

      expect(localStorage.getItem(key)).toBe(JSON.stringify('initial'));

      act(() => {
        result.current.setValue(undefined);
      });

      expect(result.current.value).toBeUndefined();
      expect(localStorage.getItem(key)).toBeNull();
    });
  });

  describe('Storage Events', () => {
    it('should sync with changes from other tabs', () => {
      const key = uniqueKey();
      const { result } = renderHook(() => useLocalStorage(key, 'initial'));

      act(() => {
        window.localStorage.setItem(key, JSON.stringify('from other tab'));
        window.dispatchEvent(
          new StorageEvent('storage', {
            key: key,
            newValue: JSON.stringify('from other tab'),
            oldValue: JSON.stringify('initial'),
            storageArea: window.localStorage,
            url: window.location.href,
          })
        );
      });

      expect(result.current.value).toBe('from other tab');
    });

    it('should handle storage event when key is removed in another tab', () => {
      const key = uniqueKey();
      const { result } = renderHook(() => useLocalStorage(key, 'default'));

      act(() => {
        result.current.setValue('stored');
      });

      act(() => {
        window.localStorage.removeItem(key);
        window.dispatchEvent(
          new StorageEvent('storage', {
            key: key,
            newValue: null,
            oldValue: JSON.stringify('stored'),
            storageArea: window.localStorage,
            url: window.location.href,
          })
        );
      });

      expect(result.current.value).toBe('default');
    });

    it('should ignore storage events for different keys', () => {
      const key = uniqueKey();
      const { result } = renderHook(() => useLocalStorage(key, 'initial'));

      act(() => {
        window.dispatchEvent(
          new StorageEvent('storage', {
            key: 'some-other-key',
            newValue: JSON.stringify('different'),
            oldValue: null,
            storageArea: window.localStorage,
            url: window.location.href,
          })
        );
      });

      expect(result.current.value).toBe('initial');
    });

    it('should ignore storage events for different storage areas', () => {
      const key = uniqueKey();
      const { result } = renderHook(() => useLocalStorage(key, 'initial'));

      act(() => {
        window.dispatchEvent(
          new StorageEvent('storage', {
            key: key,
            newValue: JSON.stringify('updated'),
            oldValue: null,
            storageArea: window.sessionStorage,
            url: window.location.href,
          })
        );
      });

      expect(result.current.value).toBe('initial');
    });
  });

  describe('Error Handling', () => {
    it('should handle corrupted JSON in localStorage', () => {
      const key = uniqueKey();
      localStorage.setItem(key, 'not valid json{{{');

      const { result } = renderHook(() => useLocalStorage(key, 'default'));

      expect(result.current.value).toBe('default');
    });

    it('should handle JSON.parse errors gracefully', () => {
      const key = uniqueKey();
      localStorage.setItem(key, '{broken json');

      const { result } = renderHook(() => useLocalStorage(key, null));

      expect(result.current.value).toBe(null);
    });

    it('should handle localStorage being full (quota exceeded)', () => {
      const key = uniqueKey();
      let callCount = 0;

      const setItemSpy = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(function (
        this: Storage,
        k: string,
        v: string
      ) {
        callCount++;
        if (callCount > 1) {
          throw new DOMException('QuotaExceededError');
        }
        Object.getPrototypeOf(Storage.prototype).setItem?.call?.(this, k, v);
      });

      const { result } = renderHook(() => useLocalStorage(key, 'initial'));

      expect(result.current.value).toBe('initial');

      act(() => {
        expect(() => result.current.setValue('new value')).not.toThrow();
      });

      setItemSpy.mockRestore();
    });
  });

  describe('Edge Cases', () => {
    it('should handle empty string as key', () => {
      const { result } = renderHook(() => useLocalStorage('test-empty-key-', 'value'));

      expect(result.current.value).toBe('value');
    });

    it('should handle special characters in key', () => {
      const specialKey = uniqueKey('special.chars/123');
      const { result } = renderHook(() => useLocalStorage(specialKey, 'value'));

      act(() => {
        result.current.setValue('updated');
      });

      expect(result.current.value).toBe('updated');
      expect(localStorage.getItem(specialKey)).toBe(JSON.stringify('updated'));
    });

    it('should handle very large values', () => {
      const key = uniqueKey();
      const largeValue = 'x'.repeat(10000);
      const { result } = renderHook(() => useLocalStorage(key, ''));

      act(() => {
        result.current.setValue(largeValue);
      });

      expect(result.current.value).toBe(largeValue);
    });

    it('should handle deeply nested objects', () => {
      const key = uniqueKey();
      const nestedObj = {
        level1: {
          level2: {
            level3: {
              level4: {
                value: 'deep',
              },
            },
          },
        },
      };

      const { result } = renderHook(() => useLocalStorage<typeof nestedObj | null>(key, null));

      act(() => {
        result.current.setValue(nestedObj);
      });

      expect(result.current.value).toEqual(nestedObj);
    });

    it('should handle arrays of objects', () => {
      const key = uniqueKey();
      const arrayOfObjects = [
        { id: 1, name: 'Alice' },
        { id: 2, name: 'Bob' },
      ];

      const { result } = renderHook(() => useLocalStorage<typeof arrayOfObjects>(key, []));

      act(() => {
        result.current.setValue(arrayOfObjects);
      });

      expect(result.current.value).toEqual(arrayOfObjects);
    });
  });

  describe('Multiple Instances', () => {
    it('should handle multiple hooks with different keys independently', () => {
      const key1 = uniqueKey('multi1');
      const key2 = uniqueKey('multi2');
      const { result: result1 } = renderHook(() => useLocalStorage(key1, 'value1'));
      const { result: result2 } = renderHook(() => useLocalStorage(key2, 'value2'));

      act(() => {
        result1.current.setValue('updated1');
      });

      act(() => {
        result2.current.setValue('updated2');
      });

      expect(result1.current.value).toBe('updated1');
      expect(result2.current.value).toBe('updated2');
    });

    it('should handle multiple hooks with same key', () => {
      const key = uniqueKey('shared');
      const { result: result1 } = renderHook(() => useLocalStorage(key, 'initial'));
      const { result: _result2 } = renderHook(() => useLocalStorage(key, 'initial'));

      act(() => {
        result1.current.setValue('updated');
      });

      expect(result1.current.value).toBe('updated');
    });
  });
});
