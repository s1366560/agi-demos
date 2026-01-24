/**
 * RightPanel - Combined Plan and Sandbox panel with tab navigation
 *
 * Replaces the original PlanPanel with a tabbed interface that includes
 * both work plan viewing and sandbox terminal/output capabilities.
 */

import React, { useMemo } from "react";
import { Tabs, Badge, Space, Button, Tooltip } from "antd";
import {
  UnorderedListOutlined,
  CodeOutlined,
  CloseOutlined,
} from "@ant-design/icons";

import { PlanViewer } from "./PlanViewer";
import { SandboxPanel } from "../agent/sandbox";
import { useSandboxStore } from "../../stores/sandbox";
import type { WorkPlan } from "../../types/agent";
import type { ToolExecution } from "../agent/sandbox/SandboxOutputViewer";

export type RightPanelTab = "plan" | "sandbox";

export interface RightPanelProps {
  /** Current work plan */
  workPlan: WorkPlan | null;
  /** Active sandbox ID */
  sandboxId?: string | null;
  /** Tool execution history for sandbox */
  toolExecutions?: ToolExecution[];
  /** Called when panel is closed */
  onClose?: () => void;
  /** Called when file is clicked in sandbox output */
  onFileClick?: (filePath: string) => void;
  /** Controlled active tab */
  activeTab?: RightPanelTab;
  /** Callback when tab changes */
  onTabChange?: (tab: RightPanelTab) => void;
}

export const RightPanel: React.FC<RightPanelProps> = ({
  workPlan,
  sandboxId: propSandboxId,
  toolExecutions: propToolExecutions,
  onClose,
  onFileClick,
  activeTab: controlledActiveTab,
  onTabChange,
}) => {
  // Get sandbox state from store
  const {
    panelVisible: sandboxPanelVisible,
    activeSandboxId: storeSandboxId,
    toolExecutions: storeToolExecutions,
    currentTool,
  } = useSandboxStore();

  // Use props if provided, otherwise use store state
  const sandboxId = propSandboxId ?? storeSandboxId;
  const toolExecutions = propToolExecutions ?? storeToolExecutions;

  // Compute default tab based on current state
  const defaultTab = useMemo((): RightPanelTab => {
    // If sandbox is active with a tool running, default to sandbox
    if (currentTool && sandboxPanelVisible) {
      return "sandbox";
    }
    // Default to plan
    return "plan";
  }, [currentTool, sandboxPanelVisible]);

  // Local tab state (uncontrolled mode)
  const [internalActiveTab, setInternalActiveTab] = React.useState<RightPanelTab>(defaultTab);

  // Use controlled or uncontrolled tab
  const activeTab = controlledActiveTab ?? internalActiveTab;

  // Handle tab change
  const handleTabChange = (key: string) => {
    const newTab = key as RightPanelTab;
    if (onTabChange) {
      onTabChange(newTab);
    } else {
      setInternalActiveTab(newTab);
    }
  };

  // Tab items
  const tabItems = [
    {
      key: "plan" as RightPanelTab,
      label: (
        <Space size={4}>
          <UnorderedListOutlined />
          <span>Plan</span>
          {workPlan && workPlan.status === "in_progress" && (
            <Badge status="processing" className="ml-1" />
          )}
        </Space>
      ),
      children: (
        <div className="h-full">
          <PlanViewer plan={workPlan} />
        </div>
      ),
    },
    {
      key: "sandbox" as RightPanelTab,
      label: (
        <Space size={4}>
          <CodeOutlined />
          <span>Sandbox</span>
          {currentTool && <Badge status="processing" className="ml-1" />}
          {!currentTool && toolExecutions.length > 0 && (
            <Badge
              count={toolExecutions.length}
              size="small"
              className="ml-1"
              style={{ backgroundColor: "#52c41a" }}
            />
          )}
        </Space>
      ),
      disabled: !sandboxId,
      children: sandboxId ? (
        <SandboxPanel
          sandboxId={sandboxId}
          toolExecutions={toolExecutions}
          currentTool={currentTool}
          onFileClick={onFileClick}
        />
      ) : (
        <div className="h-full flex items-center justify-center text-slate-400">
          <div className="text-center">
            <CodeOutlined className="text-4xl mb-2" />
            <p>No sandbox connected</p>
            <p className="text-xs">Start a sandbox to enable terminal access</p>
          </div>
        </div>
      ),
    },
  ];

  return (
    <div className="h-full flex flex-col bg-white">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-slate-200 bg-slate-50">
        <span className="font-medium text-slate-700">
          {activeTab === "plan" ? "Work Plan" : "Sandbox"}
        </span>
        <div className="flex items-center gap-1">
          {onClose && (
            <Tooltip title="Close panel">
              <Button
                type="text"
                size="small"
                icon={<CloseOutlined />}
                onClick={onClose}
                className="text-slate-400 hover:text-slate-600"
              />
            </Tooltip>
          )}
        </div>
      </div>

      {/* Tabs */}
      <Tabs
        activeKey={activeTab}
        onChange={handleTabChange}
        items={tabItems}
        className="flex-1 right-panel-tabs"
        tabBarStyle={{
          margin: 0,
          paddingLeft: 16,
          paddingRight: 16,
          borderBottom: "1px solid #e2e8f0",
        }}
      />

      {/* Styles */}
      <style>{`
        .right-panel-tabs {
          display: flex;
          flex-direction: column;
          height: 100%;
        }
        .right-panel-tabs .ant-tabs-content {
          flex: 1;
          height: 0;
        }
        .right-panel-tabs .ant-tabs-content-holder {
          flex: 1;
          display: flex;
          flex-direction: column;
        }
        .right-panel-tabs .ant-tabs-tabpane {
          height: 100%;
        }
      `}</style>
    </div>
  );
};

export default RightPanel;
