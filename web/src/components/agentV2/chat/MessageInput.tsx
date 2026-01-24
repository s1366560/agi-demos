/**
 * Message Input
 *
 * Input area for sending messages to the agent.
 */

import { useRef, useEffect, useState } from 'react';
import { SendOutlined, StopOutlined, PaperClipOutlined } from '@ant-design/icons';
import { useIsStreaming, useStreamingPhase, useAgentV2Store } from '../../../stores/agentV2';

interface MessageInputProps {
  placeholder?: string;
  disabled?: boolean;
}

export function MessageInput({
  placeholder = 'Type your message...',
  disabled = false,
}: MessageInputProps) {
  const [input, setInput] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const isStreaming = useIsStreaming();
  const streamingPhase = useStreamingPhase();
  const { currentConversation, sendMessage, stopGeneration } = useAgentV2Store();

  // Auto-resize textarea
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 200)}px`;
    }
  }, [input]);

  const handleSend = () => {
    if (!input.trim() || !currentConversation || isStreaming) return;

    const message = input.trim();
    setInput('');
    sendMessage(currentConversation.id, message);
  };

  const handleStop = () => {
    if (currentConversation) {
      stopGeneration(currentConversation.id);
    }
  };

  const canSend = input.trim() && currentConversation && !isStreaming && !disabled;

  return (
    <div className="border-t border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-4">
      <div className="max-w-4xl mx-auto">
        {/* Streaming Phase Indicator */}
        {isStreaming && streamingPhase !== 'idle' && (
          <div className="mb-3 flex items-center gap-2 text-sm text-gray-600 dark:text-gray-400">
            <span className="flex gap-0.5">
              <span className="w-1.5 h-1.5 bg-blue-500 rounded-full animate-pulse" />
              <span className="w-1.5 h-1.5 bg-blue-500 rounded-full animate-pulse delay-75" />
              <span className="w-1.5 h-1.5 bg-blue-500 rounded-full animate-pulse delay-150" />
            </span>
            <span className="capitalize">{streamingPhase}</span>
          </div>
        )}

        {/* Input Container */}
        <div className="flex items-end gap-3">
          {/* Attachment Button */}
          <button
            disabled={isStreaming}
            className="p-3 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 disabled:opacity-50 transition-colors"
            title="Attach files (coming soon)"
          >
            <PaperClipOutlined />
          </button>

          {/* Text Input */}
          <div className="flex-1 relative">
            <textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  handleSend();
                }
              }}
              placeholder={placeholder}
              disabled={isStreaming || disabled}
              rows={1}
              className="w-full px-4 py-3 pr-12 bg-gray-100 dark:bg-gray-800 border-0 rounded-xl resize-none focus:ring-2 focus:ring-blue-500 outline-none disabled:opacity-50 max-h-[200px] text-gray-900 dark:text-gray-100 placeholder-gray-500 dark:placeholder-gray-400"
            />

            {/* Character Count */}
            {input.length > 0 && (
              <div className="absolute bottom-2 right-2 text-xs text-gray-400">
                {input.length.toLocaleString()}
              </div>
            )}
          </div>

          {/* Send/Stop Button */}
          {isStreaming ? (
            <button
              onClick={handleStop}
              className="p-3 bg-red-600 hover:bg-red-700 text-white rounded-xl transition-colors"
              title="Stop generation"
            >
              <StopOutlined />
            </button>
          ) : (
            <button
              onClick={handleSend}
              disabled={!canSend}
              className={`p-3 rounded-xl transition-all ${
                canSend
                  ? 'bg-blue-600 hover:bg-blue-700 text-white shadow-lg shadow-blue-500/30'
                  : 'bg-gray-200 dark:bg-gray-800 text-gray-400 cursor-not-allowed'
              }`}
              title="Send message (Enter)"
            >
              <SendOutlined />
            </button>
          )}
        </div>

        {/* Helper Text */}
        <p className="mt-2 text-xs text-gray-500 dark:text-gray-400 text-center">
          Press Enter to send, Shift+Enter for new line
        </p>
      </div>
    </div>
  );
}
