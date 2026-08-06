import type { FC } from 'react';

import { useTranslation } from 'react-i18next';

import { Drawer, Progress, Space, Tag, Typography, Divider, Empty, Timeline } from 'antd';
import { Minimize2, Clock, Zap, Database, CheckCircle } from 'lucide-react';

import { useThemeColors, resolveThemeColor } from '@/hooks/useThemeColor';

import {
  useContextStatus,
  useContextDetailExpanded,
  useContextActions,
} from '../../../stores/contextStore';

import type { CompressionRecord, TokenDistribution } from '../../../stores/contextStore';
import type { TFunction } from 'i18next';

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

const levelDescriptionKeys: Record<string, string> = {
  none: 'agent.contextDetail.levels.none',
  l1_prune: 'agent.contextDetail.levels.l1Prune',
  l2_summarize: 'agent.contextDetail.levels.l2Summarize',
  l3_deep_compress: 'agent.contextDetail.levels.l3DeepCompress',
};

const TokenDistributionBar: FC<{ distribution: TokenDistribution; t: TFunction }> = ({
  distribution,
  t,
}) => {
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
    return (
      <Empty
        description={t('agent.contextDetail.empty.noTokenData')}
        image={Empty.PRESENTED_IMAGE_SIMPLE}
      />
    );

  const segments = [
    {
      key: 'system',
      label: t('agent.contextDetail.segments.system'),
      color: tc.info,
      value: distribution.system,
    },
    {
      key: 'user',
      label: t('agent.contextDetail.segments.user'),
      color: tc.success,
      value: distribution.user,
    },
    {
      key: 'assistant',
      label: t('agent.contextDetail.segments.assistant'),
      color: tc.purple,
      value: distribution.assistant,
    },
    {
      key: 'tool',
      label: t('agent.contextDetail.segments.tool'),
      color: tc.warning,
      value: distribution.tool,
    },
    {
      key: 'summary',
      label: t('agent.contextDetail.segments.summary'),
      color: tc.cyan,
      value: distribution.summary,
    },
  ].filter((s) => s.value > 0);

  return (
    <div>
      <div className="mb-2 flex h-5 overflow-hidden rounded">
        {segments.map((seg) => (
          <div
            key={seg.key}
            style={{
              width: `${String((seg.value / total) * 100)}%`,
              backgroundColor: seg.color,
              minWidth: seg.value > 0 ? 2 : 0,
              transition: 'width 0.3s ease',
            }}
          />
        ))}
      </div>
      <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs">
        {segments.map((seg) => (
          <span key={seg.key} className="inline-flex items-center gap-1">
            <span
              className="inline-block h-2 w-2 rounded-sm"
              style={{
                backgroundColor: seg.color,
              }}
            />
            <span style={{ color: tc.muted }}>{seg.label}</span>
            <span className="font-medium tabular-nums">
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

const CompressionTimeline: FC<{ records: CompressionRecord[]; t: TFunction }> = ({
  records,
  t,
}) => {
  if (records.length === 0) {
    return (
      <Empty
        description={t('agent.contextDetail.empty.noCompressionEvents')}
        image={Empty.PRESENTED_IMAGE_SIMPLE}
      />
    );
  }

  const items = records.map((record) => {
    const time = new Date(record.timestamp).toLocaleTimeString();
    return {
      key: record.timestamp,
      icon: <Minimize2 size={14} />,
      color: record.level.includes('l3') ? 'red' : record.level.includes('l2') ? 'orange' : 'blue',
      content: (
        <div className="text-xs leading-[1.6]">
          <div>
            <Text strong>{record.level.toUpperCase()}</Text>
            <Text type="secondary" className="ml-2">
              {time}
            </Text>
          </div>
          <Space size={12} wrap>
            <span>
              <Zap size={16} className="mr-1 inline-block align-text-bottom" />{' '}
              {t('agent.contextDetail.timeline.tokensSaved', {
                tokens: formatTokens(record.tokens_saved),
                percent: record.savings_pct.toFixed(0),
              })}
            </span>
            <span>
              <Clock size={16} className="mr-1 inline-block align-text-bottom" />{' '}
              {record.duration_ms.toFixed(0)}ms
            </span>
            <span>
              {t('agent.contextDetail.timeline.messages', {
                before: record.messages_before,
                after: record.messages_after,
              })}
            </span>
          </Space>
        </div>
      ),
    };
  });

  return <Timeline items={items} />;
};

export const ContextDetailPanel: FC = () => {
  const { t } = useTranslation();
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
  const levelDescriptionKey = levelDescriptionKeys[compressionLevel];
  const levelDescription = levelDescriptionKey ? t(levelDescriptionKey) : '';
  const history = status?.compressionHistory;
  const distribution = status?.tokenDistribution;

  return (
    <Drawer
      title={
        <Space>
          <Database size={16} />
          <span>{t('agent.contextDetail.title')}</span>
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
      <div className="mb-6">
        <Title level={5} className="!mb-3">
          {t('agent.contextDetail.contextUsage')}
        </Title>
        <div className="mb-2 text-center">
          <Progress
            type="dashboard"
            percent={Math.min(occupancy, 100)}
            strokeColor={getOccupancyColor(occupancy)}
            format={() => (
              <div>
                <div className="text-xl font-semibold tabular-nums">
                  {occupancy.toFixed(1)}%
                </div>
                <div className="text-[11px]" style={{ color: tc.muted }}>
                  {formatTokens(currentTokens)} / {formatTokens(tokenBudget)}
                </div>
              </div>
            )}
            size={140}
          />
        </div>
        <div className="text-center">
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
            {levelDescription
              ? compressionLevel.replace('l', 'L').replace('_', ' ')
              : compressionLevel}
          </Tag>
        </div>
        <div className="mt-1.5 text-center text-xs" style={{ color: tc.muted }}>
          {levelDescription}
        </div>
      </div>

      <Divider className="!my-4" />

      {/* Token Distribution */}
      <div className="mb-6">
        <Title level={5} className="!mb-3">
          {t('agent.contextDetail.tokenDistribution')}
        </Title>
        {distribution ? (
          <TokenDistributionBar distribution={distribution} t={t} />
        ) : (
          <Empty
            description={t('agent.contextDetail.empty.noData')}
            image={Empty.PRESENTED_IMAGE_SIMPLE}
          />
        )}
      </div>

      <Divider className="!my-4" />

      {/* Compression Stats */}
      {history && history.total_compressions > 0 && (
        <div className="mb-6">
          <Title level={5} className="!mb-3">
            {t('agent.contextDetail.compressionSummary')}
          </Title>
          <div className="mb-4 grid grid-cols-2 gap-3">
            <div
              className="rounded-lg px-3 py-2 text-center"
              style={{
                background: tc.success + '1a',
              }}
            >
              <div className="text-lg font-semibold" style={{ color: tc.success }}>
                {formatTokens(history.total_tokens_saved)}
              </div>
              <div className="text-[11px]" style={{ color: tc.muted }}>
                {t('agent.contextDetail.summary.tokensSaved')}
              </div>
            </div>
            <div
              className="rounded-lg px-3 py-2 text-center"
              style={{
                background: tc.info + '1a',
              }}
            >
              <div className="text-lg font-semibold" style={{ color: tc.info }}>
                {history.total_compressions}
              </div>
              <div className="text-[11px]" style={{ color: tc.muted }}>
                {t('agent.contextDetail.summary.compressions')}
              </div>
            </div>
            <div
              className="rounded-lg px-3 py-2 text-center"
              style={{
                background: tc.warningDark + '1a',
              }}
            >
              <div className="text-lg font-semibold" style={{ color: tc.warningDark }}>
                {(history.average_compression_ratio * 100).toFixed(0)}%
              </div>
              <div className="text-[11px]" style={{ color: tc.muted }}>
                {t('agent.contextDetail.summary.avgRatio')}
              </div>
            </div>
            <div
              className="rounded-lg px-3 py-2 text-center"
              style={{
                background: tc.purple + '1a',
              }}
            >
              <div className="text-lg font-semibold" style={{ color: tc.purple }}>
                {history.average_savings_pct.toFixed(0)}%
              </div>
              <div className="text-[11px]" style={{ color: tc.muted }}>
                {t('agent.contextDetail.summary.avgSavings')}
              </div>
            </div>
          </div>
        </div>
      )}

      <Divider className="!my-4" />

      {/* Compression History Timeline */}
      <div>
        <Title level={5} className="!mb-3">
          {t('agent.contextDetail.compressionHistory')}
        </Title>
        <CompressionTimeline records={history?.recent_records ?? []} t={t} />
      </div>
    </Drawer>
  );
};
