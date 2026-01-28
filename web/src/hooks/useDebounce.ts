/**
 * useDebounce Hook
 *
 * A custom hook that returns a debounced version of the provided value.
 * The debounced value will only update after the specified delay has passed
 * without the value changing again.
 *
 * @template T - The type of the value to debounce
 * @param value - The value to debounce
 * @param delay - The debounce delay in milliseconds
 * @returns The debounced value
 *
 * @example
 * const debouncedSearchTerm = useDebounce(searchTerm, 500);
 * useEffect(() => {
 *   // This will only run 500ms after searchTerm stops changing
 *   if (debouncedSearchTerm) {
 *     performSearch(debouncedSearchTerm);
 *   }
 * }, [debouncedSearchTerm]);
 */

import { useState, useEffect, useRef } from 'react';

export function useDebounce<T>(value: T, delay: number): T {
  // Track the debounced value
  const [debouncedValue, setDebouncedValue] = useState<T>(value);

  // Store timeout reference to clear on cleanup
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    // Clear any existing timeout
    if (timeoutRef.current !== null) {
      clearTimeout(timeoutRef.current);
    }

    // Set new timeout to update debounced value
    timeoutRef.current = setTimeout(() => {
      setDebouncedValue(value);
    }, delay);

    // Cleanup function to clear timeout on unmount or before new effect
    return () => {
      if (timeoutRef.current !== null) {
        clearTimeout(timeoutRef.current);
      }
    };
  }, [value, delay]);

  return debouncedValue;
}
