/**
 * useMediaQuery Hook
 *
 * A custom hook that tracks whether a CSS media query matches.
 * It listens for changes in the media query match status and updates
 * the return value accordingly.
 *
 * @param query - The CSS media query string to track
 * @returns Boolean indicating whether the media query currently matches
 *
 * @example
 * const isMobile = useMediaQuery('(max-width: 640px)');
 * const isDarkMode = useMediaQuery('(prefers-color-scheme: dark)');
 * const prefersReducedMotion = useMediaQuery('(prefers-reduced-motion: reduce)');
 */

import { useState, useEffect } from 'react';

export function useMediaQuery(query: string): boolean {
  // Default to false for SSR or when matchMedia is unavailable
  const getMatches = (query: string): boolean => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
      return false;
    }

    return window.matchMedia(query).matches;
  };

  const [matches, setMatches] = useState<boolean>(() => getMatches(query));

  useEffect(() => {
    // Skip if window or matchMedia is not available (SSR)
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
      return;
    }

    // Get media query list
    const mediaQueryList = window.matchMedia(query);

    // Define event handler
    const handleChange = (event: MediaQueryListEvent) => {
      setMatches(event.matches);
    };

    mediaQueryList.addEventListener('change', handleChange);
    return () => {
      mediaQueryList.removeEventListener('change', handleChange);
    };
  }, [query]);

  return matches;
}
