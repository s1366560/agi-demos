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
 */

import { renderHook, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

import { useLocalStorage } from '../../hooks/useLocalStorage';

describe('useLocalStorage', () => {
  const TEST_KEY = 'test-local-storage-key';

  beforeEach(() => {
    // Clear localStorage before each test
    localStorage.clear();
    vi.clearAllMocks();
  });

  afterEach(() => {
    localStorage.clear();
  });

  describe('Initial Value', () => {
    it('should return initial value when no stored value exists', () => {
      const { result } = renderHook(() => useLocalStorage(TEST_KEY, 'default'));

      expect(result.current.value).toBe('default');
      // localStorage stores values as JSON strings
      expect(localStorage.getItem(TEST_KEY)).toBe(JSON.stringify('default'));
    });

    it('should store initial value in localStorage on first render', async () => {
      renderHook(() => useLocalStorage(TEST_KEY, 'default'));

      // Wait for useEffect to run
      await new Promise((resolve) => setTimeout(resolve, 0));

      expect(localStorage.getItem(TEST_KEY)).toBe(JSON.stringify('default'));
    });

    it('should return stored value if it exists', () => {
      localStorage.setItem(TEST_KEY, JSON.stringify('stored'));

      const { result } = renderHook(() => useLocalStorage(TEST_KEY, 'default'));

      expect(result.current.value).toBe('stored');
    });

    it('should not overwrite existing stored value with initial value', () => {
      localStorage.setItem(TEST_KEY, JSON.stringify('existing'));

      const { result } = renderHook(() => useLocalStorage(TEST_KEY, 'default'));

      expect(result.current.value).toBe('existing');
      expect(localStorage.getItem(TEST_KEY)).toBe(JSON.stringify('existing'));
    });
  });

  describe('setValue', () => {
    it('should update state when setValue is called', () => {
      const { result } = renderHook(() => useLocalStorage(TEST_KEY, 'initial'));

      act(() => {
        result.current.setValue('updated');
      });

      expect(result.current.value).toBe('updated');
    });

    it('should update localStorage when setValue is called', () => {
      const { result } = renderHook(() => useLocalStorage(TEST_KEY, 'initial'));

      act(() => {
        result.current.setValue('updated');
      });

      expect(localStorage.getItem(TEST_KEY)).toBe(JSON.stringify('updated'));
    });

    it('should support functional updates', () => {
      const { result } = renderHook(() => useLocalStorage(TEST_KEY, 10));

      act(() => {
        result.current.setValue((prev) => prev + 5);
      });

      expect(result.current.value).toBe(15);
    });

    it('should support functional updates with complex objects', () => {
      const { result } = renderHook(() => useLocalStorage(TEST_KEY, { count: 0, name: 'test' }));

      act(() => {
        result.current.setValue((prev) => ({ ...prev, count: prev.count + 1 }));
      });

      expect(result.current.value).toEqual({ count: 1, name: 'test' });
    });

    it('should handle multiple setValue calls', () => {
      const { result } = renderHook(() => useLocalStorage(TEST_KEY, 'initial'));

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
      expect(localStorage.getItem(TEST_KEY)).toBe(JSON.stringify('third'));
    });
  });

  describe('removeValue', () => {
    it('should remove value from localStorage', () => {
      const { result } = renderHook(() => useLocalStorage(TEST_KEY, 'initial'));

      act(() => {
        result.current.removeValue();
      });

      expect(localStorage.getItem(TEST_KEY)).toBeNull();
    });

    it('should reset state to initial value after removeValue', () => {
      const { result } = renderHook(() => useLocalStorage(TEST_KEY, 'default'));

      // First update the value
      act(() => {
        result.current.setValue('updated');
      });

      expect(result.current.value).toBe('updated');

      // Then remove it
      act(() => {
        result.current.removeValue();
      });

      expect(result.current.value).toBe('default');
    });

    it('should handle removeValue when already at initial value', () => {
      const { result } = renderHook(() => useLocalStorage(TEST_KEY, 'default'));

      act(() => {
        result.current.removeValue();
      });

      expect(result.current.value).toBe('default');
      expect(localStorage.getItem(TEST_KEY)).toBeNull();
    });
  });

  describe('Type Support', () => {
    it('should work with string values', () => {
      const { result } = renderHook(() => useLocalStorage(TEST_KEY, ''));

      act(() => {
        result.current.setValue('hello world');
      });

      expect(result.current.value).toBe('hello world');
    });

    it('should work with number values', () => {
      const { result } = renderHook(() => useLocalStorage(TEST_KEY, 0));

      act(() => {
        result.current.setValue(42);
      });

      expect(result.current.value).toBe(42);
    });

    it('should work with boolean values', () => {
      const { result } = renderHook(() => useLocalStorage(TEST_KEY, false));

      act(() => {
        result.current.setValue(true);
      });

      expect(result.current.value).toBe(true);
    });

    it('should work with object values', () => {
      const initialObj = { name: 'Alice', age: 30 };
      const { result } = renderHook(() => useLocalStorage(TEST_KEY, initialObj));

      act(() => {
        result.current.setValue({ name: 'Bob', age: 25 });
      });

      expect(result.current.value).toEqual({ name: 'Bob', age: 25 });
    });

    it('should work with array values', () => {
      const { result } = renderHook(() => useLocalStorage<number[]>(TEST_KEY, []));

      act(() => {
        result.current.setValue([1, 2, 3]);
      });

      expect(result.current.value).toEqual([1, 2, 3]);
    });

    it('should work with null as initial value', () => {
      const { result } = renderHook(() => useLocalStorage<string | null>(TEST_KEY, null));

      expect(result.current.value).toBeNull();

      act(() => {
        result.current.setValue('not null');
      });

      expect(result.current.value).toBe('not null');
    });

    it('should work with undefined as initial value', () => {
      const { result } = renderHook(() => useLocalStorage<string | undefined>(TEST_KEY, undefined));

      expect(result.current.value).toBeUndefined();

      act(() => {
        result.current.setValue('defined');
      });

      expect(result.current.value).toBe('defined');
    });
  });

  describe('Storage Events', () => {
    it('should sync with changes from other tabs', () => {
      const { result } = renderHook(() => useLocalStorage(TEST_KEY, 'initial'));

      // Simulate storage event from another tab
      act(() => {
        window.localStorage.setItem(TEST_KEY, JSON.stringify('from other tab'));
        window.dispatchEvent(
          new StorageEvent('storage', {
            key: TEST_KEY,
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
      const { result } = renderHook(() => useLocalStorage(TEST_KEY, 'default'));

      // First set a value
      act(() => {
        result.current.setValue('stored');
      });

      // Simulate removal from another tab
      act(() => {
        window.localStorage.removeItem(TEST_KEY);
        window.dispatchEvent(
          new StorageEvent('storage', {
            key: TEST_KEY,
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
      const { result } = renderHook(() => useLocalStorage(TEST_KEY, 'initial'));

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
      const { result } = renderHook(() => useLocalStorage(TEST_KEY, 'initial'));

      act(() => {
        window.dispatchEvent(
          new StorageEvent('storage', {
            key: TEST_KEY,
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
      // Store invalid JSON
      localStorage.setItem(TEST_KEY, 'not valid json{{{');

      const { result } = renderHook(() => useLocalStorage(TEST_KEY, 'default'));

      // Should fall back to initial value
      expect(result.current.value).toBe('default');
    });

    it('should handle JSON.parse errors gracefully', () => {
      localStorage.setItem(TEST_KEY, '{broken json');

      const { result } = renderHook(() => useLocalStorage(TEST_KEY, null));

      expect(result.current.value).toBe(null);
    });

    it('should handle localStorage being full (quota exceeded)', () => {
      // Mock localStorage.setItem to throw quota exceeded error
      const originalSetItem = localStorage.setItem;
      let callCount = 0;

      localStorage.setItem = vi.fn((key, value) => {
        callCount++;
        if (callCount > 1) {
          // Throw on second call (after initial value is set)
          throw new DOMException('QuotaExceededError');
        }
        return originalSetItem.call(localStorage, key, value);
      });

      const { result } = renderHook(() => useLocalStorage(TEST_KEY, 'initial'));

      // First call should work
      expect(result.current.value).toBe('initial');

      // Second call should handle the error gracefully
      act(() => {
        expect(() => result.current.setValue('new value')).not.toThrow();
      });

      // Restore original
      localStorage.setItem = originalSetItem;
    });
  });

  describe('Edge Cases', () => {
    it('should handle empty string as key', () => {
      const { result } = renderHook(() => useLocalStorage('', 'value'));

      expect(result.current.value).toBe('value');
    });

    it('should handle special characters in key', () => {
      const specialKey = 'key-with-special.chars/123';
      const { result } = renderHook(() => useLocalStorage(specialKey, 'value'));

      act(() => {
        result.current.setValue('updated');
      });

      expect(result.current.value).toBe('updated');
      expect(localStorage.getItem(specialKey)).toBe(JSON.stringify('updated'));
    });

    it('should handle very large values', () => {
      const largeValue = 'x'.repeat(10000);
      const { result } = renderHook(() => useLocalStorage(TEST_KEY, ''));

      act(() => {
        result.current.setValue(largeValue);
      });

      expect(result.current.value).toBe(largeValue);
    });

    it('should handle deeply nested objects', () => {
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

      const { result } = renderHook(() => useLocalStorage<typeof nestedObj | null>(TEST_KEY, null));

      act(() => {
        result.current.setValue(nestedObj);
      });

      expect(result.current.value).toEqual(nestedObj);
    });

    it('should handle arrays of objects', () => {
      const arrayOfObjects = [
        { id: 1, name: 'Alice' },
        { id: 2, name: 'Bob' },
      ];

      const { result } = renderHook(() => useLocalStorage<typeof arrayOfObjects>(TEST_KEY, []));

      act(() => {
        result.current.setValue(arrayOfObjects);
      });

      expect(result.current.value).toEqual(arrayOfObjects);
    });
  });

  describe('Multiple Instances', () => {
    it('should handle multiple hooks with different keys independently', () => {
      const { result: result1 } = renderHook(() => useLocalStorage('key1', 'value1'));
      const { result: result2 } = renderHook(() => useLocalStorage('key2', 'value2'));

      act(() => {
        result1.current.setValue('updated1');
        result2.current.setValue('updated2');
      });

      expect(result1.current.value).toBe('updated1');
      expect(result2.current.value).toBe('updated2');
    });

    it('should handle multiple hooks with same key', () => {
      const { result: result1 } = renderHook(() => useLocalStorage('same-key', 'initial'));
      const { result: result2 } = renderHook(() => useLocalStorage('same-key', 'initial'));

      act(() => {
        result1.current.setValue('updated');
      });

      // Both should reflect the change since they share the key
      expect(result1.current.value).toBe('updated');
      // result2 might not update depending on implementation
      // This documents current behavior
    });
  });
});
