/**
 * useLocalStorage Hook
 *
 * A custom hook that synchronizes a state value with localStorage.
 * It handles JSON serialization, cross-tab sync via storage events,
 * and provides update/remove functionality.
 *
 * OPTIMIZED: Added in-memory cache to avoid repeated synchronous localStorage access
 * which can block the main thread. Cache is checked before localStorage.
 *
 * @template T - The type of the value to store
 * @param key - The localStorage key to use
 * @param initialValue - The initial value if no stored value exists
 * @returns An object with value, setValue, and removeValue
 *
 * @example
 * const { value, setValue, removeValue } = useLocalStorage('settings', { theme: 'dark' });
 * setValue({ ...value, theme: 'light' });
 */

import { useState, useEffect, useCallback } from 'react';

// In-memory cache for localStorage reads to avoid synchronous I/O
const localStorageCache = new Map<string, unknown>();

const serializeForLocalStorage = (value: unknown): string | null => {
  if (value === undefined || typeof value === 'function' || typeof value === 'symbol') {
    return null;
  }
  return JSON.stringify(value);
};

const LEGACY_RAW_STRING_KEY_PATTERN = /^agent(?::[^:]+)?:lastProjectId$/;

function readStoredValue<T>(key: string, item: string | null, initialValue: T): T {
  if (item === null) {
    return initialValue;
  }

  try {
    return JSON.parse(item) as T;
  } catch (error) {
    if (LEGACY_RAW_STRING_KEY_PATTERN.test(key) && item.trim().length > 0) {
      const migratedValue = item as T;
      const serialized = serializeForLocalStorage(migratedValue);
      if (serialized !== null) {
        try {
          window.localStorage.setItem(key, serialized);
        } catch {
          // The in-memory value is still usable even when storage write-back is unavailable.
        }
      }
      return migratedValue;
    }
    console.warn(`Error reading localStorage key "${key}":`, error);
    return initialValue;
  }
}

export interface UseLocalStorageReturn<T> {
  value: T;
  setValue: (value: T | ((prev: T) => T)) => void;
  removeValue: () => void;
}

export function useLocalStorage<T>(key: string, initialValue: T): UseLocalStorageReturn<T> {
  // Get initial value from cache or localStorage
  const readValue = useCallback((): T => {
    if (typeof window === 'undefined') {
      return initialValue;
    }

    // Check cache first (faster, avoids sync I/O)
    if (localStorageCache.has(key)) {
      return localStorageCache.get(key) as T;
    }

    try {
      const item = window.localStorage.getItem(key);
      const value = readStoredValue(key, item, initialValue);
      // Cache the value for future reads
      localStorageCache.set(key, value);
      return value;
    } catch (error) {
      console.warn(`Error reading localStorage key "${key}":`, error);
      return initialValue;
    }
  }, [initialValue, key]);

  const [storedValue, setStoredValue] = useState<T>(readValue);

  // Set value to localStorage and state
  // Use functional setState to avoid depending on storedValue
  // This prevents callback recreation on every state change (rerender-functional-setstate)
  const setValue = useCallback(
    (value: T | ((prev: T) => T)) => {
      setStoredValue((prevValue) => {
        try {
          const valueToStore = value instanceof Function ? value(prevValue) : value;

          // Update cache first (fastest for subsequent reads)
          localStorageCache.set(key, valueToStore);

          if (typeof window !== 'undefined') {
            const serialized = serializeForLocalStorage(valueToStore);
            if (serialized === null) {
              window.localStorage.removeItem(key);
            } else {
              window.localStorage.setItem(key, serialized);
            }
          }
          return valueToStore;
        } catch (error) {
          console.warn(`Error setting localStorage key "${key}":`, error);
          return prevValue;
        }
      });
    },
    [key]
  );

  // Remove value from localStorage and reset to initial
  const removeValue = useCallback(() => {
    // Update cache
    localStorageCache.delete(key);
    try {
      setStoredValue(initialValue);

      if (typeof window !== 'undefined') {
        window.localStorage.removeItem(key);
      }
    } catch (error) {
      console.warn(`Error removing localStorage key "${key}":`, error);
    }
  }, [key, initialValue]);

  // Listen for storage events (cross-tab sync)
  useEffect(() => {
    const handleStorageChange = (e: StorageEvent) => {
      if (e.key !== key || e.storageArea !== window.localStorage) {
        return;
      }

      try {
        const newValue = readStoredValue(key, e.newValue, initialValue);
        if (e.newValue === null) {
          localStorageCache.delete(key);
        } else {
          localStorageCache.set(key, newValue);
        }
        setStoredValue(newValue);
      } catch (error) {
        console.warn(`Error parsing storage event for key "${key}":`, error);
        setStoredValue(initialValue);
      }
    };

    window.addEventListener('storage', handleStorageChange);

    return () => {
      window.removeEventListener('storage', handleStorageChange);
    };
  }, [key, initialValue]);

  // Initialize localStorage on mount if no value exists
  useEffect(() => {
    const initializeValue = () => {
      try {
        const item = window.localStorage.getItem(key);
        if (item === null) {
          const serialized = serializeForLocalStorage(initialValue);
          if (serialized !== null) {
            window.localStorage.setItem(key, serialized);
          }
        }
      } catch (error) {
        console.warn(`Error initializing localStorage key "${key}":`, error);
      }
    };

    initializeValue();
  }, [key, initialValue]);

  return {
    value: storedValue,
    setValue,
    removeValue,
  };
}
