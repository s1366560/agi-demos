/**
 * Unified Message Renderer.
 *
 * Renders chat messages based on their role using the unified message types.
 * Supports:
 * - User messages with attachments
 * - Assistant messages with reasoning and tool calls
 * - System messages (collapsible)
 * - Tool messages (with status indicators)
 *
 * @example
 * <MessageRenderer
 *   message={message}
 *   isLatest={true}
 *   onCopy={handleCopy}
 *   onRetry={handleRetry}
 * />
 */

import React from 'react';

import { ChatMessage, UserMessage, AssistantMessage, SystemMessage, ToolMessage } from '../types/message';

import { AssistantMessage as AssistantMessageComponent } from './AssistantMessage';
import { MessageErrorBoundary } from './MessageErrorBoundary';
import { UserMessage as UserMessageComponent } from './MessageStream';

export interface MessageRendererProps {
  /** Message to render */
  message: ChatMessage;
  /** Whether this is the latest message */
  isLatest?: boolean;
  /** Click handler */
  onClick?: (message: ChatMessage) => void;
  /** Retry handler */
  onRetry?: (messageId: string) => void;
  /** Copy handler */
  onCopy?: (messageId: string) => void;
  /** Delete handler */
  onDelete?: (messageId: string) => void;
  /** Edit handler */
  onEdit?: (messageId: string, content: string) => void;
  /** Custom class names */
  className?: string;
}

/**
 * Render user message.
 */
const UserMessageRenderer: React.FC<{
  message: UserMessage;
}> = ({ message }) => {
  const fileMetadata = message.metadata?.attachments?.map((att) => ({
    filename: att.filename,
    sandbox_path: att.sandbox_path,
    mime_type: att.mime_type,
    size_bytes: att.size_bytes,
  }));

  return (
    <UserMessageComponent
      content={message.content}
      forcedSkillName={message.metadata?.forcedSkillName}
      fileMetadata={fileMetadata}
    />
  );
};

/**
 * Render assistant message.
 */
const AssistantMessageRenderer: React.FC<{
  message: AssistantMessage;
}> = ({ message }) => {
  return (
    <AssistantMessageComponent
      content={message.content}
      isReport={message.metadata?.isReport}
      isStreaming={message.metadata?.isStreaming}
      generatedAt={
        message.metadata?.timestamp ? new Date(message.metadata.timestamp).toISOString() : undefined
      }
    />
  );
};

/**
 * Render system message.
 */
const SystemMessageRenderer: React.FC<{
  message: SystemMessage;
}> = ({ message }) => {
  const [collapsed, setCollapsed] = React.useState(message.metadata?.collapsed ?? true);

  if (!message.metadata?.collapsible) {
    return (
      <div className="py-2 text-center text-xs text-slate-500 dark:text-slate-400 border-y border-slate-200 dark:border-slate-700">
        {message.content}
      </div>
    );
  }

  return (
    <div className="py-2 text-center">
      <button
        type="button"
        onClick={() => setCollapsed(!collapsed)}
        className="text-xs text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-300 transition-colors"
        aria-expanded={!collapsed}
      >
        <span className="material-symbols-outlined text-sm align-middle mr-1">
          {collapsed ? 'expand_more' : 'expand_less'}
        </span>
        {collapsed ? 'Show system message' : 'Hide system message'}
      </button>
      {!collapsed && (
        <div className="mt-2 text-xs text-slate-600 dark:text-slate-400 max-w-2xl mx-auto">
          {message.content}
        </div>
      )}
    </div>
  );
};

/**
 * Render tool message.
 */
const ToolMessageRenderer: React.FC<{
  message: ToolMessage;
}> = ({ message }) => {
  const statusColors = {
    pending: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400',
    running: 'bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-400',
    completed: 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400',
    failed: 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400',
  };

  const status = message.metadata?.status || 'completed';
  const statusColor = statusColors[status] || statusColors.completed;

  return (
    <div className="my-2 p-3 bg-slate-50 dark:bg-slate-800/50 border border-slate-200 dark:border-slate-700 rounded-lg">
      <div className="flex items-center gap-2 mb-2">
        <span className="material-symbols-outlined text-sm text-slate-500">
          {status === 'failed' ? 'error' : status === 'running' ? 'sync' : 'check_circle'}
        </span>
        <span className="text-xs font-medium text-slate-600 dark:text-slate-400">
          {message.metadata?.toolName || 'Tool'}
        </span>
        <span className={`text-[10px] px-2 py-0.5 rounded-full ${statusColor}`}>
          {status}
        </span>
      </div>
      <div className="text-xs text-slate-600 dark:text-slate-400 font-mono whitespace-pre-wrap">
        {message.content}
      </div>
      {message.metadata?.error && (
        <div className="mt-2 text-xs text-red-600 dark:text-red-400 font-mono">
          Error: {message.metadata.error}
        </div>
      )}
    </div>
  );
};

/**
 * Main message renderer with error boundary.
 */
export const MessageRenderer: React.FC<MessageRendererProps> = ({
  message,
  onClick,
  className = '',
}) => {
  const handleClick = React.useCallback(() => {
    onClick?.(message);
  }, [onClick, message]);

  const renderMessage = () => {
    switch (message.role) {
      case 'user':
        return <UserMessageRenderer message={message} />;
      case 'assistant':
        return (
          <AssistantMessageRenderer
            message={message}
          />
        );
      case 'system':
        return <SystemMessageRenderer message={message} />;
      case 'tool':
        return <ToolMessageRenderer message={message} />;
      default:
        return (
          <div className="text-sm text-slate-500">Unknown message role: {(message as any).role}</div>
        );
    }
  };

  return (
    <MessageErrorBoundary
      fallback={
        <div className="p-4 my-2 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg">
          <p className="text-sm text-red-600 dark:text-red-400">
            Failed to render message {message.id.slice(0, 8)}...
          </p>
        </div>
      }
      onError={(error) => {
        console.error(`Failed to render message ${message.id}:`, error);
      }}
    >
      <div
        className={`message-bubble ${className}`}
        data-message-id={message.id}
        data-message-role={message.role}
        onClick={handleClick}
        role="article"
        aria-label={`${message.role} message`}
      >
        {renderMessage()}
      </div>
    </MessageErrorBoundary>
  );
};

export default MessageRenderer;
