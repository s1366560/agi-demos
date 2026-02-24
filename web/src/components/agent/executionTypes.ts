/**
 * ExecutionDetailsPanel Compound Component Types
 *
 * Defines the type system for the compound ExecutionDetailsPanel component.
 */

import type { Message } from '../../types/agent';

/**
 * Available view types for the execution details panel
 */
export type ViewType = 'thinking' | 'activity' | 'tools' | 'tokens';

/**
 * ExecutionDetailsPanel context shared across compound components
 */
export interface ExecutionDetailsPanelContextValue {
  /** Message data from store containing execution metadata */
  message: Message;
  /** Whether the message is currently streaming */
  isStreaming: boolean;
  /** Compact mode for smaller displays */
  compact: boolean;
  /** Currently active view */
  currentView: ViewType;
  /** Change active view */
  setCurrentView: (view: ViewType) => void;
  /** Whether to show the view selector tabs */
  showViewSelector: boolean;
}

/**
 * Props for the root ExecutionDetailsPanel component
 */
export interface ExecutionDetailsPanelRootProps {
  /** Message data from store containing execution metadata */
  message: Message;
  /** Children for compound component pattern */
  children?: React.ReactNode | undefined;
  /** Whether the message is currently streaming */
  isStreaming?: boolean | undefined;
  /** Compact mode for smaller displays (reduced padding, smaller text) */
  compact?: boolean | undefined;
  /** Default view to show on first render */
  defaultView?: ViewType | undefined;
  /** Whether to show the view selector tabs */
  showViewSelector?: boolean | undefined;
}

/**
 * Props for Thinking sub-component
 */
export interface ExecutionThinkingProps {
  /** Optional custom class name */
  className?: string | undefined;
}

/**
 * Props for Activity sub-component
 */
export interface ExecutionActivityProps {
  /** Optional custom class name */
  className?: string | undefined;
}

/**
 * Props for Tools sub-component
 */
export interface ExecutionToolsProps {
  /** Optional custom class name */
  className?: string | undefined;
}

/**
 * Props for Tokens sub-component
 */
export interface ExecutionTokensProps {
  /** Optional custom class name */
  className?: string | undefined;
}

/**
 * Props for ViewSelector sub-component
 */
export interface ExecutionViewSelectorProps {
  /** Optional custom class name */
  className?: string | undefined;
}

/**
 * Legacy ExecutionDetailsPanelProps for backward compatibility
 * @deprecated Use ExecutionDetailsPanelRootProps with compound components instead
 */
export interface LegacyExecutionDetailsPanelProps {
  /** Message data from store containing execution metadata */
  message: Message;
  /** Whether the message is currently streaming */
  isStreaming?: boolean | undefined;
  /** Compact mode for smaller displays (reduced padding, smaller text) */
  compact?: boolean | undefined;
  /** Default view to show on first render */
  defaultView?: ViewType | undefined;
  /** Whether to show the view selector tabs */
  showViewSelector?: boolean | undefined;
}

/**
 * ExecutionDetailsPanel compound component interface
 * Extends React.FC with sub-component properties
 */
export interface ExecutionDetailsPanelCompound extends React.FC<ExecutionDetailsPanelRootProps> {
  /** Thinking view sub-component */
  Thinking: React.FC<ExecutionThinkingProps>;
  /** Activity timeline sub-component */
  Activity: React.FC<ExecutionActivityProps>;
  /** Tools visualization sub-component */
  Tools: React.FC<ExecutionToolsProps>;
  /** Token usage sub-component */
  Tokens: React.FC<ExecutionTokensProps>;
  /** View selector sub-component */
  ViewSelector: React.FC<ExecutionViewSelectorProps>;
  /** Root component alias */
  Root: React.FC<ExecutionDetailsPanelRootProps>;
}
