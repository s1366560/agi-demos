import React, { useState, useRef, useCallback } from "react";
import { Button, Input, Tooltip, Switch } from "antd";
import {
  SendOutlined,
  PaperClipOutlined,
  BuildOutlined,
  StopOutlined,
  LayoutOutlined,
  EditOutlined,
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
 * InputArea Component - Message input area for agent chat
 *
 * Provides a polished input interface with toolbar controls,
 * mode toggles, and send/abort actions.
 *
 * Features Plan Mode visual feedback with different styling.
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
  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }, [handleSend]);

  // Dynamic styling based on Plan Mode
  const planModeClass = isPlanMode
    ? "bg-blue-50/50 border-blue-200/60"
    : "bg-white/80 backdrop-blur-sm";

  const inputFieldClass = isPlanMode
    ? "border-blue-300 focus-within:ring-blue-100 focus-within:border-blue-400"
    : "border-slate-200 focus-within:ring-primary/30 focus-within:border-primary/50";

  return (
    <div
      className={`p-5 border-t ${planModeClass} transition-colors duration-300`}
      data-testid="agent-input-area"
    >
      <div className="w-full max-w-3xl lg:max-w-5xl xl:max-w-7xl mx-auto flex flex-col gap-4">
        {/* Toolbar */}
        <div className="flex items-center justify-between px-2" data-testid="agent-toolbar">
          <div className="flex items-center gap-5">
            <Tooltip
              title={
                isPlanMode
                  ? "Plan Mode Active (Read-only research)"
                  : "Switch to Plan Mode"
              }
            >
              <div
                role="button"
                tabIndex={0}
                onClick={onTogglePlanMode}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    onTogglePlanMode();
                  }
                }}
                data-testid="plan-mode-toggle"
                className={`flex items-center gap-2 px-3 py-1.5 rounded-lg hover:bg-slate-100 transition-colors cursor-pointer border ${
                  isPlanMode
                    ? "border-blue-300 bg-blue-50"
                    : "border-transparent hover:border-slate-200"
                }`}
                aria-pressed={isPlanMode}
              >
                <Switch
                  size="small"
                  checked={isPlanMode}
                  className="pointer-events-none"
                />
                <BuildOutlined
                  className={`text-sm ${
                    isPlanMode ? "text-blue-600" : "text-slate-400"
                  }`}
                />
                <span
                  className={`text-sm font-medium ${
                    isPlanMode ? "text-blue-600" : "text-slate-600"
                  }`}
                >
                  Plan Mode
                </span>
              </div>
            </Tooltip>

            <div className="h-4 w-px bg-slate-200" />

            <Tooltip title={showPlanPanel ? "Hide Plan Panel" : "Show Plan Panel"}>
              <div
                role="button"
                tabIndex={0}
                onClick={onTogglePlanPanel}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    onTogglePlanPanel();
                  }
                }}
                data-testid="plan-panel-toggle"
                className="flex items-center gap-2 px-3 py-1.5 rounded-lg hover:bg-slate-100 transition-colors cursor-pointer border border-transparent hover:border-slate-200"
                aria-pressed={showPlanPanel}
              >
                <Switch
                  size="small"
                  checked={showPlanPanel}
                  className="pointer-events-none"
                />
                <LayoutOutlined
                  className={`text-sm ${showPlanPanel ? "text-primary" : "text-slate-400"}`}
                />
                <span
                  className={`text-sm font-medium ${
                    showPlanPanel ? "text-primary" : "text-slate-600"
                  }`}
                >
                  Panel
                </span>
              </div>
            </Tooltip>
          </div>

          {/* Plan Mode indicator icon (shown when in plan mode) */}
          {isPlanMode && (
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-blue-50 border border-blue-200">
              <EditOutlined className="text-sm text-blue-600" />
              <span className="text-xs text-blue-600 font-medium">
                Planning Mode
              </span>
            </div>
          )}
        </div>

        {/* Input Field */}
        <div
          className={`relative rounded-2xl border shadow-sm bg-white transition-all duration-200 ${inputFieldClass}`}
        >
          <TextArea
            ref={textareaRef}
            id="agent-message-input"
            name="agent-message"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={
              isPlanMode
                ? "Describe what you want to plan..."
                : "Message Agent..."
            }
            autoSize={{ minRows: 2, maxRows: 8 }}
            className="!border-0 !shadow-none !bg-transparent !px-5 !py-4 !text-sm !resize-none rounded-2xl"
            disabled={isStreaming}
            data-testid="agent-message-textarea"
            aria-label={isPlanMode ? "Describe what you want to plan" : "Message Agent"}
            aria-required="false"
            style={{ fontSize: '14px', lineHeight: '1.5' }}
          />

          <div className="flex justify-between items-center px-3 pb-3">
            <Button
              type="text"
              icon={<PaperClipOutlined />}
              className="text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors rounded-lg h-9 w-9"
              disabled={isStreaming || isPlanMode}
              data-testid="attach-button"
              aria-label="Attach file"
            />

            {isStreaming ? (
              <Button
                type="primary"
                danger
                shape="circle"
                size="large"
                icon={<StopOutlined />}
                onClick={onAbort}
                className="shadow-sm hover:shadow-md transition-shadow"
                data-testid="stop-streaming-button"
                aria-label="Stop generation"
              />
            ) : (
              <Button
                type={isPlanMode ? "default" : "primary"}
                shape="circle"
                size="large"
                icon={<SendOutlined />}
                onClick={handleSend}
                disabled={!value.trim()}
                className={`shadow-sm hover:shadow-md transition-shadow ${
                  !value.trim() ? 'opacity-40' : ''
                } ${isPlanMode ? "border-blue-500 hover:bg-blue-50 hover:!bg-blue-500 hover:!text-blue-500" : ""}`}
                data-testid="send-message-button"
                aria-label="Send message"
                style={isPlanMode ? { borderColor: '#1890ff', color: '#1890ff' } : undefined}
              />
            )}
          </div>
        </div>

        <div className="text-center">
          <span className="text-[11px] text-slate-400">
            {isPlanMode
              ? "In Plan Mode: Describe your goals, and I'll create a structured plan for approval."
              : "Agent can make mistakes. Consider checking important information."
            }
          </span>
        </div>
      </div>
    </div>
  );
};
