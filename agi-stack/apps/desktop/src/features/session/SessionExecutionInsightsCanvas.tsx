import { useMemo, useState } from 'react';
import {
  CheckCircledIcon,
  ChevronRightIcon,
  CodeIcon,
  ExclamationTriangleIcon,
  MixerHorizontalIcon,
  RocketIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import type {
  SessionExecutionInsightEntry,
  SessionExecutionInsightsModel,
} from './sessionExecutionInsightsModel';
import './SessionExecutionInsightsCanvas.css';

export function SessionExecutionInsightsCanvas({
  model,
}: {
  model: SessionExecutionInsightsModel;
}) {
  const { t } = useI18n();
  const [selectedTraceKey, setSelectedTraceKey] = useState<string | null>(null);
  const [selectedEntryId, setSelectedEntryId] = useState<string | null>(null);
  const trace = useMemo(
    () =>
      model.traces.find((candidate) => candidate.groupKey === selectedTraceKey) ??
      model.activeTrace,
    [model.activeTrace, model.traces, selectedTraceKey],
  );
  const selectedEntry = useMemo(
    () =>
      trace?.entries.find((entry) => entry.id === selectedEntryId) ??
      trace?.entries.at(-1) ??
      null,
    [selectedEntryId, trace],
  );

  if (!trace) {
    return (
      <section
        className="session-execution-insights-canvas is-empty"
        aria-label={t('session.insights.title')}
      >
        <MixerHorizontalIcon aria-hidden="true" />
        <h2>{t('session.insights.empty')}</h2>
        <p>{t('session.insights.emptyDescription')}</p>
      </section>
    );
  }

  return (
    <section
      className="session-execution-insights-canvas"
      aria-label={t('session.insights.title')}
    >
      <header className="session-insights-header">
        <div className="session-insights-heading">
          <span className="session-insights-heading-icon" aria-hidden="true">
            <MixerHorizontalIcon />
          </span>
          <span>
            <small>{t('session.insights.kicker')}</small>
            <h2>{t('session.insights.title')}</h2>
          </span>
        </div>
        <div className="session-insights-identity">
          {trace.domainLane ? <span>{trace.domainLane}</span> : null}
          <code>{trace.traceId ?? trace.routeId ?? trace.groupKey}</code>
        </div>
      </header>

      {model.traces.length > 1 ? (
        <nav className="session-insights-traces" aria-label={t('session.insights.traces')}>
          {model.traces.map((candidate, index) => (
            <button
              type="button"
              className={candidate.groupKey === trace.groupKey ? 'selected' : undefined}
              aria-pressed={candidate.groupKey === trace.groupKey}
              key={candidate.groupKey}
              onClick={() => {
                setSelectedTraceKey(candidate.groupKey);
                setSelectedEntryId(null);
              }}
            >
              <strong>{t('session.insights.traceNumber', { count: index + 1 })}</strong>
              <small>{candidate.traceId ?? candidate.routeId ?? t('session.insights.standalone')}</small>
            </button>
          ))}
        </nav>
      ) : null}

      <div className="session-insights-summary" aria-label={t('session.insights.summary')}>
        <InsightMetric label={t('session.insights.events')} value={trace.entries.length} />
        <InsightMetric label={t('session.insights.routing')} value={countStage(trace.entries, 'routing')} />
        <InsightMetric
          label={t('session.insights.selection')}
          value={countStage(trace.entries, 'selection')}
        />
        <InsightMetric label={t('session.insights.policy')} value={countStage(trace.entries, 'policy')} />
        <InsightMetric
          label={t('session.insights.toolset')}
          value={countStage(trace.entries, 'toolset')}
        />
      </div>

      <div className="session-insights-pipeline" aria-label={t('session.insights.pipeline')}>
        {trace.entries.map((entry, index) => {
          const selected = selectedEntry?.id === entry.id;
          const warning = insightWarning(entry);
          return (
            <div className="session-insights-stage-slot" key={entry.id}>
              {index > 0 ? (
                <span className="session-insights-connector" aria-hidden="true">
                  <ChevronRightIcon />
                </span>
              ) : null}
              <button
                type="button"
                className={`session-insights-stage stage-${entry.stage}${selected ? ' selected' : ''}${warning ? ' has-warning' : ''}`}
                aria-pressed={selected}
                onClick={() => setSelectedEntryId(entry.id)}
              >
                <span className="session-insights-stage-icon" aria-hidden="true">
                  {stageIcon(entry)}
                </span>
                <span>
                  <small>{t(`session.insights.${entry.stage}`)}</small>
                  <strong>{stageHeadline(entry, t)}</strong>
                </span>
                {warning ? <ExclamationTriangleIcon className="session-insights-warning" /> : null}
              </button>
            </div>
          );
        })}
      </div>

      {selectedEntry ? <InsightEvidence entry={selectedEntry} /> : null}
    </section>
  );
}

function InsightMetric({ label, value }: { label: string; value: number }) {
  return (
    <span>
      <small>{label}</small>
      <strong>{value}</strong>
    </span>
  );
}

function InsightEvidence({ entry }: { entry: SessionExecutionInsightEntry }) {
  const { t } = useI18n();
  const selection = entry.selection;
  return (
    <article className={`session-insights-evidence stage-${entry.stage}`}>
      <header>
        <span>
          <small>{t('session.insights.selectedEvidence')}</small>
          <h3>{t(`session.insights.${entry.stage}`)}</h3>
        </span>
        <em>{formatInsightTime(entry.eventTimeUs)}</em>
      </header>

      {entry.routing ? (
        <div className="session-insights-routing-evidence">
          <dl className="session-insights-facts">
            <InsightFact label={t('session.insights.path')} value={entry.routing.path} />
            <InsightFact
              label={t('session.insights.confidence')}
              value={`${Math.round(entry.routing.confidence * 100)}%`}
            />
            <InsightFact label={t('session.insights.target')} value={entry.routing.target} />
          </dl>
          <EvidenceCopy label={t('session.insights.reason')} value={entry.routing.reason} />
        </div>
      ) : null}

      {selection ? (
        <div className="session-insights-selection-evidence">
          <dl className="session-insights-facts">
            <InsightFact label={t('session.insights.initialTools')} value={selection.initialCount} />
            <InsightFact label={t('session.insights.keptTools')} value={selection.finalCount} />
            <InsightFact label={t('session.insights.removedTools')} value={selection.removedTotal} />
            <InsightFact label={t('session.insights.toolBudget')} value={selection.toolBudget} />
          </dl>
          <div className="session-insights-selection-stages">
            <h4>{t('session.insights.selectionStages')}</h4>
            {selection.stages.map((stage) => (
              <div
                className={selection.budgetExceededStages.includes(stage.name) ? 'has-warning' : ''}
                key={stage.name}
              >
                <span>
                  <strong>{stage.name}</strong>
                  <small>{t('session.insights.stageDuration', { duration: stage.durationMs })}</small>
                </span>
                <span className="session-insights-stage-counts">
                  <em>{stage.beforeCount}</em>
                  <ChevronRightIcon />
                  <em>{stage.afterCount}</em>
                  <small>{t('session.insights.removedCount', { count: stage.removedCount })}</small>
                </span>
              </div>
            ))}
          </div>
          <WarningList stages={selection.budgetExceededStages} />
        </div>
      ) : null}

      {entry.policy ? (
        <div className="session-insights-policy-evidence">
          <dl className="session-insights-facts">
            <InsightFact label={t('session.insights.removedTools')} value={entry.policy.removedTotal} />
            <InsightFact label={t('session.insights.policyStages')} value={entry.policy.stageCount} />
            <InsightFact label={t('session.insights.toolBudget')} value={entry.policy.toolBudget} />
          </dl>
          <WarningList stages={entry.policy.budgetExceededStages} />
        </div>
      ) : null}

      {entry.toolset ? (
        <div className="session-insights-toolset-evidence">
          <dl className="session-insights-facts">
            <InsightFact label={t('session.insights.source')} value={entry.toolset.source} />
            <InsightFact label={t('session.insights.action')} value={entry.toolset.action} />
            <InsightFact label={t('session.insights.plugin')} value={entry.toolset.pluginName} />
            <InsightFact
              label={t('session.insights.refreshStatus')}
              value={entry.toolset.refreshStatus}
            />
            <InsightFact
              label={t('session.insights.refreshedTools')}
              value={entry.toolset.refreshedToolCount}
            />
          </dl>
          <EvidenceCopy
            label={t('session.insights.mutationFingerprint')}
            value={entry.toolset.mutationFingerprint}
            code
          />
        </div>
      ) : null}

      {entry.traceId || entry.routeId ? (
        <footer>
          {entry.traceId ? <code>trace · {entry.traceId}</code> : null}
          {entry.routeId ? <code>route · {entry.routeId}</code> : null}
        </footer>
      ) : null}
    </article>
  );
}

function InsightFact({ label, value }: { label: string; value: string | number | null }) {
  const { t } = useI18n();
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value ?? t('session.notAvailable')}</dd>
    </div>
  );
}

function EvidenceCopy({
  label,
  value,
  code = false,
}: {
  label: string;
  value: string | null;
  code?: boolean;
}) {
  if (!value) return null;
  return (
    <div className="session-insights-copy">
      <span>{label}</span>
      {code ? <code>{value}</code> : <p>{value}</p>}
    </div>
  );
}

function WarningList({ stages }: { stages: string[] }) {
  const { t } = useI18n();
  if (!stages.length) return null;
  return (
    <div className="session-insights-budget-warning" role="status">
      <ExclamationTriangleIcon aria-hidden="true" />
      <span>
        <strong>{t('session.insights.budgetExceeded')}</strong>
        <small>{stages.join(', ')}</small>
      </span>
    </div>
  );
}

function countStage(
  entries: SessionExecutionInsightEntry[],
  stage: SessionExecutionInsightEntry['stage'],
) {
  return entries.reduce((count, entry) => count + Number(entry.stage === stage), 0);
}

function insightWarning(entry: SessionExecutionInsightEntry): boolean {
  return Boolean(
    entry.selection?.budgetExceededStages.length ||
      entry.policy?.budgetExceededStages.length ||
      entry.toolset?.refreshStatus === 'failed',
  );
}

function stageIcon(entry: SessionExecutionInsightEntry) {
  if (entry.stage === 'routing') return <RocketIcon />;
  if (entry.stage === 'selection') return <MixerHorizontalIcon />;
  if (entry.stage === 'policy') return <CheckCircledIcon />;
  return <CodeIcon />;
}

function stageHeadline(
  entry: SessionExecutionInsightEntry,
  t: ReturnType<typeof useI18n>['t'],
): string {
  if (entry.routing) return entry.routing.path;
  if (entry.selection) {
    return t('session.insights.keptOfInitial', {
      kept: entry.selection.finalCount,
      initial: entry.selection.initialCount,
    });
  }
  if (entry.policy) {
    return t('session.insights.filteredTools', { count: entry.policy.removedTotal });
  }
  return entry.toolset?.pluginName ?? entry.toolset?.action ?? entry.toolset?.source ?? '';
}

function formatInsightTime(eventTimeUs: number): string {
  const date = new Date(eventTimeUs / 1000);
  if (Number.isNaN(date.getTime())) return '';
  return new Intl.DateTimeFormat(undefined, {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).format(date);
}
