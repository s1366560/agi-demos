import React, { memo, useMemo, useCallback, useState } from "react";
import { Button } from "antd";
import {
  RightOutlined,
  LeftOutlined,
} from "@ant-design/icons";
import { useAgentV3Store } from "../../stores/agentV3";

/**
 * Props for ChatLayout component
 */
interface ChatLayoutProps {
  /** Left sidebar content (conversation history) */
  sidebar: React.ReactNode;
  /** Main chat area content */
  chatArea: React.ReactNode;
  /** Right panel content (Plan + Sandbox tabs) */
  rightPanel: React.ReactNode;
  /** @deprecated Use rightPanel instead - legacy plan panel */
  planPanel?: React.ReactNode;
}

/**
 * Width constraints (in pixels)
 */
const MIN_LEFT = 200;
const MAX_LEFT = 400;
const DEFAULT_LEFT = 260;

const MIN_RIGHT = 320;
const MAX_RIGHT = 600;
const DEFAULT_RIGHT = 380;

/**
 * Custom drag handle component
 */
const DragHandle: React.FC<{
  onDrag: (deltaX: number) => void;
  className?: string;
}> = ({ onDrag, className = "" }) => {
  const [isDragging, setIsDragging] = useState(false);

  const handleMouseDown = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      setIsDragging(true);
      const startX = e.clientX;

      const handleMouseMove = (moveEvent: MouseEvent) => {
        const deltaX = moveEvent.clientX - startX;
        onDrag(deltaX);
      };

      const handleMouseUp = () => {
        setIsDragging(false);
        document.removeEventListener("mousemove", handleMouseMove);
        document.removeEventListener("mouseup", handleMouseUp);
      };

      document.addEventListener("mousemove", handleMouseMove);
      document.addEventListener("mouseup", handleMouseUp);
    },
    [onDrag]
  );

  return (
    <div
      onMouseDown={handleMouseDown}
      className={`
        absolute top-0 bottom-0 w-1 cursor-ew-resize z-50
        transition-colors duration-150
        ${isDragging ? "bg-primary" : "bg-transparent hover:bg-primary/30"}
        ${className}
      `}
    >
      {/* Visual indicator line */}
      <div
        className={`
          absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2
          w-0.5 h-8 rounded-full
          ${isDragging ? "bg-white" : "bg-slate-300"}
        `}
      />
    </div>
  );
};

/**
 * Floating Toggle Button Component
 */
const FloatingToggle: React.FC<{
  icon: React.ReactNode;
  onClick: () => void;
  label: string;
}> = ({ icon, onClick, label }) => (
  <Button
    icon={icon}
    onClick={onClick}
    type="text"
    size="middle"
    className={`
      bg-white/95 backdrop-blur-md shadow-sm border border-slate-200/70
      hover:shadow-md hover:border-primary/30 transition-all duration-200 rounded-lg
      flex items-center gap-2 px-3 h-9
    `}
    aria-label={label}
  >
    <span className="text-xs text-slate-600 font-medium">{label}</span>
  </Button>
);

/**
 * ChatLayout Component - Optimized three-panel layout with custom drag resizing
 *
 * Features:
 * - Responsive panel widths with sensible defaults
 * - Smooth drag resizing with visual feedback
 * - Floating toggle buttons for panel visibility
 * - Optimized spacing and visual hierarchy
 */
export const ChatLayout: React.FC<ChatLayoutProps> = memo(
  ({ sidebar, chatArea, rightPanel, planPanel }) => {
    const {
      showPlanPanel,
      showHistorySidebar,
      toggleHistorySidebar,
      togglePlanPanel,
      leftSidebarWidth,
      rightPanelWidth,
      setLeftSidebarWidth,
      setRightPanelWidth,
    } = useAgentV3Store();

    // Use sensible defaults if not set
    const effectiveLeftWidth = leftSidebarWidth || DEFAULT_LEFT;
    const effectiveRightWidth = rightPanelWidth || DEFAULT_RIGHT;

    const panelContent = useMemo(
      () => rightPanel || planPanel,
      [rightPanel, planPanel]
    );

    // Handle left sidebar drag
    const handleLeftDrag = useCallback(
      (deltaX: number) => {
        const newWidth = effectiveLeftWidth + deltaX;
        setLeftSidebarWidth(Math.max(MIN_LEFT, Math.min(MAX_LEFT, newWidth)));
      },
      [effectiveLeftWidth, setLeftSidebarWidth]
    );

    // Handle right panel drag
    const handleRightDrag = useCallback(
      (deltaX: number) => {
        const newWidth = effectiveRightWidth - deltaX;
        setRightPanelWidth(Math.max(MIN_RIGHT, Math.min(MAX_RIGHT, newWidth)));
      },
      [effectiveRightWidth, setRightPanelWidth]
    );

    return (
      <div className="h-screen bg-slate-50 flex overflow-hidden">
        {/* Left Sidebar */}
        {showHistorySidebar && (
          <div
            className="relative bg-white border-r border-slate-200/80 shadow-sm z-20 flex flex-col"
            style={{
              width: `${effectiveLeftWidth}px`,
              minWidth: `${MIN_LEFT}px`,
              maxWidth: `${MAX_LEFT}px`,
            }}
          >
            {sidebar}
            {/* Drag Handle on right edge */}
            <DragHandle onDrag={handleLeftDrag} className="right-0" />
          </div>
        )}

        {/* Main Content */}
        <div className="flex-1 relative flex flex-col bg-gradient-to-br from-slate-50 via-white to-slate-50/50 overflow-hidden">
          {/* Floating Controls */}
          <div className="absolute top-4 left-4 right-4 z-30 flex justify-between pointer-events-none">
            {/* Left Toggle */}
            <div className="pointer-events-auto">
              <FloatingToggle
                icon={showHistorySidebar ? <LeftOutlined /> : <RightOutlined />}
                onClick={toggleHistorySidebar}
                label={showHistorySidebar ? "Hide" : "Chats"}
                
              />
            </div>

            {/* Right Toggle */}
            <div className="pointer-events-auto">
              <FloatingToggle
                icon={showPlanPanel ? <RightOutlined /> : <LeftOutlined />}
                onClick={togglePlanPanel}
                label={showPlanPanel ? "Close" : "Panel"}
                
              />
            </div>
          </div>

          {/* Chat Area */}
          <div className="flex-1 overflow-hidden pt-16">
            {chatArea}
          </div>
        </div>

        {/* Right Panel */}
        {showPlanPanel && (
          <div
            className="relative bg-white border-l border-slate-200/80 shadow-sm z-20 flex flex-col"
            style={{
              width: `${effectiveRightWidth}px`,
              minWidth: `${MIN_RIGHT}px`,
              maxWidth: `${MAX_RIGHT}px`,
            }}
          >
            {/* Drag Handle on left edge */}
            <DragHandle onDrag={handleRightDrag} className="left-0" />
            {panelContent}
          </div>
        )}
      </div>
    );
  }
);

ChatLayout.displayName = "ChatLayout";

export default ChatLayout;
