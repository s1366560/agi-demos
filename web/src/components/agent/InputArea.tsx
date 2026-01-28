import React, { useState, useRef, useCallback } from "react";
import { Button, Input, Tooltip, Switch } from "antd";
import {
  SendOutlined,
  PaperClipOutlined,
  BuildOutlined,
  StopOutlined,
  LayoutOutlined,
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

  return (
    <div className="p-5 border-t border-slate-200/80 bg-white/80 backdrop-blur-sm" data-testid="agent-input-area">
      <div className="max-w-3xl mx-auto flex flex-col gap-4">
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
              <button
                type="button"
                onClick={onTogglePlanMode}
                data-testid="plan-mode-toggle"
                className="flex items-center gap-2 px-3 py-1.5 rounded-lg hover:bg-slate-100 transition-colors cursor-pointer border border-transparent hover:border-slate-200"
                aria-pressed={isPlanMode}
              >
                <Switch
                  size="small"
                  checked={isPlanMode}
                  className="pointer-events-none"
                />
                <BuildOutlined className={`text-sm ${isPlanMode ? "text-primary" : "text-slate-400"}`} />
                <span className={`text-sm font-medium ${
                  isPlanMode ? "text-primary" : "text-slate-600"
                }`}>
                  Plan Mode
                </span>
              </button>
            </Tooltip>

            <div className="h-4 w-px bg-slate-200" />

            <Tooltip title={showPlanPanel ? "Hide Plan Panel" : "Show Plan Panel"}>
              <button
                type="button"
                onClick={onTogglePlanPanel}
                data-testid="plan-panel-toggle"
                className="flex items-center gap-2 px-3 py-1.5 rounded-lg hover:bg-slate-100 transition-colors cursor-pointer border border-transparent hover:border-slate-200"
                aria-pressed={showPlanPanel}
              >
                <Switch
                  size="small"
                  checked={showPlanPanel}
                  className="pointer-events-none"
                />
                <LayoutOutlined className={`text-sm ${showPlanPanel ? "text-primary" : "text-slate-400"}`} />
                <span className={`text-sm font-medium ${
                  showPlanPanel ? "text-primary" : "text-slate-600"
                }`}>
                  Panel
                </span>
              </button>
            </Tooltip>
          </div>
        </div>

        {/* Input Field */}
        <div className="relative rounded-2xl border border-slate-200 shadow-sm bg-white focus-within:ring-2 focus-within:ring-primary/30 focus-within:border-primary/50 focus-within:shadow-md transition-all duration-200">
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
              disabled={isStreaming}
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
                type="primary"
                shape="circle"
                size="large"
                icon={<SendOutlined />}
                onClick={handleSend}
                disabled={!value.trim()}
                className={`shadow-sm hover:shadow-md transition-shadow ${!value.trim() ? 'opacity-40' : ''}`}
                data-testid="send-message-button"
                aria-label="Send message"
              />
            )}
          </div>
        </div>

        <div className="text-center">
          <span className="text-[11px] text-slate-400">
            Agent can make mistakes. Consider checking important information.
          </span>
        </div>
      </div>
    </div>
  );
};
