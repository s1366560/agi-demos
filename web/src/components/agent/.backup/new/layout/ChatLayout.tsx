/**
 * ChatLayout - Modern 3-Panel Layout
 * 
 * Features:
 * - Collapsible sidebars with smooth transitions
 * - Responsive design
 * - Clean visual hierarchy
 * - Smooth animations
 */

import React, { useState, useCallback, useRef, useEffect } from 'react';
import { Button, Tooltip } from 'antd';
import { 
  PanelLeft, 
  PanelRight
} from 'lucide-react';

interface ChatLayoutProps {
  sidebar: React.ReactNode;
  messageArea: React.ReactNode;
  inputBar: React.ReactNode;
  rightPanel: React.ReactNode;
  statusBar: React.ReactNode;
  sidebarCollapsed: boolean;
  panelCollapsed: boolean;
  onToggleSidebar: () => void;
  onTogglePanel: () => void;
}

// Resizer Component
const Resizer: React.FC<{
  direction: 'left' | 'right';
  onResize: (delta: number) => void;
  minWidth: number;
  maxWidth: number;
  currentWidth: number;
}> = ({ direction, onResize, minWidth, maxWidth, currentWidth }) => {
  const [isDragging, setIsDragging] = useState(false);
  const startXRef = useRef(0);
  const startWidthRef = useRef(currentWidth);

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    setIsDragging(true);
    startXRef.current = e.clientX;
    startWidthRef.current = currentWidth;
    document.body.style.cursor = 'ew-resize';
    document.body.style.userSelect = 'none';
  }, [currentWidth]);

  useEffect(() => {
    if (!isDragging) return;

    const handleMouseMove = (e: MouseEvent) => {
      const delta = direction === 'left' 
        ? e.clientX - startXRef.current 
        : startXRef.current - e.clientX;
      const newWidth = Math.max(minWidth, Math.min(maxWidth, startWidthRef.current + delta));
      onResize(newWidth);
    };

    const handleMouseUp = () => {
      setIsDragging(false);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };

    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);
    
    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isDragging, direction, minWidth, maxWidth, onResize]);

  return (
    <div
      onMouseDown={handleMouseDown}
      className={`
        absolute top-0 bottom-0 w-1 cursor-ew-resize z-50
        transition-colors duration-150 group
        ${direction === 'left' ? 'right-0' : 'left-0'}
        ${isDragging ? 'bg-primary' : 'bg-transparent hover:bg-slate-300 dark:hover:bg-slate-600'}
      `}
    >
      {/* Visual indicator */}
      <div className={`
        absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2
        w-0.5 h-8 rounded-full bg-slate-300 dark:bg-slate-600
        group-hover:bg-primary/50 transition-colors
        ${isDragging ? 'bg-primary' : ''}
      `} />
    </div>
  );
};

export const ChatLayout: React.FC<ChatLayoutProps> = ({
  sidebar,
  messageArea,
  inputBar,
  rightPanel,
  statusBar,
  sidebarCollapsed,
  panelCollapsed,
  onToggleSidebar,
  onTogglePanel,
}) => {
  const [sidebarWidth, setSidebarWidth] = useState(280);
  const [panelWidth, setPanelWidth] = useState(360);

  // Sidebar width constraints
  const SIDEBAR_MIN = 200;
  const SIDEBAR_MAX = 400;
  const SIDEBAR_COLLAPSED = 60;

  // Panel width constraints  
  const PANEL_MIN = 300;
  const PANEL_MAX = 500;
  const PANEL_COLLAPSED = 0;

  const effectiveSidebarWidth = sidebarCollapsed ? SIDEBAR_COLLAPSED : sidebarWidth;
  const effectivePanelWidth = panelCollapsed ? PANEL_COLLAPSED : panelWidth;

  return (
    <div className="h-screen w-full flex overflow-hidden bg-slate-50 dark:bg-slate-950">
      {/* Left Sidebar */}
      <aside
        className={`
          relative flex-shrink-0 h-full bg-white dark:bg-slate-900
          border-r border-slate-200 dark:border-slate-800
          transition-all duration-300 ease-out
          ${sidebarCollapsed ? 'overflow-hidden' : 'overflow-y-auto'}
        `}
        style={{ width: effectiveSidebarWidth }}
      >
        {sidebar}
        {!sidebarCollapsed && (
          <Resizer
            direction="left"
            onResize={setSidebarWidth}
            minWidth={SIDEBAR_MIN}
            maxWidth={SIDEBAR_MAX}
            currentWidth={sidebarWidth}
          />
        )}
      </aside>

      {/* Main Content Area */}
      <main className="flex-1 flex flex-col min-w-0 h-full relative">
        {/* Floating Toggle Buttons */}
        <div className="absolute top-4 left-4 right-4 z-30 flex justify-between pointer-events-none">
          {/* Sidebar Toggle */}
          <Tooltip title={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}>
            <Button
              type="text"
              icon={sidebarCollapsed ? <PanelLeft size={18} /> : <PanelLeft size={18} className="rotate-180" />}
              onClick={onToggleSidebar}
              className="pointer-events-auto bg-white/90 dark:bg-slate-800/90 backdrop-blur-sm shadow-sm border border-slate-200 dark:border-slate-700 hover:border-primary/50 transition-all rounded-lg h-9 w-9 flex items-center justify-center"
            />
          </Tooltip>

          {/* Panel Toggle */}
          <Tooltip title={panelCollapsed ? "Show panel" : "Hide panel"}>
            <Button
              type="text"
              icon={panelCollapsed ? <PanelRight size={18} /> : <PanelRight size={18} className="rotate-180" />}
              onClick={onTogglePanel}
              className="pointer-events-auto bg-white/90 dark:bg-slate-800/90 backdrop-blur-sm shadow-sm border border-slate-200 dark:border-slate-700 hover:border-primary/50 transition-all rounded-lg h-9 w-9 flex items-center justify-center"
            />
          </Tooltip>
        </div>

        {/* Message Area */}
        <div className="flex-1 overflow-hidden relative">
          {messageArea}
        </div>

        {/* Input Bar */}
        <div className="flex-shrink-0 border-t border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900">
          {inputBar}
        </div>

        {/* Status Bar */}
        <div className="flex-shrink-0">
          {statusBar}
        </div>
      </main>

      {/* Right Panel */}
      <aside
        className={`
          relative flex-shrink-0 h-full bg-white dark:bg-slate-900
          border-l border-slate-200 dark:border-slate-800
          transition-all duration-300 ease-out overflow-hidden
          ${panelCollapsed ? 'w-0 opacity-0' : 'opacity-100'}
        `}
        style={{ width: effectivePanelWidth }}
      >
        {!panelCollapsed && (
          <>
            {rightPanel}
            <Resizer
              direction="right"
              onResize={setPanelWidth}
              minWidth={PANEL_MIN}
              maxWidth={PANEL_MAX}
              currentWidth={panelWidth}
            />
          </>
        )}
      </aside>
    </div>
  );
};
