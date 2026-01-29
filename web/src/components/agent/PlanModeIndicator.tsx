/**
 * PlanModeIndicator component for displaying Plan Mode status.
 *
 * Shows a compact visual indicator when the conversation is in Plan Mode,
 * with quick actions to view the plan or exit Plan Mode.
 */

import React from "react";
import { Button, Tag, Tooltip, Badge } from "antd";
import {
  FileTextOutlined,
  ExperimentOutlined,
  BuildOutlined,
  EyeOutlined,
  CloseOutlined,
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
  build: "success",
  plan: "processing",
  explore: "warning",
};

const modeBgColors: Record<AgentMode, string> = {
  build: "bg-emerald-50 border-emerald-200",
  plan: "bg-blue-50 border-blue-200",
  explore: "bg-amber-50 border-amber-200",
};

const modeTextColors: Record<AgentMode, string> = {
  build: "text-emerald-700",
  plan: "text-blue-700",
  explore: "text-amber-700",
};

const modeIconColors: Record<AgentMode, string> = {
  build: "text-emerald-600",
  plan: "text-blue-600",
  explore: "text-amber-600",
};

const modeLabels: Record<AgentMode, string> = {
  build: "Build",
  plan: "Plan",
  explore: "Explore",
};

const modeDescriptions: Record<AgentMode, string> = {
  build: "Full access - read, write, and execute",
  plan: "Read-only + plan editing - design your approach",
  explore: "Pure read-only - exploring as SubAgent",
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
        <Tag
          color={modeColors[currentMode]}
          icon={modeIcons[currentMode]}
          className="cursor-pointer"
        >
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
    <div
      className={`
        flex items-center justify-between px-4 py-2.5 rounded-xl border
        ${modeBgColors[currentMode]} mb-4 mx-4 mt-2
        transition-all duration-200 animate-slide-down
      `}
    >
      {/* Left: Mode Icon + Info */}
      <div className="flex items-center gap-3">
        <div
          className={`
            w-8 h-8 rounded-lg flex items-center justify-center
            bg-white/80 shadow-sm
          `}
        >
          <span className={modeIconColors[currentMode]}>
            {modeIcons[currentMode]}
          </span>
        </div>
        <div className="flex flex-col">
          <div className="flex items-center gap-2">
            <span className={`font-semibold text-sm ${modeTextColors[currentMode]}`}>
              {modeLabels[currentMode]} Mode
            </span>
            <Badge status={modeColors[currentMode] as any} size="small" />
          </div>
          <span className="text-xs text-slate-500">
            {modeDescriptions[currentMode]}
          </span>
        </div>
      </div>

      {/* Right: Actions */}
      {isInPlanMode && (
        <div className="flex items-center gap-2">
          {onViewPlan && status.plan && (
            <Tooltip title="View Plan">
              <Button
                size="small"
                icon={<EyeOutlined />}
                onClick={onViewPlan}
                className="flex items-center gap-1"
              >
                View
              </Button>
            </Tooltip>
          )}
          {onExitPlanMode && (
            <Tooltip title="Exit Plan Mode">
              <Button
                size="small"
                type="primary"
                danger
                icon={<CloseOutlined />}
                onClick={onExitPlanMode}
              >
                Exit
              </Button>
            </Tooltip>
          )}
        </div>
      )}
    </div>
  );
};

export default PlanModeIndicator;
