/**
 * Symbol-tagged marker components for the MessageArea compound component pattern.
 *
 * Marker components render null -- they exist purely as declarative "slots"
 * that MessageArea detects via Symbol tags on the component function itself.
 */

import { createContext } from 'react';

// ========================================
// Marker Symbols for Sub-Components
// ========================================

export const LOADING_SYMBOL = Symbol('MessageAreaLoading');
export const EMPTY_SYMBOL = Symbol('MessageAreaEmpty');
export const SCROLL_INDICATOR_SYMBOL = Symbol('MessageAreaScrollIndicator');
export const SCROLL_BUTTON_SYMBOL = Symbol('MessageAreaScrollButton');
export const CONTENT_SYMBOL = Symbol('MessageAreaContent');
export const STREAMING_CONTENT_SYMBOL = Symbol('MessageAreaStreamingContent');

// ========================================
// Context
// ========================================

// Internal context value type — mirrors the exported MessageAreaContextValue
// but uses underscore-prefixed local types from MessageArea.tsx.
// We use `unknown` here so that the concrete type stays in MessageArea.tsx.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export const MessageAreaContext = createContext<any>(null);

export const useMessageArea = () => {
  return MessageAreaContext;
};

// ========================================
// Utility Functions
// ========================================

/** Check if scroll position is near the bottom of a scrollable element. */
export const isNearBottom = (element: HTMLElement, threshold = 100): boolean => {
  const { scrollHeight, scrollTop, clientHeight } = element;
  return scrollHeight - scrollTop - clientHeight < threshold;
};

// ========================================
// Sub-Components (Marker Components)
// ========================================

// Helper type for marker components with symbol tags and displayName
type SymbolTagged = Record<symbol, boolean> & { displayName?: string };

interface LoadingMarkerProps {
  className?: string | undefined;
  message?: string | undefined;
}
interface EmptyMarkerProps {
  className?: string | undefined;
  title?: string | undefined;
  subtitle?: string | undefined;
}
interface ScrollIndicatorMarkerProps {
  className?: string | undefined;
  label?: string | undefined;
}
interface ScrollButtonMarkerProps {
  className?: string | undefined;
  title?: string | undefined;
}
interface ContentMarkerProps {
  className?: string | undefined;
}
interface StreamingContentMarkerProps {
  className?: string | undefined;
}

export function LoadingMarker(_props: LoadingMarkerProps) {
  return null;
}
export function EmptyMarker(_props: EmptyMarkerProps) {
  return null;
}
export function ScrollIndicatorMarker(_props: ScrollIndicatorMarkerProps) {
  return null;
}
export function ScrollButtonMarker(_props: ScrollButtonMarkerProps) {
  return null;
}
export function ContentMarker(_props: ContentMarkerProps) {
  return null;
}
export function StreamingContentMarker(_props: StreamingContentMarkerProps) {
  return null;
}

// Attach symbols
(LoadingMarker as unknown as SymbolTagged)[LOADING_SYMBOL] = true;
(EmptyMarker as unknown as SymbolTagged)[EMPTY_SYMBOL] = true;
(ScrollIndicatorMarker as unknown as SymbolTagged)[SCROLL_INDICATOR_SYMBOL] = true;
(ScrollButtonMarker as unknown as SymbolTagged)[SCROLL_BUTTON_SYMBOL] = true;
(ContentMarker as unknown as SymbolTagged)[CONTENT_SYMBOL] = true;
(StreamingContentMarker as unknown as SymbolTagged)[STREAMING_CONTENT_SYMBOL] = true;

// Set display names for testing
(LoadingMarker as unknown as SymbolTagged).displayName = 'MessageAreaLoading';
(EmptyMarker as unknown as SymbolTagged).displayName = 'MessageAreaEmpty';
(ScrollIndicatorMarker as unknown as SymbolTagged).displayName = 'MessageAreaScrollIndicator';
(ScrollButtonMarker as unknown as SymbolTagged).displayName = 'MessageAreaScrollButton';
(ContentMarker as unknown as SymbolTagged).displayName = 'MessageAreaContent';
(StreamingContentMarker as unknown as SymbolTagged).displayName = 'MessageAreaStreamingContent';
