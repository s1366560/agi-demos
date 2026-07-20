import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ActivityLogIcon,
  ClockIcon,
  Pencil1Icon,
  PlusIcon,
  ReloadIcon,
  RocketIcon,
  TrashIcon,
} from '@radix-ui/react-icons';
import { AlertDialog, Badge, Button, Heading, Switch, Text } from '@radix-ui/themes';

import { DesktopApiClient, DesktopApiError } from '../../api/client';
import { useI18n } from '../../i18n';
import type {
  AutomationCapabilities,
  AutomationCreateInput,
  AutomationJob,
  AutomationRun,
} from '../../types';
import { AutomationEditorDialog } from './AutomationEditorDialog';
import {
  automationActionAvailability,
  automationCapabilityReasonCode,
  automationEnvironmentId,
  automationLastRunAt,
  automationLastRunStatus,
  automationMutationKey,
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
    | 'createAutomation'
    | 'deleteAutomation'
    | 'getAutomationCapabilities'
    | 'listAutomations'
    | 'listAutomationRuns'
    | 'toggleAutomation'
    | 'updateAutomation'
  >;
  projectId: string;
  projectName?: string | null;
  onOpenProjectSettings: () => void;
  onOpenConnection: () => void;
};

export function AutomationsPage({
  api,
  projectId,
  projectName,
  onOpenProjectSettings,
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
  const [editorOpen, setEditorOpen] = useState(false);
  const [editorJob, setEditorJob] = useState<AutomationJob | null>(null);
  const [mutationBusy, setMutationBusy] = useState(false);
  const [mutationError, setMutationError] = useState<string | null>(null);
  const mutationKeys = useRef(new Map<string, string>());
  const selectedJob = useMemo(
    () => jobs.find((job) => job.id === selectedJobId) ?? jobs[0] ?? null,
    [jobs, selectedJobId],
  );

  const loadJobs = useCallback(
    async (signal?: AbortSignal) => {
      if (!projectId) {
        setJobs([]);
        setSelectedJobId('');
        setCapabilities(null);
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
          response.items.some((job) => job.id === current)
            ? current
            : (response.items[0]?.id ?? ''),
        );
      } catch (caught) {
        if (signal?.aborted) return;
        const capabilityUnavailable =
          caught instanceof DesktopApiError && [404, 405, 501].includes(caught.status);
        setJobs([]);
        setCapabilities(null);
        setSelectedJobId('');
        setUnavailable(capabilityUnavailable);
        setError(
          capabilityUnavailable ? null : caught instanceof Error ? caught.message : String(caught),
        );
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
    handler_available: true,
    revision_required: false,
    durable_execution_required: false,
  });
  const createReasonCode = automationCapabilityReasonCode(createCapability.reason_code);
  const createReasonId = 'automation-create-disabled-reason';

  const openCreate = () => {
    setEditorJob(null);
    setMutationError(null);
    setEditorOpen(true);
  };

  const openEdit = (job: AutomationJob) => {
    setEditorJob(job);
    setMutationError(null);
    setEditorOpen(true);
  };

  const submitEditor = async (input: Omit<AutomationCreateInput, 'idempotency_key'>) => {
    setMutationBusy(true);
    setMutationError(null);
    try {
      const idempotencyKey = automationMutationKey(
        mutationKeys.current,
        editorJob ? `edit:${editorJob.id}:${editorJob.revision}` : 'create',
        input,
      );
      const saved = editorJob
        ? await api.updateAutomation(
            editorJob.id,
            {
              ...input,
              idempotency_key: idempotencyKey,
              expected_revision: editorJob.revision,
            },
            projectId,
          )
        : await api.createAutomation({ ...input, idempotency_key: idempotencyKey }, projectId);
      setJobs((current) => {
        const exists = current.some((job) => job.id === saved.id);
        return exists
          ? current.map((job) => (job.id === saved.id ? saved : job))
          : [saved, ...current];
      });
      setSelectedJobId(saved.id);
      setEditorOpen(false);
    } catch (caught) {
      setMutationError(caught instanceof Error ? caught.message : String(caught));
      if (caught instanceof DesktopApiError && caught.status === 409) void loadJobs();
    } finally {
      setMutationBusy(false);
    }
  };

  const toggleJob = async (job: AutomationJob) => {
    setMutationBusy(true);
    setMutationError(null);
    try {
      const saved = await api.toggleAutomation(
        job.id,
        {
          idempotency_key: automationMutationKey(
            mutationKeys.current,
            `toggle:${job.id}:${job.revision}`,
            { enabled: !job.enabled },
          ),
          expected_revision: job.revision,
          enabled: !job.enabled,
        },
        projectId,
      );
      setJobs((current) => current.map((item) => (item.id === saved.id ? saved : item)));
    } catch (caught) {
      setMutationError(caught instanceof Error ? caught.message : String(caught));
      if (caught instanceof DesktopApiError && caught.status === 409) void loadJobs();
    } finally {
      setMutationBusy(false);
    }
  };

  const deleteJob = async (job: AutomationJob) => {
    setMutationBusy(true);
    setMutationError(null);
    try {
      await api.deleteAutomation(
        job.id,
        {
          idempotency_key: automationMutationKey(
            mutationKeys.current,
            `delete:${job.id}:${job.revision}`,
            {},
          ),
          expected_revision: job.revision,
        },
        projectId,
      );
      setJobs((current) => current.filter((item) => item.id !== job.id));
      setSelectedJobId('');
    } catch (caught) {
      setMutationError(caught instanceof Error ? caught.message : String(caught));
      if (caught instanceof DesktopApiError && caught.status === 409) void loadJobs();
    } finally {
      setMutationBusy(false);
    }
  };

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
          <Button
            variant="surface"
            onClick={() => void loadJobs()}
            disabled={loading || !projectId}
          >
            <ReloadIcon /> {loading ? t('automations.refreshing') : t('automations.refresh')}
          </Button>
          <Button
            onClick={openCreate}
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
          {!createCapability.allowed ? (
            <span id={createReasonId} className="automation-visually-hidden">
              {t(`automations.capabilityReason.${createReasonCode}`)}
            </span>
          ) : null}
        </div>
      </header>

      <div className="automations-summary" aria-label={t('automations.summary')}>
        <AutomationMetric
          label={t('automations.project')}
          value={projectName || projectId || '—'}
        />
        <AutomationMetric label={t('automations.total')} value={String(jobs.length)} />
        <AutomationMetric label={t('automations.enabled')} value={String(enabledCount)} />
        <AutomationMetric
          label={t('automations.contract')}
          value={
            capabilities?.revision_guarded && capabilities.idempotency_guarded
              ? t('automations.guardedWrites')
              : t('automations.readOnly')
          }
        />
      </div>

      {!projectId ? (
        <AutomationEmpty
          icon={<ActivityLogIcon />}
          title={t('automations.projectRequired')}
          body={t('automations.projectRequiredBody')}
          action={<Button onClick={onOpenProjectSettings}>{t('automations.openSettings')}</Button>}
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
          action={
            createCapability.allowed ? (
              <Button onClick={openCreate}>
                <PlusIcon /> {t('automations.new')}
              </Button>
            ) : undefined
          }
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
              mutationError={mutationError}
              capabilities={capabilities}
              busy={mutationBusy}
              onEdit={() => openEdit(selectedJob)}
              onToggle={() => void toggleJob(selectedJob)}
              onDelete={() => void deleteJob(selectedJob)}
            />
          ) : null}
        </div>
      )}
      <AutomationEditorDialog
        open={editorOpen}
        job={editorJob}
        busy={mutationBusy}
        error={mutationError}
        onOpenChange={setEditorOpen}
        onSubmit={submitEditor}
      />
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
  mutationError,
  capabilities,
  busy,
  onEdit,
  onToggle,
  onDelete,
}: {
  job: AutomationJob;
  runs: AutomationRun[];
  runsLoading: boolean;
  locale: string;
  loadError: string | null;
  mutationError: string | null;
  capabilities: AutomationCapabilities | null;
  busy: boolean;
  onEdit: () => void;
  onToggle: () => void;
  onDelete: () => void;
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
    durable_execution_required: true,
  });
  const editCapability = automationActionAvailability(capabilities, 'edit', {
    handler_available: true,
    revision_required: true,
    durable_execution_required: false,
  });
  const toggleCapability = automationActionAvailability(capabilities, 'toggle', {
    handler_available: true,
    revision_required: true,
    durable_execution_required: false,
  });
  const deleteCapability = automationActionAvailability(capabilities, 'delete', {
    handler_available: true,
    revision_required: true,
    durable_execution_required: false,
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
        <div className="automation-detail-actions">
          <label className="automation-toggle-control">
            <Switch
              checked={job.enabled}
              disabled={busy || !toggleCapability.allowed}
              onCheckedChange={onToggle}
            />
            <Text size="1">{job.enabled ? t('automations.active') : t('automations.paused')}</Text>
          </label>
          <Button variant="soft" onClick={onEdit} disabled={busy || !editCapability.allowed}>
            <Pencil1Icon /> {t('automations.edit')}
          </Button>
          <AlertDialog.Root>
            <AlertDialog.Trigger>
              <Button color="red" variant="soft" disabled={busy || !deleteCapability.allowed}>
                <TrashIcon /> {t('automations.delete')}
              </Button>
            </AlertDialog.Trigger>
            <AlertDialog.Content maxWidth="420px">
              <AlertDialog.Title>{t('automations.deleteTitle')}</AlertDialog.Title>
              <AlertDialog.Description>
                {t('automations.deleteDescription', { name: job.name })}
              </AlertDialog.Description>
              <div className="automation-confirm-actions">
                <AlertDialog.Cancel>
                  <Button variant="soft" color="gray">
                    {t('automations.form.cancel')}
                  </Button>
                </AlertDialog.Cancel>
                <AlertDialog.Action>
                  <Button color="red" onClick={onDelete}>
                    {t('automations.deleteConfirm')}
                  </Button>
                </AlertDialog.Action>
              </div>
            </AlertDialog.Content>
          </AlertDialog.Root>
          <Button
            disabled={busy || !runCapability.allowed}
            aria-describedby={!runCapability.allowed ? 'automation-mutation-capability' : undefined}
          >
            <RocketIcon /> {t('automations.runNow')}
          </Button>
        </div>
      </header>

      <dl className="automation-facts">
        <AutomationFact label={t('automations.schedule')} value={scheduleValue || '—'} />
        <AutomationFact label={t('automations.timezone')} value={job.timezone || '—'} />
        <AutomationFact
          label={t('automations.lastRun')}
          value={formatDate(automationLastRunAt(job), locale, t('automations.never'))}
          detail={
            lastRunStatus ? t(`automations.runStatus.${automationRunStatus(lastRunStatus)}`) : null
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

      <div id="automation-mutation-capability" className="automation-capability-note" role="note">
        <strong>{t('automations.executionUnavailableTitle')}</strong>
        <span>{capabilityReason}</span>
        <span>{t('automations.executionUnavailableBody')}</span>
      </div>

      {mutationError ? (
        <div className="automation-inline-error" role="alert">
          {mutationError}
        </div>
      ) : null}

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
