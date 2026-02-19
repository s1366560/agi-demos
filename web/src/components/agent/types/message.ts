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
  result?: string;
  status?: 'pending' | 'running' | 'completed' | 'failed';
  error?: string;
}

/** File attachment metadata */
export interface FileAttachment {
  id: string;
  filename: string;
  sandbox_path?: string;
  mime_type: string;
  size_bytes: number;
  url?: string;
  thumbnail_url?: string;
}

/** Reasoning step for extended thinking */
export interface ReasoningStep {
  title: string;
  content: string;
  duration_ms?: number;
}

/** Message metadata */
export interface MessageMetadata {
  /** Whether this is a report-style message */
  isReport?: boolean;
  /** Whether currently streaming */
  isStreaming?: boolean;
  /** Tool calls */
  toolCalls?: ToolCall[];
  /** Reasoning content */
  reasoning?: string;
  /** Reasoning steps */
  reasoningSteps?: ReasoningStep[];
  /** Attached files */
  attachments?: FileAttachment[];
  /** Generation timestamp */
  timestamp?: number;
  /** Conversation ID */
  conversationId?: string;
  /** Parent message ID (for threading) */
  parentId?: string;
  /** Branch ID (for conversation branching) */
  branchId?: string;
  /** Token usage */
  usage?: {
    input_tokens: number;
    output_tokens: number;
    total_tokens: number;
  };
  /** Cost */
  cost?: number;
  /** Model used */
  model?: string;
  /** Provider used */
  provider?: string;
  /** Custom extra data */
  extra?: Record<string, unknown>;
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
  metadata?: MessageMetadata;
}

/** User message */
export interface UserMessage extends BaseMessage {
  role: 'user';
  metadata?: MessageMetadata & {
    /** Skill name if triggered via /skill */
    forcedSkillName?: string;
    /** Attached files */
    attachments?: FileAttachment[];
  };
}

/** Assistant message */
export interface AssistantMessage extends BaseMessage {
  role: 'assistant';
  metadata?: MessageMetadata & {
    isReport?: boolean;
    isStreaming?: boolean;
    toolCalls?: ToolCall[];
    reasoning?: string;
    reasoningSteps?: ReasoningStep[];
  };
}

/** System message */
export interface SystemMessage extends BaseMessage {
  role: 'system';
  metadata?: MessageMetadata & {
    /** Whether collapsible */
    collapsible?: boolean;
    /** Whether collapsed by default */
    collapsed?: boolean;
  };
}

/** Tool message */
export interface ToolMessage extends BaseMessage {
  role: 'tool';
  metadata?: MessageMetadata & {
    toolCallId?: string;
    toolName?: string;
    status?: 'pending' | 'running' | 'completed' | 'failed';
    error?: string;
  };
}

/** Union type for all message types */
export type ChatMessage = UserMessage | AssistantMessage | SystemMessage | ToolMessage;

/** Message renderer props */
export interface MessageRendererProps {
  message: ChatMessage;
  /** Whether this is the latest message */
  isLatest?: boolean;
  /** Callback for message actions */
  onRetry?: (messageId: string) => void;
  onCopy?: (messageId: string) => void;
  onDelete?: (messageId: string) => void;
  onEdit?: (messageId: string, content: string) => void;
  /** Custom renderers */
  renderAttachments?: (attachments: FileAttachment[]) => ReactNode;
  renderToolCalls?: (toolCalls: ToolCall[]) => ReactNode;
  renderReasoning?: (reasoning: string) => ReactNode;
}

/** Message bubble props (internal) */
export interface MessageBubbleProps {
  message: ChatMessage;
  className?: string;
  children?: ReactNode;
}

/** Context for message rendering */
export interface MessageContextValue {
  /** Current conversation ID */
  conversationId?: string;
  /** Whether dark mode */
  isDarkMode: boolean;
  /** Whether mobile */
  isMobile: boolean;
  /** Language */
  language: string;
  /** Custom components */
  components?: {
    UserMessage?: React.ComponentType<UserMessage>;
    AssistantMessage?: React.ComponentType<AssistantMessage>;
    SystemMessage?: React.ComponentType<SystemMessage>;
    ToolMessage?: React.ComponentType<ToolMessage>;
  };
}
