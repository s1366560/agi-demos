import type { ReactNode } from 'react';

import { Button } from '@radix-ui/themes';
import {
  ActivityLogIcon,
  CheckCircledIcon,
  ClockIcon,
  CodeIcon,
  CubeIcon,
  ExclamationTriangleIcon,
  FileTextIcon,
  GearIcon,
  LightningBoltIcon,
  PersonIcon,
  PlusIcon,
  ReaderIcon,
  RocketIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import type {
  AgentConversation,
  PlanSnapshot,
  ProjectSummary,
  WorkspaceAgentBinding,
  WorkspaceAuthorityCollection,
  WorkspaceAuthorityStatus,
  WorkspaceMemberSummary,
  WorkspaceSummary,
} from '../../types';
import {
  buildWorkspaceOverviewModel,
  workspaceSandboxStatusPresentation,
  type WorkspaceSessionSummary,
} from './workspaceOverviewModel';
import {
  conversationTreeStatusPresentation,
  type WorkspaceTreeStatusTone,
} from './workspaceTreeModel';
import type { WorkspaceLiveActivity } from './workspaceActivityEventModel';
import { WorkspaceContextState } from './WorkspaceContextState';
import './WorkspaceOverview.css';

type WorkspaceOverviewProps = {
  workspace: WorkspaceSummary | null;
  project: ProjectSummary | null;
  tenantName: string;
  workspaceAuthority: WorkspaceAuthorityCollection<WorkspaceSummary>;
  conversations: AgentConversation[];
  members: WorkspaceAuthorityCollection<WorkspaceMemberSummary>;
  agents: WorkspaceAuthorityCollection<WorkspaceAgentBinding>;
  plan: PlanSnapshot | null;
  sandboxStatus: string | null;
  liveActivity?: WorkspaceLiveActivity[];
  newTaskDisabledReason: string | null;
  onNewTask: () => void;
  onRetryWorkspaces: () => void;
  onOpenConversation: (conversationId: string) => void;
  onOpenSettings: () => void;
};

export function WorkspaceOverview({
  workspace,
  project,
  tenantName,
  workspaceAuthority,
  conversations,
  members,
  agents,
  plan,
  sandboxStatus,
  liveActivity = [],
  newTaskDisabledReason,
  onNewTask,
  onRetryWorkspaces,
  onOpenConversation,
  onOpenSettings,
}: WorkspaceOverviewProps) {
  const { t, locale } = useI18n();
  const model = buildWorkspaceOverviewModel({
    workspace,
    project,
    conversations,
    members,
    agents,
    plan,
    sandboxStatus,
  });
  const recentActivity = [...liveActivity, ...model.recentActivity].slice(0, 5);
  const sandboxPresentation = workspaceSandboxStatusPresentation(
    model.environment.sandboxStatus,
  );
  const projectName = project?.name ?? project?.id ?? t('overview.none');
  const workspaceName = model.workspaceName ?? t('overview.none');
  const agentRosterCopy = describeAgentRoster(
    model.agentRosterStatus,
    model.agentRosterNames.length,
    t,
  );
  const officeStatusPresentation = model.officeStatus
    ? workspaceStatusPresentation(model.officeStatus)
    : null;

  if (!project) {
    return (
      <section className="workspace-design-overview empty-project">
        <header className="workspace-design-header">
          <div>
            <span className="workspace-design-eyebrow">{tenantName}</span>
            <div className="workspace-design-title-line">
              <h1>{t('overview.noProjectTitle')}</h1>
            </div>
            <p>{t('overview.noProjectDescription')}</p>
          </div>
          <div className="workspace-design-header-actions">
            <Button variant="surface" color="gray" onClick={onOpenSettings}>
              <GearIcon /> {t('overview.configure')}
            </Button>
            <Button disabled title={newTaskDisabledReason ?? t('task.disabledProjectRequired')}>
              <PlusIcon /> {t('overview.newTask')}
            </Button>
          </div>
        </header>

        <div className="workspace-design-content">
          <section className="workspace-design-context-empty" role="status">
            <span>
              <CubeIcon />
            </span>
            <div>
              <small>{t('settings.workspaceContextEyebrow')}</small>
              <h2>{t('overview.noProjectCardTitle')}</h2>
              <p>{t('overview.noProjectCardDescription')}</p>
            </div>
            <Button variant="surface" color="gray" onClick={onOpenSettings}>
              <GearIcon /> {t('settings.workspace')}
            </Button>
          </section>
        </div>
      </section>
    );
  }

  if (!workspace) {
    if (workspaceAuthority.status === 'loading') {
      return (
        <WorkspaceContextState
          tenantName={tenantName}
          projectName={projectName}
          title={t('overview.loadingWorkspacesTitle')}
          description={t('overview.loadingWorkspacesDescription')}
          cardTitle={t('overview.loadingWorkspacesCardTitle')}
          cardDescription={t('overview.loadingWorkspacesCardDescription')}
          state="loading"
          primaryAction="none"
          newTaskDisabledReason={newTaskDisabledReason}
          onNewTask={onNewTask}
          onRetry={onRetryWorkspaces}
          onOpenSettings={onOpenSettings}
        />
      );
    }
    if (workspaceAuthority.status === 'error') {
      return (
        <WorkspaceContextState
          tenantName={tenantName}
          projectName={projectName}
          title={t('overview.workspacesUnavailableTitle')}
          description={t('overview.workspacesUnavailableDescription')}
          cardTitle={t('overview.workspaceCatalogErrorTitle')}
          cardDescription={t('overview.workspaceCatalogErrorDescription')}
          detail={workspaceAuthority.error}
          state="error"
          primaryAction="retry"
          newTaskDisabledReason={newTaskDisabledReason}
          onNewTask={onNewTask}
          onRetry={onRetryWorkspaces}
          onOpenSettings={onOpenSettings}
        />
      );
    }
    if (workspaceAuthority.status === 'unavailable') {
      return (
        <WorkspaceContextState
          tenantName={tenantName}
          projectName={projectName}
          title={t('overview.workspaceCatalogUnavailableTitle')}
          description={t('overview.workspaceCatalogUnavailableDescription')}
          cardTitle={t('overview.workspaceCatalogUnavailableCardTitle')}
          cardDescription={t('overview.workspaceCatalogUnavailableCardDescription')}
          state="error"
          primaryAction="retry"
          newTaskDisabledReason={newTaskDisabledReason}
          onNewTask={onNewTask}
          onRetry={onRetryWorkspaces}
          onOpenSettings={onOpenSettings}
        />
      );
    }
    if (workspaceAuthority.items.length === 0) {
      return (
        <WorkspaceContextState
          tenantName={tenantName}
          projectName={projectName}
          title={t('overview.noWorkspacesTitle')}
          description={t('overview.noWorkspacesDescription')}
          cardTitle={t('overview.firstTaskTitle')}
          cardDescription={t('overview.firstTaskDescription')}
          state="empty"
          primaryAction="new-task"
          newTaskDisabledReason={newTaskDisabledReason}
          onNewTask={onNewTask}
          onRetry={onRetryWorkspaces}
          onOpenSettings={onOpenSettings}
        />
      );
    }
    return (
      <WorkspaceContextState
        tenantName={tenantName}
        projectName={projectName}
        title={t('overview.workspaceSelectionUnavailableTitle')}
        description={t('overview.workspaceSelectionUnavailableDescription')}
        cardTitle={t('overview.workspaceSelectionUnavailableCardTitle')}
        cardDescription={t('overview.workspaceSelectionUnavailableCardDescription')}
        state="error"
        primaryAction="retry"
        newTaskDisabledReason={newTaskDisabledReason}
        onNewTask={onNewTask}
        onRetry={onRetryWorkspaces}
        onOpenSettings={onOpenSettings}
      />
    );
  }

  return (
    <section className="workspace-design-overview">
      <header className="workspace-design-header">
        <div>
          <span className="workspace-design-eyebrow">
            {tenantName} / {projectName}
          </span>
          <div className="workspace-design-title-line">
            <h1>{workspaceName}</h1>
            {officeStatusPresentation ? (
              <em data-status={officeStatusPresentation.tone}>
                <i />
                {t(officeStatusPresentation.labelKey)}
              </em>
            ) : null}
          </div>
          <p>{model.workspaceDescription ?? t('overview.description')}</p>
        </div>
        <div className="workspace-design-header-actions">
          <Button variant="surface" color="gray" onClick={onOpenSettings}>
            <GearIcon /> {t('overview.configure')}
          </Button>
          <Button
            disabled={Boolean(newTaskDisabledReason)}
            title={newTaskDisabledReason ?? undefined}
            onClick={onNewTask}
          >
            <PlusIcon /> {t('overview.newTask')}
          </Button>
        </div>
      </header>

      <div className="workspace-design-content">
        <section className="workspace-design-summary-grid">
          <article className="workspace-design-goal-card">
            <CardHeading
              icon={<RocketIcon />}
              eyebrow={t('overview.rootGoal')}
              title={t('overview.workspacePurpose')}
            />
            <p>{model.rootGoal ?? t('overview.rootGoalMissing')}</p>
            <div className="workspace-design-goal-facts">
              <span>
                <CubeIcon />
                {collaborationModeLabel(model.collaborationMode, t)}
              </span>
              <span>
                <CheckCircledIcon /> {t('overview.evidenceRequired')}
              </span>
              <span>
                <ClockIcon /> {formatDate(model.updatedAt, locale, t)}
              </span>
            </div>
          </article>

          <div className="workspace-design-metrics-grid">
            <Metric
              label={t('overview.activeSessions')}
              value={model.sessionCounts.total}
              note={t('overview.runningReady', {
                running: model.sessionCounts.running,
                ready: model.sessionCounts.ready,
              })}
              tone="cyan"
            />
            <Metric
              label={t('overview.needsAttention')}
              value={model.sessionCounts.attention}
              note={
                model.sessionCounts.attention
                  ? t('overview.approvalInputRequired')
                  : t('overview.noBlockedSessions')
              }
              tone={model.sessionCounts.attention ? 'amber' : 'green'}
            />
            <Metric
              label={t('overview.members')}
              value={model.memberCount}
              note={rosterMetricNote(
                model.memberRosterStatus,
                t('overview.workspaceCollaborators'),
                t('overview.loadingMembers'),
                t('overview.membersUnavailable'),
              )}
              busy={model.memberRosterStatus === 'loading'}
            />
            <Metric
              label={t('overview.activeAgents')}
              value={model.activeAgentCount}
              note={rosterMetricNote(
                model.agentRosterStatus,
                t('overview.boundToWorkspace'),
                t('overview.loadingAgents'),
                t('overview.agentsUnavailable'),
              )}
              busy={model.agentRosterStatus === 'loading'}
              tone={model.agentRosterStatus === 'ready' ? 'green' : 'neutral'}
            />
          </div>
        </section>

        <section className="workspace-design-system-grid">
          <SystemCard
            icon={<ReaderIcon />}
            title={t('overview.projectKnowledge')}
            subtitle={t('overview.sharedAcrossProject')}
            status={project?.stats ? t('overview.available') : t('overview.unavailable')}
          >
            <div className="workspace-design-knowledge-metrics">
              <KnowledgeMetric
                value={formatNumber(model.knowledge.memories, locale, t)}
                label={t('overview.projectMemories')}
              />
              <KnowledgeMetric
                value={formatNumber(model.knowledge.graphNodes, locale, t)}
                label={t('overview.graphNodes')}
              />
              <KnowledgeMetric
                value={formatBytes(model.knowledge.storageBytes, locale, t)}
                label={t('overview.storage')}
              />
            </div>
          </SystemCard>

          <SystemCard
            icon={<PersonIcon />}
            title={t('overview.agentRoster')}
            subtitle={collaborationModeLabel(model.collaborationMode, t)}
            status={rosterStatusLabel(
              model.agentRosterStatus,
              model.activeAgentCount,
              t,
            )}
            statusState={model.agentRosterStatus}
            busy={model.agentRosterStatus === 'loading'}
          >
            <div className="workspace-design-agent-roster">
              <div className="workspace-design-agent-stack" aria-hidden>
                {agentInitials(model.agentRosterNames).map((initials, index) => (
                  <span key={`${initials}-${index}`}>{initials}</span>
                ))}
              </div>
              <div>
                <b>{agentRosterCopy.title}</b>
                <small>{agentRosterCopy.description}</small>
              </div>
            </div>
          </SystemCard>

          <SystemCard
            icon={<CodeIcon />}
            title={t('overview.executionEnvironment')}
            subtitle={t('overview.projectSandbox')}
            status={t(sandboxPresentation.labelKey)}
            statusState={sandboxPresentation.state}
          >
            <div className="workspace-design-environment">
              <span data-state={sandboxPresentation.state}>
                <i />
                {t(sandboxPresentation.labelKey)}
              </span>
              <b>{t(sandboxPresentation.summaryKey)}</b>
              <small>{t('overview.runtimePolicySource')}</small>
            </div>
          </SystemCard>
        </section>

        <section className="workspace-design-lower-grid">
          <article className="workspace-design-sessions-card">
            <header>
              <div>
                <span>{t('overview.conversations')}</span>
                <h2>{t('overview.recentSessions')}</h2>
              </div>
              <small>{t('overview.totalCount', { count: model.sessionCounts.total })}</small>
            </header>
            <div>
              {model.recentSessions.length ? (
                model.recentSessions.map((session) => (
                  <SessionRow
                    key={session.id}
                    session={session}
                    locale={locale}
                    onOpen={() => onOpenConversation(session.id)}
                    t={t}
                  />
                ))
              ) : (
                <EmptyState
                  title={t('overview.noConversations')}
                  description={t('overview.noConversationsDescription')}
                />
              )}
            </div>
          </article>

          <article className="workspace-design-activity-card">
            <header>
              <div>
                <span>{t('overview.auditTrail')}</span>
                <h2>{t('overview.recentActivity')}</h2>
              </div>
              <ActivityLogIcon />
            </header>
            <div>
              {recentActivity.length ? (
                recentActivity.map((activity, index) => (
                  <div key={`${activity.title}-${index}`}>
                    <span>
                      <FileTextIcon />
                    </span>
                    <p>
                      <b>{activity.title}</b>
                      <small>{activity.detail ?? t('overview.unavailable')}</small>
                    </p>
                  </div>
                ))
              ) : (
                <EmptyState
                  title={t('overview.noActivity')}
                  description={t('overview.noActivityDescription')}
                />
              )}
            </div>
          </article>
        </section>
      </div>
    </section>
  );
}

function Metric({
  label,
  value,
  note,
  busy = false,
  tone = 'neutral',
}: {
  label: string;
  value: number | null;
  note: string;
  busy?: boolean;
  tone?: 'neutral' | 'cyan' | 'amber' | 'green';
}) {
  return (
    <article
      className="workspace-design-metric"
      data-tone={tone}
      aria-busy={busy || undefined}
      aria-live="polite"
      aria-atomic="true"
    >
      <span>{label}</span>
      <b>{value ?? '—'}</b>
      <small>{note}</small>
    </article>
  );
}

function CardHeading({
  icon,
  eyebrow,
  title,
}: {
  icon: ReactNode;
  eyebrow: string;
  title: string;
}) {
  return (
    <div className="workspace-design-card-heading">
      <span>{icon}</span>
      <div>
        <small>{eyebrow}</small>
        <h2>{title}</h2>
      </div>
    </div>
  );
}

function SystemCard({
  icon,
  title,
  subtitle,
  status,
  statusState,
  busy = false,
  children,
}: {
  icon: ReactNode;
  title: string;
  subtitle: string;
  status: string;
  statusState?: WorkspaceAuthorityStatus;
  busy?: boolean;
  children: ReactNode;
}) {
  return (
    <article className="workspace-design-system-card" aria-busy={busy || undefined}>
      <header>
        {icon}
        <div>
          <b>{title}</b>
          <small>{subtitle}</small>
        </div>
        <em data-state={statusState} aria-live="polite">
          {status}
        </em>
      </header>
      {children}
    </article>
  );
}

function KnowledgeMetric({ value, label }: { value: string; label: string }) {
  return (
    <span>
      <b>{value}</b>
      <small>{label}</small>
    </span>
  );
}

function SessionRow({
  session,
  locale,
  onOpen,
  t,
}: {
  session: WorkspaceSessionSummary;
  locale: string;
  onOpen: () => void;
  t: (key: string, values?: Record<string, string | number>) => string;
}) {
  const statusPresentation = conversationTreeStatusPresentation(session.status);
  const StatusIcon = sessionStatusIcon(statusPresentation.tone);
  return (
    <button type="button" onClick={onOpen}>
      <span
        className="workspace-design-session-icon"
        data-mode={session.capabilityMode ?? 'unknown'}
      >
        <StatusIcon />
      </span>
      <span>
        <b>{session.title}</b>
        <small>{formatDate(session.updatedAt, locale, t)}</small>
      </span>
      <em data-status={statusPresentation.tone}>{t(statusPresentation.labelKey)}</em>
    </button>
  );
}

function EmptyState({ title, description }: { title: string; description: string }) {
  return (
    <div className="workspace-design-empty">
      <b>{title}</b>
      <small>{description}</small>
    </div>
  );
}

function sessionStatusIcon(tone: WorkspaceTreeStatusTone) {
  if (tone === 'active' || tone === 'queued') return LightningBoltIcon;
  if (tone === 'attention' || tone === 'danger') return ExclamationTriangleIcon;
  if (tone === 'ready' || tone === 'completed') return CheckCircledIcon;
  return ActivityLogIcon;
}

function workspaceStatusPresentation(status: string) {
  if (status.trim().toLowerCase() === 'online') {
    return { tone: 'active' as const, labelKey: 'overview.workspaceOnline' };
  }
  return conversationTreeStatusPresentation(status);
}

function collaborationModeLabel(
  mode: string | null,
  t: (key: string, values?: Record<string, string | number>) => string,
) {
  if (mode === 'multi_agent_shared') return t('overview.sharedMultiAgent');
  if (mode === 'single_agent') return t('overview.singleAgent');
  return mode ?? t('overview.unavailable');
}

function rosterStatusLabel(
  status: WorkspaceAuthorityStatus,
  count: number | null,
  t: (key: string, values?: Record<string, string | number>) => string,
) {
  if (status === 'loading') return t('overview.loading');
  if (status === 'error') return t('overview.rosterError');
  if (status === 'unavailable') return t('overview.unavailable');
  return t('overview.activeCount', { count: count ?? 0 });
}

function rosterMetricNote(
  status: WorkspaceAuthorityStatus,
  ready: string,
  loading: string,
  unavailable: string,
) {
  if (status === 'ready') return ready;
  if (status === 'loading') return loading;
  return unavailable;
}

function describeAgentRoster(
  status: WorkspaceAuthorityStatus,
  activeCount: number,
  t: (key: string, values?: Record<string, string | number>) => string,
) {
  if (status === 'loading') {
    return {
      title: t('overview.loadingAgents'),
      description: t('overview.loadingRosterDescription'),
    };
  }
  if (status === 'error') {
    return {
      title: t('overview.agentsUnavailable'),
      description: t('overview.retryRosterDescription'),
    };
  }
  if (status === 'unavailable') {
    return {
      title: t('overview.agentsUnavailable'),
      description: t('overview.selectWorkspaceForRoster'),
    };
  }
  if (activeCount === 0) {
    return {
      title: t('overview.noBoundAgents'),
      description: t('overview.noBoundAgentsDescription'),
    };
  }
  return {
    title: t('overview.boundAgents'),
    description: t('overview.explicitWorkspaceBindings'),
  };
}

function formatNumber(
  value: number | null,
  locale: string,
  t: (key: string, values?: Record<string, string | number>) => string,
) {
  return value === null ? t('overview.unavailable') : value.toLocaleString(locale);
}

function formatBytes(
  value: number | null,
  locale: string,
  t: (key: string, values?: Record<string, string | number>) => string,
) {
  if (value === null) return t('overview.unavailable');
  if (value < 1024) return `${value.toLocaleString(locale)} B`;
  if (value < 1024 * 1024) {
    return `${(value / 1024).toLocaleString(locale, { maximumFractionDigits: 1 })} KB`;
  }
  if (value < 1024 * 1024 * 1024) {
    return `${(value / (1024 * 1024)).toLocaleString(locale, { maximumFractionDigits: 1 })} MB`;
  }
  return `${(value / (1024 * 1024 * 1024)).toLocaleString(locale, {
    maximumFractionDigits: 1,
  })} GB`;
}

function formatDate(
  value: string | null,
  locale: string,
  t: (key: string, values?: Record<string, string | number>) => string,
) {
  if (!value) return t('overview.updatedUnavailable');
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return t('overview.updatedOn', {
    date: new Intl.DateTimeFormat(locale, { month: 'short', day: 'numeric' }).format(date),
  });
}

function agentInitials(names: string[]) {
  return names.slice(0, 4).map((name) =>
    name
      .split(/[-_\s]+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((part) => part[0]?.toUpperCase() ?? '')
      .join(''),
  );
}
