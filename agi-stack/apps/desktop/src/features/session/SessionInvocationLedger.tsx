import { useMemo, useState } from 'react';
import {
  CheckCircledIcon,
  ClockIcon,
  CrossCircledIcon,
  ExclamationTriangleIcon,
  EyeOpenIcon,
  LightningBoltIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import {
  sessionInvocationLedgerSummary,
  type SessionInvocationLedgerEntry,
  type ToolInvocationStatus,
} from './sessionInvocationLedgerModel';
import './SessionInvocationLedger.css';

type SessionInvocationLedgerProps = {
  entries: readonly SessionInvocationLedgerEntry[];
};

type LedgerCopy = {
  eyebrowKey: string;
  titleKey: string;
  descriptionKey: string;
  emptyTitleKey: string;
  emptyDescriptionKey: string;
};

const activityCopy: LedgerCopy = {
  eyebrowKey: 'session.invocationLedgerEyebrow',
  titleKey: 'session.invocationLedgerTitle',
  descriptionKey: 'session.invocationLedgerDescription',
  emptyTitleKey: 'session.invocationLedgerEmpty',
  emptyDescriptionKey: 'session.invocationLedgerEmptyDescription',
};

const checksCopy: LedgerCopy = {
  eyebrowKey: 'session.executionChecksEyebrow',
  titleKey: 'session.executionChecksTitle',
  descriptionKey: 'session.executionChecksDescription',
  emptyTitleKey: 'session.executionChecksEmpty',
  emptyDescriptionKey: 'session.executionChecksEmptyDescription',
};

export function SessionInvocationActivity({ entries }: SessionInvocationLedgerProps) {
  return <SessionInvocationLedger entries={entries} copy={activityCopy} />;
}

export function SessionInvocationChecks({ entries }: SessionInvocationLedgerProps) {
  return <SessionInvocationLedger entries={entries} copy={checksCopy} />;
}

function SessionInvocationLedger({
  entries,
  copy,
}: SessionInvocationLedgerProps & { copy: LedgerCopy }) {
  const { t } = useI18n();
  const [inspectedId, setInspectedId] = useState<string | null>(null);
  const summary = useMemo(() => sessionInvocationLedgerSummary(entries), [entries]);
  const firstUnknownIndex = entries.findIndex((entry) => entry.status === 'unknown_outcome');
  const firstUnknown = firstUnknownIndex >= 0 ? entries[firstUnknownIndex] : null;
  const statusCounts: Array<{ status: ToolInvocationStatus; count: number }> = [
    { status: 'prepared', count: summary.prepared },
    { status: 'executing', count: summary.executing },
    { status: 'completed', count: summary.completed },
    { status: 'failed', count: summary.failed },
    { status: 'unknown_outcome', count: summary.unknownOutcome },
  ];

  const inspectEntry = (entry: SessionInvocationLedgerEntry, index: number) => {
    setInspectedId(entry.id);
    requestAnimationFrame(() => {
      document.getElementById(invocationRowId(index))?.scrollIntoView({ block: 'nearest' });
    });
  };

  return (
    <section className="session-invocation-ledger" aria-label={t('session.invocationLedger')}>
      <header className="session-invocation-ledger-header">
        <div>
          <span>{t(copy.eyebrowKey)}</span>
          <h2>{t(copy.titleKey)}</h2>
          <p>{t(copy.descriptionKey)}</p>
        </div>
        <strong className={summary.blocked ? 'blocked' : ''}>
          {summary.blocked
            ? t('session.invocationLedgerBlocked')
            : t('session.invocationLedgerCount', { count: summary.total })}
        </strong>
      </header>

      {firstUnknown ? (
        <div className="session-invocation-blocker" role="alert" aria-live="assertive">
          <ExclamationTriangleIcon aria-hidden />
          <div>
            <strong>{t('session.unknownOutcomeTitle')}</strong>
            <p>{t('session.unknownOutcomeDescription')}</p>
          </div>
          <button
            type="button"
            onClick={() => inspectEntry(firstUnknown, firstUnknownIndex)}
          >
            <EyeOpenIcon aria-hidden />
            {t('session.inspectInvocation')}
          </button>
        </div>
      ) : null}

      {entries.length ? (
        <>
          <div className="session-invocation-summary" aria-label={t('session.invocationStatusSummary')}>
            {statusCounts.map(({ status, count }) => (
              <article className={`status-${status}`} key={status}>
                {statusIcon(status)}
                <span>{t(statusLabelKey(status))}</span>
                <strong>{count}</strong>
              </article>
            ))}
          </div>

          <div className="session-invocation-list" role="list">
            {entries.map((entry, index) => {
              const inspectionOpen = inspectedId === entry.id;
              const detailId = invocationDetailId(index);
              return (
                <article
                  className={`session-invocation-row status-${entry.status}`}
                  id={invocationRowId(index)}
                  role="listitem"
                  key={entry.id}
                >
                  <div className="session-invocation-row-main">
                    <span className="session-invocation-status-icon" aria-hidden>
                      {statusIcon(entry.status)}
                    </span>
                    <div className="session-invocation-identity">
                      <strong>{entry.toolName || t('session.notAvailable')}</strong>
                      <span title={entry.invocationId}>
                        {t('session.invocation')} · {compactIdentifier(entry.invocationId)}
                      </span>
                    </div>
                    <span className="session-invocation-status">
                      {t(statusLabelKey(entry.status))}
                    </span>
                    <dl className="session-invocation-scope">
                      <div>
                        <dt>{t('session.invocationRun')}</dt>
                        <dd title={entry.runId ?? undefined}>
                          {entry.runId ? compactIdentifier(entry.runId) : t('session.notAvailable')}
                        </dd>
                      </div>
                      <div>
                        <dt>{t('session.invocationRevision')}</dt>
                        <dd>{entry.revision === null ? t('session.notAvailable') : `r${entry.revision}`}</dd>
                      </div>
                    </dl>
                    <button
                      type="button"
                      className="session-invocation-inspect"
                      aria-controls={detailId}
                      aria-expanded={inspectionOpen}
                      onClick={() =>
                        inspectionOpen ? setInspectedId(null) : inspectEntry(entry, index)
                      }
                    >
                      <EyeOpenIcon aria-hidden />
                      {inspectionOpen
                        ? t('session.closeInspection')
                        : t('session.inspectInvocation')}
                    </button>
                  </div>

                  {inspectionOpen ? (
                    <dl className="session-invocation-detail" id={detailId}>
                      <InvocationFact label={t('session.invocation')} value={entry.invocationId} />
                      <InvocationFact
                        label={t('session.invocationTool')}
                        value={entry.toolName || t('session.notAvailable')}
                      />
                      <InvocationFact
                        label={t('session.invocationStatus')}
                        value={t(statusLabelKey(entry.status))}
                      />
                      <InvocationFact
                        label={t('session.invocationRun')}
                        value={entry.runId || t('session.notAvailable')}
                      />
                      <InvocationFact
                        label={t('session.invocationRevision')}
                        value={
                          entry.revision === null
                            ? t('session.notAvailable')
                            : `r${entry.revision}`
                        }
                      />
                      <InvocationFact
                        label={t('session.invocationScopeSource')}
                        value={t(`session.invocationScope.${entry.scopeSource}`)}
                      />
                      <InvocationFact
                        label={t('session.invocationAuthorization')}
                        value={entry.authorizationId || t('session.notAvailable')}
                      />
                      <InvocationFact
                        label={t('session.invocationTimelineRecords')}
                        value={String(entry.sourceEventIds.length)}
                      />
                    </dl>
                  ) : null}
                </article>
              );
            })}
          </div>
        </>
      ) : (
        <div className="session-invocation-empty">
          <ClockIcon aria-hidden />
          <strong>{t(copy.emptyTitleKey)}</strong>
          <p>{t(copy.emptyDescriptionKey)}</p>
        </div>
      )}
    </section>
  );
}

function InvocationFact({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

function statusLabelKey(status: ToolInvocationStatus): string {
  return `session.invocationStatus.${status}`;
}

function statusIcon(status: ToolInvocationStatus) {
  if (status === 'completed') return <CheckCircledIcon aria-hidden />;
  if (status === 'failed') return <CrossCircledIcon aria-hidden />;
  if (status === 'unknown_outcome') return <ExclamationTriangleIcon aria-hidden />;
  if (status === 'executing') return <LightningBoltIcon aria-hidden />;
  return <ClockIcon aria-hidden />;
}

function compactIdentifier(value: string): string {
  if (value.length <= 18) return value;
  return `${value.slice(0, 8)}…${value.slice(-6)}`;
}

function invocationRowId(index: number): string {
  return `session-invocation-row-${index}`;
}

function invocationDetailId(index: number): string {
  return `session-invocation-detail-${index}`;
}
