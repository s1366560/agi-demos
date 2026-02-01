/**
 * InputBar - Modern floating input bar
 */

import React, { useState, useRef, useCallback, memo } from 'react';
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

// Memoized InputBar to prevent unnecessary re-renders (rerender-memo)
export const InputBar = memo<InputBarProps>(({
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

  // Combine disabled and isStreaming for send button state
  const canSend = !disabled && !isStreaming && content.trim().length > 0;
  
  const handleSend = useCallback(() => {
    if (!content.trim() || isStreaming || disabled) return;
    onSend(content.trim());
    setContent('');
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }
  }, [content, isStreaming, disabled, onSend]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing && !disabled && !isStreaming) {
      e.preventDefault();
      handleSend();
    }
  }, [handleSend, disabled, isStreaming]);

  const handleInput = useCallback((e: React.FormEvent<HTMLTextAreaElement>) => {
    const target = e.currentTarget;
    target.style.height = 'auto';
    target.style.height = `${Math.min(target.scrollHeight, 400)}px`;
    setContent(target.value);
  }, []);

  const charCount = content.length;
  const showCharCount = charCount > 0;

  return (
    <div className="h-full flex flex-col p-3">
      {/* Main input card */}
      <div className={`
        flex-1 flex flex-col min-h-0 rounded-xl border bg-white dark:bg-slate-800
        transition-all duration-200
        ${isFocused 
          ? 'border-primary shadow-lg shadow-primary/10' 
          : 'border-slate-200 dark:border-slate-700 shadow-sm'
        }
        ${disabled ? 'opacity-60 pointer-events-none' : ''}
      `}>
        {/* Plan Mode Badge */}
        {isPlanMode && (
          <div className="px-3 pt-2 flex-shrink-0">
            <Badge className="bg-blue-50 dark:bg-blue-900/20 text-blue-600 dark:text-blue-400 border-blue-200 dark:border-blue-800 text-xs">
              <span className="flex items-center gap-1">
                <Wand2 size={12} />
                Plan Mode Active
              </span>
            </Badge>
          </div>
        )}

        {/* Text Area - fills available space */}
        <div className="flex-1 min-h-0 px-3 py-2">
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
            className="
              w-full h-full resize-none bg-transparent
              text-slate-900 dark:text-slate-100
              placeholder:text-slate-400
              focus:outline-none
              text-sm leading-relaxed
            "
          />
        </div>

        {/* Toolbar */}
        <div className="flex-shrink-0 px-2 pb-2 flex items-center justify-between">
          {/* Left Actions */}
          <div className="flex items-center gap-1">
            <Tooltip title="Attach file">
              <Button
                type="text"
                size="small"
                icon={<Paperclip size={16} />}
                className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-300"
              />
            </Tooltip>
            <Tooltip title="Voice input">
              <Button
                type="text"
                size="small"
                icon={<Mic size={16} />}
                className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-300"
              />
            </Tooltip>
            <div className="w-px h-4 bg-slate-200 dark:bg-slate-700 mx-1" />
            <Tooltip title={isPlanMode ? "Exit Plan Mode" : "Enter Plan Mode"}>
              <Button
                type="text"
                size="small"
                onClick={onTogglePlanMode}
                className={`
                  flex items-center gap-1
                  ${isPlanMode 
                    ? 'text-blue-600 bg-blue-50 dark:bg-blue-900/20' 
                    : 'text-slate-400 hover:text-slate-600'
                  }
                `}
              >
                <Wand2 size={14} />
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
                size="small"
                icon={<Square size={14} />}
                onClick={onAbort}
                className="rounded-lg flex items-center gap-1"
              >
                Stop
              </Button>
            ) : (
              <Button
                type="primary"
                size="small"
                icon={<Send size={14} />}
                onClick={handleSend}
                disabled={!canSend}
                className="
                  rounded-lg flex items-center gap-1
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

      {/* Footer hint - outside card, below it */}
      <div className="flex-shrink-0 mt-1.5 text-center">
        <p className="text-[10px] text-slate-400 dark:text-slate-500">
          <kbd className="px-1 py-0.5 bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded text-slate-500 dark:text-slate-400 font-sans">Enter</kbd> to send, <kbd className="px-1 py-0.5 bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded text-slate-500 dark:text-slate-400 font-sans">Shift + Enter</kbd> for new line
        </p>
      </div>
    </div>
  );
});

InputBar.displayName = 'InputBar';

export default InputBar;
