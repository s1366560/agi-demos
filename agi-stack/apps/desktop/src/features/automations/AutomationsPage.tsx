import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ActivityLogIcon,
  ClockIcon,
  PlusIcon,
  ReloadIcon,
  RocketIcon,
} from '@radix-ui/react-icons';
import { Badge, Button, Heading, Text } from '@radix-ui/themes';

import { DesktopApiClient, DesktopApiError } from '../../api/client';
import { useI18n } from '../../i18n';
import type { AutomationCapabilities, AutomationJob, AutomationRun } from '../../types';
import {
  automationActionAvailability,
  automationCapabilityReasonCode,
  automationEnvironmentId,
  automationLastRunAt,
  automationLastRunStatus,
  automationNextRunAt,
  automationPermissionProfile,
  automationScheduleValue,
  automationTriggerKind,
  automationRunStatus,
  automationRunTrigger,
} from './automationModel';
import './AutomationsPage.css';

type AutomationsPageProps = {
  api: Pick<
    DesktopApiClient,
    'getAutomationCapabilities' | 'listAutomations' | 'listAutomationRuns'
  >;
  projectId: string;
  projectName?: string | null;
  onOpenConnection: () => void;
};

export function AutomationsPage({
  api,
  projectId,
  projectName,
  onOpenConnection,
}: AutomationsPageProps) {
  const { locale, t } = useI18n();
  const [jobs, setJobs] = useState<AutomationJob[]>([]);
  const [selectedJobId, setSelectedJobId] = useState('');
  const [runs, setRuns] = useState<AutomationRun[]>([]);
  const [loading, setLoading] = useState(false);
  const [runsLoading, setRunsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [runsError, setRunsError] = useState<string | null>(null);
  const [capabilities, setCapabilities] = useState<AutomationCapabilities | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  const selectedJob = useMemo(
    () => jobs.find((job) => job.id === selectedJobId) ?? jobs[0] ?? null,
    [jobs, selectedJobId],
  );

  const loadJobs = useCallback(
    async (signal?: AbortSignal) => {
      if (!projectId) {
        setJobs([]);
        setSelectedJobId('');
        setError(null);
        setUnavailable(false);
        return;
      }
      setLoading(true);
      setError(null);
      setUnavailable(false);
      try {
        const [response, capabilityResponse] = await Promise.all([
          api.listAutomations(projectId, signal),
          api.getAutomationCapabilities(projectId, signal).catch((caught) => {
            if (signal?.aborted) throw caught;
            if (caught instanceof DesktopApiError && [404, 405, 501].includes(caught.status)) {
              return null;
            }
            throw caught;
          }),
        ]);
        setJobs(response.items);
        setCapabilities(capabilityResponse);
        setSelectedJobId((current) =>
          response.items.some((job) => job.id === current) ? current : (response.items[0]?.id ?? ''),
        );
      } catch (caught) {
        if (signal?.aborted) return;
        const capabilityUnavailable =
          caught instanceof DesktopApiError && [404, 405, 501].includes(caught.status);
        setJobs([]);
        setCapabilities(null);
        setSelectedJobId('');
        setUnavailable(capabilityUnavailable);
        setError(capabilityUnavailable ? null : caught instanceof Error ? caught.message : String(caught));
      } finally {
        if (!signal?.aborted) setLoading(false);
      }
    },
    [api, projectId],
  );

  useEffect(() => {
    const controller = new AbortController();
    void loadJobs(controller.signal);
    return () => controller.abort();
  }, [loadJobs]);

  useEffect(() => {
    if (!selectedJob || !projectId) {
      setRuns([]);
      return;
    }
    const controller = new AbortController();
    setRunsLoading(true);
    setRuns([]);
    setRunsError(null);
    void api
      .listAutomationRuns(selectedJob.id, projectId, controller.signal)
      .then((response) => setRuns(response.items))
      .catch((caught) => {
        if (!controller.signal.aborted) {
          setRunsError(caught instanceof Error ? caught.message : String(caught));
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setRunsLoading(false);
      });
    return () => controller.abort();
  }, [api, projectId, selectedJob]);

  const enabledCount = jobs.filter((job) => job.enabled).length;
  const createCapability = automationActionAvailability(capabilities, 'create', {
    handler_available: false,
    revision_required: false,
  });
  const createReasonCode = automationCapabilityReasonCode(createCapability.reason_code);
  const createReasonId = 'automation-create-disabled-reason';

  return (
    <section className="automations-page" aria-labelledby="automations-title">
      <header className="automations-header">
        <div>
          <Text size="1" weight="bold" color="cyan">
            {t('automations.kicker')}
          </Text>
          <Heading id="automations-title" as="h1" size="6">
            {t('automations.title')}
          </Heading>
          <Text as="p" size="2" color="gray">
            {t('automations.description')}
          </Text>
        </div>
        <div className="automations-header-actions">
          <Button variant="surface" onClick={() => void loadJobs()} disabled={loading || !projectId}>
            <ReloadIcon /> {loading ? t('automations.refreshing') : t('automations.refresh')}
          </Button>
          <Button
            disabled={!createCapability.allowed}
            aria-describedby={!createCapability.allowed ? createReasonId : undefined}
            title={
              !createCapability.allowed
                ? t(`automations.capabilityReason.${createReasonCode}`)
                : undefined
            }
          >
            <PlusIcon /> {t('automations.new')}
          </Button>
          <span id={createReasonId} className="automation-visually-hidden">
            {t(`automations.capabilityReason.${createReasonCode}`)}
          </span>
        </div>
      </header>

      <div className="automations-summary" aria-label={t('automations.summary')}>
        <AutomationMetric label={t('automations.project')} value={projectName || projectId || '—'} />
        <AutomationMetric label={t('automations.total')} value={String(jobs.length)} />
        <AutomationMetric label={t('automations.enabled')} value={String(enabledCount)} />
        <AutomationMetric label={t('automations.contract')} value={t('automations.readOnly')} />
      </div>

      {!projectId ? (
        <AutomationEmpty
          icon={<ActivityLogIcon />}
          title={t('automations.projectRequired')}
          body={t('automations.projectRequiredBody')}
          action={<Button onClick={onOpenConnection}>{t('automations.openSettings')}</Button>}
        />
      ) : unavailable ? (
        <AutomationEmpty
          icon={<ActivityLogIcon />}
          title={t('automations.unavailable')}
          body={t('automations.unavailableBody')}
          action={<Button onClick={onOpenConnection}>{t('automations.openConnection')}</Button>}
        />
      ) : error && jobs.length === 0 ? (
        <AutomationEmpty
          error
          icon={<ActivityLogIcon />}
          title={t('automations.loadFailed')}
          body={error}
          action={<Button onClick={() => void loadJobs()}>{t('automations.retry')}</Button>}
        />
      ) : loading && jobs.length === 0 ? (
        <AutomationEmpty
          icon={<ClockIcon />}
          title={t('automations.loading')}
          body={t('automations.loadingBody')}
        />
      ) : jobs.length === 0 ? (
        <AutomationEmpty
          icon={<ActivityLogIcon />}
          title={t('automations.empty')}
          body={t('automations.emptyBody')}
        />
      ) : (
        <div className="automations-workbench">
          <div className="automations-list" aria-label={t('automations.list')}>
            {jobs.map((job) => (
              <AutomationListItem
                key={job.id}
                job={job}
                selected={job.id === selectedJob?.id}
                onSelect={() => setSelectedJobId(job.id)}
              />
            ))}
          </div>
          {selectedJob ? (
            <AutomationDetail
              job={selectedJob}
              runs={runs}
              runsLoading={runsLoading}
              locale={locale}
              loadError={runsError}
              capabilities={capabilities}
            />
          ) : null}
        </div>
      )}
    </section>
  );
}

function AutomationListItem({
  job,
  selected,
  onSelect,
}: {
  job: AutomationJob;
  selected: boolean;
  onSelect: () => void;
}) {
  const { t } = useI18n();
  const trigger = automationTriggerKind(job);
  const schedule = automationScheduleValue(job);
  return (
    <button
      type="button"
      className={`automation-list-item ${selected ? 'selected' : ''}`}
      aria-pressed={selected}
      onClick={onSelect}
    >
      <span className="automation-list-item-heading">
        <strong>{job.name}</strong>
        <Badge color={job.enabled ? 'green' : 'gray'} variant="soft">
          {job.enabled ? t('automations.active') : t('automations.paused')}
        </Badge>
      </span>
      <span>{job.description || t('automations.noDescription')}</span>
      <small>
        {t(`automations.trigger.${trigger}`)}
        {schedule ? ` · ${schedule}` : ''}
      </small>
    </button>
  );
}

function AutomationDetail({
  job,
  runs,
  runsLoading,
  locale,
  loadError,
  capabilities,
}: {
  job: AutomationJob;
  runs: AutomationRun[];
  runsLoading: boolean;
  locale: string;
  loadError: string | null;
  capabilities: AutomationCapabilities | null;
}) {
  const { t } = useI18n();
  const trigger = automationTriggerKind(job);
  const scheduleValue = automationScheduleValue(job);
  const environmentId = automationEnvironmentId(job);
  const permissionProfile = automationPermissionProfile(job);
  const lastRunStatus = automationLastRunStatus(job);
  const runCapability = automationActionAvailability(capabilities, 'run_now', {
    handler_available: false,
    revision_required: true,
  });
  const capabilityReason = t(
    `automations.capabilityReason.${automationCapabilityReasonCode(runCapability.reason_code)}`,
  );
  return (
    <article className="automation-detail">
      <header>
        <div>
          <Text size="1" color="gray">
            {t(`automations.trigger.${trigger}`)}
          </Text>
          <Heading as="h2" size="4">
            {job.name}
          </Heading>
        </div>
        <Button
          disabled={!runCapability.allowed}
          aria-describedby={!runCapability.allowed ? 'automation-mutation-capability' : undefined}
        >
          <RocketIcon /> {t('automations.runNow')}
        </Button>
      </header>

      <dl className="automation-facts">
        <AutomationFact label={t('automations.schedule')} value={scheduleValue || '—'} />
        <AutomationFact label={t('automations.timezone')} value={job.timezone || '—'} />
        <AutomationFact
          label={t('automations.lastRun')}
          value={formatDate(automationLastRunAt(job), locale, t('automations.never'))}
          detail={
            lastRunStatus
              ? t(`automations.runStatus.${automationRunStatus(lastRunStatus)}`)
              : null
          }
        />
        <AutomationFact
          label={t('automations.nextRun')}
          value={formatDate(automationNextRunAt(job), locale, t('automations.notDeclared'))}
        />
        <AutomationFact
          label={t('automations.environment')}
          value={environmentId || t('automations.notDeclared')}
        />
        <AutomationFact
          label={t('automations.permissionProfile')}
          value={permissionProfile || t('automations.notDeclared')}
        />
        <AutomationFact label={t('automations.payload')} value={job.payload.kind} />
        <AutomationFact label={t('automations.delivery')} value={job.delivery.kind} />
      </dl>

      <div
        id="automation-mutation-capability"
        className="automation-capability-note"
        role="note"
      >
        <strong>{t('automations.readOnlyTitle')}</strong>
        <span>{capabilityReason}</span>
        <span>{t('automations.readOnlyBody')}</span>
      </div>

      <section className="automation-history" aria-labelledby="automation-history-title">
        <header>
          <Heading id="automation-history-title" as="h3" size="3">
            {t('automations.runHistory')}
          </Heading>
          <Text size="1" color="gray">
            {t('automations.runCount', { count: runs.length })}
          </Text>
        </header>
        {runsLoading ? (
          <Text size="2" color="gray">
            {t('automations.loadingRuns')}
          </Text>
        ) : loadError && runs.length === 0 ? (
          <div className="automation-inline-error" role="alert">
            {loadError}
          </div>
        ) : runs.length === 0 ? (
          <Text size="2" color="gray">
            {t('automations.noRuns')}
          </Text>
        ) : (
          <div className="automation-run-list">
            {runs.map((run) => (
              <AutomationRunRow key={run.id} run={run} locale={locale} />
            ))}
          </div>
        )}
      </section>
    </article>
  );
}

function AutomationRunRow({ run, locale }: { run: AutomationRun; locale: string }) {
  const { t } = useI18n();
  const status = automationRunStatus(run.status);
  const trigger = automationRunTrigger(run.trigger_type);
  const color =
    status === 'success'
      ? 'green'
      : status === 'failed' || status === 'timeout'
        ? 'red'
        : status === 'running' || status === 'queued'
          ? 'cyan'
          : 'gray';
  return (
    <article className="automation-run-row">
      <span>
        <Badge color={color} variant="soft">
          {t(`automations.runStatus.${status}`)}
        </Badge>
        <strong>{formatDate(run.started_at, locale, run.started_at)}</strong>
      </span>
      <small>
        {t(`automations.runTrigger.${trigger}`)} ·{' '}
        {run.duration_ms != null
          ? t('automations.durationMs', { count: run.duration_ms })
          : t('automations.durationPending')}
      </small>
      {run.conversation_id ? <code>{run.conversation_id}</code> : null}
      {run.error_message ? <p role="alert">{run.error_message}</p> : null}
    </article>
  );
}

function AutomationMetric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

function AutomationFact({
  label,
  value,
  detail,
}: {
  label: string;
  value: string;
  detail?: string | null;
}) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value}</dd>
      {detail ? <small>{detail}</small> : null}
    </div>
  );
}

function AutomationEmpty({
  icon,
  title,
  body,
  action,
  error = false,
}: {
  icon: React.ReactNode;
  title: string;
  body: string;
  action?: React.ReactNode;
  error?: boolean;
}) {
  return (
    <div className={`automation-empty ${error ? 'error' : ''}`} role={error ? 'alert' : 'status'}>
      <span>{icon}</span>
      <Heading as="h2" size="4">
        {title}
      </Heading>
      <Text as="p" size="2" color="gray">
        {body}
      </Text>
      {action}
    </div>
  );
}

function formatDate(value: string | null, locale: string, fallback: string): string {
  if (!value) return fallback;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(locale, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(date);
}
