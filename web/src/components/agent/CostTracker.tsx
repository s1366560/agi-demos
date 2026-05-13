/**
 * CostTracker Component
 *
 * Displays real-time cost tracking information for the current conversation.
 * Shows token usage and estimated cost.
 */

import React from 'react';

import { useTranslation } from 'react-i18next';

import { DollarSign, Zap } from 'lucide-react';


import { useThemeColors } from '@/hooks/useThemeColor';

import { formatTimeOnly } from '@/utils/date';

import { Typography, Space, Tooltip, Progress } from '@/components/ui/lazyAntd';

import type { CostTrackingState } from '../../types/conversationState';

const { Text } = Typography;

interface CostTrackerProps {
  costTracking: CostTrackingState | null;
  compact?: boolean | undefined;
  showModel?: boolean | undefined;
}

/**
 * Format number with K/M suffix
 */
function formatTokenCount(count: number): string {
  if (count >= 1_000_000) {
    return `${(count / 1_000_000).toFixed(1)}M`;
  }
  if (count >= 1_000) {
    return `${(count / 1_000).toFixed(1)}K`;
  }
  return count.toString();
}

/**
 * Format cost with appropriate precision
 */
function formatCost(cost: number): string {
  if (cost < 0.001) {
    return `$${cost.toFixed(6)}`;
  }
  if (cost < 0.01) {
    return `$${cost.toFixed(4)}`;
  }
  return `$${cost.toFixed(3)}`;
}

/**
 * Compact cost display for status bar
 */
export const CostTrackerCompact: React.FC<CostTrackerProps> = ({
  costTracking,
  showModel = false,
}) => {
  const { t } = useTranslation();
  const colors = useThemeColors({
    warning: '--color-warning',
    success: '--color-success',
  });

  if (!costTracking) {
    return null;
  }

  return (
    <Tooltip
      title={
        <Space direction="vertical" size={4}>
          <div>{t('agent.costTracker.inputTokens', { value: costTracking.inputTokens.toLocaleString() })}</div>
          <div>{t('agent.costTracker.outputTokens', { value: costTracking.outputTokens.toLocaleString() })}</div>
          <div>{t('agent.costTracker.totalTokens', { value: costTracking.totalTokens.toLocaleString() })}</div>
          <div>{t('agent.costTracker.costLabel', { value: formatCost(costTracking.costUsd) })}</div>
          {showModel && <div>{t('agent.costTracker.modelLabel', { model: costTracking.model })}</div>}
        </Space>
      }
    >
      <Space size={4} style={{ cursor: 'help' }}>
        <Zap style={{ color: colors.warning}} size={12} />
        <Text type="secondary" style={{ fontSize: 12 }}>
          {formatTokenCount(costTracking.totalTokens)}
        </Text>
        <DollarSign style={{ color: colors.success}} size={12} />
        <Text type="secondary" style={{ fontSize: 12 }}>
          {formatCost(costTracking.costUsd)}
        </Text>
      </Space>
    </Tooltip>
  );
};

/**
 * Full cost display panel
 */
export const CostTrackerPanel: React.FC<CostTrackerProps> = ({
  costTracking,
  showModel = true,
}) => {
  const { t } = useTranslation();
  const colors = useThemeColors({
    muted: '--color-text-muted',
    info: '--color-info',
    success: '--color-success',
    borderDark: '--color-border-dark',
  });

  if (!costTracking) {
    return (
      <div style={{ padding: '8px 12px', color: colors.muted }}>
        <Text type="secondary">{t('agent.costTracker.empty')}</Text>
      </div>
    );
  }

  const inputPercent =
    costTracking.totalTokens > 0 ? (costTracking.inputTokens / costTracking.totalTokens) * 100 : 0;

  return (
    <div style={{ padding: '12px 16px' }}>
      <Space direction="vertical" style={{ width: '100%' }} size="small">
        {/* Model */}
        {showModel && (
          <div>
            <Text type="secondary">{t('agent.costTracker.modelPrefix')}</Text>
            <Text strong>{costTracking.model}</Text>
          </div>
        )}

        {/* Token Bar */}
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
            <Text type="secondary">{t('agent.costTracker.tokenUsage')}</Text>
            <Text>{costTracking.totalTokens.toLocaleString()}</Text>
          </div>
          <Progress
            percent={100}
            success={{ percent: inputPercent }}
            showInfo={false}
            size="small"
            strokeColor={colors.info}
            trailColor={colors.borderDark}
          />
          <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 4 }}>
            <Space size={16}>
              <Text type="secondary" style={{ fontSize: 12 }}>
                <span style={{ color: colors.success }}>●</span> {t('agent.costTracker.inputShort')}{' '}
                {formatTokenCount(costTracking.inputTokens)}
              </Text>
              <Text type="secondary" style={{ fontSize: 12 }}>
                <span style={{ color: colors.info }}>●</span> {t('agent.costTracker.outputShort')}{' '}
                {formatTokenCount(costTracking.outputTokens)}
              </Text>
            </Space>
          </div>
        </div>

        {/* Cost */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Text type="secondary">{t('agent.costTracker.estimatedCost')}</Text>
          <Text strong style={{ fontSize: 16, color: colors.success }}>
            {formatCost(costTracking.costUsd)}
          </Text>
        </div>

        {/* Last Updated */}
        <Text type="secondary" style={{ fontSize: 11 }}>
          {t('agent.costTracker.updatedAt', { time: formatTimeOnly(costTracking.lastUpdated) })}
        </Text>
      </Space>
    </div>
  );
};

/**
 * Default export: Auto-selects based on compact prop
 */
export const CostTracker: React.FC<CostTrackerProps> = (props) => {
  if (props.compact) {
    return <CostTrackerCompact {...props} />;
  }
  return <CostTrackerPanel {...props} />;
};

export default CostTracker;
