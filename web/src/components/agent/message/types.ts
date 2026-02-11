/**
 * MessageArea Compound Component Types
 *
 * Defines the type system for the compound MessageArea component.
 */

import type { TimelineEvent, PlanModeStatus } from '../../../types/agent';

// ========================================
// Domain Types (re-exported for convenience)
// ========================================

export type { TimelineEvent, PlanModeStatus };

// ========================================
// Context Types
// ========================================

/**
 * Scroll state managed by MessageArea context
 */
export interface MessageAreaScrollState {
  /** Whether scroll-to-bottom button is visible */
  showScrollButton: boolean;
  /** Whether loading indicator is visible */
  showLoadingIndicator: boolean;
  /** Scroll to bottom handler */
  scrollToBottom: () => void;
  /** Container ref for scroll access */
  containerRef: React.RefObject<HTMLDivElement | null>;
}

/**
 * MessageArea context value
 */
export interface MessageAreaContextValue {
  /** Timeline events to display */
  timeline: TimelineEvent[];
  /** Streaming content from assistant */
  streamingContent?: string;
  /** Streaming thought content */
  streamingThought?: string;
  /** Whether content is actively streaming */
  isStreaming: boolean;
  /** Whether thought is actively streaming */
  isThinkingStreaming?: boolean;
  /** Initial loading state */
  isLoading: boolean;
  /** Plan mode status */
  planModeStatus: PlanModeStatus | null;
  /** View plan callback */
  onViewPlan: () => void;
  /** Exit plan mode callback */
  onExitPlanMode: () => void;
  /** Whether there are earlier messages to load */
  hasEarlierMessages: boolean;
  /** Load earlier messages callback */
  onLoadEarlier?: () => void;
  /** Loading earlier messages state */
  isLoadingEarlier: boolean;
  /** Preload trigger threshold */
  preloadItemCount: number;
  /** Current conversation ID for scroll reset */
  conversationId?: string | null;
  /** Scroll state */
  scroll: MessageAreaScrollState;
}

// ========================================
// Component Props
// ========================================

/**
 * Props for the root MessageArea component
 */
export interface MessageAreaRootProps {
  /** Timeline events to display */
  timeline: TimelineEvent[];
  /** Streaming content from assistant */
  streamingContent?: string;
  /** Streaming thought content */
  streamingThought?: string;
  /** Whether content is actively streaming */
  isStreaming: boolean;
  /** Whether thought is actively streaming */
  isThinkingStreaming?: boolean;
  /** Initial loading state */
  isLoading: boolean;
  /** Plan mode status */
  planModeStatus: PlanModeStatus | null;
  /** View plan callback */
  onViewPlan: () => void;
  /** Exit plan mode callback */
  onExitPlanMode: () => void;
  /** Whether there are earlier messages to load */
  hasEarlierMessages?: boolean;
  /** Load earlier messages callback */
  onLoadEarlier?: () => void;
  /** Loading earlier messages state */
  isLoadingEarlier?: boolean;
  /** Preload trigger threshold (default: 10) */
  preloadItemCount?: number;
  /** Current conversation ID for scroll reset */
  conversationId?: string | null;
  /** Follow-up suggestions to show after assistant response */
  suggestions?: string[];
  /** Callback when user clicks a suggestion chip */
  onSuggestionSelect?: (suggestion: string) => void;
  /** Children for compound component pattern */
  children?: React.ReactNode;
}

/**
 * Props for Container sub-component
 */
export interface MessageAreaContainerProps {
  /** Optional custom class name */
  className?: string;
}

/**
 * Props for Loading sub-component
 */
export interface MessageAreaLoadingProps {
  /** Optional custom class name */
  className?: string;
  /** Optional custom message */
  message?: string;
}

/**
 * Props for Empty sub-component
 */
export interface MessageAreaEmptyProps {
  /** Optional custom class name */
  className?: string;
  /** Optional custom title */
  title?: string;
  /** Optional custom subtitle */
  subtitle?: string;
}

/**
 * Props for ScrollIndicator sub-component
 */
export interface MessageAreaScrollIndicatorProps {
  /** Optional custom class name */
  className?: string;
  /** Optional custom label */
  label?: string;
}

/**
 * Props for ScrollButton sub-component
 */
export interface MessageAreaScrollButtonProps {
  /** Optional custom class name */
  className?: string;
  /** Optional custom title */
  title?: string;
}

/**
 * Props for Content sub-component
 */
export interface MessageAreaContentProps {
  /** Optional custom class name */
  className?: string;
}

/**
 * Props for PlanBanner sub-component
 */
export interface MessageAreaPlanBannerProps {
  /** Optional custom class name */
  className?: string;
}

/**
 * Props for StreamingContent sub-component
 */
export interface MessageAreaStreamingContentProps {
  /** Optional custom class name */
  className?: string;
}

/**
 * MessageArea compound component interface
 */
export interface MessageAreaCompound extends React.FC<MessageAreaRootProps> {
  /** Scroll context provider */
  Provider: React.FC<{ children: React.ReactNode }>;
  /** Container for message list with scroll handling */
  Container: React.FC<MessageAreaContainerProps>;
  /** Initial loading state */
  Loading: React.FC<MessageAreaLoadingProps>;
  /** Empty state when no messages */
  Empty: React.FC<MessageAreaEmptyProps>;
  /** Loading indicator for earlier messages */
  ScrollIndicator: React.FC<MessageAreaScrollIndicatorProps>;
  /** Scroll to bottom button */
  ScrollButton: React.FC<MessageAreaScrollButtonProps>;
  /** Message list content */
  Content: React.FC<MessageAreaContentProps>;
  /** Plan mode banner */
  PlanBanner: React.FC<MessageAreaPlanBannerProps>;
  /** Streaming content bubble */
  StreamingContent: React.FC<MessageAreaStreamingContentProps>;
  /** Root component alias */
  Root: React.FC<MessageAreaRootProps>;
}
