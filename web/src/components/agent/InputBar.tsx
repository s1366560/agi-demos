/**
 * InputBar - Modern floating input bar
 */

import React, { useState, useRef, useCallback } from 'react';
import { Button, Tooltip, Badge } from 'antd';
import { 
  Send, 
  Square, 
  Paperclip, 
  Mic,
  Wand2
} from 'lucide-react';

interface InputBarProps {
  onSend: (content: string) => void;
  onAbort: () => void;
  isStreaming: boolean;
  isPlanMode: boolean;
  onTogglePlanMode: () => void;
  disabled?: boolean;
}

export const InputBar: React.FC<InputBarProps> = ({
  onSend,
  onAbort,
  isStreaming,
  isPlanMode,
  onTogglePlanMode,
  disabled,
}) => {
  const [content, setContent] = useState('');
  const [isFocused, setIsFocused] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const handleSend = useCallback(() => {
    if (!content.trim() || isStreaming) return;
    onSend(content.trim());
    setContent('');
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }
  }, [content, isStreaming, onSend]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }, [handleSend]);

  const handleInput = useCallback((e: React.FormEvent<HTMLTextAreaElement>) => {
    const target = e.currentTarget;
    target.style.height = 'auto';
    target.style.height = `${Math.min(target.scrollHeight, 200)}px`;
    setContent(target.value);
  }, []);

  const charCount = content.length;
  const showCharCount = charCount > 0;

  return (
    <div className="px-4 py-4">
      <div className={`
        max-w-4xl mx-auto
        rounded-xl border bg-white dark:bg-slate-800
        transition-all duration-200
        ${isFocused 
          ? 'border-primary shadow-lg shadow-primary/10' 
          : 'border-slate-200 dark:border-slate-700 shadow-sm'
        }
        ${disabled ? 'opacity-60 pointer-events-none' : ''}
      `}>
        {/* Plan Mode Badge */}
        {isPlanMode && (
          <div className="px-4 pt-3">
            <Badge className="bg-blue-50 dark:bg-blue-900/20 text-blue-600 dark:text-blue-400 border-blue-200 dark:border-blue-800 text-xs">
              <span className="flex items-center gap-1">
                <Wand2 size={12} />
                Plan Mode Active
              </span>
            </Badge>
          </div>
        )}

        {/* Text Area */}
        <div className="px-4 py-3">
          <textarea
            ref={textareaRef}
            value={content}
            onChange={handleInput}
            onKeyDown={handleKeyDown}
            onFocus={() => setIsFocused(true)}
            onBlur={() => setIsFocused(false)}
            placeholder={isPlanMode 
              ? "Describe what you want to plan..." 
              : "Message the AI or type '/' for commands..."
            }
            rows={1}
            className="
              w-full resize-none bg-transparent
              text-slate-900 dark:text-slate-100
              placeholder:text-slate-400
              focus:outline-none
              text-sm leading-relaxed
            "
            style={{ minHeight: '24px', maxHeight: '200px' }}
          />
        </div>

        {/* Toolbar */}
        <div className="px-3 pb-3 flex items-center justify-between">
          {/* Left Actions */}
          <div className="flex items-center gap-1">
            <Tooltip title="Attach file">
              <Button
                type="text"
                icon={<Paperclip size={18} />}
                className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-300"
              />
            </Tooltip>
            <Tooltip title="Voice input">
              <Button
                type="text"
                icon={<Mic size={18} />}
                className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-300"
              />
            </Tooltip>
            <div className="w-px h-5 bg-slate-200 dark:bg-slate-700 mx-1.5" />
            <Tooltip title={isPlanMode ? "Exit Plan Mode" : "Enter Plan Mode"}>
              <Button
                type="text"
                onClick={onTogglePlanMode}
                className={`
                  flex items-center gap-1.5
                  ${isPlanMode 
                    ? 'text-blue-600 bg-blue-50 dark:bg-blue-900/20' 
                    : 'text-slate-400 hover:text-slate-600'
                  }
                `}
              >
                <Wand2 size={16} />
                <span className="text-xs font-medium">Plan</span>
              </Button>
            </Tooltip>
          </div>

          {/* Right Actions */}
          <div className="flex items-center gap-2">
            {/* Character Count */}
            {showCharCount && (
              <span className={`
                text-xs transition-colors
                ${charCount > 4000 ? 'text-amber-500' : 'text-slate-400'}
              `}>
                {charCount}
              </span>
            )}

            {/* Send/Stop Button */}
            {isStreaming ? (
              <Button
                type="primary"
                danger
                icon={<Square size={16} />}
                onClick={onAbort}
                className="rounded-xl flex items-center gap-2"
              >
                Stop
              </Button>
            ) : (
              <Button
                type="primary"
                icon={<Send size={16} />}
                onClick={handleSend}
                disabled={!content.trim()}
                className="
                  rounded-xl flex items-center gap-2
                  bg-primary hover:bg-primary-600
                  disabled:opacity-40 disabled:cursor-not-allowed
                "
              >
                Send
              </Button>
            )}
          </div>
        </div>
      </div>

      {/* Footer hint */}
      <div className="max-w-4xl mx-auto mt-2 text-center">
        <p className="text-xs text-slate-500 dark:text-slate-400">
          Press <kbd className="px-1.5 py-0.5 bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded text-slate-600 dark:text-slate-400 font-sans">Enter</kbd> to send, <kbd className="px-1.5 py-0.5 bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded text-slate-600 dark:text-slate-400 font-sans">Shift + Enter</kbd> for new line
        </p>
      </div>
    </div>
  );
};
