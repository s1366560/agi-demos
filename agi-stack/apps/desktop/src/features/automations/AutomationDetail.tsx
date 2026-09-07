import { Pencil1Icon, RocketIcon, TrashIcon } from '@radix-ui/react-icons';
import { AlertDialog, Badge, Button, Heading, Switch, Text } from '@radix-ui/themes';
import { useI18n } from '../../i18n';
import type { AutomationCapabilities, AutomationJob, AutomationRun } from '../../types';
import type { DesktopCapabilityView } from '../runtime/capabilitySnapshot';
import { AutomationRecoveryNotice } from './AutomationRecoveryNotice';
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

export function AutomationDetail({
  job,
  runs,
  runsLoading,
  locale,
  loadError,
  mutationError,
  capabilities,
  runtimeRunCapability,
  busy,
  onEdit,
  onToggle,
  onRun,
  onDelete,
}: {
  job: AutomationJob;
  runs: AutomationRun[];
  runsLoading: boolean;
  locale: string;
  loadError: string | null;
  mutationError: string | null;
  capabilities: AutomationCapabilities | null;
  runtimeRunCapability: DesktopCapabilityView;
  busy: boolean;
  onEdit: () => void;
  onToggle: () => void;
  onRun: () => void;
  onDelete: () => void;
}) {
  const { t } = useI18n();
  const trigger = automationTriggerKind(job);
  const scheduleValue = automationScheduleValue(job);
  const environmentId = automationEnvironmentId(job);
  const permissionProfile = automationPermissionProfile(job);
  const lastRunStatus = automationLastRunStatus(job);
  const declaredRunCapability = automationActionAvailability(capabilities, 'run_now', {
    handler_available: true,
    revision_required: true,
    durable_execution_required: true,
  });
  const runCapability = runtimeRunCapability.available
    ? declaredRunCapability
    : {
        allowed: false,
        reason_code:
          runtimeRunCapability.reason_code ?? 'capability_contract_unavailable',
      };
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
            onClick={onRun}
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

      <AutomationRecoveryNotice
        job={job}
        runAllowed={runCapability.allowed}
        busy={busy}
        onRun={onRun}
      />

      {!runCapability.allowed ? (
        <div id="automation-mutation-capability" className="automation-capability-note" role="note">
          <strong>{t('automations.executionUnavailableTitle')}</strong>
          <span>{capabilityReason}</span>
          <span>{t('automations.executionUnavailableBody')}</span>
        </div>
      ) : null}

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

function formatDate(value: string | null, locale: string, fallback: string): string {
  if (!value) return fallback;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(locale, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(date);
}
