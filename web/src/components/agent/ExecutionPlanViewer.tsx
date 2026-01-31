/**
 * ExecutionPlanViewer Component
 *
 * Displays real-time execution progress of an ExecutionPlan.
 *
 * Features:
 * - Progress overview with statistics
 * - Step-by-step execution status
 * - Reflection results display
 * - Plan adjustments history
 * - Real-time SSE updates
 *
 * Part of Plan Mode UI.
 *
 * @module components/agent/ExecutionPlanViewer
 */

import React, { useMemo } from "react";
import {
  Progress,
  Typography,
  Card,
  List,
  Tag,
  Space,
  Spin,
  Empty,
} from "antd";
import {
  CheckCircleOutlined,
  LoadingOutlined,
  ClockCircleOutlined,
  CloseCircleOutlined,
  MinusCircleOutlined,
  PlusCircleOutlined,
  EditOutlined,
  SwapOutlined,
} from "@ant-design/icons";
import { ExecutionPlan, ExecutionStep } from "../../types/agent";
import { usePlanModeEvents, ReflectionResult, PlanAdjustment } from "../../hooks/usePlanModeEvents";

const { Text } = Typography;

/**
 * Component Props
 */
interface ExecutionPlanViewerProps {
  planId: string | null;
  plan: ExecutionPlan | null;
}

/**
 * Get status icon for a step
 */
const getStepStatusIcon = (status: string): React.ReactNode => {
  switch (status) {
    case "completed":
      return <CheckCircleOutlined className="text-green-500" />;
    case "running":
      return <LoadingOutlined className="text-blue-500 spin" />;
    case "failed":
      return <CloseCircleOutlined className="text-red-500" />;
    case "skipped":
      return <MinusCircleOutlined className="text-gray-400" />;
    case "cancelled":
      return <MinusCircleOutlined className="text-gray-400" />;
    default:
      return <ClockCircleOutlined className="text-gray-400" />;
  }
};

/**
 * Get status color for a step
 */
const getStepStatusColor = (status: string): string => {
  switch (status) {
    case "completed":
      return "success";
    case "running":
      return "processing";
    case "failed":
      return "error";
    case "skipped":
      return "default";
    case "cancelled":
      return "default";
    default:
      return "default";
  }
};

/**
 * Get adjustment icon
 */
const getAdjustmentIcon = (type: PlanAdjustment["type"]): React.ReactNode => {
  switch (type) {
    case "step_added":
      return <PlusCircleOutlined className="text-green-500" />;
    case "step_removed":
      return <MinusCircleOutlined className="text-red-500" />;
    case "step_modified":
      return <EditOutlined className="text-blue-500" />;
    case "step_reordered":
      return <SwapOutlined className="text-orange-500" />;
    default:
      return null;
  }
};

/**
 * PlanProgressCard Component
 *
 * Displays progress overview with statistics.
 */
interface PlanProgressCardProps {
  plan: ExecutionPlan;
}

const PlanProgressCard: React.FC<PlanProgressCardProps> = ({ plan }) => {
  const { totalSteps, completedCount, failedCount, remainingCount, progressPercentage } =
    useMemo(() => {
      const totalSteps = plan.steps.length;
      const completedCount = plan.completed_steps.length;
      const failedCount = plan.failed_steps.length;
      const remainingCount = totalSteps - completedCount - failedCount;
      const progressPercentage = plan.progress_percentage;

      return { totalSteps, completedCount, failedCount, remainingCount, progressPercentage };
    }, [plan]);

  const progressStatus = useMemo(() => {
    if (plan.status === "failed") return "exception";
    if (plan.status === "completed") return "success";
    return "active";
  }, [plan.status]);

  // Calculate estimated time (simplified - in real implementation would use actual timing)
  const estimatedTimeRemaining = useMemo(() => {
    if (plan.status === "completed" || remainingCount === 0) return null;

    // Rough estimate: 5 seconds per remaining step
    const seconds = remainingCount * 5;
    if (seconds < 60) return `${seconds}s`;
    const minutes = Math.ceil(seconds / 60);
    return `${minutes}m`;
  }, [plan.status, remainingCount]);

  return (
    <Card className="mb-4" size="small">
      <Space direction="vertical" className="w-full" size="small">
        <div className="flex items-center justify-between">
          <Text strong>Execution Progress</Text>
          <Tag color={progressStatus === "exception" ? "red" : progressStatus === "success" ? "green" : "blue"}>
            {plan.status.toUpperCase()}
          </Tag>
        </div>

        <Progress
          percent={Math.round(progressPercentage)}
          status={progressStatus}
          strokeColor={{
            "0%": "#108ee9",
            "100%": "#87d068",
          }}
          aria-label="Plan execution progress"
        />

        <div className="flex justify-between text-xs text-gray-600">
          <Text>Total Steps: {totalSteps}</Text>
          <Text type="success">Completed: {completedCount}</Text>
          <Text type="danger">Failed: {failedCount}</Text>
          <Text type="secondary">Remaining: {remainingCount}</Text>
        </div>

        {estimatedTimeRemaining && (
          <Text type="secondary" className="text-xs">
            Estimated Time: {estimatedTimeRemaining}
          </Text>
        )}

        {plan.reflection_enabled && (
          <Text type="secondary" className="text-xs">
            Reflection Cycles: 0/{plan.max_reflection_cycles}
          </Text>
        )}
      </Space>
    </Card>
  );
};

/**
 * StepItem Component
 *
 * Displays a single execution step with its status.
 */
interface StepItemProps {
  step: ExecutionStep;
}

const StepItem: React.FC<StepItemProps> = ({ step }) => {
  const [expanded, setExpanded] = React.useState(false);

  const handleToggle = () => {
    setExpanded(!expanded);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      setExpanded(!expanded);
    }
  };

  return (
    <div
      data-testid={`step-item-${step.step_id}`}
      className={`p-3 border border-gray-200 rounded mb-2 step-item status-${step.status}`}
      role="button"
      tabIndex={0}
      onClick={handleToggle}
      onKeyDown={handleKeyDown}
    >
      <div className="flex items-center justify-between cursor-pointer">
        <Space size="small">
          {getStepStatusIcon(step.status)}
          <Text strong>{step.description}</Text>
        </Space>

        <Space size="small">
          <Tag color={getStepStatusColor(step.status)}>{step.status.toUpperCase()}</Tag>
          <Text type="secondary" className="text-xs">
            {step.tool_name}
          </Text>
        </Space>
      </div>

      {expanded && (
        <div className="mt-3 pt-3 border-t border-gray-100" data-testid={`step-details-${step.step_id}`}>
          <Space orientation="vertical" className="w-full" size="small">
            <div className="text-xs">
              <Text strong>Tool:</Text> {step.tool_name}
            </div>

            {step.dependencies.length > 0 && (
              <div className="text-xs">
                <Text strong>Depends on:</Text> {step.dependencies.join(", ")}
              </div>
            )}

            {step.status === "failed" && step.error && (
              <div className="text-xs">
                <Text type="danger">
                  <Text strong>Error:</Text> {step.error}
                </Text>
              </div>
            )}

            {step.status === "completed" && step.result && (
              <div className="text-xs">
                <Text strong>Result:</Text> {step.result}
              </div>
            )}

            {step.started_at && (
              <div className="text-xs">
                <Text type="secondary">
                  Started: {new Date(step.started_at).toLocaleTimeString()}
                </Text>
              </div>
            )}

            {step.completed_at && (
              <div className="text-xs">
                <Text type="secondary">
                  Completed: {new Date(step.completed_at).toLocaleTimeString()}
                </Text>
              </div>
            )}
          </Space>
        </div>
      )}
    </div>
  );
};

/**
 * ReflectionCard Component
 *
 * Displays a single reflection result.
 */
interface ReflectionCardProps {
  reflection: ReflectionResult;
}

const ReflectionCard: React.FC<ReflectionCardProps> = ({ reflection }) => {
  return (
    <Card size="small" className="mb-2" data-testid={`reflection-${reflection.id}`}>
      <div className="flex items-center justify-between mb-2">
        <Space size="small">
          <Tag color="blue">Cycle {reflection.cycle_number}</Tag>
          <Text type="secondary" className="text-xs">
            {new Date(reflection.timestamp).toLocaleTimeString()}
          </Text>
        </Space>
        {reflection.confidence !== undefined && (
          <Text className="text-xs">Confidence: {Math.round(reflection.confidence * 100)}%</Text>
        )}
      </div>

      <Text className="text-sm block mb-2">{reflection.summary}</Text>

      {reflection.suggested_changes.length > 0 && (
        <div>
          <Text strong className="text-xs">
            Suggested Changes:
          </Text>
          <ul className="ml-4 mt-1 text-xs">
            {reflection.suggested_changes.map((change, idx) => (
              <li key={idx}>{change}</li>
            ))}
          </ul>
        </div>
      )}

      {reflection.issues_found && reflection.issues_found.length > 0 && (
        <div className="mt-2">
          <Text strong className="text-xs" type="danger">
            Issues Found:
          </Text>
          <ul className="ml-4 mt-1 text-xs">
            {reflection.issues_found.map((issue, idx) => (
              <li key={idx} className="text-red-600">
                {issue}
              </li>
            ))}
          </ul>
        </div>
      )}
    </Card>
  );
};

/**
 * AdjustmentsList Component
 *
 * Displays plan adjustment history.
 */
interface AdjustmentsListProps {
  adjustments: PlanAdjustment[];
}

const AdjustmentsList: React.FC<AdjustmentsListProps> = ({ adjustments }) => {
  if (adjustments.length === 0) return null;

  return (
    <Card size="small" title="Adjustments" className="mt-4">
      <List
        size="small"
        dataSource={adjustments}
        renderItem={(adjustment) => (
          <List.Item
            key={adjustment.id}
            data-testid={`adjustment-${adjustment.id}`}
            className={`adjustment-item type-${adjustment.type}`}
          >
            <Space size="small">
              {getAdjustmentIcon(adjustment.type)}
              <Text>{adjustment.description}</Text>
              <Text type="secondary" className="text-xs">
                {new Date(adjustment.timestamp).toLocaleTimeString()}
              </Text>
            </Space>
          </List.Item>
        )}
      />
    </Card>
  );
};

/**
 * Main ExecutionPlanViewer Component
 *
 * Displays complete execution plan viewer with:
 * - Progress overview
 * - Steps list
 * - Reflections
 * - Adjustments
 */
export const ExecutionPlanViewer: React.FC<ExecutionPlanViewerProps> = ({ plan }) => {
   
  usePlanModeEvents({});

  // Create empty reflections and adjustments arrays
  const reflections: ReflectionResult[] = [];
  const adjustments: PlanAdjustment[] = [];
  void adjustments; // Mark as intentionally unused for now

  // Loading state
  if (!plan) {
    return (
      <Card>
        <div className="text-center py-8">
          <Spin />
          <div className="mt-2">Loading plan...</div>
        </div>
      </Card>
    );
  }

  // Empty state
  if (plan.steps.length === 0) {
    return (
      <Card>
        <Empty description="No steps in this plan" />
      </Card>
    );
  }

  return (
    <div className="execution-plan-viewer">
      {/* Progress Overview */}
      <PlanProgressCard plan={plan} />

      {/* Steps List */}
      <Card title="Steps" size="small" className="mb-4">
        <div role="list">
          {plan.steps.map((step) => (
            <StepItem key={step.step_id} step={step} />
          ))}
        </div>
      </Card>

      {/* Reflections */}
      {reflections.length > 0 && (
        <Card title="Reflections" size="small" className="mb-4">
          {reflections.map((reflection: ReflectionResult) => (
            <ReflectionCard key={reflection.id} reflection={reflection} />
          ))}
        </Card>
      )}

      {/* Adjustments */}
      <AdjustmentsList adjustments={[]} />

      {/* Execution Statistics */}
      {plan.started_at && (
        <Card size="small" className="mt-4" title="Execution Statistics">
          <Space direction="vertical" className="w-full" size="small">
            <Text className="text-xs">
              <Text strong>Duration:</Text>{" "}
              {plan.completed_at
                ? `${Math.round((new Date(plan.completed_at).getTime() - new Date(plan.started_at).getTime()) / 1000)}s`
                : "Running..."}
            </Text>
            <Text type="secondary" className="text-xs">
              Started: {new Date(plan.started_at).toLocaleString()}
            </Text>
            {plan.completed_at && (
              <Text type="secondary" className="text-xs">
                Completed at: {new Date(plan.completed_at).toLocaleString()}
              </Text>
            )}
            {plan.error && (
              <Text type="danger" className="text-xs">
                Error: {plan.error}
              </Text>
            )}
          </Space>
        </Card>
      )}
    </div>
  );
};

export default ExecutionPlanViewer;
