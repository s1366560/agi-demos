/**
 * SandboxSection - Sandbox integration for the new Agent Chat UI
 *
 * Provides Terminal and Remote Desktop functionality in a modern tabbed interface.
 */

import React, { useState, useEffect, useRef } from 'react';

import {
  Terminal,
  Monitor,
  Play,
  Square,
  RefreshCw,
  Maximize2,
  Minimize2,
} from 'lucide-react';

import {
  LazyTabs,
  LazyButton,
  LazyBadge,
  LazyEmpty,
  Empty,
  LazyTooltip,
} from '@/components/ui/lazyAntd';

import { useSandboxStore } from '../../stores/sandbox';

import { RemoteDesktopViewer } from './sandbox/RemoteDesktopViewer';
import { SandboxTerminal } from './sandbox/SandboxTerminal';

type SandboxTab = 'terminal' | 'desktop';

interface SandboxSectionProps {
  sandboxId: string | null;
  className?: string;
}

// Terminal Tab Content
const TerminalTab: React.FC<{
  sandboxId: string;
  projectId?: string;
  terminalStatus: any;
  onStartTerminal: () => Promise<void>;
  isTerminalLoading: boolean;
}> = ({ sandboxId, projectId, terminalStatus, onStartTerminal, isTerminalLoading }) => {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  // Use ref to track auto-start attempt (avoids setState in effect)
  const autoStartAttemptedRef = useRef(false);

  // Auto-start terminal if not running (only once per component mount)
  useEffect(() => {
    // Only auto-start once, and only if sandbox is available
    if (
      !autoStartAttemptedRef.current &&
      !terminalStatus?.running &&
      !isTerminalLoading &&
      !isConnected &&
      sandboxId
    ) {
      autoStartAttemptedRef.current = true;
      onStartTerminal();
    }
  }, [terminalStatus?.running, isTerminalLoading, isConnected, sandboxId, onStartTerminal]);

  // If terminal is not running, show start button
  if (!terminalStatus?.running && !isConnected) {
    return (
      <div className="h-full flex items-center justify-center bg-slate-900">
        <LazyEmpty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={
            <div className="text-center">
              <p className="text-slate-400 mb-4">Terminal is not running</p>
              <LazyButton
                type="primary"
                icon={<Play size={16} />}
                onClick={onStartTerminal}
                loading={isTerminalLoading}
              >
                Start Terminal
              </LazyButton>
            </div>
          }
        />
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col">
      {/* Terminal Status Bar */}
      <div className="flex items-center justify-between px-3 py-2 bg-slate-900 border-b border-slate-700">
        <div className="flex items-center gap-2">
          <div
            className={`w-2 h-2 rounded-full ${isConnected ? 'bg-green-500' : 'bg-amber-500 animate-pulse'}`}
          />
          <span className="text-xs text-slate-400">
            {isConnected ? 'Connected' : 'Connecting...'}
          </span>
          {sessionId && <span className="text-xs text-slate-600">({sessionId.slice(0, 8)})</span>}
        </div>
        <div className="flex items-center gap-1">
          <LazyTooltip title="Reconnect">
            <LazyButton
              type="text"
              size="small"
              icon={<RefreshCw size={14} />}
              className="text-slate-400 hover:text-white"
              onClick={() => {
                setSessionId(null);
                setIsConnected(false);
                onStartTerminal();
              }}
            />
          </LazyTooltip>
        </div>
      </div>

      {/* Terminal */}
      <div className="flex-1 min-h-0">
        <SandboxTerminal
          sandboxId={sandboxId}
          projectId={projectId}
          sessionId={sessionId || undefined}
          onConnect={(id) => {
            setSessionId(id);
            setIsConnected(true);
          }}
          onDisconnect={() => setIsConnected(false)}
          height="100%"
          showToolbar={false}
        />
      </div>
    </div>
  );
};

// Desktop Tab Content
const DesktopTab: React.FC<{
  sandboxId: string;
  projectId?: string;
  desktopStatus: any;
  onStartDesktop: () => Promise<void>;
  onStopDesktop: () => Promise<void>;
  isDesktopLoading: boolean;
}> = ({ sandboxId, projectId, desktopStatus, onStartDesktop, onStopDesktop, isDesktopLoading }) => {
  const [isFullscreen, setIsFullscreen] = useState(false);
  // Use ref to track auto-start attempt (avoids setState in effect)
  const autoStartAttemptedRef = useRef(false);

  // Auto-start desktop if not running (only once per component mount)
  useEffect(() => {
    // Only auto-start once, and only if sandbox is available
    if (
      !autoStartAttemptedRef.current &&
      !desktopStatus?.running &&
      !isDesktopLoading &&
      sandboxId
    ) {
      autoStartAttemptedRef.current = true;
      onStartDesktop();
    }
  }, [desktopStatus?.running, isDesktopLoading, sandboxId, onStartDesktop]);

  if (!desktopStatus?.running) {
    return (
      <div className="h-full flex items-center justify-center bg-slate-900">
        <LazyEmpty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={
            <div className="text-center">
              <p className="text-slate-400 mb-4">Desktop is not running</p>
              <LazyButton
                type="primary"
                icon={<Play size={16} />}
                onClick={onStartDesktop}
                loading={isDesktopLoading}
              >
                Start Desktop
              </LazyButton>
            </div>
          }
        />
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col bg-slate-900">
      {/* Desktop Toolbar */}
      <div className="flex items-center justify-between px-3 py-2 bg-slate-800 border-b border-slate-700">
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-green-500" />
          <span className="text-xs text-slate-300">Desktop Running</span>
          <span className="text-xs text-slate-500">({sandboxId.slice(0, 8)})</span>
        </div>
        <div className="flex items-center gap-1">
          <LazyTooltip title={isFullscreen ? 'Exit Fullscreen' : 'Fullscreen'}>
            <LazyButton
              type="text"
              size="small"
              icon={isFullscreen ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
              onClick={() => setIsFullscreen(!isFullscreen)}
              className="text-slate-400 hover:text-white"
            />
          </LazyTooltip>
          <LazyTooltip title="Stop Desktop">
            <LazyButton
              type="text"
              size="small"
              icon={<Square size={14} />}
              onClick={onStopDesktop}
              loading={isDesktopLoading}
              className="text-slate-400 hover:text-red-400"
            />
          </LazyTooltip>
        </div>
      </div>

      {/* Desktop Viewer */}
      <div className={`flex-1 min-h-0 ${isFullscreen ? 'fixed inset-0 z-50' : ''}`}>
        <RemoteDesktopViewer
          sandboxId={sandboxId}
          projectId={projectId}
          desktopStatus={desktopStatus}
          height="100%"
          showToolbar={false}
        />
      </div>
    </div>
  );
};

export const SandboxSection: React.FC<SandboxSectionProps> = ({
  sandboxId,
  className,
}) => {
  const [activeTab, setActiveTab] = useState<SandboxTab>('terminal');
  const {
    activeProjectId,
    desktopStatus,
    terminalStatus,
    startDesktop,
    stopDesktop,
    startTerminal,
    isDesktopLoading,
    isTerminalLoading,
  } = useSandboxStore();

  const tabItems = [
    {
      key: 'terminal' as SandboxTab,
      label: (
        <div className="flex items-center gap-2">
          <Terminal size={16} />
          <span>Terminal</span>
          {terminalStatus?.running && <LazyBadge status="success" className="ml-1" />}
        </div>
      ),
      children: sandboxId ? (
        <TerminalTab
          sandboxId={sandboxId}
          projectId={activeProjectId || undefined}
          terminalStatus={terminalStatus}
          onStartTerminal={startTerminal}
          isTerminalLoading={isTerminalLoading}
        />
      ) : (
        <div className="h-full flex items-center justify-center">
          <LazyEmpty description="No sandbox connected" />
        </div>
      ),
    },
    {
      key: 'desktop' as SandboxTab,
      label: (
        <div className="flex items-center gap-2">
          <Monitor size={16} />
          <span>Desktop</span>
          {desktopStatus?.running && <LazyBadge status="success" className="ml-1" />}
        </div>
      ),
      children: sandboxId ? (
        <DesktopTab
          sandboxId={sandboxId}
          projectId={activeProjectId || undefined}
          desktopStatus={desktopStatus}
          onStartDesktop={startDesktop}
          onStopDesktop={stopDesktop}
          isDesktopLoading={isDesktopLoading}
        />
      ) : (
        <div className="h-full flex items-center justify-center">
          <LazyEmpty description="No sandbox connected" />
        </div>
      ),
    },
  ];

  return (
    <div className={`h-full flex flex-col bg-white dark:bg-slate-900 ${className}`}>
      {/* Tabs */}
      <LazyTabs
        activeKey={activeTab}
        onChange={(key: string) => setActiveTab(key as SandboxTab)}
        items={tabItems}
        className="flex-1 sandbox-tabs"
        tabBarStyle={{
          margin: 0,
          padding: '0 16px',
        }}
      />

      {/* Custom styles for tabs */}
      <style>{`
        .sandbox-tabs {
          display: flex;
          flex-direction: column;
          height: 100%;
        }
        .sandbox-tabs > .ant-tabs-nav {
          border-bottom: 1px solid #e2e8f0;
        }
        .dark .sandbox-tabs > .ant-tabs-nav {
          border-bottom: 1px solid #334155;
        }
        .sandbox-tabs .ant-tabs-content {
          flex: 1;
          height: 0;
        }
        .sandbox-tabs .ant-tabs-content-holder {
          flex: 1;
          display: flex;
          flex-direction: column;
        }
        .sandbox-tabs .ant-tabs-tabpane {
          height: 100%;
        }
      `}</style>
    </div>
  );
};

export default SandboxSection;
