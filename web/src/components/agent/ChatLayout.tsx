import React, { memo, useMemo, useCallback, useState } from "react";
import { Button } from "antd";
import {
  MenuFoldOutlined,
  MenuUnfoldOutlined,
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
const MIN_LEFT = 180;
const MAX_LEFT = 500;

const MIN_RIGHT = 280;
const MAX_RIGHT = 700;

/**
 * Custom drag handle component
 */
const DragHandle: React.FC<{
  onDrag: (deltaX: number) => void;
  className?: string;
}> = ({ onDrag, className = "" }) => {
  const [isDragging, setIsDragging] = useState(false);

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    setIsDragging(true);
    const startX = e.clientX;

    const handleMouseMove = (moveEvent: MouseEvent) => {
      const deltaX = moveEvent.clientX - startX;
      onDrag(deltaX);
    };

    const handleMouseUp = () => {
      setIsDragging(false);
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
    };

    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);
  }, [onDrag]);

  return (
    <div
      onMouseDown={handleMouseDown}
      className={`
        absolute top-0 bottom-0 w-1.5 bg-slate-200 hover:bg-primary
        cursor-ew-resize transition-colors z-50
        ${isDragging ? 'bg-primary' : ''}
        ${className}
      `}
      style={{ width: isDragging ? '6px' : '6px' }}
    />
  );
};

/**
 * ChatLayout Component - Three-panel layout with custom drag resizing
 */
export const ChatLayout: React.FC<ChatLayoutProps> = memo(({
  sidebar,
  chatArea,
  rightPanel,
  planPanel,
}) => {
  const {
    showPlanPanel,
    showHistorySidebar,
    toggleHistorySidebar,
    leftSidebarWidth,
    rightPanelWidth,
    setLeftSidebarWidth,
    setRightPanelWidth,
  } = useAgentV3Store();

  const panelContent = useMemo(() => rightPanel || planPanel, [rightPanel, planPanel]);

  const sidebarIcon = useMemo(() => {
    return showHistorySidebar ? <MenuFoldOutlined /> : <MenuUnfoldOutlined />;
  }, [showHistorySidebar]);

  const handleToggleSidebar = useCallback(() => {
    toggleHistorySidebar();
  }, [toggleHistorySidebar]);

  // Handle left sidebar drag
  const handleLeftDrag = useCallback((deltaX: number) => {
    const newWidth = leftSidebarWidth + deltaX;
    setLeftSidebarWidth(Math.max(MIN_LEFT, Math.min(MAX_LEFT, newWidth)));
  }, [leftSidebarWidth, setLeftSidebarWidth]);

  // Handle right panel drag
  const handleRightDrag = useCallback((deltaX: number) => {
    const newWidth = rightPanelWidth - deltaX; // Negative because we're dragging from the left edge
    setRightPanelWidth(Math.max(MIN_RIGHT, Math.min(MAX_RIGHT, newWidth)));
  }, [rightPanelWidth, setRightPanelWidth]);

  return (
    <div className="h-full bg-slate-50 flex overflow-hidden">
      {/* Left Sidebar */}
      {showHistorySidebar && (
        <div
          className="relative bg-white border-r border-slate-200 shadow-sm z-20 overflow-hidden"
          style={{ width: `${leftSidebarWidth}px`, minWidth: `${MIN_LEFT}px`, maxWidth: `${MAX_LEFT}px` }}
        >
          <div className="flex flex-col h-full">{sidebar}</div>
          {/* Drag Handle on right edge */}
          <DragHandle onDrag={handleLeftDrag} className="right-0" />
        </div>
      )}

      {/* Main Content */}
      <div className="flex-1 relative bg-gradient-to-br from-slate-50 to-white overflow-hidden">
        {/* Floating toggle button */}
        <div className="absolute top-4 left-4 z-10 pointer-events-none">
          <Button
            icon={sidebarIcon}
            onClick={handleToggleSidebar}
            type="text"
            size="large"
            className="pointer-events-auto bg-white/90 backdrop-blur-md shadow-md border border-slate-200/60 hover:shadow-lg hover:border-primary/30 transition-all duration-200 rounded-xl"
            aria-label={showHistorySidebar ? "Hide conversation history" : "Show conversation history"}
          />
        </div>
        {chatArea}
      </div>

      {/* Right Panel */}
      {showPlanPanel && (
        <div
          className="relative bg-white border-l border-slate-200 shadow-sm z-20 overflow-auto"
          style={{ width: `${rightPanelWidth}px`, minWidth: `${MIN_RIGHT}px`, maxWidth: `${MAX_RIGHT}px` }}
        >
          {/* Drag Handle on left edge */}
          <DragHandle onDrag={handleRightDrag} className="left-0" />
          {panelContent}
        </div>
      )}
    </div>
  );
});

ChatLayout.displayName = 'ChatLayout';
