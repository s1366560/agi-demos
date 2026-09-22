import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ActivityLogIcon,
  ClockIcon,
  PlusIcon,
  ReloadIcon,
} from '@radix-ui/react-icons';
import { Badge, Button, Heading, Text } from '@radix-ui/themes';

import { DesktopApiError } from '../../api/client';
import { useI18n } from '../../i18n';
import type {
  AutomationCapabilities,
  AutomationCreateInput,
  AutomationJob,
  AutomationRun,
} from '../../types';
import type { DesktopCapabilityView } from '../runtime/capabilitySnapshot';
import { AutomationEditorDialog } from './AutomationEditorDialog';
import { AutomationDetail } from './AutomationDetail';
import {
  automationRunAttemptKey,
  settleAutomationRunAttempt,
  type DesktopAutomationApi,
} from './automationClient';
import {
  automationActionAvailability,
  automationCapabilityReasonCode,
  automationManualRunInput,
  automationMutationKey,
  automationScheduleValue,
  automationTriggerKind,
} from './automationModel';
import {
  EMPTY_AUTOMATION_CONVERSATIONS,
  type AutomationConversationChoice,
} from './automationConversationModel';
import './AutomationsPage.css';

type AutomationsPageProps = {
  api: DesktopAutomationApi;
  projectId: string;
  projectName?: string | null;
  conversations?: readonly AutomationConversationChoice[];
  runCapability: DesktopCapabilityView;
  onOpenProjectSettings: () => void;
  onOpenConnection: () => void;
  onOpenConversation?: (choice: AutomationConversationChoice) => void;
};

export function AutomationsPage({
  api,
  projectId,
  projectName,
  conversations = EMPTY_AUTOMATION_CONVERSATIONS,
  runCapability,
  onOpenConversation,
  onOpenProjectSettings,
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
  const [editorOpen, setEditorOpen] = useState(false);
  const [editorJob, setEditorJob] = useState<AutomationJob | null>(null);
  const [mutationBusy, setMutationBusy] = useState(false);
  const [mutationError, setMutationError] = useState<string | null>(null);
  const editorFocusReturnRef = useRef<HTMLElement | null>(null);
  const editorFocusFrameRef = useRef<number | null>(null);
  const mutationKeys = useRef(new Map<string, string>());
  const runAttempts = useRef(
    new Map<string, { fingerprint: string; idempotencyKey: string }>(),
  );
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
        return;
      }
      setLoading(true);
      setError(null);
      try {
        const response = await api.listAutomations(projectId, signal);
        setJobs(response.items);
        setSelectedJobId((current) =>
          response.items.some((job) => job.id === current)
            ? current
            : (response.items[0]?.id ?? ''),
        );
        try {
          setCapabilities(await api.getAutomationCapabilities(projectId, signal));
        } catch (caught) {
          if (signal?.aborted) throw caught;
          setCapabilities(null);
        }
      } catch (caught) {
        if (signal?.aborted) return;
        setJobs([]);
        setCapabilities(null);
        setSelectedJobId('');
        setError(caught instanceof Error ? caught.message : String(caught));
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

  useEffect(
    () => () => {
      if (editorFocusFrameRef.current !== null) {
        cancelAnimationFrame(editorFocusFrameRef.current);
      }
    },
    [],
  );

  const enabledCount = jobs.filter((job) => job.enabled).length;
  const createCapability = automationActionAvailability(capabilities, 'create', {
    handler_available: true,
    revision_required: false,
    durable_execution_required: false,
  });
  const createReasonCode = automationCapabilityReasonCode(createCapability.reason_code);
  const createReasonId = 'automation-create-disabled-reason';

  const rememberEditorFocusReturn = () => {
    editorFocusReturnRef.current =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
  };

  const setEditorOpenWithFocusReturn = (open: boolean) => {
    setEditorOpen(open);
    if (open) return;
    const target = editorFocusReturnRef.current;
    editorFocusReturnRef.current = null;
    if (!target) return;
    if (editorFocusFrameRef.current !== null) {
      cancelAnimationFrame(editorFocusFrameRef.current);
    }
    editorFocusFrameRef.current = requestAnimationFrame(() => {
      editorFocusFrameRef.current = null;
      if (target.isConnected) target.focus({ preventScroll: true });
    });
  };

  const openCreate = () => {
    rememberEditorFocusReturn();
    setEditorJob(null);
    setMutationError(null);
    setEditorOpen(true);
  };

  const openEdit = (job: AutomationJob) => {
    rememberEditorFocusReturn();
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
      setEditorOpenWithFocusReturn(false);
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

  const runJob = async (job: AutomationJob) => {
    setMutationBusy(true);
    setMutationError(null);
    const attemptScope = `${projectId}:${job.id}`;
    const attemptInput = automationManualRunInput(job);
    const idempotencyKey = automationRunAttemptKey(
      runAttempts.current,
      attemptScope,
      attemptInput,
    );
    try {
      await api.runAutomation(
        job.id,
        {
          ...attemptInput,
          idempotency_key: idempotencyKey,
        },
        projectId,
      );
      settleAutomationRunAttempt(runAttempts.current, attemptScope);
      const [jobResponse, runResponse] = await Promise.all([
        api.listAutomations(projectId),
        api.listAutomationRuns(job.id, projectId),
      ]);
      setJobs(jobResponse.items);
      setRuns(runResponse.items);
    } catch (caught) {
      settleAutomationRunAttempt(runAttempts.current, attemptScope, caught);
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
          <Heading id="automations-title" as="h1" size="6">
            {t('automations.title')}
          </Heading>
          <dl className="automations-summary" aria-label={t('automations.summary')}>
            <AutomationMetric
              label={t('automations.project')}
              value={projectName || projectId || '—'}
            />
            <AutomationMetric label={t('automations.total')} value={String(jobs.length)} />
            <AutomationMetric label={t('automations.enabled')} value={String(enabledCount)} />
          </dl>
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


      {!projectId ? (
        <AutomationEmpty
          icon={<ActivityLogIcon />}
          title={t('automations.projectRequired')}
          body={t('automations.projectRequiredBody')}
          action={<Button onClick={onOpenProjectSettings}>{t('automations.openSettings')}</Button>}
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
              conversations={conversations}
              onOpenConversation={onOpenConversation}
              runs={runs}
              runsLoading={runsLoading}
              locale={locale}
              loadError={runsError}
              mutationError={mutationError}
              capabilities={capabilities}
              runtimeRunCapability={runCapability}
              busy={mutationBusy}
              onEdit={() => openEdit(selectedJob)}
              onToggle={() => void toggleJob(selectedJob)}
              onRun={() => void runJob(selectedJob)}
              onDelete={() => void deleteJob(selectedJob)}
            />
          ) : null}
        </div>
      )}
      <AutomationEditorDialog
        open={editorOpen}
        job={editorJob}
        conversations={conversations}
        busy={mutationBusy}
        error={mutationError}
        onOpenChange={setEditorOpenWithFocusReturn}
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

function AutomationMetric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value}</dd>
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
