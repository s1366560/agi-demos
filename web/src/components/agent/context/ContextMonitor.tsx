import { useMemo } from 'react';
import type { FC } from 'react';

import { CompressOutlined, DatabaseOutlined } from '@ant-design/icons';
import { Tooltip, Progress } from 'antd';

import { useThemeColors, resolveThemeColor } from '@/hooks/useThemeColor';

import { useContextStatus, useContextActions } from '../../../stores/contextStore';

interface ContextMonitorProps {
  compact?: boolean | undefined;
}

const levelLabels: Record<string, string> = {
  none: 'Normal',
  l1_prune: 'L1 Prune',
  l2_summarize: 'L2 Summarize',
  l3_deep_compress: 'L3 Compress',
};

const levelColors: Record<string, string> = {
  get none() { return resolveThemeColor('--color-success', '#52c41a'); },
  get l1_prune() { return resolveThemeColor('--color-warning', '#faad14'); },
  get l2_summarize() { return resolveThemeColor('--color-warning-dark', '#fa8c16'); },
  get l3_deep_compress() { return resolveThemeColor('--color-error', '#f5222d'); },
};

function getOccupancyColor(pct: number): string {
  if (pct < 60) return resolveThemeColor('--color-success', '#52c41a');
  if (pct < 80) return resolveThemeColor('--color-warning', '#faad14');
  if (pct < 90) return resolveThemeColor('--color-warning-dark', '#fa8c16');
  return resolveThemeColor('--color-error', '#f5222d');
}

function formatTokens(tokens: number): string {
  if (tokens >= 1000000) return `${(tokens / 1000000).toFixed(1)}M`;
  if (tokens >= 1000) return `${(tokens / 1000).toFixed(1)}K`;
  return String(tokens);
}

export const ContextMonitor: FC<ContextMonitorProps> = ({ compact = true }) => {
  const status = useContextStatus();
  const { setDetailExpanded } = useContextActions();

  const tc = useThemeColors({
    muted: '--color-text-muted',
    success: '--color-success',
  });

  const occupancy = status?.occupancyPct ?? 0;
  const currentTokens = status?.currentTokens ?? 0;
  const tokenBudget = status?.tokenBudget ?? 128000;
  const compressionLevel = status?.compressionLevel ?? 'none';
  const totalSaved = status?.compressionHistory?.total_tokens_saved ?? 0;

  const progressColor = useMemo(() => getOccupancyColor(occupancy), [occupancy]);
  const levelLabel = levelLabels[compressionLevel] ?? compressionLevel;
  const levelColor = levelColors[compressionLevel] ?? tc.success;

  if (!status) return null;

  const tooltipContent = (
    <div style={{ fontSize: 12, lineHeight: 1.6 }}>
      <div>
        Tokens: {formatTokens(currentTokens)} / {formatTokens(tokenBudget)}
      </div>
      <div>Occupancy: {occupancy.toFixed(1)}%</div>
      <div>Compression: {levelLabel}</div>
      {totalSaved > 0 && <div>Total saved: {formatTokens(totalSaved)} tokens</div>}
    </div>
  );

  if (compact) {
    return (
      <Tooltip title={tooltipContent} placement="bottom">
        <div
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 8,
            cursor: 'pointer',
            padding: '2px 8px',
            borderRadius: 6,
            fontSize: 12,
            color: tc.muted,
            transition: 'background 0.2s',
          }}
          onClick={() => {
            setDetailExpanded(true);
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.background = 'rgba(0,0,0,0.04)';
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.background = 'transparent';
          }}
        >
          <DatabaseOutlined style={{ fontSize: 13, color: progressColor }} />
          <Progress
            percent={Math.min(occupancy, 100)}
            size={[80, 6]}
            strokeColor={progressColor}
            showInfo={false}
            style={{ margin: 0 }}
          />
          <span style={{ minWidth: 36, textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
            {occupancy.toFixed(0)}%
          </span>
          {compressionLevel !== 'none' && (
            <span
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 2,
                padding: '0 4px',
                borderRadius: 4,
                fontSize: 11,
                background: `${levelColor}15`,
                color: levelColor,
                fontWeight: 500,
              }}
            >
              <CompressOutlined style={{ fontSize: 10 }} />
              {levelLabel}
            </span>
          )}
        </div>
      </Tooltip>
    );
  }

  return null;
};
