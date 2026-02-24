/**
 * TimelineEventItem Compound Component Types
 *
 * Defines the type system for the compound TimelineEventItem component.
 */

import type { TimelineEvent } from '../../../types/agent';

// Re-export commonly used types
export type { TimelineEvent };

// ========================================
// Event Type Extractors
// ========================================

export type UserMessageEvent = Extract<TimelineEvent, { type: 'user_message' }>;
export type AssistantMessageEvent = Extract<TimelineEvent, { type: 'assistant_message' }>;
export type ThoughtEvent = Extract<TimelineEvent, { type: 'thought' }>;
export type ActEvent = Extract<TimelineEvent, { type: 'act' }>;
export type ObserveEvent = Extract<TimelineEvent, { type: 'observe' }>;
export type WorkPlanEvent = Extract<TimelineEvent, { type: 'work_plan' }>;
export type TextDeltaEvent = Extract<TimelineEvent, { type: 'text_delta' }>;
export type TextEndEvent = Extract<TimelineEvent, { type: 'text_end' }>;
export type ClarificationAskedEvent = Extract<TimelineEvent, { type: 'clarification_asked' }>;
export type DecisionAskedEvent = Extract<TimelineEvent, { type: 'decision_asked' }>;
export type EnvVarRequestedEvent = Extract<TimelineEvent, { type: 'env_var_requested' }>;
export type ArtifactCreatedEvent = Extract<TimelineEvent, { type: 'artifact_created' }>;

// ========================================
// Component Props
// ========================================

/**
 * Common props for all event item sub-components
 */
export interface EventItemProps {
  /** The timeline event to render */
  event: TimelineEvent;
  /** Whether currently streaming */
  isStreaming?: boolean | undefined;
  /** All timeline events (for finding related events) */
  allEvents?: TimelineEvent[] | undefined;
}

/**
 * Props for the root TimelineEventItem component
 */
export interface TimelineEventItemRootProps extends EventItemProps {
  /** Children for compound component pattern */
  children?: React.ReactNode | undefined;
}

/**
 * Props for User Message sub-component
 */
export interface UserMessageProps extends EventItemProps {
  event: UserMessageEvent;
}

/**
 * Props for Assistant Message sub-component
 */
export interface AssistantMessageProps extends EventItemProps {
  event: AssistantMessageEvent;
}

/**
 * Props for Thought sub-component
 */
export interface ThoughtProps extends EventItemProps {
  event: ThoughtEvent;
}

/**
 * Props for Act (tool call) sub-component
 */
export interface ActProps extends EventItemProps {
  event: ActEvent;
}

/**
 * Props for Observe sub-component
 */
export interface ObserveProps extends EventItemProps {
  event: ObserveEvent;
}

/**
 * Props for WorkPlan sub-component
 */
export interface WorkPlanProps extends EventItemProps {
  event: WorkPlanEvent;
}

/**
 * Props for TextDelta sub-component
 */
export interface TextDeltaProps extends EventItemProps {
  event: TextDeltaEvent;
}

/**
 * Props for TextEnd sub-component
 */
export interface TextEndProps extends EventItemProps {
  event: TextEndEvent;
}

/**
 * Props for Clarification sub-component
 */
export interface ClarificationProps extends EventItemProps {
  event: ClarificationAskedEvent;
}

/**
 * Props for Decision sub-component
 */
export interface DecisionProps extends EventItemProps {
  event: DecisionAskedEvent;
}

/**
 * Props for EnvVarRequest sub-component
 */
export interface EnvVarRequestProps extends EventItemProps {
  event: EnvVarRequestedEvent;
}

/**
 * Props for Artifact sub-component
 */
export interface ArtifactProps extends EventItemProps {
  event: ArtifactCreatedEvent;
}

/**
 * TimelineEventItem compound component interface
 */
export interface TimelineEventItemCompound extends React.FC<TimelineEventItemRootProps> {
  /** User message renderer */
  User: React.FC<UserMessageProps>;
  /** Assistant message renderer */
  Assistant: React.FC<AssistantMessageProps>;
  /** Thought/renderer */
  Thought: React.FC<ThoughtProps>;
  /** Act (tool call) renderer */
  Act: React.FC<ActProps>;
  /** Observe renderer */
  Observe: React.FC<ObserveProps>;
  /** WorkPlan renderer */
  WorkPlan: React.FC<WorkPlanProps>;
  /** TextDelta renderer */
  TextDelta: React.FC<TextDeltaProps>;
  /** TextEnd renderer */
  TextEnd: React.FC<TextEndProps>;
  /** Clarification (HITL) renderer */
  Clarification: React.FC<ClarificationProps>;
  /** Decision (HITL) renderer */
  Decision: React.FC<DecisionProps>;
  /** EnvVarRequest renderer */
  EnvVarRequest: React.FC<EnvVarRequestProps>;
  /** Artifact renderer */
  Artifact: React.FC<ArtifactProps>;
  /** Root component alias */
  Root: React.FC<TimelineEventItemRootProps>;
}
