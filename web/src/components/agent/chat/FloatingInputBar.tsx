/**
 * FloatingInputBar - Floating input bar for agent messages
 *
 * Bottom-centered input bar with attachment, voice input, and send buttons.
 * Matches design from docs/statics/project workbench/agent/start/
 * Supports disabled state with stop button during agent execution.
 */

import { KeyboardEvent, useState } from "react";

export interface FloatingInputBarProps {
  /** Current input value */
  value?: string;
  /** Callback when input value changes */
  onChange?: (value: string) => void;
  /** Callback when send button is clicked */
  onSend?: (message: string) => void;
  /** Callback when stop button is clicked */
  onStop?: () => void;
  /** Whether input is disabled (during agent execution) */
  disabled?: boolean;
  /** Placeholder text */
  placeholder?: string;
  /** Whether to show attachment button */
  showAttachment?: boolean;
  /** Whether to show voice input button */
  showVoice?: boolean;
  /** Optional stop button label */
  stopLabel?: string;
  /** Maximum input length */
  maxLength?: number;
  /** Whether to show footer label */
  showFooter?: boolean;
  /** Callback when Plan Mode button is clicked */
  onPlanMode?: () => void;
  /** Whether currently in Plan Mode */
  isInPlanMode?: boolean;
  /** Whether Plan Mode button should be disabled */
  planModeDisabled?: boolean;
}

/**
 * FloatingInputBar component
 *
 * @example
 * <FloatingInputBar
 *   value={message}
 *   onChange={setMessage}
 *   onSend={(msg) => sendMessage(msg)}
 * />
 */
export function FloatingInputBar({
  value = "",
  onChange,
  onSend,
  onStop,
  disabled = false,
  placeholder = "Message the Agent or type '/' for commands...",
  showAttachment = true,
  showVoice = true,
  stopLabel = "Stop",
  maxLength = 5000,
  showFooter: _showFooter = true,
  onPlanMode,
  isInPlanMode = false,
  planModeDisabled = false,
}: FloatingInputBarProps) {
  const [internalValue, setInternalValue] = useState(value);
  const [deepSearch, setDeepSearch] = useState(true);
  const [markdownExport, setMarkdownExport] = useState(false);

  // Use controlled or uncontrolled based on whether onChange is provided
  const inputValue = onChange !== undefined ? value : internalValue;
  const handleChange = (newValue: string) => {
    if (onChange) {
      onChange(newValue);
    } else {
      setInternalValue(newValue);
    }
  };

  const handleSend = () => {
    const trimmed = inputValue.trim();
    if (trimmed && !disabled) {
      onSend?.(trimmed);
      handleChange("");
    }
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleStop = () => {
    onStop?.();
  };

  return (
    <div className="w-full">
      <div className="bg-white dark:bg-surface-dark border border-slate-200 dark:border-border-dark shadow-sm rounded-2xl p-2 flex flex-col gap-2">
        {/* Attached Items (Mock) */}
        {/* 
        <div className="flex items-center gap-2 px-2 overflow-x-auto py-1 custom-scrollbar">
            <div className="flex items-center gap-2 bg-slate-100 dark:bg-slate-800 rounded-lg px-2 py-1 pr-1 shrink-0 border border-slate-200 dark:border-slate-700">
                <span className="material-symbols-outlined text-xs text-slate-500">article</span>
                <span className="text-[10px] font-medium max-w-[80px] truncate">q3_report.pdf</span>
                <button className="hover:text-red-500 flex items-center"><span className="material-symbols-outlined text-[14px]">close</span></button>
            </div>
        </div>
        */}

        <div className="flex items-end gap-2">
          {/* Attachment Button */}
          {showAttachment && !disabled && (
            <button
              className="p-2.5 text-slate-500 hover:text-primary transition-colors"
              title="Attach context"
              type="button"
            >
              <span className="material-symbols-outlined">attach_file</span>
            </button>
          )}

          {/* Text Input */}
          <input
            value={inputValue}
            onChange={(e) => handleChange(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={disabled ? "Agent is thinking..." : placeholder}
            disabled={disabled}
            maxLength={maxLength}
            className={`flex-1 bg-transparent border-none focus:ring-0 text-slate-900 dark:text-white py-2 px-0 placeholder:text-text-muted text-sm ${
              disabled ? "cursor-not-allowed opacity-50" : ""
            }`}
            type="text"
          />

          {/* Right side buttons */}
          <div className="flex items-center gap-1 pb-1 pr-1">
            {/* Voice Input Button (only when not disabled) */}
            {showVoice && !disabled && (
              <button
                className="p-2.5 text-slate-500 hover:text-red-500 transition-colors"
                title="Voice input"
                type="button"
              >
                <span className="material-symbols-outlined">mic</span>
              </button>
            )}

            {/* Send or Stop Button */}
            {disabled ? (
              <button
                onClick={handleStop}
                className="w-10 h-10 bg-red-500/10 hover:bg-red-500/20 text-red-600 rounded-xl flex items-center justify-center transition-all border border-red-500/20"
                type="button"
                title={stopLabel}
              >
                <span className="material-symbols-outlined text-[18px]">
                  stop_circle
                </span>
              </button>
            ) : (
              <button
                onClick={handleSend}
                disabled={!inputValue.trim()}
                className="w-10 h-10 bg-primary text-white rounded-xl flex items-center justify-center hover:bg-blue-700 shadow-lg shadow-primary/20 transition-all disabled:bg-slate-200 disabled:shadow-none"
                title="Send message"
                type="button"
              >
                <span className="material-symbols-outlined">send</span>
              </button>
            )}
          </div>
        </div>

        {/* Options Footer */}
        <div className="flex justify-between items-center mt-1 px-2 pb-1 border-t border-slate-100 dark:border-slate-800/50 pt-2">
          <div className="flex items-center gap-4">
            <label className="flex items-center gap-2 cursor-pointer group">
              <input
                type="checkbox"
                checked={deepSearch}
                onChange={(e) => setDeepSearch(e.target.checked)}
                className="rounded border-slate-300 text-primary focus:ring-primary h-3 w-3"
              />
              <span className="text-[10px] font-semibold text-slate-500 group-hover:text-slate-700 dark:group-hover:text-slate-300 transition-colors uppercase tracking-wider">
                Deep Search
              </span>
            </label>
            <label className="flex items-center gap-2 cursor-pointer group">
              <input
                type="checkbox"
                checked={markdownExport}
                onChange={(e) => setMarkdownExport(e.target.checked)}
                className="rounded border-slate-300 text-primary focus:ring-primary h-3 w-3"
              />
              <span className="text-[10px] font-semibold text-slate-500 group-hover:text-slate-700 dark:group-hover:text-slate-300 transition-colors uppercase tracking-wider">
                Markdown Export
              </span>
            </label>
            {/* Plan Mode Button */}
            {onPlanMode && !isInPlanMode && (
              <>
                <div className="h-4 w-px bg-slate-200 dark:bg-slate-700" />
                <button
                  type="button"
                  onClick={onPlanMode}
                  disabled={planModeDisabled || disabled}
                  className="flex items-center gap-1.5 text-[10px] font-semibold text-purple-600 hover:text-purple-700 dark:text-purple-400 dark:hover:text-purple-300 transition-colors uppercase tracking-wider disabled:opacity-50 disabled:cursor-not-allowed"
                  title="Enter Plan Mode to create and refine implementation plans"
                >
                  <span className="material-symbols-outlined text-sm">
                    architecture
                  </span>
                  Plan Mode
                </button>
              </>
            )}
            {isInPlanMode && (
              <>
                <div className="h-4 w-px bg-slate-200 dark:bg-slate-700" />
                <span className="flex items-center gap-1.5 text-[10px] font-semibold text-purple-600 dark:text-purple-400 uppercase tracking-wider">
                  <span className="material-symbols-outlined text-sm">
                    architecture
                  </span>
                  In Plan Mode
                </span>
              </>
            )}
          </div>
          <div className="text-[10px] text-slate-400">
            Press{" "}
            <kbd className="px-1 py-0.5 bg-slate-100 dark:bg-slate-800 rounded border border-slate-200 dark:border-slate-700 font-sans">
              Enter
            </kbd>{" "}
            to send
          </div>
        </div>
      </div>
    </div>
  );
}

export default FloatingInputBar;
