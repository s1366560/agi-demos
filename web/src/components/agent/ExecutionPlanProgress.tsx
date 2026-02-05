/**
 * ExecutionPlanProgress Component
 *
 * Displays progress of an ExecutionPlan with step counts and status.
 *
 * Part of Plan Mode UI.
 */

import React, { useMemo } from "react";

import { Progress, Typography, Badge } from "antd";

import { ExecutionPlan, ExecutionPlanStatus } from "../../types/agent";

const { Text } = Typography;

interface ExecutionPlanProgressProps {
  plan: ExecutionPlan | null;
}

/**
 * Get status color for plan
 */
const getStatusColor = (status: ExecutionPlanStatus): string => {
  switch (status) {
    case "draft":
      return "default";
    case "approved":
      return "blue";
    case "executing":
      return "processing";
    case "paused":
      return "warning";
    case "completed":
      return "success";
    case "failed":
      return "error";
    case "cancelled":
      return "default";
    default:
      return "default";
  }
};

/**
 * Get status text for plan
 */
const getStatusText = (status: ExecutionPlanStatus): string => {
  switch (status) {
    case "draft":
      return "Draft";
    case "approved":
      return "Approved";
    case "executing":
      return "Executing";
    case "paused":
      return "Paused";
    case "completed":
      return "Completed";
    case "failed":
      return "Failed";
    case "cancelled":
      return "Cancelled";
    default:
      return "Unknown";
  }
};

export const ExecutionPlanProgress: React.FC<ExecutionPlanProgressProps> = ({ plan }) => {
  const { percent, completedCount, failedCount, totalCount, statusColor, statusText } = useMemo(() => {
    if (!plan) {
      return {
        percent: 0,
        completedCount: 0,
        failedCount: 0,
        totalCount: 0,
        statusColor: "default",
        statusText: "No Plan",
      };
    }

    const completedCount = plan.completed_steps.length;
    const failedCount = plan.failed_steps.length;
    const totalCount = plan.steps.length;
    const percent = totalCount > 0 ? plan.progress_percentage : 0;
    const statusColor = getStatusColor(plan.status);
    const statusText = getStatusText(plan.status);

    return { percent, completedCount, failedCount, totalCount, statusColor, statusText };
  }, [plan]);

  if (!plan) {
    return (
      <div className="p-4 bg-slate-50 border border-slate-200 rounded-lg">
        <Text type="secondary">No execution plan</Text>
      </div>
    );
  }

  return (
    <div className="p-4 bg-white border border-slate-200 rounded-lg shadow-sm">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Text strong>Execution Progress</Text>
          <Badge status={statusColor as any} text={statusText} />
        </div>
        <Text type="secondary" className="text-sm">
          {completedCount} / {totalCount} steps
        </Text>
      </div>

      <Progress
        percent={Math.round(percent)}
        status={plan.status === "failed" ? "exception" : plan.status === "completed" ? "success" : "active"}
        strokeColor={{
          "0%": "#108ee9",
          "100%": "#87d068",
        }}
      />

      <div className="flex justify-between mt-2 text-xs text-slate-500">
        <span>Completed: {completedCount}</span>
        <span>Failed: {failedCount}</span>
        <span>Remaining: {totalCount - completedCount - failedCount}</span>
      </div>

      {plan.reflection_enabled && (
        <div className="mt-3 pt-3 border-t border-slate-100">
          <Text type="secondary" className="text-xs">
            Reflection: {plan.max_reflection_cycles} max cycles
          </Text>
        </div>
      )}
    </div>
  );
};

export default ExecutionPlanProgress;
