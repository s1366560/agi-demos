import React, { useMemo, useState } from 'react';

import { useTranslation } from 'react-i18next';

import { Button, Tabs } from 'antd';
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Clock,
  FileText,
  ListChecks,
  Radio,
  RefreshCcw,
  ShieldAlert,
  X,
} from 'lucide-react';

import { confirmAction } from '@/utils/confirmAction';
import { formatDateTime } from '@/utils/date';
import { formatTaskProjectionLabel } from '@/utils/workspaceTaskProjection';

import { parseCanonicalStory } from '../agent/canonicalStory/canonicalStory';
import { CanonicalStoryCard } from '../agent/canonicalStory/CanonicalStoryCard';

import type {
  TaskExecutionSession,
  TaskRecoveryAction,
  WorkspaceAgent,
  WorkspaceTask,
  WorkspaceTaskExperienceSummary,
  WorkspaceTaskTransitionGate,
} from '@/types/workspace';

import type { TFunction } from 'i18next';

interface TaskExperiencePanelProps {
  task: WorkspaceTask;
  agents: WorkspaceAgent[];
  experience: WorkspaceTaskExperienceSummary | null;
  executionSession: TaskExecutionSession | null;
  loading: boolean;
  recoveryActionLoading: boolean;
  error: string | null;
  onRecoveryAction: (action: TaskRecoveryAction) => void;
  onClose: () => void;
  /** Optional refetch handler — renders a Retry action in the error banner. */
  onRetry?: (() => void) | undefined;
  embedded?: boolean;
  className?: string;
}

type PanelTab = 'overview' | 'contract' | 'execution' | 'evidence' | 'diagnostics' | 'activity';

const TAB_KEYS: PanelTab[] = [
  'overview',
  'contract',
  'execution',
  'evidence',
  'diagnostics',
  'activity',
];

const UNKNOWN_SESSION_HEALTH_TONE =
  'border-border-light bg-surface-muted text-text-secondary dark:border-border-dark dark:bg-background-dark dark:text-text-muted';

const SESSION_HEALTH_TONES: Record<string, string> = {
  healthy:
    'border-success-border bg-success-bg text-status-text-success dark:border-success-border-dark dark:bg-success-bg-dark dark:text-status-text-success-dark',
  warning:
    'border-warning-border bg-warning-bg text-status-text-warning dark:border-warning-border-dark dark:bg-warning-bg-dark dark:text-status-text-warning-dark',
  degraded:
    'border-error-border bg-error-bg text-status-text-error dark:border-error-border-dark dark:bg-error-bg-dark dark:text-status-text-error-dark',
  blocked:
    'border-error-border bg-error-bg text-status-text-error dark:border-error-border-dark dark:bg-error-bg-dark dark:text-status-text-error-dark',
  unknown: UNKNOWN_SESSION_HEALTH_TONE,
};

const RECOVERY_ACTION_ORDER: TaskRecoveryAction[] = [
  'new_attempt',
  'retry_launch',
  'terminate_stale_conversation',
  'mark_human_blocked',
];

/** Recovery actions that change/destroy execution state — require confirmation. */
const DESTRUCTIVE_RECOVERY_ACTIONS = new Set<TaskRecoveryAction>([
  'terminate_stale_conversation',
  'mark_human_blocked',
]);

function taskExperienceText(
  t: TFunction,
  key: string,
  defaultValue: string,
  options?: Record<string, unknown>
): string {
  return t(`workspaceDetail.taskExperience.${key}`, {
    defaultValue,
    ...options,
  });
}

export const TaskExperiencePanel: React.FC<TaskExperiencePanelProps> = ({
  task,
  agents,
  experience,
  executionSession,
  loading,
  recoveryActionLoading,
  error,
  onRecoveryAction,
  onClose,
  onRetry,
  embedded = false,
  className,
}) => {
  const { t } = useTranslation();
  const assignedAgent = useMemo(() => resolveAgentLabel(task, agents), [agents, task]);
  const readiness = experience?.readiness;
  const evidence = experience?.evidence;
  const execution = experience?.execution ?? {};
  const diagnostics = experience?.diagnostics ?? {};
  const activity = experience?.activity ?? [];
  const gates = readiness?.transition_gates ?? diagnostics.transition_gates ?? {};

  const items = TAB_KEYS.map((key) => ({
    key,
    label: tabLabel(key, t),
    children:
      key === 'overview' ? (
        <OverviewTab
          task={task}
          assignedAgent={assignedAgent}
          experience={experience}
          executionSession={executionSession}
          recoveryActionLoading={recoveryActionLoading}
          onRecoveryAction={onRecoveryAction}
        />
      ) : key === 'contract' ? (
        <ContractTab readiness={readiness} gates={gates} />
      ) : key === 'execution' ? (
        <ExecutionTab
          task={task}
          execution={execution}
          assignedAgent={assignedAgent}
          executionSession={executionSession}
        />
      ) : key === 'evidence' ? (
        <EvidenceTab evidence={evidence} />
      ) : key === 'diagnostics' ? (
        <DiagnosticsTab
          task={task}
          diagnostics={diagnostics}
          gates={gates}
          executionSession={executionSession}
        />
      ) : (
        <ActivityTab activity={activity} />
      ),
  }));
  const panelClassName = [
    embedded
      ? 'min-h-0 bg-transparent'
      : 'min-h-[360px] rounded-lg border border-border-light bg-surface-light shadow-sm dark:border-border-dark dark:bg-surface-dark',
    className,
  ]
    .filter(Boolean)
    .join(' ');
  const headerClassName = [
    'flex items-start gap-3 border-b border-border-light dark:border-border-dark',
    embedded ? 'px-4 py-4' : 'px-4 py-3',
  ].join(' ');

  return (
    <aside
      className={panelClassName}
      aria-label={taskExperienceText(t, 'title', 'Task experience')}
    >
      <div className={headerClassName}>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="rounded-full border border-border-light bg-surface-muted px-2 py-0.5 text-[10px] font-semibold uppercase text-text-secondary dark:border-border-dark dark:bg-background-dark dark:text-text-muted">
              {formatTaskProjectionLabel(task.status)}
            </span>
            {task.priority && (
              <span className="rounded-full border border-border-light bg-surface-muted px-2 py-0.5 text-[10px] font-semibold uppercase text-text-secondary dark:border-border-dark dark:bg-background-dark dark:text-text-muted">
                {task.priority}
              </span>
            )}
          </div>
          <h3 className="mt-2 break-words text-sm font-semibold leading-5 text-text-primary dark:text-text-inverse">
            {task.title}
          </h3>
          {task.description &&
            (() => {
              const parsed = parseCanonicalStory(task.description);
              if (parsed.story) {
                return (
                  <div className="mt-2">
                    <CanonicalStoryCard result={parsed} defaultOpen />
                  </div>
                );
              }
              return (
                <p className="mt-1 line-clamp-2 text-xs leading-5 text-text-secondary dark:text-text-muted">
                  {task.description}
                </p>
              );
            })()}
        </div>
        <Button
          type="text"
          size="small"
          icon={<X size={14} />}
          aria-label={taskExperienceText(t, 'close', 'Close task details')}
          onClick={onClose}
        />
      </div>

      {loading && (
        <div className="space-y-2 px-4 py-3" role="status">
          <div className="h-3 w-3/4 rounded bg-surface-muted dark:bg-background-dark" />
          <div className="h-3 w-1/2 rounded bg-surface-muted dark:bg-background-dark" />
          <div className="h-3 w-2/3 rounded bg-surface-muted dark:bg-background-dark" />
        </div>
      )}

      {error && !loading && (
        <div
          role="alert"
          className="mx-4 mt-3 flex items-center justify-between gap-2 rounded-md border border-warning-border bg-warning-bg px-3 py-2 text-xs text-status-text-warning dark:border-warning-border-dark dark:bg-warning-bg-dark dark:text-status-text-warning-dark"
        >
          <span>{error}</span>
          {onRetry && (
            <button
              type="button"
              onClick={onRetry}
              className="shrink-0 rounded px-2 py-0.5 font-medium transition-colors hover:bg-warning-border/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
            >
              {t('common.retry', { defaultValue: 'Retry' })}
            </button>
          )}
        </div>
      )}

      <Tabs
        size="small"
        tabBarGutter={8}
        className="task-experience-tabs px-4 pb-4"
        items={items}
        destroyOnHidden={false}
      />
    </aside>
  );
};

function OverviewTab({
  task,
  assignedAgent,
  experience,
  executionSession,
  recoveryActionLoading,
  onRecoveryAction,
}: {
  task: WorkspaceTask;
  assignedAgent: string;
  experience: WorkspaceTaskExperienceSummary | null;
  executionSession: TaskExecutionSession | null;
  recoveryActionLoading: boolean;
  onRecoveryAction: (action: TaskRecoveryAction) => void;
}) {
  const { t } = useTranslation();
  const diagnostics = experience?.diagnostics ?? {};
  const evidence = experience?.evidence ?? {};
  return (
    <div className="space-y-4">
      <SessionHealthSection
        session={executionSession}
        recoveryActionLoading={recoveryActionLoading}
        onRecoveryAction={onRecoveryAction}
      />
      <Section
        title={taskExperienceText(t, 'sections.status', 'Status')}
        icon={<Radio size={13} />}
      >
        <MetaRow
          label={taskExperienceText(t, 'labels.workspaceTask', 'Workspace task')}
          value={task.id}
          mono
        />
        <MetaRow
          label={taskExperienceText(t, 'labels.assignee', 'Assignee')}
          value={
            assignedAgent ||
            task.assignee_user_id ||
            taskExperienceText(t, 'values.unassigned', 'Unassigned')
          }
        />
        <MetaRow
          label={taskExperienceText(t, 'labels.pendingAdjudication', 'Pending adjudication')}
          value={boolText(diagnostics.pending_leader_adjudication, t)}
        />
        <MetaRow
          label={taskExperienceText(t, 'labels.missingConversation', 'Missing conversation')}
          value={boolText(diagnostics.missing_conversation, t)}
        />
      </Section>
      <Section
        title={taskExperienceText(t, 'sections.evidenceSignal', 'Evidence signal')}
        icon={<CheckCircle2 size={13} />}
      >
        <MetaRow
          label={taskExperienceText(t, 'labels.goalGrade', 'Goal grade')}
          value={textValue(evidence.goal_evidence_grade)}
        />
        <InlineList
          label={taskExperienceText(t, 'labels.artifacts', 'Artifacts')}
          items={stringList(evidence.artifacts)}
        />
        <InlineList
          label={taskExperienceText(t, 'labels.checks', 'Checks')}
          items={stringList(evidence.verification_summaries)}
        />
      </Section>
    </div>
  );
}

function ContractTab({
  readiness,
  gates,
}: {
  readiness: WorkspaceTaskExperienceSummary['readiness'] | undefined;
  gates:
    | Record<string, WorkspaceTaskTransitionGate>
    | Partial<Record<string, WorkspaceTaskTransitionGate>>;
}) {
  const { t } = useTranslation();
  const contract = readiness?.goal_contract ?? {};
  return (
    <div className="space-y-4">
      <Section
        title={taskExperienceText(t, 'sections.goalContract', 'Goal contract')}
        icon={<FileText size={13} />}
      >
        <MetaRow
          label={taskExperienceText(t, 'labels.role', 'Role')}
          value={textValue(contract.task_role)}
        />
        <MetaRow
          label={taskExperienceText(t, 'labels.rootGoal', 'Root goal')}
          value={textValue(contract.root_goal_task_id)}
          mono
        />
        <MetaRow
          label={taskExperienceText(t, 'labels.health', 'Health')}
          value={textValue(contract.goal_health)}
        />
        <MetaRow
          label={taskExperienceText(t, 'labels.remediation', 'Remediation')}
          value={textValue(contract.remediation_status)}
        />
        <MetaRow
          label={taskExperienceText(t, 'labels.progress', 'Progress')}
          value={textValue(contract.goal_progress_summary)}
        />
      </Section>
      <Section
        title={taskExperienceText(t, 'sections.transitionGates', 'Transition gates')}
        icon={<ListChecks size={13} />}
      >
        <GateRow label={taskExperienceText(t, 'labels.done', 'Done')} gate={gates.done} />
        <GateRow label={taskExperienceText(t, 'labels.blocked', 'Blocked')} gate={gates.blocked} />
        <InlineList
          label={taskExperienceText(t, 'labels.missingEvidence', 'Missing evidence')}
          items={readiness?.missing_evidence ?? []}
        />
        <InlineList
          label={taskExperienceText(t, 'labels.blockedRequirements', 'Blocked requirements')}
          items={readiness?.blocked_requirements ?? []}
        />
      </Section>
    </div>
  );
}

function ExecutionTab({
  task,
  execution,
  assignedAgent,
  executionSession,
}: {
  task: WorkspaceTask;
  execution: Record<string, unknown>;
  assignedAgent: string;
  executionSession: TaskExecutionSession | null;
}) {
  const { t } = useTranslation();
  const activeAttempt = asRecord(execution.active_attempt);
  return (
    <div className="space-y-4">
      <ExecutionSessionSection session={executionSession} />
      <Section
        title={taskExperienceText(t, 'sections.currentOwner', 'Current owner')}
        icon={<Activity size={13} />}
      >
        <MetaRow
          label={taskExperienceText(t, 'labels.agent', 'Agent')}
          value={assignedAgent || textValue(execution.assignee_agent_id)}
        />
        <MetaRow
          label={taskExperienceText(t, 'labels.user', 'User')}
          value={textValue(execution.assignee_user_id ?? task.assignee_user_id)}
        />
        <MetaRow
          label={taskExperienceText(t, 'labels.workspaceBinding', 'Workspace binding')}
          value={textValue(execution.workspace_agent_id)}
          mono
        />
      </Section>
      <Section
        title={taskExperienceText(t, 'sections.attempt', 'Attempt')}
        icon={<Radio size={13} />}
      >
        <MetaRow
          label={taskExperienceText(t, 'labels.attemptId', 'Attempt id')}
          value={textValue(execution.current_attempt_id)}
          mono
        />
        <MetaRow
          label={taskExperienceText(t, 'labels.attemptNumber', 'Attempt number')}
          value={textValue(execution.current_attempt_number)}
        />
        <MetaRow
          label={taskExperienceText(t, 'labels.conversation', 'Conversation')}
          value={textValue(execution.current_attempt_conversation_id)}
          mono
        />
        <MetaRow
          label={taskExperienceText(t, 'labels.workerBinding', 'Worker binding')}
          value={textValue(execution.current_attempt_worker_binding_id)}
          mono
        />
        <MetaRow
          label={taskExperienceText(t, 'labels.workerAgent', 'Worker agent')}
          value={textValue(execution.current_attempt_worker_agent_id)}
          mono
        />
        <MetaRow
          label={taskExperienceText(t, 'labels.activeStatus', 'Active status')}
          value={textValue(activeAttempt.status)}
        />
        <MetaRow
          label={taskExperienceText(t, 'labels.lastAttempt', 'Last attempt')}
          value={textValue(execution.last_attempt_status)}
        />
      </Section>
    </div>
  );
}

function SessionHealthSection({
  session,
  recoveryActionLoading,
  onRecoveryAction,
}: {
  session: TaskExecutionSession | null;
  recoveryActionLoading: boolean;
  onRecoveryAction: (action: TaskRecoveryAction) => void;
}) {
  const { t } = useTranslation();
  if (!session) {
    return (
      <Section
        title={taskExperienceText(t, 'sections.executionSession', 'Execution session')}
        icon={<ShieldAlert size={13} />}
      >
        <EmptyLine label={taskExperienceText(t, 'empty.noSessionData', 'No session data')} />
      </Section>
    );
  }
  const runnableActions = RECOVERY_ACTION_ORDER.filter((action) =>
    session.available_interventions.includes(action)
  );
  return (
    <Section
      title={taskExperienceText(t, 'sections.executionSession', 'Execution session')}
      icon={<ShieldAlert size={13} />}
    >
      <div className="flex flex-wrap items-center gap-1.5">
        <span
          className={`inline-flex rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase ${
            SESSION_HEALTH_TONES[session.health] ?? UNKNOWN_SESSION_HEALTH_TONE
          }`}
        >
          {formatTaskProjectionLabel(session.health)}
        </span>
        <span className="inline-flex rounded-full border border-border-light bg-surface-muted px-2 py-0.5 text-[10px] font-semibold uppercase text-text-secondary dark:border-border-dark dark:bg-background-dark dark:text-text-muted">
          {formatTaskProjectionLabel(session.session_status)}
        </span>
      </div>
      <MetaRow
        label={taskExperienceText(t, 'labels.conversation', 'Conversation')}
        value={session.conversation_id}
        mono
      />
      <MetaRow
        label={taskExperienceText(t, 'labels.attempt', 'Attempt')}
        value={session.attempt_id}
        mono
      />
      <MetaRow
        label={taskExperienceText(t, 'labels.leaderDecision', 'Leader decision')}
        value={formatTaskProjectionLabel(textValue(session.recommended_recovery_action))}
      />
      <MetaRow
        label={taskExperienceText(t, 'labels.lastEvent', 'Last event')}
        value={formatTimestamp(session.last_event_at)}
      />
      <MetaRow
        label={taskExperienceText(t, 'labels.assistantEvent', 'Assistant event')}
        value={formatTimestamp(session.last_assistant_event_at)}
      />
      <MetaRow
        label={taskExperienceText(t, 'labels.lastError', 'Last error')}
        value={session.last_error}
      />
      <InlineList
        label={taskExperienceText(t, 'labels.incidents', 'Incidents')}
        items={session.incidents.map((incident) => incident.type)}
      />
      {runnableActions.length > 0 && (
        <RecoveryActionRow
          actions={runnableActions}
          loading={recoveryActionLoading}
          onRecoveryAction={onRecoveryAction}
        />
      )}
      {session.available_interventions.includes('reassign') && (
        <MetaRow
          label={taskExperienceText(t, 'actions.reassign', 'Reassign')}
          value={taskExperienceText(
            t,
            'values.reassignAvailable',
            'Available from agent assignment control'
          )}
        />
      )}
    </Section>
  );
}

function ExecutionSessionSection({ session }: { session: TaskExecutionSession | null }) {
  const { t } = useTranslation();
  if (!session) {
    return (
      <Section
        title={taskExperienceText(t, 'sections.sessionRuntime', 'Session runtime')}
        icon={<Clock size={13} />}
      >
        <EmptyLine label={taskExperienceText(t, 'empty.noRuntimeState', 'No runtime state')} />
      </Section>
    );
  }
  return (
    <Section
      title={taskExperienceText(t, 'sections.sessionRuntime', 'Session runtime')}
      icon={<Clock size={13} />}
    >
      <MetaRow
        label={taskExperienceText(t, 'labels.session', 'Session')}
        value={formatTaskProjectionLabel(session.session_status)}
      />
      <MetaRow
        label={taskExperienceText(t, 'labels.executionRow', 'Execution row')}
        value={session.execution_status}
      />
      <MetaRow
        label={taskExperienceText(t, 'labels.userInput', 'User input')}
        value={boolText(session.has_user_input, t)}
      />
      <MetaRow
        label={taskExperienceText(t, 'labels.assistantOutput', 'Assistant output')}
        value={boolText(session.has_assistant_output, t)}
      />
      <InlineList
        label={taskExperienceText(t, 'labels.recentEvents', 'Recent events')}
        items={session.recent_events.map((event) => textValue(event.type))}
      />
    </Section>
  );
}

function IncidentSection({ session }: { session: TaskExecutionSession | null }) {
  const { t } = useTranslation();
  if (!session) {
    return (
      <Section
        title={taskExperienceText(t, 'sections.sessionIncidents', 'Session incidents')}
        icon={<AlertTriangle size={13} />}
      >
        <EmptyLine label={taskExperienceText(t, 'empty.noSessionData', 'No session data')} />
      </Section>
    );
  }
  const ledger = session.recovery_actions.map((item) =>
    [textValue(item.action), textValue(item.status), formatTimestamp(item.at)]
      .filter(Boolean)
      .join(' · ')
  );
  return (
    <Section
      title={taskExperienceText(t, 'sections.sessionIncidents', 'Session incidents')}
      icon={<AlertTriangle size={13} />}
    >
      {session.incidents.length === 0 ? (
        <EmptyLine label={taskExperienceText(t, 'empty.noOpenIncidents', 'No open incidents')} />
      ) : (
        session.incidents.map((incident) => (
          <div
            key={`${incident.type}-${incident.opened_at ?? ''}`}
            className="border-b border-border-light py-2 last:border-0 dark:border-border-dark"
          >
            <p className="text-xs font-medium text-text-primary dark:text-text-inverse">
              {formatTaskProjectionLabel(incident.type)}
            </p>
            <p className="mt-0.5 break-words text-[11px] leading-4 text-text-secondary dark:text-text-muted">
              {incident.summary}
            </p>
            {incident.opened_at && (
              <p className="mt-1 font-mono text-[10px] text-text-muted dark:text-text-muted">
                {formatTimestamp(incident.opened_at)}
              </p>
            )}
          </div>
        ))
      )}
      <InlineList
        label={taskExperienceText(t, 'labels.recoveryLedger', 'Recovery ledger')}
        items={ledger}
      />
    </Section>
  );
}

function RecoveryActionRow({
  actions,
  loading,
  onRecoveryAction,
}: {
  actions: TaskRecoveryAction[];
  loading: boolean;
  onRecoveryAction: (action: TaskRecoveryAction) => void;
}) {
  const { t } = useTranslation();
  const [clickedAction, setClickedAction] = useState<TaskRecoveryAction | null>(null);

  const effectiveClicked = loading ? clickedAction : null;

  const handleClick = (action: TaskRecoveryAction) => {
    setClickedAction(action);
    if (!DESTRUCTIVE_RECOVERY_ACTIONS.has(action)) {
      onRecoveryAction(action);
      return;
    }

    void confirmAction({
      title: taskExperienceText(t, 'confirm.recoveryTitle', 'Run this recovery action?'),
      content: taskExperienceText(
        t,
        'confirm.recoveryContent',
        '"{{action}}" changes the execution state of this task.',
        { action: recoveryActionLabel(action, t) }
      ),
      okText: t('common.confirm', { defaultValue: 'Confirm' }),
      cancelText: t('common.cancel', { defaultValue: 'Cancel' }),
      danger: true,
    }).then((confirmed) => {
      if (confirmed) {
        onRecoveryAction(action);
      } else {
        setClickedAction(null);
      }
    });
  };

  return (
    <div className="grid grid-cols-[112px_minmax(0,1fr)] gap-2 text-xs">
      <span className="text-text-muted dark:text-text-muted">
        {taskExperienceText(t, 'labels.actions', 'Actions')}
      </span>
      <div className="flex min-w-0 flex-wrap gap-1.5">
        {actions.map((action) => (
          <Button
            key={action}
            size="small"
            icon={<RefreshCcw size={12} />}
            loading={loading && effectiveClicked === action}
            danger={action === 'mark_human_blocked'}
            onClick={() => {
              handleClick(action);
            }}
          >
            {recoveryActionLabel(action, t)}
          </Button>
        ))}
      </div>
    </div>
  );
}

function EvidenceTab({
  evidence,
}: {
  evidence: WorkspaceTaskExperienceSummary['evidence'] | undefined;
}) {
  const { t } = useTranslation();
  const workerReport = asRecord(evidence?.worker_report);
  return (
    <div className="space-y-4">
      <Section
        title={taskExperienceText(t, 'sections.evidence', 'Evidence')}
        icon={<CheckCircle2 size={13} />}
      >
        <InlineList
          label={taskExperienceText(t, 'labels.refs', 'Refs')}
          items={evidence?.evidence_refs ?? []}
        />
        <InlineList
          label={taskExperienceText(t, 'labels.artifacts', 'Artifacts')}
          items={evidence?.artifacts ?? []}
        />
        <InlineList
          label={taskExperienceText(t, 'labels.checks', 'Checks')}
          items={evidence?.verification_summaries ?? []}
        />
      </Section>
      <Section
        title={taskExperienceText(t, 'sections.workerReport', 'Worker report')}
        icon={<FileText size={13} />}
      >
        <MetaRow
          label={taskExperienceText(t, 'labels.type', 'Type')}
          value={textValue(workerReport.type)}
        />
        <MetaRow
          label={taskExperienceText(t, 'labels.summary', 'Summary')}
          value={textValue(workerReport.summary)}
        />
        <MetaRow
          label={taskExperienceText(t, 'labels.reportId', 'Report id')}
          value={textValue(workerReport.id)}
          mono
        />
        <MetaRow
          label={taskExperienceText(t, 'labels.fingerprint', 'Fingerprint')}
          value={textValue(workerReport.fingerprint)}
          mono
        />
      </Section>
    </div>
  );
}

function DiagnosticsTab({
  task,
  diagnostics,
  gates,
  executionSession,
}: {
  task: WorkspaceTask;
  diagnostics: Record<string, unknown>;
  gates:
    | Record<string, WorkspaceTaskTransitionGate>
    | Partial<Record<string, WorkspaceTaskTransitionGate>>;
  executionSession: TaskExecutionSession | null;
}) {
  const { t } = useTranslation();
  return (
    <div className="space-y-4">
      <IncidentSection session={executionSession} />
      <Section
        title={taskExperienceText(t, 'sections.diagnostics', 'Diagnostics')}
        icon={<AlertTriangle size={13} />}
      >
        <MetaRow
          label={taskExperienceText(t, 'labels.blocker', 'Blocker')}
          value={task.blocker_reason || textValue(diagnostics.blocker_reason)}
        />
        <MetaRow
          label={taskExperienceText(t, 'labels.durableVerdict', 'Durable verdict')}
          value={textValue(diagnostics.durable_plan_verdict)}
        />
        <MetaRow
          label={taskExperienceText(t, 'labels.lastAttempt', 'Last attempt')}
          value={textValue(diagnostics.last_attempt_status)}
        />
        <MetaRow
          label={taskExperienceText(t, 'labels.pendingAdjudication', 'Pending adjudication')}
          value={boolText(diagnostics.pending_leader_adjudication, t)}
        />
        <MetaRow
          label={taskExperienceText(t, 'labels.missingConversation', 'Missing conversation')}
          value={boolText(diagnostics.missing_conversation, t)}
        />
      </Section>
      <Section
        title={taskExperienceText(t, 'sections.gateReasons', 'Gate reasons')}
        icon={<ListChecks size={13} />}
      >
        <GateRow label={taskExperienceText(t, 'labels.done', 'Done')} gate={gates.done} />
        <GateRow label={taskExperienceText(t, 'labels.blocked', 'Blocked')} gate={gates.blocked} />
      </Section>
    </div>
  );
}

function ActivityTab({ activity }: { activity: Array<Record<string, unknown>> }) {
  const { t } = useTranslation();
  return (
    <div className="space-y-2">
      {activity.length === 0 ? (
        <EmptyLine
          label={taskExperienceText(t, 'empty.noActivityRecorded', 'No activity recorded')}
        />
      ) : (
        activity.map((item, index) => (
          <div
            key={`${textValue(item.type)}-${String(index)}`}
            className="border-b border-border-light py-2 last:border-0 dark:border-border-dark"
          >
            <p className="text-xs font-medium text-text-primary dark:text-text-inverse">
              {formatTaskProjectionLabel(textValue(item.type))}
            </p>
            <p className="mt-0.5 break-words text-[11px] leading-4 text-text-secondary dark:text-text-muted">
              {textValue(item.summary) ||
                textValue(item.status) ||
                taskExperienceText(t, 'empty.noSummary', 'No summary')}
            </p>
            {textValue(item.at) && (
              <p className="mt-1 font-mono text-[10px] text-text-muted dark:text-text-muted">
                {formatTimestamp(item.at)}
              </p>
            )}
          </div>
        ))
      )}
    </div>
  );
}

function Section({
  title,
  icon,
  children,
}: {
  title: string;
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section>
      <div className="mb-2 flex items-center gap-1.5 text-[11px] font-semibold uppercase text-text-secondary dark:text-text-muted">
        {icon}
        {title}
      </div>
      <div className="space-y-1.5">{children}</div>
    </section>
  );
}

function MetaRow({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: unknown;
  mono?: boolean;
}) {
  const { t } = useTranslation();
  const display = textValue(value);
  return (
    <div className="grid grid-cols-[112px_minmax(0,1fr)] gap-2 text-xs">
      <span className="text-text-muted dark:text-text-muted">{label}</span>
      <span
        className={`min-w-0 break-words text-text-primary dark:text-text-inverse ${
          mono ? 'font-mono text-[11px]' : ''
        }`}
      >
        {display || <EmptyLine label={taskExperienceText(t, 'empty.none', 'None')} />}
      </span>
    </div>
  );
}

function InlineList({ label, items }: { label: string; items: string[] }) {
  const { t } = useTranslation();
  const cleaned = stringList(items);
  return (
    <div className="grid grid-cols-[112px_minmax(0,1fr)] gap-2 text-xs">
      <span className="text-text-muted dark:text-text-muted">{label}</span>
      {cleaned.length === 0 ? (
        <EmptyLine label={taskExperienceText(t, 'empty.none', 'None')} />
      ) : (
        <div className="flex min-w-0 flex-wrap gap-1">
          {cleaned.map((item) => (
            <span
              key={item}
              className="max-w-full break-words rounded-full border border-border-light bg-surface-muted px-2 py-0.5 text-[11px] text-text-secondary dark:border-border-dark dark:bg-background-dark dark:text-text-muted"
            >
              {item}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function GateRow({
  label,
  gate,
}: {
  label: string;
  gate: WorkspaceTaskTransitionGate | undefined;
}) {
  const { t } = useTranslation();
  if (!gate) {
    return (
      <MetaRow label={label} value={taskExperienceText(t, 'empty.noGateData', 'No gate data')} />
    );
  }
  return (
    <div className="grid grid-cols-[112px_minmax(0,1fr)] gap-2 text-xs">
      <span className="text-text-muted dark:text-text-muted">{label}</span>
      <div className="min-w-0 space-y-1">
        <span
          className={`inline-flex rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase ${
            gate.would_block
              ? 'border-warning-border bg-warning-bg text-status-text-warning dark:border-warning-border-dark dark:bg-warning-bg-dark dark:text-status-text-warning-dark'
              : 'border-success-border bg-success-bg text-status-text-success dark:border-success-border-dark dark:bg-success-bg-dark dark:text-status-text-success-dark'
          }`}
        >
          {gate.would_block
            ? taskExperienceText(t, 'values.needsEvidence', 'Needs evidence')
            : taskExperienceText(t, 'values.ready', 'Ready')}
        </span>
        <InlineList
          label={taskExperienceText(t, 'labels.missing', 'Missing')}
          items={gate.missing}
        />
        <InlineList
          label={taskExperienceText(t, 'labels.reasons', 'Reasons')}
          items={gate.reasons}
        />
      </div>
    </div>
  );
}

function EmptyLine({ label }: { label: string }) {
  return <span className="text-[11px] text-text-muted dark:text-text-muted">{label}</span>;
}

function resolveAgentLabel(task: WorkspaceTask, agents: WorkspaceAgent[]): string {
  const bindingId = task.workspace_agent_id || task.current_attempt_worker_binding_id;
  const agentId = task.assignee_agent_id || task.current_attempt_worker_agent_id;
  const binding = agents.find((agent) => agent.id === bindingId || agent.agent_id === agentId);
  return binding?.display_name || binding?.agent_id || agentId || '';
}

function tabLabel(key: PanelTab, t: TFunction): string {
  const labels: Record<PanelTab, string> = {
    overview: 'Overview',
    contract: 'Goal Contract',
    execution: 'Execution',
    evidence: 'Evidence',
    diagnostics: 'Diagnostics',
    activity: 'Activity',
  };
  return taskExperienceText(t, `tabs.${key}`, labels[key]);
}

function textValue(value: unknown): string {
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  return '';
}

/** Format an ISO timestamp for display; falls back to the raw value when unparsable. */
function formatTimestamp(value: unknown): string {
  const raw = textValue(value);
  if (!raw) return '';
  return formatDateTime(raw) || raw;
}

function boolText(value: unknown, t: TFunction): string {
  return value === true
    ? taskExperienceText(t, 'values.yes', 'Yes')
    : taskExperienceText(t, 'values.no', 'No');
}

function recoveryActionLabel(action: TaskRecoveryAction, t: TFunction): string {
  const labels: Record<TaskRecoveryAction, { key: string; defaultValue: string }> = {
    retry_launch: { key: 'actions.retryLaunch', defaultValue: 'Retry launch' },
    new_attempt: { key: 'actions.newAttempt', defaultValue: 'New attempt' },
    reassign: { key: 'actions.reassign', defaultValue: 'Reassign' },
    mark_human_blocked: { key: 'actions.needHuman', defaultValue: 'Need human' },
    terminate_stale_conversation: { key: 'actions.archiveStale', defaultValue: 'Archive stale' },
  };
  const label = labels[action];
  return taskExperienceText(t, label.key, label.defaultValue);
}

function stringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === 'string' && item.length > 0);
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? (value as Record<string, unknown>) : {};
}
