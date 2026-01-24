/**
 * PlanModeIndicator component for displaying Plan Mode status.
 *
 * Shows a visual indicator when the conversation is in Plan Mode,
 * with quick actions to view the plan or exit Plan Mode.
 */

import React from "react";
import { Alert, Button, Space, Tag, Tooltip } from "antd";
import {
  FileTextOutlined,
  ExperimentOutlined,
  BuildOutlined,
  EyeOutlined,
} from "@ant-design/icons";
import type { AgentMode, PlanModeStatus } from "../../types/agent";

interface PlanModeIndicatorProps {
  status: PlanModeStatus | null;
  onViewPlan?: () => void;
  onExitPlanMode?: () => void;
  compact?: boolean;
}

const modeIcons: Record<AgentMode, React.ReactNode> = {
  build: <BuildOutlined />,
  plan: <FileTextOutlined />,
  explore: <ExperimentOutlined />,
};

const modeColors: Record<AgentMode, string> = {
  build: "green",
  plan: "blue",
  explore: "purple",
};

const modeLabels: Record<AgentMode, string> = {
  build: "Build Mode",
  plan: "Plan Mode",
  explore: "Explore Mode",
};

const modeDescriptions: Record<AgentMode, string> = {
  build: "Full access - you can read, write, and execute code",
  plan: "Read-only + plan editing - explore the codebase and design your approach",
  explore: "Pure read-only - exploring as a SubAgent",
};

export const PlanModeIndicator: React.FC<PlanModeIndicatorProps> = ({
  status,
  onViewPlan,
  onExitPlanMode,
  compact = false,
}) => {
  if (!status) {
    return null;
  }

  const currentMode = status.current_mode;
  const isInPlanMode = status.is_in_plan_mode;

  if (compact) {
    return (
      <Tooltip title={modeDescriptions[currentMode]}>
        <Tag color={modeColors[currentMode]} icon={modeIcons[currentMode]}>
          {modeLabels[currentMode]}
        </Tag>
      </Tooltip>
    );
  }

  if (!isInPlanMode && currentMode === "build") {
    // Default state, no need to show indicator
    return null;
  }

  return (
    <Alert
      type={
        currentMode === "plan"
          ? "info"
          : currentMode === "explore"
          ? "warning"
          : "success"
      }
      showIcon
      icon={modeIcons[currentMode]}
      message={
        <Space>
          <span>{modeLabels[currentMode]}</span>
          {status.plan && <Tag color="blue">{status.plan.title}</Tag>}
        </Space>
      }
      description={modeDescriptions[currentMode]}
      action={
        isInPlanMode && (
          <Space direction="vertical" size="small">
            {onViewPlan && status.plan && (
              <Button size="small" icon={<EyeOutlined />} onClick={onViewPlan}>
                View Plan
              </Button>
            )}
            {onExitPlanMode && (
              <Button size="small" type="primary" onClick={onExitPlanMode}>
                Exit Plan Mode
              </Button>
            )}
          </Space>
        )
      }
      style={{ marginBottom: 16 }}
    />
  );
};

export default PlanModeIndicator;
