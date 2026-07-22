import { useMemo, useState, type CSSProperties } from 'react';
import {
  ArchiveIcon,
  ClockIcon,
  DashboardIcon,
  LayersIcon,
  PieChartIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import type {
  SessionContextCompressionRecord,
  SessionContextTokenDistribution,
  SessionContextWindowModel,
} from './sessionContextWindowModel';
import './SessionContextWindowCanvas.css';

type DistributionSegment = {
  key: keyof Omit<SessionContextTokenDistribution, 'total'>;
  label: string;
  value: number;
  percentage: number;
};

export function SessionContextWindowCanvas({ model }: { model: SessionContextWindowModel }) {
  const { t } = useI18n();
  const [selectedRecordId, setSelectedRecordId] = useState<string | null>(null);
  const current = model.current;
  const recentRecords = current?.compressionHistory.recentRecords ?? [];
  const selectedRecord = useMemo(
    () =>
      recentRecords.find((record) => record.id === selectedRecordId) ??
      recentRecords.at(-1) ??
      null,
    [recentRecords, selectedRecordId],
  );
  const tokenDistributionSegments = useMemo(
    () => (current ? distributionSegments(current.tokenDistribution, t) : []),
    [current, t],
  );
  const latestCompression = model.compressions.at(-1) ?? null;

  if (!current) {
    return (
      <section
        className="session-context-window-canvas is-empty"
        aria-label={t('session.context.title')}
      >
        <DashboardIcon aria-hidden="true" />
        <h2>{t('session.context.empty')}</h2>
        <p>{t('session.context.emptyDescription')}</p>
      </section>
    );
  }

  const occupancyStyle = {
    '--context-occupancy': `${Math.min(current.occupancyPct, 100)}%`,
  } as CSSProperties;

  return (
    <section className="session-context-window-canvas" aria-label={t('session.context.title')}>
      <header className="session-context-header">
        <div className="session-context-heading">
          <span aria-hidden="true">
            <DashboardIcon />
          </span>
          <div>
            <small>{t('session.context.kicker')}</small>
            <h2>{t('session.context.title')}</h2>
          </div>
        </div>
        <div className="session-context-badges">
          <code>{current.compressionLevel}</code>
          {current.fromCache ? <span>{t('session.context.cached')}</span> : null}
        </div>
      </header>

      <div className="session-context-usage">
        <article className="session-context-occupancy" style={occupancyStyle}>
          <span>{t('session.context.occupancy')}</span>
          <strong>{formatPercentage(current.occupancyPct)}</strong>
          <div role="img" aria-label={t('session.context.occupancyValue', { value: formatPercentage(current.occupancyPct) })}>
            <i />
          </div>
          <small>
            {formatTokens(current.currentTokens)} / {formatTokens(current.tokenBudget)}
          </small>
        </article>
        <ContextMetric
          icon={<LayersIcon />}
          label={t('session.context.currentTokens')}
          value={formatTokens(current.currentTokens)}
          detail={t('session.context.tokenBudgetValue', { value: formatTokens(current.tokenBudget) })}
        />
        <ContextMetric
          icon={<ArchiveIcon />}
          label={t('session.context.summaryMessages')}
          value={current.messagesInSummary.toLocaleString()}
          detail={current.compressionLevel}
        />
        <ContextMetric
          icon={<ClockIcon />}
          label={t('session.context.updates')}
          value={model.summary.updates.toLocaleString()}
          detail={formatContextTime(current.updatedAtUs)}
        />
      </div>

      <article className="session-context-section session-context-distribution">
        <header>
          <span aria-hidden="true"><PieChartIcon /></span>
          <div>
            <h3>{t('session.context.distribution')}</h3>
            <small>{t('session.context.distributionDescription')}</small>
          </div>
        </header>
        {tokenDistributionSegments.length ? (
          <>
            <div className="session-context-distribution-bar" aria-label={t('session.context.distribution')}>
              {tokenDistributionSegments.map((segment) => (
                <i
                  className={`segment-${segment.key}`}
                  key={segment.key}
                  style={{ width: `${segment.percentage}%` }}
                  title={`${segment.label}: ${formatTokens(segment.value)}`}
                />
              ))}
            </div>
            <div className="session-context-distribution-legend">
              {tokenDistributionSegments.map((segment) => (
                <span className={`segment-${segment.key}`} key={segment.key}>
                  <i />
                  <small>{segment.label}</small>
                  <strong>{formatTokens(segment.value)}</strong>
                  <em>{formatPercentage(segment.percentage)}</em>
                </span>
              ))}
            </div>
          </>
        ) : (
          <p className="session-context-empty-copy">{t('session.context.noDistribution')}</p>
        )}
      </article>

      <div className="session-context-compression-summary" aria-label={t('session.context.compressionSummary')}>
        <ContextStat
          label={t('session.context.compressions')}
          value={current.compressionHistory.totalCompressions.toLocaleString()}
        />
        <ContextStat
          label={t('session.context.tokensSaved')}
          value={formatTokens(current.compressionHistory.totalTokensSaved)}
        />
        <ContextStat
          label={t('session.context.averageRatio')}
          value={formatRatio(current.compressionHistory.averageCompressionRatio)}
        />
        <ContextStat
          label={t('session.context.averageSavings')}
          value={formatPercentage(current.compressionHistory.averageSavingsPct)}
        />
      </div>

      <div className="session-context-history-grid">
        <article className="session-context-section session-context-history">
          <header>
            <span aria-hidden="true"><ClockIcon /></span>
            <div>
              <h3>{t('session.context.history')}</h3>
              <small>{t('session.context.historyDescription')}</small>
            </div>
          </header>
          {recentRecords.length ? (
            <nav aria-label={t('session.context.history')}>
              {recentRecords.map((record) => {
                const selected = selectedRecord?.id === record.id;
                return (
                  <button
                    type="button"
                    className={selected ? 'selected' : undefined}
                    aria-pressed={selected}
                    key={record.id}
                    onClick={() => setSelectedRecordId(record.id)}
                  >
                    <span>
                      <strong>{record.level}</strong>
                      <small>{formatRecordTime(record.timestamp)}</small>
                    </span>
                    <span>
                      <strong>{formatTokens(record.tokensSaved)}</strong>
                      <small>{t('session.context.saved')}</small>
                    </span>
                  </button>
                );
              })}
            </nav>
          ) : (
            <p className="session-context-empty-copy">{t('session.context.noHistory')}</p>
          )}
        </article>

        <article className="session-context-section session-context-record-detail">
          <header>
            <span aria-hidden="true"><ArchiveIcon /></span>
            <div>
              <h3>{t('session.context.selectedCompression')}</h3>
              <small>{selectedRecord?.level ?? latestCompression?.compressionLevel ?? t('session.notAvailable')}</small>
            </div>
          </header>
          {selectedRecord ? (
            <CompressionRecordDetail record={selectedRecord} />
          ) : latestCompression ? (
            <dl>
              <ContextFact label={t('session.context.strategy')} value={latestCompression.strategy} />
              <ContextFact
                label={t('session.context.messages')}
                value={`${latestCompression.originalMessageCount} → ${latestCompression.finalMessageCount}`}
              />
              <ContextFact
                label={t('session.context.tokensSaved')}
                value={formatTokens(latestCompression.tokensSaved)}
              />
              <ContextFact
                label={t('session.context.duration')}
                value={`${formatNumber(latestCompression.durationMs)} ms`}
              />
              <ContextFact
                label={t('session.context.toolOutputsPruned')}
                value={latestCompression.prunedToolOutputs.toLocaleString()}
              />
              <ContextFact
                label={t('session.context.summarizedMessages')}
                value={latestCompression.summarizedMessageCount.toLocaleString()}
              />
            </dl>
          ) : (
            <p className="session-context-empty-copy">{t('session.context.noCompressionEvent')}</p>
          )}
        </article>
      </div>
    </section>
  );
}

function CompressionRecordDetail({ record }: { record: SessionContextCompressionRecord }) {
  const { t } = useI18n();
  return (
    <dl>
      <ContextFact
        label={t('session.context.messages')}
        value={`${record.messagesBefore} → ${record.messagesAfter}`}
      />
      <ContextFact
        label={t('session.context.tokens')}
        value={`${formatTokens(record.tokensBefore)} → ${formatTokens(record.tokensAfter)}`}
      />
      <ContextFact label={t('session.context.tokensSaved')} value={formatTokens(record.tokensSaved)} />
      <ContextFact label={t('session.context.savings')} value={formatPercentage(record.savingsPct)} />
      <ContextFact label={t('session.context.ratio')} value={formatRatio(record.compressionRatio)} />
      <ContextFact label={t('session.context.duration')} value={`${formatNumber(record.durationMs)} ms`} />
    </dl>
  );
}

function ContextMetric({
  icon,
  label,
  value,
  detail,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  detail: string;
}) {
  return (
    <article className="session-context-metric">
      <span aria-hidden="true">{icon}</span>
      <small>{label}</small>
      <strong>{value}</strong>
      <em>{detail}</em>
    </article>
  );
}

function ContextStat({ label, value }: { label: string; value: string }) {
  return (
    <span>
      <small>{label}</small>
      <strong>{value}</strong>
    </span>
  );
}

function ContextFact({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

function distributionSegments(
  distribution: SessionContextTokenDistribution,
  t: (key: string, params?: Record<string, string | number>) => string,
): DistributionSegment[] {
  if (distribution.total <= 0) return [];
  return (['system', 'user', 'assistant', 'tool', 'summary'] as const)
    .map((key) => ({
      key,
      label: t(`session.context.segment.${key}`),
      value: distribution[key],
      percentage: (distribution[key] / distribution.total) * 100,
    }))
    .filter((segment) => segment.value > 0);
}

function formatTokens(value: number): string {
  if (value >= 1_000_000) return `${formatNumber(value / 1_000_000)}M`;
  if (value >= 1_000) return `${formatNumber(value / 1_000)}K`;
  return formatNumber(value);
}

function formatNumber(value: number): string {
  return Number.isInteger(value) ? value.toLocaleString() : value.toFixed(1);
}

function formatPercentage(value: number): string {
  return `${value.toFixed(1)}%`;
}

function formatRatio(value: number): string {
  return `${(value * 100).toFixed(0)}%`;
}

function formatContextTime(eventTimeUs: number): string {
  if (!eventTimeUs) return '—';
  return new Date(eventTimeUs / 1000).toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

function formatRecordTime(timestamp: string): string {
  const value = new Date(timestamp);
  if (Number.isNaN(value.valueOf())) return timestamp;
  return value.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}
