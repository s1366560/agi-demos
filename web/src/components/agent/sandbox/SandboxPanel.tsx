/**
 * SandboxPanel - Main sandbox panel combining terminal and output viewer
 *
 * Provides a tabbed interface for interacting with sandbox containers,
 * including terminal access and tool execution output viewing.
 */

import { useState, useCallback } from "react";
import { Tabs, Empty, Button, Tooltip, Badge, Space } from "antd";
import {
  CodeOutlined,
  FileTextOutlined,
  CloseOutlined,
} from "@ant-design/icons";

import { SandboxTerminal } from "./SandboxTerminal";
import { SandboxOutputViewer, ToolExecution } from "./SandboxOutputViewer";

export interface SandboxPanelProps {
  /** Active sandbox ID */
  sandboxId: string | null;
  /** Tool execution history */
  toolExecutions?: ToolExecution[];
  /** Current tool being executed */
  currentTool?: { name: string; input: Record<string, unknown> } | null;
  /** Called when panel is closed */
  onClose?: () => void;
  /** Called when file is clicked in output */
  onFileClick?: (filePath: string) => void;
  /** Default tab (default: "terminal") */
  defaultTab?: "terminal" | "output";
}

type TabKey = "terminal" | "output";

export function SandboxPanel({
  sandboxId,
  toolExecutions = [],
  currentTool,
  onClose,
  onFileClick,
  defaultTab = "terminal",
}: SandboxPanelProps) {
  const [activeTab, setActiveTab] = useState<TabKey>(defaultTab);
  const [terminalSessionId, setTerminalSessionId] = useState<string | null>(
    null
  );
  const [isTerminalConnected, setIsTerminalConnected] = useState(false);

  // Handle terminal connection
  const handleTerminalConnect = useCallback((sessionId: string) => {
    setTerminalSessionId(sessionId);
    setIsTerminalConnected(true);
  }, []);

  const handleTerminalDisconnect = useCallback(() => {
    setIsTerminalConnected(false);
  }, []);

  // Tab items
  const tabItems = [
    {
      key: "terminal" as TabKey,
      label: (
        <Space size={4}>
          <CodeOutlined />
          <span>Terminal</span>
          {isTerminalConnected && (
            <Badge status="success" className="ml-1" />
          )}
        </Space>
      ),
      children: sandboxId ? (
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
        <div className="h-full flex items-center justify-center">
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description="No sandbox connected"
          />
        </div>
      ),
    },
    {
      key: "output" as TabKey,
      label: (
        <Space size={4}>
          <FileTextOutlined />
          <span>Output</span>
          {toolExecutions.length > 0 && (
            <Badge
              count={toolExecutions.length}
              size="small"
              className="ml-1"
            />
          )}
        </Space>
      ),
      children: (
        <SandboxOutputViewer
          executions={toolExecutions}
          onFileClick={onFileClick}
          maxHeight="100%"
        />
      ),
    },
  ];

  return (
    <div className="h-full flex flex-col bg-white border-l border-slate-200">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-slate-200 bg-slate-50">
        <div className="flex items-center gap-2">
          <CodeOutlined className="text-slate-500" />
          <span className="font-medium text-slate-700">Sandbox</span>
          {sandboxId && (
            <span className="text-xs text-slate-400">
              ({sandboxId.slice(0, 12)})
            </span>
          )}
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

      {/* Tabs */}
      <Tabs
        activeKey={activeTab}
        onChange={(key) => setActiveTab(key as TabKey)}
        items={tabItems}
        className="flex-1 sandbox-panel-tabs"
        tabBarStyle={{ margin: 0, paddingLeft: 16, paddingRight: 16 }}
      />

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
  );
}

export default SandboxPanel;
