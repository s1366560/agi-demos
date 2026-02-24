/**
 * FocusDesktopOverlay - Fullscreen desktop with floating chat bubble
 *
 * Used in "focus" layout mode. Renders the remote desktop at 100% viewport
 * with a floating chat bubble in the bottom-left corner.
 * Pressing ESC or the minimize button exits focus mode.
 */

import type { FC } from 'react';
import { useState, useEffect, useRef, useCallback } from 'react';

import { MessageSquare, X, Minimize2, Send } from 'lucide-react';
import { useShallow } from 'zustand/react/shallow';

import { useLayoutModeStore } from '@/stores/layoutMode';

interface FocusDesktopOverlayProps {
  /** Remote desktop content */
  desktopContent: React.ReactNode;
  /** Chat messages content (compact version) */
  chatContent: React.ReactNode;
  /** Input handler */
  onSend?: (content: string) => void;
  /** Whether agent is streaming */
  isStreaming?: boolean;
}

export const FocusDesktopOverlay: FC<FocusDesktopOverlayProps> = ({
  desktopContent,
  chatContent,
  onSend,
  isStreaming,
}) => {
  const [focusChatExpanded, setFocusChatExpanded] = useState(false);
  const toggleFocusChat = useCallback(() => { setFocusChatExpanded((v) => !v); }, []);
  const { setMode } = useLayoutModeStore(
    useShallow((state) => ({
      setMode: state.setMode,
    }))
  );

  const [inputValue, setInputValue] = useState('');
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // ESC to exit focus mode
  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        setMode('chat');
      }
    },
    [setMode]
  );

  useEffect(() => {
    window.addEventListener('keydown', handleKeyDown);
    return () => { window.removeEventListener('keydown', handleKeyDown); };
  }, [handleKeyDown]);

  const handleSend = useCallback(() => {
    if (!inputValue.trim() || !onSend) return;
    onSend(inputValue.trim());
    setInputValue('');
  }, [inputValue, onSend]);

  return (
    <div className="fixed inset-0 z-50 bg-black">
      {/* Fullscreen Desktop */}
      <div className="absolute inset-0">{desktopContent}</div>

      {/* Exit Focus Mode Button */}
      <button
        type="button"
        onClick={() => { setMode('chat'); }}
        className="absolute top-4 right-4 z-[60] flex items-center gap-2 px-3 py-1.5 rounded-lg
          bg-black/60 hover:bg-black/80 text-white/80 hover:text-white text-xs font-medium
          backdrop-blur-sm transition-all cursor-pointer"
        title="Exit focus mode (ESC)"
      >
        <Minimize2 size={14} />
        <span>ESC</span>
      </button>

      {/* Floating Chat Bubble */}
      {!focusChatExpanded ? (
        <button
          type="button"
          onClick={toggleFocusChat}
          className={`
            absolute bottom-6 left-6 z-[60] w-12 h-12 rounded-full
            flex items-center justify-center cursor-pointer
            bg-blue-600 hover:bg-blue-500 text-white shadow-lg
            transition-all duration-200 hover:scale-110
            ${isStreaming ? 'animate-pulse' : ''}
          `}
          aria-label="Open chat"
        >
          <MessageSquare size={20} />
          {isStreaming && (
            <span className="absolute -top-1 -right-1 w-3 h-3 bg-amber-400 rounded-full animate-ping" />
          )}
        </button>
      ) : (
        /* Expanded Chat Panel */
        <div
          className="absolute bottom-6 left-6 z-[60] w-[420px] h-[500px] max-h-[70vh]
            rounded-2xl overflow-hidden shadow-2xl border border-white/10
            bg-white dark:bg-slate-900 flex flex-col"
        >
          {/* Chat Header */}
          <div className="flex items-center justify-between px-4 py-3 border-b border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/50">
            <div className="flex items-center gap-2">
              <MessageSquare size={16} className="text-blue-500" />
              <span className="text-sm font-medium text-slate-900 dark:text-slate-100">Chat</span>
              {isStreaming && (
                <span className="flex items-center gap-1 text-xs text-amber-600">
                  <span className="w-1.5 h-1.5 bg-amber-500 rounded-full animate-pulse" />
                  Streaming
                </span>
              )}
            </div>
            <button
              type="button"
              onClick={toggleFocusChat}
              className="p-1 rounded-md text-slate-400 hover:text-slate-600 hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors cursor-pointer"
              aria-label="Close chat"
            >
              <X size={16} />
            </button>
          </div>

          {/* Chat Messages (scrollable) */}
          <div className="flex-1 overflow-y-auto min-h-0">{chatContent}</div>

          {/* Quick Input */}
          <div className="flex-shrink-0 p-3 border-t border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900">
            <div className="flex items-end gap-2">
              <textarea
                ref={inputRef}
                value={inputValue}
                onChange={(e) => { setInputValue(e.target.value); }}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    handleSend();
                  }
                }}
                placeholder="Send a message..."
                rows={1}
                className="flex-1 resize-none rounded-lg border border-slate-300 dark:border-slate-600
                  bg-slate-50 dark:bg-slate-800 px-3 py-2 text-sm
                  text-slate-900 dark:text-slate-100
                  placeholder:text-slate-400
                  focus:outline-none focus:ring-2 focus:ring-blue-500/40 focus:border-blue-500
                  max-h-[100px]"
              />
              <button
                type="button"
                onClick={handleSend}
                disabled={!inputValue.trim() || isStreaming}
                className={`
                  flex-shrink-0 p-2 rounded-lg transition-colors cursor-pointer
                  ${
                    inputValue.trim() && !isStreaming
                      ? 'bg-blue-600 text-white hover:bg-blue-500'
                      : 'bg-slate-200 dark:bg-slate-700 text-slate-400 cursor-not-allowed'
                  }
                `}
                aria-label="Send message"
              >
                <Send size={16} />
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
