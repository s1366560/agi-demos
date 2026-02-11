/**
 * MessageBubble Compound Component Types
 *
 * Defines the type system for the compound MessageBubble component.
 */

import type {
  TimelineEvent,
  ActEvent,
  ObserveEvent,
  ArtifactCreatedEvent,
} from '../../../types/agent';

// Re-export commonly used types
export type { TimelineEvent, ActEvent, ObserveEvent, ArtifactCreatedEvent };

// ========================================
// Event Type Extractors
// ========================================

export type UserMessageEvent = Extract<TimelineEvent, { type: 'user_message' }>;
export type AssistantMessageEvent = Extract<TimelineEvent, { type: 'assistant_message' }>;
export type TextDeltaEvent = Extract<TimelineEvent, { type: 'text_delta' }>;
export type TextEndEvent = Extract<TimelineEvent, { type: 'text_end' }>;
export type ThoughtEvent = Extract<TimelineEvent, { type: 'thought' }>;
export type WorkPlanEvent = Extract<TimelineEvent, { type: 'work_plan' }>;
export type StepStartEvent = Extract<TimelineEvent, { type: 'step_start' }>;

// ========================================
// Component Props
// ========================================

/**
 * Common props for all message bubble sub-components
 */
export interface MessageBubbleProps {
  /** The timeline event to render */
  event: TimelineEvent;
  /** Whether currently streaming */
  isStreaming?: boolean;
  /** All timeline events (for finding related events like observe for act) */
  allEvents?: TimelineEvent[];
  /** Whether this message is pinned */
  isPinned?: boolean;
  /** Callback to toggle pin state */
  onPin?: () => void;
}

/**
 * Props for the root MessageBubble component
 */
export interface MessageBubbleRootProps extends MessageBubbleProps {
  /** Children for compound component pattern */
  children?: React.ReactNode;
  /** Callback when user clicks Reply on a message */
  onReply?: () => void;
}

/**
 * Props for User Message sub-component
 */
export interface UserMessageProps {
  content: string;
  onReply?: () => void;
}

/**
 * Props for Assistant Message sub-component
 */
export interface AssistantMessageProps {
  content: string;
  isStreaming?: boolean;
  isPinned?: boolean;
  onPin?: () => void;
  onReply?: () => void;
}

/**
 * Props for Text Delta sub-component
 */
export interface TextDeltaProps {
  content: string;
}

/**
 * Props for Thought sub-component
 */
export interface ThoughtProps {
  content: string;
}

/**
 * Props for Tool Execution sub-component
 */
export interface ToolExecutionProps {
  event: ActEvent;
  observeEvent?: ObserveEvent;
}

/**
 * Props for Work Plan sub-component
 */
export interface WorkPlanProps {
  event: WorkPlanEvent;
}

/**
 * Props for Step Start sub-component
 */
export interface StepStartProps {
  event: StepStartEvent;
}

/**
 * Props for Text End sub-component
 */
export interface TextEndProps {
  event: TextEndEvent;
  isPinned?: boolean;
  onPin?: () => void;
  onReply?: () => void;
}

/**
 * Props for Artifact Created sub-component
 */
export interface ArtifactCreatedProps {
  event: ArtifactCreatedEvent & { error?: string };
}

/**
 * MessageBubble compound component interface
 */
export interface MessageBubbleCompound extends React.FC<MessageBubbleRootProps> {
  /** User message renderer */
  User: React.FC<UserMessageProps>;
  /** Assistant message renderer */
  Assistant: React.FC<AssistantMessageProps>;
  /** Text delta (streaming) renderer */
  TextDelta: React.FC<TextDeltaProps>;
  /** Thought/reasoning renderer */
  Thought: React.FC<ThoughtProps>;
  /** Tool execution renderer */
  ToolExecution: React.FC<ToolExecutionProps>;
  /** Work plan renderer */
  WorkPlan: React.FC<WorkPlanProps>;
  /** Step start renderer */
  StepStart: React.FC<StepStartProps>;
  /** Text end renderer */
  TextEnd: React.FC<TextEndProps>;
  /** Artifact created renderer */
  ArtifactCreated: React.FC<ArtifactCreatedProps>;
  /** Root component alias */
  Root: React.FC<MessageBubbleRootProps>;
}
