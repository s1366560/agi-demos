import { Cross2Icon } from '@radix-ui/react-icons';
import { Button } from '@radix-ui/themes';

import { useI18n } from '../../i18n';
import type {
  TenantAgentDashboardController,
  TenantAgentDashboardViewModel,
} from './tenantAgentDashboardController';
import type { TenantAgentRun } from './tenantAgentDashboardClient';

export function TenantAgentDashboardTraceView({
  model,
  controller,
}: Readonly<{
  model: TenantAgentDashboardViewModel;
  controller: TenantAgentDashboardController | null;
}>) {
  const { t } = useI18n();
  const trace = model.selectedTrace;
  if (!trace) return null;
  const runs = [...trace.runs].sort((left, right) => left.createdAt.localeCompare(right.createdAt));
  const totalDuration = runs.reduce((sum, run) => sum + (run.executionTimeMs ?? 0), 0);
  const totalTokens = runs.reduce((sum, run) => sum + (run.tokensUsed ?? 0), 0);
  return (
    <section className="tenant-agent-dashboard-trace">
      <header>
        <div>
          <span>{t('tenantAgentDashboard.trace.eyebrow')}</span>
          <h2>{t('tenantAgentDashboard.trace.title')}</h2>
          <code>{trace.traceId ?? trace.conversationId}</code>
        </div>
        <Button color="gray" variant="ghost" onClick={() => controller?.clearSelection()}>
          <Cross2Icon />
          {t('common.close')}
        </Button>
      </header>
      <div className="tenant-agent-dashboard-trace-summary">
        <span>
          {t('tenantAgentDashboard.trace.runCount', {
            count: runs.length,
          })}
        </span>
        <span>
          {t('tenantAgentDashboard.trace.duration', {
            duration: formatDuration(totalDuration),
          })}
        </span>
        <span>
          {t('tenantAgentDashboard.trace.tokens', {
            count: totalTokens,
          })}
        </span>
      </div>
      <ol>
        {runs.map((run) => (
          <TraceRun key={run.runId} run={run} />
        ))}
      </ol>
    </section>
  );
}

function TraceRun({ run }: Readonly<{ run: TenantAgentRun }>) {
  const { t } = useI18n();
  return (
    <li>
      <div className="tenant-agent-dashboard-trace-title">
        <strong>{run.subagentName}</strong>
        <span data-status={run.status}>{run.status}</span>
      </div>
      <p>{run.task}</p>
      <dl>
        <TraceValue label={t('tenantAgentDashboard.trace.runId')} value={run.runId} />
        <TraceValue
          label={t('tenantAgentDashboard.trace.conversationId')}
          value={run.conversationId}
        />
        <TraceValue label={t('tenantAgentDashboard.trace.createdAt')} value={run.createdAt} />
        <TraceValue
          label={t('tenantAgentDashboard.trace.startedAt')}
          value={run.startedAt ?? '—'}
        />
        <TraceValue label={t('tenantAgentDashboard.trace.endedAt')} value={run.endedAt ?? '—'} />
        <TraceValue
          label={t('tenantAgentDashboard.trace.durationLabel')}
          value={formatDuration(run.executionTimeMs)}
        />
        <TraceValue
          label={t('tenantAgentDashboard.trace.tokensLabel')}
          value={
            run.tokensUsed === null
              ? '—'
              : t('tenantAgentDashboard.trace.tokens', {
                  count: run.tokensUsed,
                })
          }
        />
        <TraceValue label={t('tenantAgentDashboard.trace.traceId')} value={run.traceId ?? '—'} />
        <TraceValue
          label={t('tenantAgentDashboard.trace.parentSpanId')}
          value={run.parentSpanId ?? '—'}
        />
      </dl>
      {run.summary ? <p className="tenant-agent-dashboard-trace-result">{run.summary}</p> : null}
      {run.error ? <p className="tenant-agent-dashboard-trace-error">{run.error}</p> : null}
    </li>
  );
}

function TraceValue({ label, value }: Readonly<{ label: string; value: string }>) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

function formatDuration(value: number | null): string {
  if (value === null) return '—';
  if (value < 1_000) return `${String(value)} ms`;
  return `${(value / 1_000).toFixed(2)} s`;
}
