/**
 * useUrlState - Sync local UI state (e.g. selected tab, panel) to URL search params.
 *
 * Inspired by Routa's `kanban-tab.tsx` URL-state pattern: refresh, back/forward,
 * and shared links all restore the user's panel/tab selection.
 *
 * Behavior:
 * - Reads the initial value from `?<key>=...` (validated against `allowed`).
 * - Falls back to `defaultValue` when the param is missing or invalid.
 * - Calls `replaceState` (no history entry) on programmatic updates so tab
 *   switches don't pollute browser history.
 *
 * Usage:
 *   const [tab, setTab] = useUrlState<'tasks' | 'insights'>('panel', 'tasks', {
 *     allowed: ['tasks', 'insights'],
 *   });
 */

import { useCallback, useMemo } from 'react';

import { useSearchParams } from 'react-router-dom';

export interface UrlStateOptions<T extends string> {
  /** Allowed values; if provided, URL params outside this set are ignored. */
  allowed?: readonly T[];
  /** Use `pushState` (history entry) instead of the default `replaceState`. */
  pushHistory?: boolean;
}

export function useUrlState<T extends string>(
  key: string,
  defaultValue: T,
  options: UrlStateOptions<T> = {}
): [T, (next: T) => void] {
  const { allowed, pushHistory = false } = options;
  const [searchParams, setSearchParams] = useSearchParams();

  // Derive the current value directly from the URL on every render. This keeps
  // browser back/forward and external navigation in sync without needing a
  // useEffect+setState dance.
  const value = useMemo<T>(() => {
    const raw = searchParams.get(key);
    if (raw == null) return defaultValue;
    if (allowed && !allowed.includes(raw as T)) return defaultValue;
    return raw as T;
  }, [searchParams, key, defaultValue, allowed]);

  const update = useCallback(
    (next: T) => {
      setSearchParams(
        (prev) => {
          const updated = new URLSearchParams(prev);
          if (next === defaultValue) {
            // Keep URL clean: omit the param when it matches the default.
            updated.delete(key);
          } else {
            updated.set(key, next);
          }
          return updated;
        },
        { replace: !pushHistory }
      );
    },
    [setSearchParams, key, defaultValue, pushHistory]
  );

  return [value, update];
}
