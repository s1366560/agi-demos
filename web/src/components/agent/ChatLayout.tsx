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

import {
  PanelLeft,
  PanelRight
} from 'lucide-react';

import { LazyButton, LazyTooltip } from '@/components/ui/lazyAntd';

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
        absolute top-0 bottom-0 w-1.5 cursor-ew-resize z-50
        transition-all duration-150 group
        ${direction === 'left' ? 'right-0' : 'left-0'}
        bg-transparent
        hover:bg-slate-200/50 dark:hover:bg-slate-700/50
        ${isDragging ? 'bg-slate-300/70 dark:bg-slate-600/70' : ''}
      `}
    >
      {/* Visual indicator - subtle dots */}
      <div className={`
        absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2
        w-0.5 h-6 rounded-full
        bg-slate-400/50 dark:bg-slate-500/50
        opacity-0 group-hover:opacity-100
        ${isDragging ? 'opacity-100 bg-slate-500 dark:bg-slate-400' : ''}
        transition-all duration-150
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
    <div className="h-full w-full flex overflow-hidden bg-slate-50 dark:bg-slate-950">
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
        {/* Floating Toggle Buttons - positioned at top corners to avoid blocking content */}
        <div className="absolute top-3 left-3 z-30 pointer-events-none">
          {/* Sidebar Toggle */}
          <LazyTooltip title={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}>
            <LazyButton
              type="text"
              icon={sidebarCollapsed ? <PanelLeft size={16} /> : <PanelLeft size={16} className="rotate-180" />}
              onClick={onToggleSidebar}
              className="pointer-events-auto bg-slate-100/80 dark:bg-slate-800/80 hover:bg-slate-200 dark:hover:bg-slate-700 transition-all rounded-md h-7 w-7 flex items-center justify-center text-slate-500"
            />
          </LazyTooltip>
        </div>
        
        <div className="absolute top-3 right-3 z-30 pointer-events-none">
          {/* Panel Toggle */}
          <LazyTooltip title={panelCollapsed ? "Show panel" : "Hide panel"}>
            <LazyButton
              type="text"
              icon={panelCollapsed ? <PanelRight size={16} /> : <PanelRight size={16} className="rotate-180" />}
              onClick={onTogglePanel}
              className="pointer-events-auto bg-slate-100/80 dark:bg-slate-800/80 hover:bg-slate-200 dark:hover:bg-slate-700 transition-all rounded-md h-7 w-7 flex items-center justify-center text-slate-500"
            />
          </LazyTooltip>
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
