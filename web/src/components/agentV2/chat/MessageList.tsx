/**
 * Message List
 *
 * Container for displaying all messages in the conversation.
 */

import { useRef, useEffect } from "react";
import { UserMessage } from "./UserMessage";
import { AssistantMessage } from "./AssistantMessage";
import {
  useMessages,
  useStreamingContent,
  useIsStreamingText,
} from "../../../stores/agentV2";

interface MessageListProps {
  scrollRef?: React.RefObject<HTMLDivElement | null>;
}

export function MessageList({ scrollRef }: MessageListProps) {
  const localScrollRef = useRef<HTMLDivElement>(null);
  const messages = useMessages();
  const streamingContent = useStreamingContent();
  const isStreamingText = useIsStreamingText();
  const scrollContainer = scrollRef || localScrollRef;

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    if (scrollContainer.current) {
      scrollContainer.current.scrollTop = scrollContainer.current.scrollHeight;
    }
  }, [messages, streamingContent, scrollContainer]);

  return (
    <div ref={scrollContainer} className="flex-1 overflow-y-auto px-4 py-6">
      <div className="max-w-4xl mx-auto space-y-6">
        {messages.length === 0 && !isStreamingText ? (
          <div className="flex flex-col items-center justify-center min-h-full text-center">
            <div className="w-16 h-16 bg-gradient-to-br from-blue-500 to-purple-600 rounded-2xl flex items-center justify-center mb-4">
              <svg
                className="w-8 h-8 text-white"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M13 10V3L4 14h7v7l9-11h-7z"
                />
              </svg>
            </div>
            <h2 className="text-xl font-semibold text-gray-900 dark:text-gray-100 mb-2">
              Welcome to Agent Chat
            </h2>
            <p className="text-gray-500 dark:text-gray-400 max-w-md">
              Start a conversation by typing a message below. I can help you
              search memories, analyze data, and answer questions using your
              knowledge graph.
            </p>
          </div>
        ) : (
          messages.map((message) => (
            <div key={message.id}>
              {message.role === "user" ? (
                <UserMessage content={message.content} />
              ) : (
                <AssistantMessage
                  content={message.content}
                  createdAt={message.created_at}
                />
              )}
            </div>
          ))
        )}

        {/* Streaming content */}
        {isStreamingText && streamingContent && (
          <AssistantMessage content={streamingContent} isStreaming={true} />
        )}
      </div>

      {/* Scroll spacer */}
      <div className="h-4" />
    </div>
  );
}
