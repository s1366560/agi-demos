/**
 * CostTracker Component
 *
 * Displays real-time cost tracking information for the current conversation.
 * Shows token usage and estimated cost.
 */

import React from 'react';

import { DollarOutlined, ThunderboltOutlined } from '@ant-design/icons';

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
  if (!costTracking) {
    return null;
  }

  return (
    <Tooltip
      title={
        <Space direction="vertical" size={4}>
          <div>输入 Tokens: {costTracking.inputTokens.toLocaleString()}</div>
          <div>输出 Tokens: {costTracking.outputTokens.toLocaleString()}</div>
          <div>总计: {costTracking.totalTokens.toLocaleString()}</div>
          <div>费用: {formatCost(costTracking.costUsd)}</div>
          {showModel && <div>模型: {costTracking.model}</div>}
        </Space>
      }
    >
      <Space size={4} style={{ cursor: 'help' }}>
        <ThunderboltOutlined style={{ color: '#faad14', fontSize: 12 }} />
        <Text type="secondary" style={{ fontSize: 12 }}>
          {formatTokenCount(costTracking.totalTokens)}
        </Text>
        <DollarOutlined style={{ color: '#52c41a', fontSize: 12 }} />
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
  if (!costTracking) {
    return (
      <div style={{ padding: '8px 12px', color: '#999' }}>
        <Text type="secondary">暂无费用数据</Text>
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
            <Text type="secondary">模型：</Text>
            <Text strong>{costTracking.model}</Text>
          </div>
        )}

        {/* Token Bar */}
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
            <Text type="secondary">Token 使用</Text>
            <Text>{costTracking.totalTokens.toLocaleString()}</Text>
          </div>
          <Progress
            percent={100}
            success={{ percent: inputPercent }}
            showInfo={false}
            size="small"
            strokeColor="#1890ff"
            trailColor="#f0f0f0"
          />
          <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 4 }}>
            <Space size={16}>
              <Text type="secondary" style={{ fontSize: 12 }}>
                <span style={{ color: '#52c41a' }}>●</span> 输入:{' '}
                {formatTokenCount(costTracking.inputTokens)}
              </Text>
              <Text type="secondary" style={{ fontSize: 12 }}>
                <span style={{ color: '#1890ff' }}>●</span> 输出:{' '}
                {formatTokenCount(costTracking.outputTokens)}
              </Text>
            </Space>
          </div>
        </div>

        {/* Cost */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Text type="secondary">估算费用</Text>
          <Text strong style={{ fontSize: 16, color: '#52c41a' }}>
            {formatCost(costTracking.costUsd)}
          </Text>
        </div>

        {/* Last Updated */}
        <Text type="secondary" style={{ fontSize: 11 }}>
          更新于: {formatTimeOnly(costTracking.lastUpdated)}
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
