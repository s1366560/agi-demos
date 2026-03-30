/**
 * SkillExecutionCard component
 *
 * Displays skill execution progress including matched skill,
 * execution mode, tool chain progress, and results.
 *
 * Part of L2 Skill Layer visualization.
 */

import React, { memo } from 'react';

import { Card, Typography, Space, Tag, Progress, Steps, Tooltip } from 'antd';
import { AlertTriangle, CheckCircle2, Edit, Loader2, Rocket, XCircle, Zap } from 'lucide-react';


import { formatTimeOnly } from '@/utils/date';

import type { SkillExecutionState, SkillToolExecution } from '../../types/agent';

const { Text } = Typography;

interface SkillExecutionCardProps {
  skillExecution: SkillExecutionState;
}

const formatDuration = (ms: number): string => {
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
};

const getStatusConfig = (status: SkillExecutionState['status']) => {
  const configs = {
    matched: {
      icon: <Zap size={16} />,
      label: 'Matched',
      color: 'blue',
      bgClass: 'bg-blue-50',
      borderClass: 'border-blue-300',
    },
    executing: {
      icon: <Loader2 className="animate-spin" size={16} />,
      label: 'Executing',
      color: 'processing',
      bgClass: 'bg-blue-50',
      borderClass: 'border-blue-300',
    },
    completed: {
      icon: <CheckCircle2 size={16} />,
      label: 'Completed',
      color: 'success',
      bgClass: 'bg-green-50',
      borderClass: 'border-green-300',
    },
    failed: {
      icon: <XCircle size={16} />,
      label: 'Failed',
      color: 'error',
      bgClass: 'bg-red-50',
      borderClass: 'border-red-200',
    },
    fallback: {
      icon: <AlertTriangle size={16} />,
      label: 'Fallback to LLM',
      color: 'warning',
      bgClass: 'bg-yellow-50',
      borderClass: 'border-yellow-300',
    },
  };
  return configs[status] || configs.executing;
};

const getToolStepStatus = (
  toolExec: SkillToolExecution
): 'wait' | 'process' | 'finish' | 'error' => {
  switch (toolExec.status) {
    case 'running':
      return 'process';
    case 'completed':
      return 'finish';
    case 'error':
      return 'error';
    default:
      return 'wait';
  }
};

const getModeIcon = (mode: 'direct' | 'prompt') => {
  if (mode === 'direct') {
    return (
      <Tooltip title="Direct execution - bypassing LLM">
        <Rocket className="text-blue-500" size={16} />
      </Tooltip>
    );
  }
  return (
    <Tooltip title="Prompt injection - guided by LLM">
      <Edit className="text-green-500" size={16} />
    </Tooltip>
  );
};

export const SkillExecutionCard: React.FC<SkillExecutionCardProps> = ({ skillExecution }) => {
  const statusConfig = getStatusConfig(skillExecution.status);
  const progressPercent =
    skillExecution.total_steps > 0
      ? Math.round((skillExecution.current_step / skillExecution.total_steps) * 100)
      : 0;

  // Build steps items for the Steps component
  const stepsItems = skillExecution.tools.map((toolName, index) => {
    const toolExec = skillExecution.tool_executions.find((te) => te.step_index === index);

    let status: 'wait' | 'process' | 'finish' | 'error' = 'wait';
    let description: React.ReactNode = null;

    if (toolExec) {
      status = getToolStepStatus(toolExec);
      if (toolExec.duration_ms) {
        description = (
          <Text type="secondary" style={{ fontSize: 10 }}>
            {formatDuration(toolExec.duration_ms)}
          </Text>
        );
      }
      if (toolExec.error) {
        description = (
          <Text type="danger" style={{ fontSize: 10 }}>
            {toolExec.error.substring(0, 50)}...
          </Text>
        );
      }
    }

    return {
      title: toolName,
      status,
      description,
    };
  });

  return (
    <Card
      data-testid="skill-execution-card"
      size="small"
      className={`skill-execution-card status-${skillExecution.status} ${statusConfig.bgClass} border border-solid ${statusConfig.borderClass}`}
      style={{
        marginBottom: 8,
      }}
      aria-label={`Skill execution: ${skillExecution.skill_name}`}
    >
      <Space direction="vertical" size="small" style={{ width: '100%' }}>
        {/* Header */}
        <Space style={{ width: '100%', justifyContent: 'space-between' }}>
          <Space>
            <Zap className="text-yellow-500" size={16} />
            <Text strong>{skillExecution.skill_name}</Text>
            {getModeIcon(skillExecution.execution_mode)}
            <Tag
              icon={statusConfig.icon}
              color={statusConfig.color}
              data-testid="skill-status-indicator"
            >
              {statusConfig.label}
            </Tag>
          </Space>
          <Space>
            <Tooltip title="Match confidence">
              <Tag color="purple">{(skillExecution.match_score * 100).toFixed(0)}%</Tag>
            </Tooltip>
          </Space>
        </Space>

        {/* Progress Bar (for executing state) */}
        {skillExecution.status === 'executing' && (
          <Progress
            percent={progressPercent}
            size="small"
            status="active"
            format={() => `${skillExecution.current_step}/${skillExecution.total_steps}`}
          />
        )}

        {/* Tool Chain Steps */}
        {skillExecution.tool_executions.length > 0 && (
          <div style={{ marginTop: 8 }}>
            <Text type="secondary" style={{ fontSize: 11, marginBottom: 4 }}>
              Tool Chain:
            </Text>
            <Steps
              size="small"
              current={skillExecution.current_step}
              items={stepsItems}
              style={{ marginTop: 4 }}
            />
          </div>
        )}

        {/* Tools list (when no executions yet) */}
        {skillExecution.tool_executions.length === 0 && skillExecution.tools.length > 0 && (
          <div>
            <Text type="secondary" style={{ fontSize: 11 }}>
              Tools:{' '}
            </Text>
            <Space wrap size={4}>
              {skillExecution.tools.map((tool) => (
                <Tag key={tool} style={{ fontSize: 10 }}>
                  {tool}
                </Tag>
              ))}
            </Space>
          </div>
        )}

        {/* Summary (when completed) */}
        {skillExecution.summary && (
          <div
            className="bg-neutral-50"
            style={{
              padding: 8,
              borderRadius: 4,
              marginTop: 4,
            }}
          >
            <Text type="secondary" style={{ fontSize: 11 }}>
              Summary:
            </Text>
            <div style={{ marginTop: 2 }}>
              <Text style={{ fontSize: 12 }}>{skillExecution.summary}</Text>
            </div>
          </div>
        )}

        {/* Error (when failed or fallback) */}
        {skillExecution.error && (
          <div
            className="bg-red-50"
            style={{
              padding: 8,
              borderRadius: 4,
              marginTop: 4,
            }}
          >
            <Text type="danger" style={{ fontSize: 11 }}>
              {skillExecution.error}
            </Text>
          </div>
        )}

        {/* Metadata */}
        <Space wrap style={{ marginTop: 4 }}>
          {skillExecution.execution_time_ms && (
            <Text type="secondary" style={{ fontSize: 10 }}>
              Duration: {formatDuration(skillExecution.execution_time_ms)}
            </Text>
          )}
          {skillExecution.started_at && (
            <Text type="secondary" style={{ fontSize: 10 }}>
              Started: {formatTimeOnly(skillExecution.started_at)}
            </Text>
          )}
        </Space>
      </Space>
    </Card>
  );
};

export default memo(SkillExecutionCard);
