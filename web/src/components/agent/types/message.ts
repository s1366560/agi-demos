/**
 * Unified Message Types for Chat Components.
 *
 * Provides consistent message interface across all chat components:
 * - UserMessage
 * - AssistantMessage
 * - SystemMessage
 * - ToolMessage
 *
 * @example
 * const message: ChatMessage = {
 *   id: 'msg-1',
 *   role: 'assistant',
 *   content: 'Hello!',
 *   metadata: { isStreaming: true },
 * };
 */

import { ReactNode } from 'react';

/** Tool call definition */
export interface ToolCall {
  id: string;
  name: string;
  arguments: Record<string, unknown>;
  result?: string | undefined;
  status?: 'pending' | 'running' | 'completed' | 'failed' | undefined;
  error?: string | undefined;
}

/** File attachment metadata */
export interface FileAttachment {
  id: string;
  filename: string;
  sandbox_path?: string | undefined;
  mime_type: string;
  size_bytes: number;
  url?: string | undefined;
  thumbnail_url?: string | undefined;
}

/** Reasoning step for extended thinking */
export interface ReasoningStep {
  title: string;
  content: string;
  duration_ms?: number | undefined;
}

/** Message metadata */
export interface MessageMetadata {
  /** Whether this is a report-style message */
  isReport?: boolean | undefined;
  /** Whether currently streaming */
  isStreaming?: boolean | undefined;
  /** Tool calls */
  toolCalls?: ToolCall[] | undefined;
  /** Reasoning content */
  reasoning?: string | undefined;
  /** Reasoning steps */
  reasoningSteps?: ReasoningStep[] | undefined;
  /** Attached files */
  attachments?: FileAttachment[] | undefined;
  /** Generation timestamp */
  timestamp?: number | undefined;
  /** Conversation ID */
  conversationId?: string | undefined;
  /** Parent message ID (for threading) */
  parentId?: string | undefined;
  /** Branch ID (for conversation branching) */
  branchId?: string | undefined;
  /** Token usage */
  usage?: {
    input_tokens: number;
    output_tokens: number;
    total_tokens: number;
  } | undefined;
  /** Cost */
  cost?: number | undefined;
  /** Model used */
  model?: string | undefined;
  /** Provider used */
  provider?: string | undefined;
  /** Custom extra data */
  extra?: Record<string, unknown> | undefined;
}

/** Base message interface */
export interface BaseMessage {
  /** Unique message ID */
  id: string;
  /** Message role */
  role: 'system' | 'user' | 'assistant' | 'tool';
  /** Message content (markdown for assistant/user, plain text for system/tool) */
  content: string;
  /** Additional metadata */
  metadata?: MessageMetadata | undefined;
}

/** User message */
export interface UserMessage extends BaseMessage {
  role: 'user';
  metadata?: MessageMetadata & {
    /** Skill name if triggered via /skill */
    forcedSkillName?: string | undefined;
    /** Attached files */
    attachments?: FileAttachment[] | undefined;
  } | undefined;
}

/** Assistant message */
export interface AssistantMessage extends BaseMessage {
  role: 'assistant';
  metadata?: MessageMetadata & {
    isReport?: boolean | undefined;
    isStreaming?: boolean | undefined;
    toolCalls?: ToolCall[] | undefined;
    reasoning?: string | undefined;
    reasoningSteps?: ReasoningStep[] | undefined;
  } | undefined;
}

/** System message */
export interface SystemMessage extends BaseMessage {
  role: 'system';
  metadata?: MessageMetadata & {
    /** Whether collapsible */
    collapsible?: boolean | undefined;
    /** Whether collapsed by default */
    collapsed?: boolean | undefined;
  } | undefined;
}

/** Tool message */
export interface ToolMessage extends BaseMessage {
  role: 'tool';
  metadata?: MessageMetadata & {
    toolCallId?: string | undefined;
    toolName?: string | undefined;
    status?: 'pending' | 'running' | 'completed' | 'failed' | undefined;
    error?: string | undefined;
  } | undefined;
}

/** Union type for all message types */
export type ChatMessage = UserMessage | AssistantMessage | SystemMessage | ToolMessage;

/** Message renderer props */
export interface MessageRendererProps {
  message: ChatMessage;
  /** Whether this is the latest message */
  isLatest?: boolean | undefined;
  /** Callback for message actions */
  onRetry?: ((messageId: string) => void) | undefined;
  onCopy?: ((messageId: string) => void) | undefined;
  onDelete?: ((messageId: string) => void) | undefined;
  onEdit?: ((messageId: string, content: string) => void) | undefined;
  /** Custom renderers */
  renderAttachments?: ((attachments: FileAttachment[]) => ReactNode) | undefined;
  renderToolCalls?: ((toolCalls: ToolCall[]) => ReactNode) | undefined;
  renderReasoning?: ((reasoning: string) => ReactNode) | undefined;
}

/** Message bubble props (internal) */
export interface MessageBubbleProps {
  message: ChatMessage;
  className?: string | undefined;
  children?: ReactNode | undefined;
}

/** Context for message rendering */
export interface MessageContextValue {
  /** Current conversation ID */
  conversationId?: string | undefined;
  /** Whether dark mode */
  isDarkMode: boolean;
  /** Whether mobile */
  isMobile: boolean;
  /** Language */
  language: string;
  /** Custom components */
  components?: {
    UserMessage?: React.ComponentType<UserMessage> | undefined;
    AssistantMessage?: React.ComponentType<AssistantMessage> | undefined;
    SystemMessage?: React.ComponentType<SystemMessage> | undefined;
    ToolMessage?: React.ComponentType<ToolMessage> | undefined;
  } | undefined;
}
