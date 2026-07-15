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
  ConnectionState,
  PlanSnapshot,
  ProjectSummary,
  WorkspaceSummary,
} from '../../types';
import {
  buildWorkspaceOverviewModel,
  type WorkspaceSessionSummary,
} from './workspaceOverviewModel';
import './WorkspaceOverview.css';

type WorkspaceOverviewProps = {
  workspace: WorkspaceSummary | null;
  project: ProjectSummary | null;
  tenantName: string;
  conversations: AgentConversation[];
  plan: PlanSnapshot | null;
  sandboxStatus: string | null;
  connection: ConnectionState;
  newTaskDisabledReason: string | null;
  onNewTask: () => void;
  onOpenConversation: (conversationId: string) => void;
  onOpenSettings: () => void;
};

export function WorkspaceOverview({
  workspace,
  project,
  tenantName,
  conversations,
  plan,
  sandboxStatus,
  connection,
  newTaskDisabledReason,
  onNewTask,
  onOpenConversation,
  onOpenSettings,
}: WorkspaceOverviewProps) {
  const { t, locale } = useI18n();
  const model = buildWorkspaceOverviewModel({
    workspace,
    project,
    conversations,
    plan,
    sandboxStatus,
    connection,
  });
  const projectName = project?.name ?? project?.id ?? t('overview.none');
  const workspaceName = model.workspaceName ?? t('overview.none');

  return (
    <main className="workspace-design-overview">
      <header className="workspace-design-header">
        <div>
          <span className="workspace-design-eyebrow">
            {tenantName} / {projectName}
          </span>
          <div className="workspace-design-title-line">
            <h1>{workspaceName}</h1>
            {model.officeStatus ? (
              <em data-status={model.officeStatus}>
                <i />
                {workspaceStatusLabel(model.officeStatus, t)}
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
              note={t('overview.workspaceCollaborators')}
            />
            <Metric
              label={t('overview.activeAgents')}
              value={model.activeAgentCount}
              note={t('overview.boundToWorkspace')}
              tone="green"
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
            status={countLabel(model.activeAgentCount, t)}
          >
            <div className="workspace-design-agent-roster">
              <div className="workspace-design-agent-stack" aria-hidden>
                {agentInitials(conversations).map((initials, index) => (
                  <span key={`${initials}-${index}`}>{initials}</span>
                ))}
              </div>
              <div>
                <b>{t('overview.boundAgents')}</b>
                <small>{t('overview.explicitWorkspaceBindings')}</small>
              </div>
            </div>
          </SystemCard>

          <SystemCard
            icon={<CodeIcon />}
            title={t('overview.executionEnvironment')}
            subtitle={t('overview.projectSandbox')}
            status={connectionLabel(model.environment.connection, t)}
          >
            <div className="workspace-design-environment">
              <span>
                <i data-state={model.environment.sandboxStatus ?? 'unknown'} />
                {model.environment.sandboxStatus ?? t('overview.unavailable')}
              </span>
              <b>{t('overview.sandboxReportedByRuntime')}</b>
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
              {model.recentActivity.length ? (
                model.recentActivity.map((activity, index) => (
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
    </main>
  );
}

function Metric({
  label,
  value,
  note,
  tone = 'neutral',
}: {
  label: string;
  value: number | null;
  note: string;
  tone?: 'neutral' | 'cyan' | 'amber' | 'green';
}) {
  return (
    <article className="workspace-design-metric" data-tone={tone}>
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
  children,
}: {
  icon: ReactNode;
  title: string;
  subtitle: string;
  status: string;
  children: ReactNode;
}) {
  return (
    <article className="workspace-design-system-card">
      <header>
        {icon}
        <div>
          <b>{title}</b>
          <small>{subtitle}</small>
        </div>
        <em>{status}</em>
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
  const StatusIcon = sessionStatusIcon(session.status);
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
      <em data-status={session.status}>{sessionStatusLabel(session.status, t)}</em>
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

function sessionStatusIcon(status: string) {
  if (status === 'running') return LightningBoltIcon;
  if (status === 'needs_input' || status === 'needs_approval') return ExclamationTriangleIcon;
  return CheckCircledIcon;
}

function sessionStatusLabel(
  status: string,
  t: (key: string, values?: Record<string, string | number>) => string,
) {
  if (status === 'running') return t('overview.statusRunning');
  if (status === 'needs_input' || status === 'needs_approval') {
    return t('overview.statusNeedsInput');
  }
  if (status === 'ready_review') return t('overview.statusReady');
  if (status === 'completed') return t('overview.statusCompleted');
  return status;
}

function workspaceStatusLabel(
  status: string,
  t: (key: string, values?: Record<string, string | number>) => string,
) {
  return status === 'online' ? t('overview.workspaceOnline') : status;
}

function collaborationModeLabel(
  mode: string | null,
  t: (key: string, values?: Record<string, string | number>) => string,
) {
  if (mode === 'multi_agent_shared') return t('overview.sharedMultiAgent');
  if (mode === 'single_agent') return t('overview.singleAgent');
  return mode ?? t('overview.unavailable');
}

function connectionLabel(
  connection: ConnectionState,
  t: (key: string, values?: Record<string, string | number>) => string,
) {
  return connection === 'ready' ? t('overview.connected') : t('overview.unavailable');
}

function countLabel(
  count: number | null,
  t: (key: string, values?: Record<string, string | number>) => string,
) {
  return count === null ? t('overview.unavailable') : t('overview.activeCount', { count });
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

function agentInitials(conversations: AgentConversation[]) {
  const agents = [...new Set(conversations.flatMap((item) => item.participant_agents ?? []))];
  return agents.slice(0, 4).map((agent) =>
    agent
      .split(/[-_\s]+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((part) => part[0]?.toUpperCase() ?? '')
      .join(''),
  );
}
