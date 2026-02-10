/**
 * PlanModeViewer Component
 *
 * Displays detailed view of an ExecutionPlan with all steps,
 * their status, and reflection results.
 *
 * Part of Plan Mode UI.
 */

import React, { useMemo } from 'react';

import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  LoadingOutlined,
  ClockCircleOutlined,
  MinusCircleOutlined,
  StopOutlined,
} from '@ant-design/icons';
import { Typography, Card, Tag, Space, Collapse, Alert, Descriptions, Badge } from 'antd';

import { formatDateTime, formatTimeOnly } from '@/utils/date';

import {
  ExecutionPlan,
  ExecutionStep,
  ExecutionStepStatus,
  ReflectionResult,
} from '../../types/agent';

const { Title, Text, Paragraph } = Typography;
const { Panel } = Collapse;

interface PlanModeViewerProps {
  plan: ExecutionPlan | null;
  reflection?: ReflectionResult | null;
  className?: string;
}

/**
 * Get icon for step status
 */
const getStepIcon = (status: ExecutionStepStatus) => {
  switch (status) {
    case 'completed':
      return <CheckCircleOutlined className="text-emerald-500" />;
    case 'failed':
      return <CloseCircleOutlined className="text-red-500" />;
    case 'running':
      return <LoadingOutlined className="text-blue-500" />;
    case 'skipped':
      return <MinusCircleOutlined className="text-slate-400" />;
    case 'cancelled':
      return <StopOutlined className="text-slate-400" />;
    default:
      return <ClockCircleOutlined className="text-slate-300" />;
  }
};

/**
 * Get color for step status
 */
const getStepColor = (status: ExecutionStepStatus): string => {
  switch (status) {
    case 'completed':
      return 'success';
    case 'failed':
      return 'error';
    case 'running':
      return 'processing';
    case 'skipped':
      return 'default';
    case 'cancelled':
      return 'warning';
    default:
      return 'default';
  }
};

/**
 * Get status text for step
 */
const getStepStatusText = (status: ExecutionStepStatus): string => {
  switch (status) {
    case 'pending':
      return 'Pending';
    case 'running':
      return 'Running';
    case 'completed':
      return 'Completed';
    case 'failed':
      return 'Failed';
    case 'skipped':
      return 'Skipped';
    case 'cancelled':
      return 'Cancelled';
    default:
      return 'Unknown';
  }
};

/**
 * Single step display component
 */
interface StepDisplayProps {
  step: ExecutionStep;
  index: number;
}

const StepDisplay: React.FC<StepDisplayProps> = ({ step, index }) => {
  const hasResult = step.result && step.result.length > 0;
  const hasError = step.error && step.error.length > 0;
  const hasDependencies = step.dependencies && step.dependencies.length > 0;

  return (
    <Card size="small" className="mb-2">
      <div className="flex items-start gap-3">
        <div className="mt-1">{getStepIcon(step.status)}</div>

        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between mb-1">
            <Space>
              <Text strong>Step {index + 1}</Text>
              <Tag color={getStepColor(step.status) as any}>{getStepStatusText(step.status)}</Tag>
              <Text type="secondary" className="text-xs">
                {step.tool_name}
              </Text>
            </Space>

            {step.step_id && (
              <Text type="secondary" className="text-xs">
                {step.step_id.slice(0, 8)}
              </Text>
            )}
          </div>

          <Paragraph className="mb-2 text-sm">{step.description}</Paragraph>

          {hasDependencies && (
            <div className="mb-2">
              <Text type="secondary" className="text-xs">
                Dependencies: {step.dependencies.join(', ')}
              </Text>
            </div>
          )}

          {step.started_at && (
            <Text type="secondary" className="text-xs block">
              Started: {formatTimeOnly(step.started_at)}
            </Text>
          )}

          {hasResult && (
            <Alert
              type="success"
              message="Result"
              description={
                <Text className="text-xs" ellipsis={{ tooltip: step.result }}>
                  {step.result}
                </Text>
              }
              className="mt-2"
              banner
            />
          )}

          {hasError && (
            <Alert
              type="error"
              message="Error"
              description={
                <Text className="text-xs" ellipsis={{ tooltip: step.error }}>
                  {step.error}
                </Text>
              }
              className="mt-2"
              banner
            />
          )}
        </div>
      </div>
    </Card>
  );
};

export const PlanModeViewer: React.FC<PlanModeViewerProps> = ({
  plan,
  reflection,
  className = '',
}) => {
  const { sortedSteps, reflectionBadge, reflectionSummary } = useMemo(() => {
    if (!plan) {
      return { sortedSteps: [], reflectionBadge: null, reflectionSummary: null };
    }

    // Sort steps by dependencies (topological-ish)
    const sortedSteps = [...plan.steps].sort((a, b) => {
      const aHasDepOnB = a.dependencies.includes(b.step_id);
      const bHasDepOnA = b.dependencies.includes(a.step_id);

      if (aHasDepOnB && !bHasDepOnA) return 1;
      if (bHasDepOnA && !aHasDepOnB) return -1;
      return 0;
    });

    let reflectionBadge = null;
    let reflectionSummary = null;

    if (reflection) {
      const assessmentColors: Record<string, string> = {
        on_track: 'success',
        needs_adjustment: 'warning',
        off_track: 'error',
        complete: 'success',
        failed: 'error',
      };

      reflectionBadge = (
        <Badge
          status={assessmentColors[reflection.assessment] as any}
          text={reflection.assessment.replace(/_/g, ' ')}
        />
      );

      reflectionSummary = (
        <Alert
          type={
            reflection.assessment === 'on_track' || reflection.assessment === 'complete'
              ? 'success'
              : 'warning'
          }
          message={reflection.assessment.replace(/_/g, ' ').toUpperCase()}
          description={reflection.reasoning}
          className="mb-4"
        />
      );
    }

    return { sortedSteps, reflectionBadge, reflectionSummary };
  }, [plan, reflection]);

  if (!plan) {
    return (
      <div className={`p-8 text-center text-slate-400 ${className}`}>
        <p>No execution plan available</p>
      </div>
    );
  }

  return (
    <div className={className}>
      {/* Header */}
      <div className="mb-4 pb-4 border-b border-slate-200">
        <div className="flex items-center justify-between mb-2">
          <Title level={5} className="!m-0">
            Execution Plan
          </Title>
          <Space>
            <Tag color="blue">{plan.status}</Tag>
            {reflectionBadge}
          </Space>
        </div>

        <Descriptions size="small" column={2}>
          <Descriptions.Item label="Plan ID">{plan.id.slice(0, 8)}...</Descriptions.Item>
          <Descriptions.Item label="Total Steps">{plan.steps.length}</Descriptions.Item>
          <Descriptions.Item label="Completed">{plan.completed_steps.length}</Descriptions.Item>
          <Descriptions.Item label="Failed">{plan.failed_steps.length}</Descriptions.Item>
          <Descriptions.Item label="Reflection">
            {plan.reflection_enabled ? 'Enabled' : 'Disabled'}
          </Descriptions.Item>
          <Descriptions.Item label="Max Cycles">{plan.max_reflection_cycles}</Descriptions.Item>
        </Descriptions>

        <Text type="secondary" className="text-xs block mt-2">
          Query: {plan.user_query}
        </Text>
      </div>

      {/* Reflection Summary */}
      {reflectionSummary}

      {/* Steps */}
      <div className="mt-4">
        <Title level={5} className="!mb-3">
          Steps ({plan.steps.length})
        </Title>

        {sortedSteps.length === 0 ? (
          <Text type="secondary">No steps in this plan</Text>
        ) : (
          <Collapse defaultActiveKey={[]} ghost>
            {sortedSteps.map((step, index) => (
              <Panel
                header={
                  <div className="flex items-center gap-2 pr-4">
                    {getStepIcon(step.status)}
                    <span>
                      Step {index + 1}: {step.description}
                    </span>
                    <Tag color={getStepColor(step.status) as any} className="ml-auto">
                      {getStepStatusText(step.status)}
                    </Tag>
                  </div>
                }
                key={step.step_id}
              >
                <StepDisplay step={step} index={index} />
              </Panel>
            ))}
          </Collapse>
        )}
      </div>

      {/* Footer */}
      {plan.started_at && (
        <div className="mt-4 pt-4 border-t border-slate-200 text-xs text-slate-500">
          Started: {formatDateTime(plan.started_at)}
          {plan.completed_at && (
            <span className="ml-4">Completed: {formatDateTime(plan.completed_at)}</span>
          )}
        </div>
      )}
    </div>
  );
};

export default PlanModeViewer;
