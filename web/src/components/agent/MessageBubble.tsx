/**
 * MessageBubble - Modern message bubble component
 *
 * Compound Component Pattern for flexible message rendering.
 * Re-exports from the compound component implementation.
 *
 * @example
 * // Automatic rendering based on event type
 * <MessageBubble event={event} allEvents={events} />
 *
 * @example
 * // Direct sub-component usage
 * <MessageBubble.User content="Hello" />
 * <MessageBubble.Assistant content="Hi there!" />
 * <MessageBubble.ToolExecution event={actEvent} observeEvent={observeEvent} />
 */

export { MessageBubble } from './messageBubble/MessageBubble';
export type {
  MessageBubbleProps,
  MessageBubbleRootProps,
  UserMessageProps,
  AssistantMessageProps,
  TextDeltaProps,
  ThoughtProps,
  ToolExecutionProps,
  WorkPlanProps,
  TextEndProps,
  ArtifactCreatedProps,
  MessageBubbleCompound,
} from './messageBubble/types';
