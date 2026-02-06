/**
 * CSS Containment Utilities
 *
 * Provides TypeScript-safe class names and utilities for CSS containment
 * performance optimizations.
 *
 * CSS Containment allows the browser to optimize rendering by:
 * 1. content-visibility: Skip rendering work for off-screen content
 * 2. contain: Isolate element changes from affecting rest of page
 * 3. contain-intrinsic-size: Reserve space for unrendered content
 *
 * @see https://web.dev/content-visibility/
 * @see https://developer.mozilla.org/en-US/docs/Web/CSS/contain
 */

/**
 * Content-visibility utilities
 */
export const contentVisibility = {
  /** Auto: Browser skips rendering off-screen content */
  auto: 'content-visibility-auto',
  /** Hidden: Content is not rendered but space is reserved */
  hidden: 'content-visibility-hidden',
} as const;

/**
 * Contain property utilities
 */
export const contain = {
  /** Isolate layout calculations */
  layout: 'contain-layout',
  /** Isolate paint operations */
  paint: 'contain-paint',
  /** Combine layout and paint containment */
  layoutPaint: 'contain-layout-paint',
  /** Strict containment (layout + paint + style + size) */
  strict: 'contain-strict',
} as const;

/**
 * Preset optimization classes for common UI patterns
 */
export const presets = {
  /** Optimized for list items (80px intrinsic size) */
  listItem: 'list-item-optimized',
  /** Optimized for table rows (48px intrinsic size) */
  tableRow: 'table-row-optimized',
  /** Optimized for cards (200px intrinsic size) */
  card: 'card-optimized',
  /** Low priority rendering for non-critical UI */
  lowPriority: 'render-priority-low',
} as const;

/**
 * Animation performance hints
 */
export const animation = {
  /** Hint that transform will animate */
  willChangeTransform: 'will-change-transform',
  /** Hint that opacity will animate */
  willChangeOpacity: 'will-change-opacity',
  /** Hint that position will animate */
  willChangeTopLeft: 'will-change-top-left',
  /** Force GPU acceleration */
  gpuAccelerated: 'gpu-accelerated',
} as const;

/**
 * Layout optimization utilities
 */
export const layout = {
  /** Prevent layout thrashing for frequently updated elements */
  noThrashing: 'no-layout-thrashing',
  /** Composite layer for animated elements */
  compositeLayer: 'composite-layer',
} as const;

/**
 * Combine multiple containment classes
 */
export function combineContainment(...classes: (string | undefined | null | false)[]): string {
  return classes.filter(Boolean).join(' ');
}

/**
 * Get containment class for list items
 */
export function listItemOptimized(extra?: string): string {
  return combineContainment(presets.listItem, extra);
}

/**
 * Get containment class for table rows
 */
export function tableRowOptimized(extra?: string): string {
  return combineContainment(presets.tableRow, extra);
}

/**
 * Get containment class for cards
 */
export function cardOptimized(extra?: string): string {
  return combineContainment(presets.card, extra);
}

/**
 * Get containment class for low-priority elements
 */
export function lowPriority(extra?: string): string {
  return combineContainment(presets.lowPriority, extra);
}

/**
 * Get GPU acceleration hint for animated elements
 */
export function gpuAccelerated(extra?: string): string {
  return combineContainment(animation.gpuAccelerated, extra);
}

/**
 * Type-safe class names object
 */
export const containmentClasses = {
  ...contentVisibility,
  ...contain,
  ...presets,
  ...animation,
  ...layout,
} as const;

export type ContainmentClass = (typeof containmentClasses)[keyof typeof containmentClasses];
