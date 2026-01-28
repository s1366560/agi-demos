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
    <div className="p-4 border-t border-slate-200 bg-white">
      <div className="max-w-4xl mx-auto flex flex-col gap-3">
        {/* Toolbar */}
        <div className="flex items-center justify-between px-1">
          <div className="flex items-center gap-4">
            <Tooltip
              title={
                isPlanMode
                  ? "Plan Mode Active (Read-only research)"
                  : "Switch to Plan Mode"
              }
            >
              <div
                className="flex items-center gap-2 cursor-pointer"
                onClick={onTogglePlanMode}
              >
                <Switch size="small" checked={isPlanMode} />
                <span
                  className={`text-xs font-medium ${
                    isPlanMode ? "text-purple-600" : "text-slate-500"
                  }`}
                >
                  <BuildOutlined className="mr-1" />
                  Plan Mode
                </span>
              </div>
            </Tooltip>

            <div className="h-4 w-px bg-slate-200" />

            <Tooltip title={showPlanPanel ? "Hide Plan Panel" : "Show Plan Panel"}>
              <div
                className="flex items-center gap-2 cursor-pointer"
                onClick={onTogglePlanPanel}
              >
                <Switch size="small" checked={showPlanPanel} />
                <span
                  className={`text-xs font-medium ${
                    showPlanPanel ? "text-blue-600" : "text-slate-500"
                  }`}
                >
                  <LayoutOutlined className="mr-1" />
                  Plan Panel
                </span>
              </div>
            </Tooltip>
          </div>
        </div>

        {/* Input Field */}
        <div className="relative rounded-xl border border-slate-200 shadow-sm bg-white focus-within:ring-2 focus-within:ring-primary/20 transition-all">
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
            autoSize={{ minRows: 1, maxRows: 8 }}
            className="!border-0 !shadow-none !bg-transparent !px-4 !py-3 !text-sm !resize-none"
            disabled={isStreaming}
          />

          <div className="flex justify-between items-center px-2 pb-2">
            <Button
              type="text"
              icon={<PaperClipOutlined />}
              className="text-slate-400 hover:text-slate-600"
              disabled={isStreaming}
            />

            {isStreaming ? (
              <Button
                type="primary"
                danger
                shape="circle"
                icon={<StopOutlined />}
                onClick={onAbort}
              />
            ) : (
              <Button
                type="primary"
                shape="circle"
                icon={<SendOutlined />}
                onClick={handleSend}
                disabled={!value.trim()}
              />
            )}
          </div>
        </div>

        <div className="text-center">
          <span className="text-[10px] text-slate-400">
            Agent V3 can make mistakes. Check important info.
          </span>
        </div>
      </div>
    </div>
  );
};
