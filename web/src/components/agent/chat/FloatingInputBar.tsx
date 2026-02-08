/**
 * FloatingInputBar - Floating input bar for agent messages
 *
 * Bottom-centered input bar with attachment, voice input, and send buttons.
 * Matches design from docs/statics/project workbench/agent/start/
 * Supports disabled state with stop button during agent execution.
 *
 * REFACTORED: Boolean props replaced with config object pattern for better extensibility.
 * Backward compatibility maintained through individual prop support.
 */

import { KeyboardEvent, useState, useId, useRef, useCallback } from 'react';

/**
 * Plan mode configuration
 */
export interface FloatingInputBarPlanModeConfig {
  /** Callback when Plan Mode button is clicked */
  onPlanMode: () => void;
  /** Whether currently in Plan Mode */
  isInPlanMode: boolean;
  /** Whether Plan Mode button should be disabled */
  disabled: boolean;
}

/**
 * Configuration object for FloatingInputBar
 *
 * Replaces multiple boolean props with a structured configuration.
 * This pattern makes the component more maintainable and extensible.
 */
export interface FloatingInputBarConfig {
  /** Whether to show attachment button */
  showAttachment?: boolean;
  /** Whether to show voice input button */
  showVoice?: boolean;
  /** Whether to show footer with options */
  showFooter?: boolean;
  /** Plan mode configuration */
  planMode?: FloatingInputBarPlanModeConfig;
}

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
  /** Optional stop button label */
  stopLabel?: string;
  /** Maximum input length */
  maxLength?: number;

  // Legacy individual props (for backward compatibility)
  /** @deprecated Use config.showAttachment instead */
  showAttachment?: boolean;
  /** @deprecated Use config.showVoice instead */
  showVoice?: boolean;
  /** @deprecated Use config.showFooter instead */
  showFooter?: boolean;
  /** @deprecated Use config.planMode instead */
  onPlanMode?: () => void;
  /** @deprecated Use config.planMode.isInPlanMode instead */
  isInPlanMode?: boolean;
  /** @deprecated Use config.planMode.disabled instead */
  planModeDisabled?: boolean;

  /** New config object pattern */
  config?: FloatingInputBarConfig;
}

/**
 * Merge config with individual props (config takes precedence)
 */
function useFloatingInputBarConfig(props: FloatingInputBarProps) {
  const {
    config,
    showAttachment: propShowAttachment,
    showVoice: propShowVoice,
    showFooter: propShowFooter,
    onPlanMode: propOnPlanMode,
    isInPlanMode: propIsInPlanMode,
    planModeDisabled: propPlanModeDisabled,
  } = props;

  const showAttachment = config?.showAttachment ?? propShowAttachment ?? true;
  const showVoice = config?.showVoice ?? propShowVoice ?? true;
  const showFooter = config?.showFooter ?? propShowFooter ?? true;

  // Plan mode config merging
  const planMode = config?.planMode
    ? config.planMode
    : propOnPlanMode
      ? {
          onPlanMode: propOnPlanMode,
          isInPlanMode: propIsInPlanMode ?? false,
          disabled: propPlanModeDisabled ?? false,
        }
      : undefined;

  return {
    showAttachment,
    showVoice,
    showFooter,
    planMode,
  };
}

/**
 * FloatingInputBar component
 *
 * @example
 * // Using config object (recommended)
 * <FloatingInputBar
 *   value={message}
 *   onChange={setMessage}
 *   onSend={(msg) => sendMessage(msg)}
 *   config={{
 *     showAttachment: true,
 *     showVoice: false,
 *     planMode: { onPlanMode, isInPlanMode: false, disabled: false }
 *   }}
 * />
 *
 * @example
 * // Using individual props (legacy, still supported)
 * <FloatingInputBar
 *   value={message}
 *   onChange={setMessage}
 *   onSend={(msg) => sendMessage(msg)}
 *   showAttachment={true}
 *   showVoice={false}
 * />
 */
export function FloatingInputBar({
  value = '',
  onChange,
  onSend,
  onStop,
  disabled = false,
  placeholder = "Message the Agent or type '/' for commands...",
  stopLabel = 'Stop',
  maxLength = 5000,
  ...restProps
}: FloatingInputBarProps) {
  const [internalValue, setInternalValue] = useState(value);
  const [deepSearch, setDeepSearch] = useState(true);
  const [markdownExport, setMarkdownExport] = useState(false);

  // Generate unique IDs for form elements
  const deepSearchId = useId();
  const markdownExportId = useId();

  // Merge config with individual props
  const { showAttachment, showVoice, showFooter, planMode } = useFloatingInputBarConfig(restProps);

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
      handleChange('');
    }
  };

  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleInput = useCallback((e: React.FormEvent<HTMLTextAreaElement>) => {
    const target = e.currentTarget;
    target.style.height = 'auto';
    // Minimum height for 3 lines (approx 60px + padding)
    const minHeight = 60;
    const newHeight = Math.max(minHeight, Math.min(target.scrollHeight, 200));
    target.style.height = `${newHeight}px`;
  }, []);

  const handleStop = () => {
    onStop?.();
  };

  return (
    <div className="w-full">
      <div className="bg-white dark:bg-surface-dark border border-slate-200 dark:border-border-dark shadow-sm rounded-2xl p-2 flex flex-col gap-2">
        <div className="flex items-end gap-2">
          {/* Attachment Button */}
          {showAttachment && !disabled && (
            <button
              className="p-2.5 text-slate-500 hover:text-primary transition-colors"
              title="Attach context"
              type="button"
              aria-label="Attach context"
            >
              <span className="material-symbols-outlined">attach_file</span>
            </button>
          )}

          {/* Text Input - Textarea for multi-line support */}
          <textarea
            ref={textareaRef}
            value={inputValue}
            onChange={(e) => {
              handleChange(e.target.value);
              handleInput(e);
            }}
            onKeyDown={handleKeyDown}
            placeholder={disabled ? 'Agent is thinking...' : placeholder}
            disabled={disabled}
            maxLength={maxLength}
            rows={3}
            className={`flex-1 bg-transparent border-none focus:ring-0 text-slate-900 dark:text-white py-2 px-0 placeholder:text-text-muted text-sm resize-none overflow-hidden min-h-[60px] ${
              disabled ? 'cursor-not-allowed opacity-50' : ''
            }`}
            aria-label="Message input"
          />

          {/* Right side buttons */}
          <div className="flex items-center gap-1 pb-1 pr-1">
            {/* Voice Input Button (only when not disabled) */}
            {showVoice && !disabled && (
              <button
                className="p-2.5 text-slate-500 hover:text-red-500 transition-colors"
                title="Voice input"
                type="button"
                aria-label="Voice input"
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
                aria-label={stopLabel}
              >
                <span className="material-symbols-outlined text-[18px]">stop_circle</span>
              </button>
            ) : (
              <button
                onClick={handleSend}
                disabled={!inputValue.trim()}
                className="w-10 h-10 bg-primary text-white rounded-xl flex items-center justify-center hover:bg-blue-700 shadow-lg shadow-primary/20 transition-all disabled:bg-slate-200 disabled:shadow-none"
                title="Send message"
                type="submit"
                aria-label="Send message"
              >
                <span className="material-symbols-outlined">send</span>
              </button>
            )}
          </div>
        </div>

        {/* Options Footer */}
        {showFooter && (
          <div className="flex justify-between items-center mt-1 px-2 pb-1 border-t border-slate-100 dark:border-slate-800/50 pt-2">
            <div className="flex items-center gap-4">
              <label
                htmlFor={deepSearchId}
                className="flex items-center gap-2 cursor-pointer group"
              >
                <input
                  id={deepSearchId}
                  type="checkbox"
                  checked={deepSearch}
                  onChange={(e) => setDeepSearch(e.target.checked)}
                  className="rounded border-slate-300 text-primary focus:ring-primary h-3 w-3"
                />
                <span className="text-[10px] font-semibold text-slate-500 group-hover:text-slate-700 dark:group-hover:text-slate-300 transition-colors uppercase tracking-wider">
                  Deep Search
                </span>
              </label>
              <label
                htmlFor={markdownExportId}
                className="flex items-center gap-2 cursor-pointer group"
              >
                <input
                  id={markdownExportId}
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
              {planMode && !planMode.isInPlanMode && (
                <>
                  <div className="h-4 w-px bg-slate-200 dark:bg-slate-700" />
                  <button
                    type="button"
                    onClick={planMode.onPlanMode}
                    disabled={planMode.disabled || disabled}
                    className="flex items-center gap-1.5 text-[10px] font-semibold text-purple-600 hover:text-purple-700 dark:text-purple-400 dark:hover:text-purple-300 transition-colors uppercase tracking-wider disabled:opacity-50 disabled:cursor-not-allowed"
                    title="Enter Plan Mode to create and refine implementation plans"
                  >
                    <span className="material-symbols-outlined text-sm">architecture</span>
                    Plan Mode
                  </button>
                </>
              )}
              {planMode?.isInPlanMode && (
                <>
                  <div className="h-4 w-px bg-slate-200 dark:bg-slate-700" />
                  <span className="flex items-center gap-1.5 text-[10px] font-semibold text-purple-600 dark:text-purple-400 uppercase tracking-wider">
                    <span className="material-symbols-outlined text-sm">architecture</span>
                    In Plan Mode
                  </span>
                </>
              )}
            </div>

          </div>
        )}
      </div>
    </div>
  );
}

export default FloatingInputBar;
