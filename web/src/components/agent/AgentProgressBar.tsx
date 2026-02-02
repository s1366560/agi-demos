/**
 * AgentProgressBar component (T050)
 *
 * Displays the overall progress of agent execution,
 * including work plan steps and current execution status.
 */

import React from 'react'
import { LazyProgress, LazySpace, Typography } from '@/components/ui/lazyAntd'
import {
  CheckCircleOutlined,
  LoadingOutlined,
  CloseCircleOutlined,
  ClockCircleOutlined,
  ThunderboltFilled,
} from '@ant-design/icons'

const { Text } = Typography

interface AgentProgressBarProps {
  current: number
  total: number
  status: 'thinking' | 'work_planning' | 'step_executing' | 'acting' | 'observing' | 'completed' | 'failed'
  label?: string
  estimatedTimeRemaining?: string
  showSteps?: boolean
  compact?: boolean
  animate?: boolean
}

const statusConfig: Record<
  AgentProgressBarProps['status'],
  { color: string; icon: React.ReactNode; label: string; class: string }
> = {
  thinking: { color: 'default', icon: <ClockCircleOutlined />, label: 'Thinking', class: 'status-thinking' },
  work_planning: { color: 'purple', icon: <ThunderboltFilled />, label: 'Planning', class: 'status-planning' },
  step_executing: { color: 'blue', icon: <LoadingOutlined />, label: 'Executing', class: 'status-running' },
  acting: { color: 'orange', icon: <LoadingOutlined />, label: 'Acting', class: 'status-running' },
  observing: { color: 'cyan', icon: <LoadingOutlined />, label: 'Observing', class: 'status-running' },
  completed: { color: 'success', icon: <CheckCircleOutlined />, label: 'Completed', class: 'status-completed' },
  failed: { color: 'exception', icon: <CloseCircleOutlined />, label: 'Failed', class: 'status-failed' },
}

const getPercentage = (current: number, total: number): number => {
  if (total === 0) return 0
  if (current > total) return 100
  return Math.round((current / total) * 100)
}

export const AgentProgressBar: React.FC<AgentProgressBarProps> = ({
  current,
  total,
  status,
  label: customLabel,
  estimatedTimeRemaining,
  showSteps = false,
  compact = false,
  animate = false,
}) => {
  const config = statusConfig[status]
  const percentage = getPercentage(current, total)
  const displayLabel = customLabel || config.label

  // Step indicators (dots)
  const stepIndicators = showSteps && !compact ? (
    <LazySpace size={4}>
      {Array.from({ length: total }).map((_, index) => {
        const stepNumber = index + 1
        let stepClass = 'step-dot-pending'
        let testId = 'pending-dot'

        if (stepNumber < current) {
          stepClass = 'step-dot-completed'
          testId = 'completed-dot'
        } else if (stepNumber === current) {
          stepClass = 'step-dot-current'
          testId = 'current-dot'
        }

        return (
          <div
            key={index}
            data-testid={testId}
            data-step-dot={stepNumber <= current ? 'completed' : 'pending'}
            className={stepClass}
            style={{
              width: 12,
              height: 12,
              borderRadius: '50%',
              backgroundColor:
                stepNumber < current ? '#52c41a' :
                stepNumber === current ? '#1890ff' :
                '#d9d9d9',
              border: stepNumber === current ? '2px solid #1890ff' : undefined,
            }}
          />
        )
      })}
    </LazySpace>
  ) : null

  return (
    <div
      data-testid="agent-progress-bar"
      role="progressbar"
      aria-valuenow={current}
      aria-valuemin={0}
      aria-valuemax={total}
      aria-live="polite"
      className={`agent-progress-bar ${compact ? 'compact' : ''}`}
    >
      <LazySpace orientation="vertical" size="small" style={{ width: '100%' }}>
        {/* Label and Step Indicators */}
        <LazySpace style={{ width: '100%', justifyContent: 'space-between' }}>
          <LazySpace>
            {config.icon}
            <Text strong>{displayLabel}</Text>
            {estimatedTimeRemaining && (
              <Text type="secondary" style={{ fontSize: 11 }}>
                (~{estimatedTimeRemaining} remaining)
              </Text>
            )}
          </LazySpace>

          {!compact && (
            <LazySpace>
              <Text type="secondary">
                {current} / {total}
              </Text>
              <Text strong>{percentage}%</Text>
            </LazySpace>
          )}
        </LazySpace>

        {/* Progress Bar */}
        <LazyProgress
          percent={percentage}
          status={status === 'failed' ? 'exception' : status === 'completed' ? 'success' : 'active'}
          size="small"
          strokeColor={{
            '0%': status === 'failed' ? '#ff4d4f' : status === 'completed' ? '#52c41a' : '#1890ff',
            '100%': status === 'failed' ? '#ff7875' : status === 'completed' ? '#73d13d' : '#40a9ff',
          }}
          className={`progress-fill ${config.class} ${animate ? 'animate-progress' : ''} ${status === 'step_executing' || status === 'acting' ? 'progress-striped' : ''}`}
          style={{ marginBottom: showSteps && !compact ? 8 : 0 }}
        />

        {/* Step Indicators */}
        {stepIndicators}
      </LazySpace>
    </div>
  )
}
