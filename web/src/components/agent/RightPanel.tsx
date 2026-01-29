/**
 * RightPanel - Combined Plan and Sandbox panel with tab navigation
 *
 * Replaces the original PlanPanel with a tabbed interface that includes
 * both work plan viewing, plan editing, and sandbox terminal/desktop/output capabilities.
 *
 * Plan tab shows:
 * - PlanEditor for draft/reviewing plans (editable)
 * - PlanModeViewer for executing plans (read-only with progress)
 * - PlanViewer for WorkPlan visualization
 */

import React, { useMemo, useCallback, useEffect, useState } from "react";
import { Tabs, Badge, Space, Button, Tooltip, Segmented } from "antd";
import {
  UnorderedListOutlined,
  CodeOutlined,
  CloseOutlined,
  EditOutlined,
  EyeOutlined,
} from "@ant-design/icons";

import { PlanViewer } from "./PlanViewer";
import { PlanEditor } from "./PlanEditor";
import { PlanModeViewer } from "./PlanModeViewer";
import { SandboxPanel } from "./sandbox";
import { useSandboxStore, isSandboxTool } from "../../stores/sandbox";
import { usePlanModeStore } from "../../stores/agent/planModeStore";
import type { WorkPlan } from "../../types/agent";
import type { ToolExecution } from "./sandbox/SandboxOutputViewer";
import type { ExecutionPlan } from "../../types/agent";

export type RightPanelTab = "plan" | "sandbox";
export type PlanViewMode = "work" | "document" | "execution";

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
  /** Execution plan for plan mode (optional) */
  executionPlan?: ExecutionPlan | null;
}

export const RightPanel: React.FC<RightPanelProps> = ({
  workPlan,
  sandboxId: propSandboxId,
  toolExecutions: propToolExecutions,
  onClose,
  onFileClick,
  activeTab: controlledActiveTab,
  onTabChange,
  executionPlan,
}) => {
  // Get sandbox state from store (including desktop and terminal status)
  const {
    panelVisible: sandboxPanelVisible,
    activeSandboxId: storeSandboxId,
    toolExecutions: storeToolExecutions,
    currentTool,
    desktopStatus,
    terminalStatus,
    isDesktopLoading,
    isTerminalLoading,
    startDesktop,
    stopDesktop,
    startTerminal,
    stopTerminal,
  } = useSandboxStore();

  // Get plan mode state
  const { currentPlan, updatePlan, exitPlanMode, submitPlanForReview } = usePlanModeStore();

  // Use props if provided, otherwise use store state
  const sandboxId = propSandboxId ?? storeSandboxId;
  const toolExecutions = propToolExecutions ?? storeToolExecutions;

  // Plan view mode state (for plan tab)
  const [planViewMode, setPlanViewMode] = useState<PlanViewMode>("work");

  // Determine available plan view modes based on state
  const availablePlanModes = useMemo(() => {
    const modes: { value: PlanViewMode; label: string; icon: React.ReactNode }[] = [];

    // Work plan view (always available)
    modes.push({ value: "work", label: "Work Plan", icon: <UnorderedListOutlined /> });

    // Document view (available when there's a plan document)
    if (currentPlan) {
      modes.push({ value: "document", label: "Document", icon: <EditOutlined /> });
    }

    // Execution view (available when there's an execution plan)
    if (executionPlan) {
      modes.push({ value: "execution", label: "Execution", icon: <EyeOutlined /> });
    }

    return modes;
  }, [currentPlan, executionPlan]);

  // Auto-switch plan view mode based on state
  useEffect(() => {
    if (executionPlan && planViewMode === "work") {
      setPlanViewMode("execution");
    } else if (!executionPlan && !currentPlan && planViewMode !== "work") {
      setPlanViewMode("work");
    } else if (!executionPlan && currentPlan && planViewMode === "execution") {
      setPlanViewMode("document");
    }
  }, [executionPlan, currentPlan, planViewMode]);

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

  // Stable callback for tab changes
  const handleTabChange = useCallback((key: string) => {
    const newTab = key as RightPanelTab;
    if (onTabChange) {
      onTabChange(newTab);
    } else {
      setInternalActiveTab(newTab);
    }
  }, [onTabChange]);

  // Auto-switch to sandbox tab when a sandbox tool is being executed
  useEffect(() => {
    if (currentTool && isSandboxTool(currentTool.name) && sandboxId) {
      if (onTabChange) {
        onTabChange("sandbox");
      } else {
        setInternalActiveTab("sandbox");
      }
    }
  }, [currentTool, sandboxId, onTabChange]);

  // Render plan content based on view mode
  const planContent = useMemo(() => {
    // Execution plan view (read-only with progress)
    if (planViewMode === "execution" && executionPlan) {
      return (
        <div className="h-full overflow-auto p-4">
          <PlanModeViewer plan={executionPlan} />
        </div>
      );
    }

    // Document view (editable)
    if (planViewMode === "document" && currentPlan) {
      return (
        <div className="h-full overflow-auto p-4">
          <PlanEditor
            plan={currentPlan}
            onUpdate={async (content) => {
              // Handle plan update via planModeStore
              await updatePlan(currentPlan.id, { content });
            }}
            onSubmitForReview={async () => {
              // Handle submit for review via planModeStore
              await submitPlanForReview(currentPlan.id);
            }}
            onExit={async (approve, summary) => {
              // Handle plan exit via planModeStore
              // Use empty string for conversation_id if not available
              const conversationId = currentPlan.conversation_id || "";
              await exitPlanMode(conversationId, currentPlan.id, approve, summary);
            }}
          />
        </div>
      );
    }

    // Work plan view (default)
    return (
      <div className="h-full">
        <PlanViewer plan={workPlan} />
      </div>
    );
  }, [planViewMode, executionPlan, currentPlan, workPlan]);

  // Memoized tab items
  const tabItems = useMemo(() => [
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
        <div className="h-full flex flex-col">
          {/* Plan view mode selector - shown when multiple modes available */}
          {availablePlanModes.length > 1 && (
            <div className="px-4 pt-3 pb-2 border-b border-slate-100">
              <Segmented
                value={planViewMode}
                onChange={(value) => setPlanViewMode(value as PlanViewMode)}
                options={availablePlanModes.map((mode) => ({
                  value: mode.value,
                  label: mode.label,
                  icon: mode.icon,
                }))}
                size="small"
              />
            </div>
          )}
          {planContent}
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
          desktopStatus={desktopStatus}
          terminalStatus={terminalStatus}
          onDesktopStart={startDesktop}
          onDesktopStop={stopDesktop}
          onTerminalStart={startTerminal}
          onTerminalStop={stopTerminal}
          isDesktopLoading={isDesktopLoading}
          isTerminalLoading={isTerminalLoading}
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
  ], [
    workPlan,
    currentTool,
    toolExecutions,
    sandboxId,
    onFileClick,
    desktopStatus,
    terminalStatus,
    isDesktopLoading,
    isTerminalLoading,
    startDesktop,
    stopDesktop,
    startTerminal,
    stopTerminal,
  ]);

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
