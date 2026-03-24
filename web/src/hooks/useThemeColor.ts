/**
 * useThemeColor Hook
 *
 * Resolves CSS custom properties (design tokens from @theme) to actual hex color strings.
 * Required for APIs that cannot accept CSS var() references:
 *   - Ant Design component props (strokeColor, trailColor)
 *   - Recharts/SVG fill/stroke attributes
 *   - xterm.js ITheme color palette
 *
 * Listens for theme changes (light/dark) and re-resolves automatically.
 *
 * @example
 * ```tsx
 * const primary = useThemeColor('--color-primary');
 *
 * const colors = useThemeColors({
 *   primary: '--color-primary',
 *   success: '--color-success',
 *   error: '--color-error',
 * });
 * ```
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { useThemeStore } from '@/stores/theme';

function resolveVar(property: string, fallback = ''): string {
  if (typeof window === 'undefined') return fallback;
  const value = getComputedStyle(document.documentElement)
    .getPropertyValue(property)
    .trim();
  return value || fallback;
}

export function useThemeColor(property: string, fallback = ''): string {
  const computedTheme = useThemeStore((s) => s.computedTheme);
  const [resolved, setResolved] = useState(() => resolveVar(property, fallback));

  // biome-ignore lint/correctness/useExhaustiveDependencies: computedTheme triggers re-resolution on theme change
  useEffect(() => {
    const id = requestAnimationFrame(() => {
      setResolved(resolveVar(property, fallback));
    });
    return () => { cancelAnimationFrame(id); };
  }, [property, fallback, computedTheme]);

  return resolved;
}

export function useThemeColors<K extends string>(
  tokenMap: Record<K, string>,
): Record<K, string> {
  const computedTheme = useThemeStore((s) => s.computedTheme);
  const tokenMapRef = useRef(tokenMap);
  useEffect(() => {
    tokenMapRef.current = tokenMap;
  });

  const resolve = useCallback((): Record<K, string> => {
    const result = {} as Record<K, string>;
    const entries = Object.entries(tokenMapRef.current) as Array<[K, string]>;
    for (const [key, prop] of entries) {
      result[key] = resolveVar(prop);
    }
    return result;
  }, []);

  const [resolved, setResolved] = useState(() => {
    const result = {} as Record<K, string>;
    const entries = Object.entries(tokenMap) as Array<[K, string]>;
    for (const [key, prop] of entries) {
      result[key] = resolveVar(prop);
    }
    return result;
  });

  // biome-ignore lint/correctness/useExhaustiveDependencies: computedTheme triggers re-resolution on theme change
  useEffect(() => {
    const id = requestAnimationFrame(() => {
      setResolved(resolve());
    });
    return () => { cancelAnimationFrame(id); };
  }, [resolve, computedTheme]);

  return resolved;
}

/**
 * Non-hook utility: resolve a CSS custom property imperatively.
 * Use outside React components (e.g., xterm.js terminal init).
 */
export function resolveThemeColor(property: string, fallback = ''): string {
  return resolveVar(property, fallback);
}
