/**
 * MessageBubble component
 *
 * Displays chat messages with markdown rendering and execution details.
 *
 * PERFORMANCE: Wrapped with React.memo to prevent unnecessary re-renders.
 * Only re-renders when message.id or message.content changes.
 */

import React, { memo, useMemo } from "react";
import ReactMarkdown from "react-markdown";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { vscDarkPlus } from "react-syntax-highlighter/dist/esm/styles/prism";
import { UserOutlined, RobotOutlined } from "@ant-design/icons";
import { Message } from "../../types/agent";
import { ExecutionDetailsPanel } from "./ExecutionDetailsPanel";
import remarkGfm from "remark-gfm";

interface MessageBubbleProps {
  message: Message;
  isStreaming?: boolean;
}

export const MessageBubble: React.FC<MessageBubbleProps> = memo(({
  message,
  isStreaming,
}) => {
  const isUser = message.role === "user";

  // Memoize timestamp formatting to avoid re-computing on every render
  const formattedTime = useMemo(
    () => new Date(message.created_at).toLocaleTimeString(),
    [message.created_at]
  );

  return (
    <div
      className={`flex w-full mb-6 ${isUser ? "justify-end" : "justify-start"}`}
    >
      <div
        className={`flex max-w-[85%] ${
          isUser ? "flex-row-reverse" : "flex-row"
        } gap-3`}
      >
        {/* Avatar */}
        <div
          className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 ${
            isUser ? "bg-blue-600 text-white" : "bg-emerald-600 text-white"
          }`}
        >
          {isUser ? <UserOutlined /> : <RobotOutlined />}
        </div>

        {/* Content */}
        <div
          className={`flex flex-col ${
            isUser ? "items-end" : "items-start"
          } min-w-0`}
        >
          <div className="flex items-center gap-2 mb-1 px-1">
            <span className="text-xs font-semibold text-slate-700">
              {isUser ? "You" : "Agent"}
            </span>
            <span className="text-xs text-slate-400">
              {formattedTime}
            </span>
          </div>

          <div
            className={`rounded-2xl px-5 py-3 shadow-sm max-w-full overflow-hidden ${
              isUser
                ? "bg-blue-600 text-white rounded-tr-none"
                : "bg-white border border-slate-100 rounded-tl-none text-slate-800"
            }`}
          >
            {!isUser && (
              <ExecutionDetailsPanel
                message={message}
                isStreaming={isStreaming}
                defaultView="thinking"
              />
            )}

            <div
              className={`prose prose-sm max-w-none ${
                isUser ? "prose-invert" : ""
              }`}
            >
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  code({ node: _node, className, children, ...props }: any) {
                    const inline = (props as any)?.inline;
                    const match = /language-(\w+)/.exec(className || "");
                    return !inline && match ? (
                      <SyntaxHighlighter
                        style={vscDarkPlus as any}
                        language={match[1]}
                        PreTag="div"
                      >
                        {String(children).replace(/\n$/, "")}
                      </SyntaxHighlighter>
                    ) : (
                      <code className={className} {...props}>
                        {children}
                      </code>
                    );
                  },
                }}
              >
                {message.content || (isStreaming && !isUser ? "..." : "")}
              </ReactMarkdown>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
});

// Display name for debugging
MessageBubble.displayName = 'MessageBubble';

export default MessageBubble;
