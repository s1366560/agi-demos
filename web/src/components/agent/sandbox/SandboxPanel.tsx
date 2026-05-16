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

import { useState, useCallback, Children, isValidElement } from 'react';
import type { ReactNode } from 'react';

import { useTranslation } from 'react-i18next';

import { Tabs, Empty, Button, Tooltip, Badge, Space } from 'antd';
import { Code, FileText, Monitor, X } from 'lucide-react';

import { useSandboxStore } from '../../../stores/sandbox';

import { RemoteDesktopViewer } from './RemoteDesktopViewer';
import { SandboxControlPanel } from './SandboxControlPanel';
import { SandboxOutputViewer } from './SandboxOutputViewer';
import { SandboxPanelProvider } from './SandboxPanelContext';
import { SandboxTerminal } from './SandboxTerminal';

import type { ToolExecution as OutputToolExecution } from './SandboxOutputViewer';
import type {
  SandboxTabKey,
  SandboxPanelRootProps,
  SandboxPanelToolExecution,
  SandboxTerminalProps,
  SandboxDesktopProps,
  SandboxControlProps,
  SandboxOutputProps,
  SandboxHeaderProps,
} from './types';
import type { TabsProps } from 'antd';
import type { TFunction } from 'i18next';

// ========================================
// Marker Symbols for Sub-Components
// ========================================

const TERMINAL_SYMBOL = Symbol('SandboxPanelTerminal');
const DESKTOP_SYMBOL = Symbol('SandboxPanelDesktop');
const CONTROL_SYMBOL = Symbol('SandboxPanelControl');
const OUTPUT_SYMBOL = Symbol('SandboxPanelOutput');
const HEADER_SYMBOL = Symbol('SandboxPanelHeader');

type SandboxPanelMarker =
  | typeof TERMINAL_SYMBOL
  | typeof DESKTOP_SYMBOL
  | typeof CONTROL_SYMBOL
  | typeof OUTPUT_SYMBOL
  | typeof HEADER_SYMBOL;

type MarkerComponent<P> = ((props: P) => null) &
  Partial<Record<SandboxPanelMarker, true>> & {
    displayName?: string | undefined;
  };

function tFallback(t: TFunction, key: string, fallback: string): string {
  const translated = t(key, fallback);
  return translated === key ? fallback : translated;
}

function markComponent<P>(
  component: (props: P) => null,
  marker: SandboxPanelMarker,
  displayName: string
): MarkerComponent<P> {
  const markedComponent = component as MarkerComponent<P>;
  markedComponent[marker] = true;
  markedComponent.displayName = displayName;
  return markedComponent;
}

function childHasMarker(child: ReactNode, marker: SandboxPanelMarker): boolean {
  if (!isValidElement(child) || typeof child.type !== 'function') return false;
  return (child.type as MarkerComponent<unknown>)[marker] === true;
}

function formatToolOutput(output: unknown): string | undefined {
  if (output === undefined || output === null) return undefined;
  if (typeof output === 'string') return output;
  try {
    return JSON.stringify(output, null, 2);
  } catch {
    return '[unserializable output]';
  }
}

function normalizeToolExecutions(executions: SandboxPanelToolExecution[]): OutputToolExecution[] {
  return executions.map((execution) => {
    const output = formatToolOutput(execution.output);
    return {
      id: execution.id,
      toolName: execution.toolName,
      input: execution.input,
      timestamp: execution.timestamp,
      ...(output !== undefined ? { output } : {}),
    };
  });
}

// ========================================
// Sub-Components (Marker Components)
// ========================================

SandboxPanel.Terminal = markComponent(
  function SandboxPanelTerminalMarker(_props: SandboxTerminalProps) {
    return null;
  },
  TERMINAL_SYMBOL,
  'SandboxPanelTerminal'
);

SandboxPanel.Desktop = markComponent(
  function SandboxPanelDesktopMarker(_props: SandboxDesktopProps) {
    return null;
  },
  DESKTOP_SYMBOL,
  'SandboxPanelDesktop'
);

SandboxPanel.Control = markComponent(
  function SandboxPanelControlMarker(_props: SandboxControlProps) {
    return null;
  },
  CONTROL_SYMBOL,
  'SandboxPanelControl'
);

SandboxPanel.Output = markComponent(
  function SandboxPanelOutputMarker(_props: SandboxOutputProps) {
    return null;
  },
  OUTPUT_SYMBOL,
  'SandboxPanelOutput'
);

SandboxPanel.Header = markComponent(
  function SandboxPanelHeaderMarker(_props: SandboxHeaderProps) {
    return null;
  },
  HEADER_SYMBOL,
  'SandboxPanelHeader'
);

// ========================================
// Internal Components
// ========================================

interface HeaderRenderProps {
  currentTool: { name: string; input: Record<string, unknown> } | null;
  sandboxId: string | null;
  onClose?: (() => void) | undefined;
}

function SandboxHeaderRender({ currentTool, sandboxId, onClose }: HeaderRenderProps) {
  const { t } = useTranslation();
  const title = tFallback(t, 'components.sandboxPanel.title', 'Sandbox');

  return (
    <div className="flex items-center justify-between px-4 py-2 border-b border-slate-200 bg-slate-50">
      <div className="flex items-center gap-2">
        <Code size={16} className="text-slate-500" />
        <span className="font-medium text-slate-700">{title}</span>
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
            icon={<X size={16} />}
            onClick={onClose}
            className="text-slate-400 hover:text-slate-600"
          />
        )}
      </div>
    </div>
  );
}

interface TabContentProps {
  sandboxId?: string | null | undefined;
  desktopStatus?: SandboxPanelRootProps['desktopStatus'];
  terminalStatus?: SandboxPanelRootProps['terminalStatus'];
  toolExecutions?: SandboxPanelToolExecution[] | undefined;
  onFileClick?: ((filePath: string) => void) | undefined;
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
        desktopStatus={desktopStatus ?? null}
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
  isDesktopLoading?: boolean | undefined;
  isTerminalLoading?: boolean | undefined;
  onDesktopStart?: (() => void) | undefined;
  onDesktopStop?: (() => void) | undefined;
  onTerminalStart?: (() => void) | undefined;
  onTerminalStop?: (() => void) | undefined;
}) {
  return sandboxId ? (
    <div className="h-full overflow-y-auto p-4">
      <SandboxControlPanel
        sandboxId={sandboxId}
        desktopStatus={desktopStatus ?? null}
        terminalStatus={terminalStatus ?? null}
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
  const executions = normalizeToolExecutions(toolExecutions);
  return <SandboxOutputViewer executions={executions} onFileClick={onFileClick} maxHeight="100%" />;
}

function EmptyState() {
  const { t } = useTranslation();
  const description = tFallback(
    t,
    'components.sandboxPanel.noSandboxConnected',
    'No sandbox connected'
  );

  return (
    <div className="h-full flex items-center justify-center">
      <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={description} />
    </div>
  );
}

// ========================================
// Main Component
// ========================================

export function SandboxPanel(props: SandboxPanelRootProps) {
  const { t } = useTranslation();
  const terminalLabel = tFallback(t, 'components.sandboxPanel.terminal', 'Terminal');
  const desktopLabel = tFallback(t, 'components.sandboxPanel.desktop', 'Desktop');
  const controlLabel = tFallback(t, 'components.sandboxPanel.control', 'Control');
  const outputLabel = tFallback(t, 'components.sandboxPanel.output', 'Output');
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
  const terminalChild = childrenArray.find((child) => childHasMarker(child, TERMINAL_SYMBOL));
  const desktopChild = childrenArray.find((child) => childHasMarker(child, DESKTOP_SYMBOL));
  const controlChild = childrenArray.find((child) => childHasMarker(child, CONTROL_SYMBOL));
  const outputChild = childrenArray.find((child) => childHasMarker(child, OUTPUT_SYMBOL));

  // Determine if using compound mode (has explicit sub-components)
  const hasSubComponents =
    terminalChild !== undefined ||
    desktopChild !== undefined ||
    controlChild !== undefined ||
    outputChild !== undefined;

  // In legacy mode, include all tabs by default
  // In compound mode, only include explicitly specified tabs
  // Header is always included by default (can be explicitly excluded with a prop in the future)
  const includeTerminal = hasSubComponents ? !!terminalChild : true;
  const includeDesktop = hasSubComponents ? !!desktopChild : true;
  const includeControl = hasSubComponents ? !!controlChild : true;
  const includeOutput = hasSubComponents ? !!outputChild : true;
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
    : (availableTabs[0] ?? 'terminal');

  // Build tab items based on included sub-components
  const tabItems: NonNullable<TabsProps['items']> = [];

  const [internalActiveTab, setInternalActiveTab] = useState<SandboxTabKey>(actualDefaultTab);

  if (includeTerminal) {
    tabItems.push({
      key: 'terminal',
      label: (
        <Space size={4}>
          <Code size={16} />
          <span>{terminalLabel}</span>
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
          <Monitor size={16} />
          <span>{desktopLabel}</span>
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
          <Monitor size={16} />
          <span>{controlLabel}</span>
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
          <FileText size={16} />
          <span>{outputLabel}</span>
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
        <SandboxHeaderRender currentTool={currentTool} sandboxId={sandboxId} onClose={onClose} />

        {/* Tabs */}
        {tabItems.length > 0 && (
          <Tabs
            activeKey={internalActiveTab}
            onChange={(key) => {
              setInternalActiveTab(key as SandboxTabKey);
            }}
            items={tabItems}
            className="flex-1 sandbox-panel-tabs"
            tabBarStyle={{ margin: 0, paddingLeft: 16, paddingRight: 16 }}
          />
        )}
      </div>
    </SandboxPanelProvider>
  );
}

// Export Root alias
SandboxPanel.Root = SandboxPanel;

// Set display name
SandboxPanel.displayName = 'SandboxPanel';

export default SandboxPanel;
