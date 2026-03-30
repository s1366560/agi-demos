import type { FC } from 'react';

import { Drawer, Progress, Space, Tag, Typography, Divider, Empty, Timeline } from 'antd';
import { Minimize2, Clock, Zap, Database, CheckCircle } from 'lucide-react';

import { useThemeColors, resolveThemeColor } from '@/hooks/useThemeColor';

import {
  useContextStatus,
  useContextDetailExpanded,
  useContextActions,
} from '../../../stores/contextStore';

import type { CompressionRecord, TokenDistribution } from '../../../stores/contextStore';

const { Text, Title } = Typography;

function formatTokens(tokens: number): string {
  if (tokens >= 1000000) return `${(tokens / 1000000).toFixed(1)}M`;
  if (tokens >= 1000) return `${(tokens / 1000).toFixed(1)}K`;
  return String(tokens);
}

function getOccupancyColor(pct: number): string {
  if (pct < 60) return resolveThemeColor('--color-success', '#52c41a');
  if (pct < 80) return resolveThemeColor('--color-warning', '#faad14');
  if (pct < 90) return resolveThemeColor('--color-warning-dark', '#fa8c16');
  return resolveThemeColor('--color-error', '#f5222d');
}

const levelDescriptions: Record<string, string> = {
  none: 'No compression active. Context usage is within normal range.',
  l1_prune: 'Old tool outputs are being pruned to reclaim space.',
  l2_summarize: 'Historical messages are being incrementally summarized.',
  l3_deep_compress: 'Full context distillation active. Maximum compression.',
};

const TokenDistributionBar: FC<{ distribution: TokenDistribution }> = ({ distribution }) => {
  const tc = useThemeColors({
    info: '--color-info',
    success: '--color-success',
    purple: '--color-tile-purple',
    warning: '--color-warning-dark',
    cyan: '--color-tile-cyan',
    muted: '--color-text-muted',
    mutedLight: '--color-text-muted-light',
  });

  const total =
    distribution.system +
    distribution.user +
    distribution.assistant +
    distribution.tool +
    distribution.summary;
  if (total === 0)
    return <Empty description="No token data" image={Empty.PRESENTED_IMAGE_SIMPLE} />;

  const segments = [
    { key: 'system', label: 'System', color: tc.info, value: distribution.system },
    { key: 'user', label: 'User', color: tc.success, value: distribution.user },
    { key: 'assistant', label: 'Assistant', color: tc.purple, value: distribution.assistant },
    { key: 'tool', label: 'Tool', color: tc.warning, value: distribution.tool },
    { key: 'summary', label: 'Summary', color: tc.cyan, value: distribution.summary },
  ].filter((s) => s.value > 0);

  return (
    <div>
      <div
        style={{
          display: 'flex',
          height: 20,
          borderRadius: 4,
          overflow: 'hidden',
          marginBottom: 8,
        }}
      >
        {segments.map((seg) => (
          <div
            key={seg.key}
            style={{
              width: `${(seg.value / total) * 100}%`,
              backgroundColor: seg.color,
              minWidth: seg.value > 0 ? 2 : 0,
              transition: 'width 0.3s ease',
            }}
          />
        ))}
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 12px', fontSize: 12 }}>
        {segments.map((seg) => (
          <span key={seg.key} style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
            <span
              style={{
                width: 8,
                height: 8,
                borderRadius: 2,
                backgroundColor: seg.color,
                display: 'inline-block',
              }}
            />
            <span style={{ color: tc.muted }}>{seg.label}</span>
            <span style={{ fontWeight: 500, fontVariantNumeric: 'tabular-nums' }}>
              {formatTokens(seg.value)}
            </span>
            <span style={{ color: tc.mutedLight }}>
              ({((seg.value / total) * 100).toFixed(0)}%)
            </span>
          </span>
        ))}
      </div>
    </div>
  );
};

const CompressionTimeline: FC<{ records: CompressionRecord[] }> = ({ records }) => {
  if (records.length === 0) {
    return <Empty description="No compression events yet" image={Empty.PRESENTED_IMAGE_SIMPLE} />;
  }

  const items = records.map((record) => {
    const time = new Date(record.timestamp).toLocaleTimeString();
    return {
      key: record.timestamp,
      icon: <Minimize2 size={14} />,
      color: record.level.includes('l3') ? 'red' : record.level.includes('l2') ? 'orange' : 'blue',
      content: (
        <div style={{ fontSize: 12, lineHeight: 1.6 }}>
          <div>
            <Text strong>{record.level.toUpperCase()}</Text>
            <Text type="secondary" style={{ marginLeft: 8 }}>
              {time}
            </Text>
          </div>
          <Space size={12} wrap>
            <span>
              <Zap size={16} className="mr-1 inline-block align-text-bottom" /> Saved {formatTokens(record.tokens_saved)} tokens (
              {record.savings_pct.toFixed(0)}%)
            </span>
            <span>
              <Clock size={16} className="mr-1 inline-block align-text-bottom" /> {record.duration_ms.toFixed(0)}ms
            </span>
            <span>
              Messages: {record.messages_before} → {record.messages_after}
            </span>
          </Space>
        </div>
      ),
    };
  });

  return <Timeline items={items} />;
};

export const ContextDetailPanel: FC = () => {
  const status = useContextStatus();
  const expanded = useContextDetailExpanded();
  const { setDetailExpanded } = useContextActions();

  const tc = useThemeColors({
    muted: '--color-text-muted',
    success: '--color-success',
    info: '--color-info',
    warningDark: '--color-warning-dark',
    purple: '--color-tile-purple',
  });

  const occupancy = status?.occupancyPct ?? 0;
  const currentTokens = status?.currentTokens ?? 0;
  const tokenBudget = status?.tokenBudget ?? 128000;
  const compressionLevel = status?.compressionLevel ?? 'none';
  const history = status?.compressionHistory;
  const distribution = status?.tokenDistribution;

  return (
    <Drawer
      title={
        <Space>
          <Database size={16} />
          <span>Context Monitor</span>
        </Space>
      }
      placement="right"
      size="default"
      open={expanded}
      onClose={() => {
        setDetailExpanded(false);
      }}
      styles={{ body: { padding: '16px 20px' } }}
    >
      {/* Overall Usage */}
      <div style={{ marginBottom: 24 }}>
        <Title level={5} style={{ marginBottom: 12 }}>
          Context Usage
        </Title>
        <div style={{ textAlign: 'center', marginBottom: 8 }}>
          <Progress
            type="dashboard"
            percent={Math.min(occupancy, 100)}
            strokeColor={getOccupancyColor(occupancy)}
            format={() => (
              <div>
                <div style={{ fontSize: 20, fontWeight: 600, fontVariantNumeric: 'tabular-nums' }}>
                  {occupancy.toFixed(1)}%
                </div>
                <div style={{ fontSize: 11, color: tc.muted }}>
                  {formatTokens(currentTokens)} / {formatTokens(tokenBudget)}
                </div>
              </div>
            )}
            size={140}
          />
        </div>
        <div style={{ textAlign: 'center' }}>
          <Tag
            color={
              compressionLevel === 'none'
                ? 'green'
                : compressionLevel.includes('l3')
                  ? 'red'
                  : compressionLevel.includes('l2')
                    ? 'orange'
                    : 'gold'
            }
            icon={compressionLevel === 'none' ? <CheckCircle size={16} /> : <Minimize2 size={16} />}
          >
            {levelDescriptions[compressionLevel]
              ? compressionLevel.replace('l', 'L').replace('_', ' ')
              : compressionLevel}
          </Tag>
        </div>
        <div style={{ fontSize: 12, color: tc.muted, textAlign: 'center', marginTop: 6 }}>
          {levelDescriptions[compressionLevel] ?? ''}
        </div>
      </div>

      <Divider style={{ margin: '16px 0' }} />

      {/* Token Distribution */}
      <div style={{ marginBottom: 24 }}>
        <Title level={5} style={{ marginBottom: 12 }}>
          Token Distribution
        </Title>
        {distribution ? (
          <TokenDistributionBar distribution={distribution} />
        ) : (
          <Empty description="No data" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        )}
      </div>

      <Divider style={{ margin: '16px 0' }} />

      {/* Compression Stats */}
      {history && history.total_compressions > 0 && (
        <div style={{ marginBottom: 24 }}>
          <Title level={5} style={{ marginBottom: 12 }}>
            Compression Summary
          </Title>
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: '1fr 1fr',
              gap: 12,
              marginBottom: 16,
            }}
          >
            <div
              style={{
                background: tc.success + '1a',
                borderRadius: 8,
                padding: '8px 12px',
                textAlign: 'center',
              }}
            >
              <div style={{ fontSize: 18, fontWeight: 600, color: tc.success }}>
                {formatTokens(history.total_tokens_saved)}
              </div>
              <div style={{ fontSize: 11, color: tc.muted }}>Tokens Saved</div>
            </div>
            <div
              style={{
                background: tc.info + '1a',
                borderRadius: 8,
                padding: '8px 12px',
                textAlign: 'center',
              }}
            >
              <div style={{ fontSize: 18, fontWeight: 600, color: tc.info }}>
                {history.total_compressions}
              </div>
              <div style={{ fontSize: 11, color: tc.muted }}>Compressions</div>
            </div>
            <div
              style={{
                background: tc.warningDark + '1a',
                borderRadius: 8,
                padding: '8px 12px',
                textAlign: 'center',
              }}
            >
              <div style={{ fontSize: 18, fontWeight: 600, color: tc.warningDark }}>
                {(history.average_compression_ratio * 100).toFixed(0)}%
              </div>
              <div style={{ fontSize: 11, color: tc.muted }}>Avg Ratio</div>
            </div>
            <div
              style={{
                background: tc.purple + '1a',
                borderRadius: 8,
                padding: '8px 12px',
                textAlign: 'center',
              }}
            >
              <div style={{ fontSize: 18, fontWeight: 600, color: tc.purple }}>
                {history.average_savings_pct.toFixed(0)}%
              </div>
              <div style={{ fontSize: 11, color: tc.muted }}>Avg Savings</div>
            </div>
          </div>
        </div>
      )}

      <Divider style={{ margin: '16px 0' }} />

      {/* Compression History Timeline */}
      <div>
        <Title level={5} style={{ marginBottom: 12 }}>
          Compression History
        </Title>
        <CompressionTimeline records={history?.recent_records ?? []} />
      </div>
    </Drawer>
  );
};
