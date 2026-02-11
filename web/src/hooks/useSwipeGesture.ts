/**
 * useSwipeGesture - Detect horizontal swipe gestures via pointer events
 *
 * Returns a ref to attach to the swipe-sensitive element.
 * Calls onSwipeLeft / onSwipeRight when a qualifying swipe is detected.
 */

import { useRef, useEffect, useCallback } from 'react';

interface SwipeGestureOptions {
  onSwipeLeft?: () => void;
  onSwipeRight?: () => void;
  /** Minimum horizontal distance (px) to qualify as swipe */
  threshold?: number;
  /** Maximum vertical distance (px) -- reject diagonal swipes */
  maxVertical?: number;
  /** Only trigger on touch (not mouse) */
  touchOnly?: boolean;
}

export function useSwipeGesture<T extends HTMLElement = HTMLDivElement>(
  options: SwipeGestureOptions
) {
  const ref = useRef<T>(null);
  const startRef = useRef<{ x: number; y: number; time: number } | null>(null);

  const { onSwipeLeft, onSwipeRight, threshold = 80, maxVertical = 60, touchOnly = true } = options;

  const handlePointerDown = useCallback(
    (e: PointerEvent) => {
      if (touchOnly && e.pointerType !== 'touch') return;
      startRef.current = { x: e.clientX, y: e.clientY, time: Date.now() };
    },
    [touchOnly]
  );

  const handlePointerUp = useCallback(
    (e: PointerEvent) => {
      if (!startRef.current) return;
      if (touchOnly && e.pointerType !== 'touch') return;

      const dx = e.clientX - startRef.current.x;
      const dy = Math.abs(e.clientY - startRef.current.y);
      const elapsed = Date.now() - startRef.current.time;
      startRef.current = null;

      // Must be quick (< 500ms), horizontal enough, and long enough
      if (elapsed > 500 || dy > maxVertical || Math.abs(dx) < threshold) return;

      if (dx > 0) {
        onSwipeRight?.();
      } else {
        onSwipeLeft?.();
      }
    },
    [onSwipeLeft, onSwipeRight, threshold, maxVertical, touchOnly]
  );

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    el.addEventListener('pointerdown', handlePointerDown, { passive: true });
    el.addEventListener('pointerup', handlePointerUp, { passive: true });

    return () => {
      el.removeEventListener('pointerdown', handlePointerDown);
      el.removeEventListener('pointerup', handlePointerUp);
    };
  }, [handlePointerDown, handlePointerUp]);

  return ref;
}
