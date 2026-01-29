import React, { useState, useRef, useCallback } from "react";
import { Button, Input, Tooltip, Badge } from "antd";
import {
  SendOutlined,
  PaperClipOutlined,
  BuildOutlined,
  StopOutlined,
  LayoutOutlined,
  LoadingOutlined,
} from "@ant-design/icons";

const { TextArea } = Input;

interface InputAreaProps {
  onSend: (content: string) => void;
  onAbort: () => void;
  isStreaming: boolean;
  isPlanMode: boolean;
  onTogglePlanMode: () => void;
  showPlanPanel: boolean;
  onTogglePlanPanel: () => void;
}

/**
 * InputArea Component - Optimized message input area for agent chat
 *
 * Features:
 * - Compact toolbar with integrated mode indicators
 * - Clean input field with floating action buttons
 * - Visual feedback for Plan Mode
 * - Responsive design
 *
 * @component
 */
export const InputArea: React.FC<InputAreaProps> = ({
  onSend,
  onAbort,
  isStreaming,
  isPlanMode,
  onTogglePlanMode,
  showPlanPanel,
  onTogglePlanPanel,
}) => {
  const [value, setValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Stable callback for sending messages
  const handleSend = useCallback(() => {
    if (!value.trim()) return;
    onSend(value);
    setValue("");
  }, [value, onSend]);

  // Stable callback for keyboard shortcuts
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend]
  );

  // Dynamic styling based on Plan Mode
  const containerClass = isPlanMode
    ? "bg-gradient-to-r from-blue-50/80 via-white/90 to-blue-50/80 border-t-blue-200/50"
    : "bg-white/95 border-t-slate-200/60";

  const inputContainerClass = isPlanMode
    ? "border-blue-300/60 shadow-blue-100/50 focus-within:ring-blue-200 focus-within:border-blue-400"
    : "border-slate-200/80 focus-within:ring-primary/20 focus-within:border-primary/40";

  return (
    <div
      className={`${containerClass} border-t backdrop-blur-xl transition-all duration-300`}
      data-testid="agent-input-area"
    >
      <div className="w-full max-w-4xl mx-auto px-4 py-4">
        {/* Compact Toolbar */}
        <div
          className="flex items-center justify-between mb-3 px-1"
          data-testid="agent-toolbar"
        >
          {/* Left: Mode Toggles */}
          <div className="flex items-center gap-2">
            {/* Plan Mode Toggle */}
            <Tooltip
              title={
                isPlanMode
                  ? "Exit Plan Mode (Read-only research)"
                  : "Enter Plan Mode"
              }
            >
              <button
                onClick={onTogglePlanMode}
                data-testid="plan-mode-toggle"
                className={`
                  flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-medium
                  transition-all duration-200 border
                  ${
                    isPlanMode
                      ? "bg-blue-100 border-blue-300 text-blue-700 shadow-sm"
                      : "bg-slate-100 border-slate-200 text-slate-600 hover:bg-slate-200"
                  }
                `}
              >
                <BuildOutlined className="text-xs" />
                <span>Plan</span>
                {isStreaming && isPlanMode && (
                  <LoadingOutlined className="text-xs ml-1" spin />
                )}
              </button>
            </Tooltip>

            {/* Panel Toggle */}
            <Tooltip
              title={showPlanPanel ? "Hide Side Panel" : "Show Side Panel"}
            >
              <button
                onClick={onTogglePlanPanel}
                data-testid="plan-panel-toggle"
                className={`
                  flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-medium
                  transition-all duration-200 border
                  ${
                    showPlanPanel
                      ? "bg-primary/10 border-primary/30 text-primary shadow-sm"
                      : "bg-slate-100 border-slate-200 text-slate-600 hover:bg-slate-200"
                  }
                `}
              >
                <LayoutOutlined className="text-xs" />
                <span>Panel</span>
              </button>
            </Tooltip>
          </div>

          {/* Right: Status */}
          <div className="flex items-center gap-2">
            {isStreaming && (
              <Badge
                status="processing"
                text={<span className="text-xs text-slate-500">Thinking...</span>}
              />
            )}
          </div>
        </div>

        {/* Input Field Container */}
        <div
          className={`
            relative rounded-2xl border bg-white shadow-sm
            transition-all duration-200 ${inputContainerClass}
            focus-within:ring-2 focus-within:shadow-md
          `}
        >
          {/* Plan Mode Badge - Floating */}
          {isPlanMode && (
            <div className="absolute -top-3 left-4 z-10">
              <span className="px-2.5 py-0.5 rounded-full bg-blue-500 text-white text-[10px] font-medium shadow-sm">
                Plan Mode
              </span>
            </div>
          )}

          <TextArea
            ref={textareaRef}
            id="agent-message-input"
            name="agent-message"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={
              isPlanMode
                ? "Describe what you want to plan... (Shift+Enter for new line)"
                : "Message the AI agent... (Shift+Enter for new line)"
            }
            autoSize={{ minRows: 1, maxRows: 6 }}
            className="!border-0 !shadow-none !bg-transparent !px-4 !py-3.5 !text-sm !resize-none rounded-2xl"
            disabled={isStreaming}
            data-testid="agent-message-textarea"
            aria-label={
              isPlanMode ? "Describe what you want to plan" : "Message Agent"
            }
            style={{
              fontSize: "14px",
              lineHeight: "1.6",
            }}
          />

          {/* Action Buttons */}
          <div className="flex justify-between items-center px-3 pb-3 pt-1">
            {/* Left: Attach */}
            <Tooltip title="Attach file (coming soon)">
              <Button
                type="text"
                icon={<PaperClipOutlined />}
                className="text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors rounded-lg h-8 w-8"
                disabled={isStreaming || isPlanMode}
                data-testid="attach-button"
              />
            </Tooltip>

            {/* Right: Send/Stop */}
            <div className="flex items-center gap-2">
              {/* Character Count - subtle */}
              {value.length > 0 && !isStreaming && (
                <span className="text-[10px] text-slate-400 px-2">
                  {value.length}
                </span>
              )}

              {isStreaming ? (
                <Button
                  type="primary"
                  danger
                  shape="circle"
                  size="large"
                  icon={<StopOutlined />}
                  onClick={onAbort}
                  className="shadow-md hover:shadow-lg transition-all"
                  data-testid="stop-streaming-button"
                />
              ) : (
                <Button
                  type={isPlanMode ? "default" : "primary"}
                  shape="circle"
                  size="large"
                  icon={<SendOutlined />}
                  onClick={handleSend}
                  disabled={!value.trim()}
                  className={`
                    shadow-sm hover:shadow-md transition-all
                    ${!value.trim() ? "opacity-40" : ""}
                    ${
                      isPlanMode
                        ? "border-blue-500 text-blue-500 hover:bg-blue-50"
                        : ""
                    }
                  `}
                  data-testid="send-message-button"
                />
              )}
            </div>
          </div>
        </div>

        {/* Footer Hint */}
        <div className="text-center mt-2">
          <span className="text-[10px] text-slate-400">
            {isPlanMode ? (
              <span className="text-blue-500/70">
                Plan Mode: AI will help create a structured plan for approval
              </span>
            ) : (
              "AI responses are generated based on context and may vary"
            )}
          </span>
        </div>
      </div>
    </div>
  );
};

export default InputArea;
