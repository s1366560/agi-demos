/**
 * SandboxSection - Sandbox integration for the new Agent Chat UI
 *
 * Provides Terminal and Remote Desktop functionality in a modern tabbed interface.
 */

import React, { useState, useEffect, useRef } from 'react';

import { useTranslation } from 'react-i18next';

import { Terminal, Monitor, Play, Square, RefreshCw, Maximize2, Minimize2 } from 'lucide-react';
import { useShallow } from 'zustand/react/shallow';

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

import type { DesktopStatus, TerminalStatus } from '../../types/agent';

type SandboxTab = 'terminal' | 'desktop';

interface SandboxSectionProps {
  sandboxId: string | null;
  className?: string | undefined;
}

// Terminal Tab Content
const TerminalTab: React.FC<{
  sandboxId: string;
  projectId?: string | undefined;
  terminalStatus: TerminalStatus | null;
  onStartTerminal: () => Promise<void>;
  isTerminalLoading: boolean;
}> = ({ sandboxId, projectId, terminalStatus, onStartTerminal, isTerminalLoading }) => {
  const { t } = useTranslation();
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
      void onStartTerminal();
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
              <p className="text-slate-400 mb-4">
                {t('components.sandboxSection.terminalNotRunning')}
              </p>
              <LazyButton
                type="primary"
                icon={<Play size={16} />}
                onClick={() => {
                  void onStartTerminal();
                }}
                loading={isTerminalLoading}
              >
                {t('components.sandboxSection.startTerminal')}
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
            className={`w-2 h-2 rounded-full ${isConnected ? 'bg-green-500' : 'bg-amber-500 animate-pulse motion-reduce:animate-none'}`}
          />
          <span className="text-xs text-slate-400">
            {isConnected
              ? t('components.sandboxSection.connected')
              : t('components.sandboxSection.connecting')}
          </span>
          {sessionId && <span className="text-xs text-slate-600">({sessionId.slice(0, 8)})</span>}
        </div>
        <div className="flex items-center gap-1">
          <LazyTooltip title={t('components.sandboxSection.reconnect')}>
            <LazyButton
              type="text"
              size="small"
              icon={<RefreshCw size={14} />}
              aria-label={t('components.sandboxSection.reconnect')}
              className="text-slate-400 hover:text-white"
              onClick={() => {
                setSessionId(null);
                setIsConnected(false);
                void onStartTerminal();
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
          onDisconnect={() => {
            setIsConnected(false);
          }}
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
  projectId?: string | undefined;
  desktopStatus: DesktopStatus | null;
  onStartDesktop: () => Promise<void>;
  onStopDesktop: () => Promise<void>;
  isDesktopLoading: boolean;
}> = ({ sandboxId, projectId, desktopStatus, onStartDesktop, onStopDesktop, isDesktopLoading }) => {
  const { t } = useTranslation();
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
      void onStartDesktop();
    }
  }, [desktopStatus?.running, isDesktopLoading, sandboxId, onStartDesktop]);

  // Escape exits fullscreen (mouse and keyboard users alike)
  useEffect(() => {
    if (!isFullscreen) return;
    const handleEscape = (event: globalThis.KeyboardEvent) => {
      if (event.key === 'Escape') {
        setIsFullscreen(false);
      }
    };
    document.addEventListener('keydown', handleEscape);
    return () => {
      document.removeEventListener('keydown', handleEscape);
    };
  }, [isFullscreen]);

  if (!desktopStatus?.running) {
    return (
      <div className="h-full flex items-center justify-center bg-slate-900">
        <LazyEmpty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={
            <div className="text-center">
              <p className="text-slate-400 mb-4">
                {t('components.sandboxSection.desktopNotRunning')}
              </p>
              <LazyButton
                type="primary"
                icon={<Play size={16} />}
                onClick={() => {
                  void onStartDesktop();
                }}
                loading={isDesktopLoading}
              >
                {t('components.sandboxSection.startDesktop')}
              </LazyButton>
            </div>
          }
        />
      </div>
    );
  }

  return (
    <div
      className={`h-full flex flex-col bg-slate-900 ${isFullscreen ? 'fixed inset-0 z-50' : ''}`}
    >
      {/* Desktop Toolbar */}
      <div className="flex items-center justify-between px-3 py-2 bg-slate-800 border-b border-slate-700">
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-green-500" />
          <span className="text-xs text-slate-300">
            {t('components.sandboxSection.desktopRunning')}
          </span>
          <span className="text-xs text-slate-500">({sandboxId.slice(0, 8)})</span>
        </div>
        <div className="flex items-center gap-1">
          <LazyTooltip
            title={
              isFullscreen
                ? t('components.sandboxSection.exitFullscreen')
                : t('components.sandboxSection.fullscreen')
            }
          >
            <LazyButton
              type="text"
              size="small"
              icon={isFullscreen ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
              aria-label={
                isFullscreen
                  ? t('components.sandboxSection.exitFullscreen')
                  : t('components.sandboxSection.fullscreen')
              }
              onClick={() => {
                setIsFullscreen(!isFullscreen);
              }}
              className="text-slate-400 hover:text-white"
            />
          </LazyTooltip>
          <LazyTooltip title={t('components.sandboxSection.stopDesktop')}>
            <LazyButton
              type="text"
              size="small"
              icon={<Square size={14} />}
              aria-label={t('components.sandboxSection.stopDesktop')}
              onClick={() => {
                void onStopDesktop();
              }}
              loading={isDesktopLoading}
              className="text-slate-400 hover:text-red-400"
            />
          </LazyTooltip>
        </div>
      </div>

      {/* Desktop Viewer */}
      <div className="flex-1 min-h-0">
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

export const SandboxSection: React.FC<SandboxSectionProps> = ({ sandboxId, className = '' }) => {
  const { t } = useTranslation();
  const [activeTab, setActiveTab] = useState<SandboxTab>('terminal');
  const ensureAttemptedProjectRef = useRef<string | null>(null);
  const {
    activeProjectId,
    connectionStatus,
    desktopStatus,
    terminalStatus,
    ensureSandbox,
    startDesktop,
    stopDesktop,
    startTerminal,
    isDesktopLoading,
    isTerminalLoading,
  } = useSandboxStore(
    useShallow((state) => ({
      activeProjectId: state.activeProjectId,
      connectionStatus: state.connectionStatus,
      desktopStatus: state.desktopStatus,
      terminalStatus: state.terminalStatus,
      ensureSandbox: state.ensureSandbox,
      startDesktop: state.startDesktop,
      stopDesktop: state.stopDesktop,
      startTerminal: state.startTerminal,
      isDesktopLoading: state.isDesktopLoading,
      isTerminalLoading: state.isTerminalLoading,
    }))
  );

  useEffect(() => {
    if (!activeProjectId || sandboxId || connectionStatus === 'connecting') {
      return;
    }
    if (ensureAttemptedProjectRef.current === activeProjectId) {
      return;
    }

    ensureAttemptedProjectRef.current = activeProjectId;
    void ensureSandbox(activeProjectId);
  }, [activeProjectId, connectionStatus, ensureSandbox, sandboxId]);

  const sandboxEmptyDescription =
    connectionStatus === 'connecting'
      ? t('components.sandboxSection.connecting')
      : t('components.sandboxSection.noSandboxConnected');

  const tabItems = [
    {
      key: 'terminal' as SandboxTab,
      label: (
        <div className="flex items-center gap-2">
          <Terminal size={16} />
          <span>{t('components.sandboxSection.terminal')}</span>
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
          <LazyEmpty description={sandboxEmptyDescription} />
        </div>
      ),
    },
    {
      key: 'desktop' as SandboxTab,
      label: (
        <div className="flex items-center gap-2">
          <Monitor size={16} />
          <span>{t('components.sandboxSection.desktop')}</span>
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
          <LazyEmpty description={sandboxEmptyDescription} />
        </div>
      ),
    },
  ];

  return (
    <div className={`h-full flex flex-col bg-white dark:bg-slate-900 ${className}`}>
      {/* Tabs */}
      <LazyTabs
        activeKey={activeTab}
        onChange={(key: string) => {
          setActiveTab(key as SandboxTab);
        }}
        items={tabItems}
        className="flex-1 sandbox-tabs"
        tabBarStyle={{
          margin: 0,
          padding: '0 16px',
        }}
      />
    </div>
  );
};

export default SandboxSection;
