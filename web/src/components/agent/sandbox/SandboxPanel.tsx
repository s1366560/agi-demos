/**
 * SandboxPanel - Compound Component for Sandbox Interface
 *
 * ## Usage
 *
 * ### Convenience Usage (Default tabs)
 * ```tsx
 * <SandboxPanel sandboxId="abc" />
 * ```
 *
 * ### Compound Components (Custom tabs)
 * ```tsx
 * <SandboxPanel sandboxId="abc">
 *   <SandboxPanel.Terminal />
 *   <SandboxPanel.Desktop />
 *   <SandboxPanel.Control />
 *   <SandboxPanel.Output />
 * </SandboxPanel>
 * ```
 *
 * ### Namespace Usage
 * ```tsx
 * <SandboxPanel.Root sandboxId="abc">
 *   <SandboxPanel.Terminal />
 *   <SandboxPanel.Desktop />
 * </SandboxPanel.Root>
 * ```
 */

import { useState, useCallback, Children } from 'react';

import { CodeOutlined, FileTextOutlined, DesktopOutlined, CloseOutlined } from '@ant-design/icons';
import { Tabs, Empty, Button, Tooltip, Badge, Space } from 'antd';

import { useSandboxStore } from '../../../stores/sandbox';

import { RemoteDesktopViewer } from './RemoteDesktopViewer';
import { SandboxControlPanel } from './SandboxControlPanel';
import { SandboxOutputViewer } from './SandboxOutputViewer';
import { SandboxPanelProvider } from './SandboxPanelContext';
import { SandboxTerminal } from './SandboxTerminal';

import type {
  SandboxTabKey,
  SandboxPanelRootProps,
  SandboxTerminalProps,
  SandboxDesktopProps,
  SandboxControlProps,
  SandboxOutputProps,
  SandboxHeaderProps,
} from './types';

// ========================================
// Marker Symbols for Sub-Components
// ========================================

const TERMINAL_SYMBOL = Symbol('SandboxPanelTerminal');
const DESKTOP_SYMBOL = Symbol('SandboxPanelDesktop');
const CONTROL_SYMBOL = Symbol('SandboxPanelControl');
const OUTPUT_SYMBOL = Symbol('SandboxPanelOutput');
const HEADER_SYMBOL = Symbol('SandboxPanelHeader');

// ========================================
// Sub-Components (Marker Components)
// ========================================

SandboxPanel.Terminal = function SandboxPanelTerminalMarker(_props: SandboxTerminalProps) {
  return null;
};
(SandboxPanel.Terminal as any)[TERMINAL_SYMBOL] = true;

SandboxPanel.Desktop = function SandboxPanelDesktopMarker(_props: SandboxDesktopProps) {
  return null;
};
(SandboxPanel.Desktop as any)[DESKTOP_SYMBOL] = true;

SandboxPanel.Control = function SandboxPanelControlMarker(_props: SandboxControlProps) {
  return null;
};
(SandboxPanel.Control as any)[CONTROL_SYMBOL] = true;

SandboxPanel.Output = function SandboxPanelOutputMarker(_props: SandboxOutputProps) {
  return null;
};
(SandboxPanel.Output as any)[OUTPUT_SYMBOL] = true;

SandboxPanel.Header = function SandboxPanelHeaderMarker(_props: SandboxHeaderProps) {
  return null;
};
(SandboxPanel.Header as any)[HEADER_SYMBOL] = true;

// Set display names for testing
(SandboxPanel.Terminal as any).displayName = 'SandboxPanelTerminal';
(SandboxPanel.Desktop as any).displayName = 'SandboxPanelDesktop';
(SandboxPanel.Control as any).displayName = 'SandboxPanelControl';
(SandboxPanel.Output as any).displayName = 'SandboxPanelOutput';
(SandboxPanel.Header as any).displayName = 'SandboxPanelHeader';

// ========================================
// Internal Components
// ========================================

interface HeaderRenderProps {
  currentTool: { name: string; input: Record<string, unknown> } | null;
  sandboxId: string | null;
  onClose?: () => void;
}

function SandboxHeaderRender({ currentTool, sandboxId, onClose }: HeaderRenderProps) {
  return (
    <div className="flex items-center justify-between px-4 py-2 border-b border-slate-200 bg-slate-50">
      <div className="flex items-center gap-2">
        <CodeOutlined className="text-slate-500" />
        <span className="font-medium text-slate-700">Sandbox</span>
        {sandboxId && <span className="text-xs text-slate-400">({sandboxId.slice(0, 12)})</span>}
      </div>
      <div className="flex items-center gap-1">
        {currentTool && (
          <Tooltip title={`Running: ${currentTool.name}`}>
            <Badge status="processing" text={currentTool.name} />
          </Tooltip>
        )}
        {onClose && (
          <Button
            type="text"
            size="small"
            icon={<CloseOutlined />}
            onClick={onClose}
            className="text-slate-400 hover:text-slate-600"
          />
        )}
      </div>
    </div>
  );
}

interface TabContentProps {
  sandboxId?: string | null;
  desktopStatus?: any;
  terminalStatus?: any;
  toolExecutions?: any[];
  onFileClick?: (filePath: string) => void;
}

function TerminalTabContent({ sandboxId }: TabContentProps) {
  const [terminalSessionId, setTerminalSessionId] = useState<string | null>(null);
  const [, setIsTerminalConnected] = useState(false);

  const handleTerminalConnect = useCallback((sessionId: string) => {
    setTerminalSessionId(sessionId);
    setIsTerminalConnected(true);
  }, []);

  const handleTerminalDisconnect = useCallback(() => {
    setIsTerminalConnected(false);
  }, []);

  return sandboxId ? (
    <div className="h-full">
      <SandboxTerminal
        sandboxId={sandboxId}
        sessionId={terminalSessionId || undefined}
        onConnect={handleTerminalConnect}
        onDisconnect={handleTerminalDisconnect}
        height="100%"
        showToolbar={true}
      />
    </div>
  ) : (
    <EmptyState />
  );
}

function DesktopTabContent({ sandboxId, desktopStatus }: TabContentProps) {
  const activeProjectId = useSandboxStore((state) => state.activeProjectId);
  return sandboxId ? (
    <div className="h-full">
      <RemoteDesktopViewer
        sandboxId={sandboxId}
        projectId={activeProjectId || undefined}
        desktopStatus={desktopStatus}
        height="100%"
        showToolbar={true}
      />
    </div>
  ) : (
    <EmptyState />
  );
}

function ControlTabContent({
  sandboxId,
  desktopStatus,
  terminalStatus,
  onDesktopStart,
  onDesktopStop,
  onTerminalStart,
  onTerminalStop,
  isDesktopLoading,
  isTerminalLoading,
}: TabContentProps & {
  isDesktopLoading?: boolean;
  isTerminalLoading?: boolean;
  onDesktopStart?: () => void;
  onDesktopStop?: () => void;
  onTerminalStart?: () => void;
  onTerminalStop?: () => void;
}) {
  return sandboxId ? (
    <div className="h-full overflow-y-auto p-4">
      <SandboxControlPanel
        sandboxId={sandboxId}
        desktopStatus={desktopStatus}
        terminalStatus={terminalStatus}
        onDesktopStart={onDesktopStart}
        onDesktopStop={onDesktopStop}
        onTerminalStart={onTerminalStart}
        onTerminalStop={onTerminalStop}
        isDesktopLoading={isDesktopLoading}
        isTerminalLoading={isTerminalLoading}
      />
    </div>
  ) : (
    <EmptyState />
  );
}

function OutputTabContent({ toolExecutions = [], onFileClick }: TabContentProps) {
  return (
    <SandboxOutputViewer executions={toolExecutions} onFileClick={onFileClick} maxHeight="100%" />
  );
}

function EmptyState() {
  return (
    <div className="h-full flex items-center justify-center">
      <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No sandbox connected" />
    </div>
  );
}

// ========================================
// Main Component
// ========================================

export function SandboxPanel(props: SandboxPanelRootProps) {
  const {
    sandboxId,
    defaultTab = 'terminal',
    toolExecutions = [],
    currentTool = null,
    onClose,
    onFileClick,
    desktopStatus = null,
    terminalStatus = null,
    onDesktopStart,
    onDesktopStop,
    onTerminalStart,
    onTerminalStop,
    isDesktopLoading = false,
    isTerminalLoading = false,
    children,
  } = props;

  // Parse children to detect sub-components
  const childrenArray = Children.toArray(children);
  const terminalChild = childrenArray.find((child: any) => child?.type?.[TERMINAL_SYMBOL]) as any;
  const desktopChild = childrenArray.find((child: any) => child?.type?.[DESKTOP_SYMBOL]) as any;
  const controlChild = childrenArray.find((child: any) => child?.type?.[CONTROL_SYMBOL]) as any;
  const outputChild = childrenArray.find((child: any) => child?.type?.[OUTPUT_SYMBOL]) as any;

  // Determine if using compound mode (has explicit sub-components)
  const hasSubComponents = terminalChild || desktopChild || controlChild || outputChild;

  // In legacy mode, include all tabs by default
  // In compound mode, only include explicitly specified tabs
  // Header is always included by default (can be explicitly excluded with a prop in the future)
  const includeTerminal = hasSubComponents ? !!terminalChild : true;
  const includeDesktop = hasSubComponents ? !!desktopChild : true;
  const includeControl = hasSubComponents ? !!controlChild : true;
  const includeOutput = hasSubComponents ? !!outputChild : true;
  // Header is always included by default
  const includeHeader = true;

  // Determine the actual default tab
  // In compound mode, use defaultTab if that tab is included, otherwise use first available
  const getAvailableTabs = (): SandboxTabKey[] => {
    const tabs: SandboxTabKey[] = [];
    if (includeTerminal) tabs.push('terminal');
    if (includeDesktop) tabs.push('desktop');
    if (includeControl) tabs.push('control');
    if (includeOutput) tabs.push('output');
    return tabs;
  };

  const availableTabs = getAvailableTabs();
  const actualDefaultTab = availableTabs.includes(defaultTab)
    ? defaultTab
    : availableTabs[0] || 'terminal';

  // Build tab items based on included sub-components
  const tabItems: any[] = [];

  const [internalActiveTab, setInternalActiveTab] = useState<SandboxTabKey>(actualDefaultTab);

  if (includeTerminal) {
    tabItems.push({
      key: 'terminal',
      label: (
        <Space size={4}>
          <CodeOutlined />
          <span>Terminal</span>
        </Space>
      ),
      children: <TerminalTabContent sandboxId={sandboxId} />,
    });
  }

  if (includeDesktop) {
    tabItems.push({
      key: 'desktop',
      label: (
        <Space size={4}>
          <DesktopOutlined />
          <span>Desktop</span>
          {desktopStatus?.running && <Badge status="success" className="ml-1" />}
        </Space>
      ),
      children: <DesktopTabContent sandboxId={sandboxId} desktopStatus={desktopStatus} />,
    });
  }

  if (includeControl) {
    tabItems.push({
      key: 'control',
      label: (
        <Space size={4}>
          <DesktopOutlined />
          <span>Control</span>
        </Space>
      ),
      children: (
        <ControlTabContent
          sandboxId={sandboxId}
          desktopStatus={desktopStatus}
          terminalStatus={terminalStatus}
          onDesktopStart={onDesktopStart}
          onDesktopStop={onDesktopStop}
          onTerminalStart={onTerminalStart}
          onTerminalStop={onTerminalStop}
          isDesktopLoading={isDesktopLoading}
          isTerminalLoading={isTerminalLoading}
        />
      ),
    });
  }

  if (includeOutput) {
    tabItems.push({
      key: 'output',
      label: (
        <Space size={4}>
          <FileTextOutlined />
          <span>Output</span>
          {toolExecutions.length > 0 && (
            <Badge count={toolExecutions.length} size="small" className="ml-1" />
          )}
        </Space>
      ),
      children: <OutputTabContent toolExecutions={toolExecutions} onFileClick={onFileClick} />,
    });
  }

  return (
    <SandboxPanelProvider
      sandboxId={sandboxId}
      defaultTab={defaultTab}
      toolExecutions={toolExecutions}
      currentTool={currentTool}
      desktopStatus={desktopStatus}
      terminalStatus={terminalStatus}
      onDesktopStart={onDesktopStart}
      onDesktopStop={onDesktopStop}
      onTerminalStart={onTerminalStart}
      onTerminalStop={onTerminalStop}
      isDesktopLoading={isDesktopLoading}
      isTerminalLoading={isTerminalLoading}
      onFileClick={onFileClick}
      onClose={onClose}
    >
      <div className="h-full flex flex-col bg-white border-l border-slate-200">
        {/* Header */}
        {includeHeader && (
          <SandboxHeaderRender currentTool={currentTool} sandboxId={sandboxId} onClose={onClose} />
        )}

        {/* Tabs */}
        {tabItems.length > 0 && (
          <Tabs
            activeKey={internalActiveTab}
            onChange={(key) => setInternalActiveTab(key as SandboxTabKey)}
            items={tabItems}
            className="flex-1 sandbox-panel-tabs"
            tabBarStyle={{ margin: 0, paddingLeft: 16, paddingRight: 16 }}
          />
        )}

        {/* Styles */}
        <style>{`
          .sandbox-panel-tabs {
            display: flex;
            flex-direction: column;
            height: 100%;
          }
          .sandbox-panel-tabs .ant-tabs-content {
            flex: 1;
            height: 0;
          }
          .sandbox-panel-tabs .ant-tabs-content-holder {
            flex: 1;
            display: flex;
            flex-direction: column;
          }
          .sandbox-panel-tabs .ant-tabs-tabpane {
            height: 100%;
          }
        `}</style>
      </div>
    </SandboxPanelProvider>
  );
}

// Export Root alias
SandboxPanel.Root = SandboxPanel;

// Set display name
SandboxPanel.displayName = 'SandboxPanel';

export default SandboxPanel;
