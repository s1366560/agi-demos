import type { ReactNode } from 'react';

import { Badge, Button, Heading, Text } from '@radix-ui/themes';
import {
  ActivityLogIcon,
  ArchiveIcon,
  ChatBubbleIcon,
  CheckCircledIcon,
  ChevronRightIcon,
  ExclamationTriangleIcon,
  GearIcon,
  GridIcon,
  PlusIcon,
  RocketIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import type {
  AgentConversation,
  ConnectionState,
  PlanSnapshot,
  ProjectSummary,
  WorkspaceSummary,
  WorkspaceTask,
} from '../../types';
import { summarizeWorkspaceExecution } from './workspaceExecutionModel';

type WorkspaceOverviewProps = {
  workspace: WorkspaceSummary | null;
  project: ProjectSummary | null;
  tenantName: string;
  conversations: AgentConversation[];
  tasks: WorkspaceTask[];
  plan: PlanSnapshot | null;
  messageCount: number;
  sandboxStatus: string;
  connection: ConnectionState;
  refreshDisabledReason: string | null;
  onRefresh: () => void;
  onNewTask: () => void;
  onOpenConversation: (conversationId: string) => void;
  onOpenBoard: () => void;
  onOpenReview: () => void;
  onOpenSettings: () => void;
};

export function WorkspaceOverview({
  workspace,
  project,
  tenantName,
  conversations,
  tasks,
  plan,
  messageCount,
  sandboxStatus,
  connection,
  refreshDisabledReason,
  onRefresh,
  onNewTask,
  onOpenConversation,
  onOpenBoard,
  onOpenReview,
  onOpenSettings,
}: WorkspaceOverviewProps) {
  const { t } = useI18n();
  const summary = summarizeWorkspaceExecution(tasks, plan);
  const projectedConversations = Array.isArray(plan?.conversation_plans)
    ? plan.conversation_plans
    : [];
  const workspaceName = workspace?.name ?? workspace?.title ?? workspace?.id ?? t('overview.none');
  const projectName = project?.name ?? project?.id ?? t('overview.none');
  const rootGoal = rootGoalFromPlan(plan);
  const status = workspace?.status ?? 'open';
  const unfinishedTasks = tasks.filter(
    (task) => !['done', 'closed', 'completed'].includes((task.status ?? '').toLowerCase()),
  );

  return (
    <section className="pane-shell overview-shell workspace-overview-shell">
      <header className="workspace-overview-head">
        <div className="workspace-overview-identity">
          <span className="workspace-overview-eyebrow">
            {tenantName} <ChevronRightIcon aria-hidden /> {projectName}
          </span>
          <div className="workspace-overview-title-row">
            <Heading as="h2" size="5">
              {workspaceName}
            </Heading>
            <Badge color={status === 'closed' ? 'gray' : 'green'} variant="soft">
              {status}
            </Badge>
          </div>
          <Text as="p" size="2" color="gray">
            {workspace?.description ?? t('overview.description')}
          </Text>
        </div>
        <div className="workspace-overview-head-actions">
          <Button size="2" variant="soft" onClick={onOpenSettings}>
            <GearIcon /> {t('overview.configure')}
          </Button>
          <Button size="2" onClick={onNewTask}>
            <PlusIcon /> {t('overview.newTask')}
          </Button>
        </div>
      </header>

      <div className="overview-content workspace-overview-content">
        <section className="workspace-goal-card">
          <div className="workspace-goal-icon" aria-hidden>
            <RocketIcon />
          </div>
          <div>
            <span>{t('overview.rootGoal')}</span>
            <Heading as="h3" size="3">
              {rootGoal ?? t('overview.rootGoalMissing')}
            </Heading>
            <Text as="p" size="1" color="gray">
              {rootGoal ? t('overview.rootGoalDescription') : t('overview.rootGoalMissingHelp')}
            </Text>
          </div>
          <Button
            size="1"
            variant="ghost"
            onClick={onRefresh}
            disabled={Boolean(refreshDisabledReason) || connection === 'loading'}
            loading={connection === 'loading'}
          >
            {t('overview.refresh')}
          </Button>
        </section>

        <div className="overview-metrics workspace-execution-metrics">
          <ExecutionMetric
            label={t('overview.activeRuns')}
            value={summary.activeRuns}
            detail={t('overview.sessionsCount', { count: summary.conversations })}
          />
          <ExecutionMetric
            label={t('overview.needsAttention')}
            value={summary.attentionRuns + summary.pendingRequests}
            detail={t('overview.pendingRequests', { count: summary.pendingRequests })}
            tone={summary.attentionRuns + summary.pendingRequests > 0 ? 'warning' : 'neutral'}
          />
          <ExecutionMetric
            label={t('overview.planTasks')}
            value={summary.taskTotal}
            detail={t('overview.completedTasks', { count: summary.completedTasks })}
          />
          <ExecutionMetric
            label={t('overview.evidence')}
            value={summary.artifacts}
            detail={t('overview.deliveries', { count: summary.deliveries })}
          />
        </div>

        <div className="workspace-overview-grid">
          <section className="workspace-overview-card workspace-active-sessions">
            <CardHeader
              icon={<ActivityLogIcon />}
              title={t('overview.activeSessions')}
              actionLabel={t('overview.reviewAll')}
              onAction={onOpenReview}
            />
            <div className="workspace-session-list">
              {projectedConversations.length ? (
                projectedConversations.slice(0, 5).map((item) => (
                  <button
                    type="button"
                    className="workspace-session-row"
                    key={item.conversation_id}
                    onClick={() => onOpenConversation(item.conversation_id)}
                  >
                    <span className="workspace-session-mode">
                      {item.capability_mode === 'code' ? '</>' : 'AG'}
                    </span>
                    <span className="workspace-session-copy">
                      <strong>{item.title ?? item.conversation_id}</strong>
                      <small>
                        {item.plan
                          ? t('overview.planVersion', {
                              version: item.plan.version,
                              status: item.plan.status,
                            })
                          : t('overview.noPlan')}
                      </small>
                    </span>
                    <Badge
                      color={runBadgeColor(item.run?.status)}
                      variant="soft"
                      className="workspace-session-status"
                    >
                      {item.run?.status ?? item.current_mode ?? t('overview.idle')}
                    </Badge>
                    <ChevronRightIcon aria-hidden />
                  </button>
                ))
              ) : (
                <OverviewEmpty
                  title={t('overview.noExecution')}
                  description={t('overview.noExecutionDescription')}
                />
              )}
            </div>
          </section>

          <section className="workspace-overview-card workspace-attention-card">
            <CardHeader icon={<ExclamationTriangleIcon />} title={t('overview.attention')} />
            <div className="workspace-attention-summary">
              <strong>{summary.pendingRequests}</strong>
              <span>{t('overview.pendingHumanRequests')}</span>
            </div>
            <div className="workspace-attention-summary">
              <strong>{summary.attentionRuns}</strong>
              <span>{t('overview.runsNeedAttention')}</span>
            </div>
            <Button variant="soft" size="2" onClick={onOpenReview}>
              {t('overview.openReview')}
            </Button>
          </section>

          <section className="workspace-overview-card workspace-task-card">
            <CardHeader
              icon={<GridIcon />}
              title={t('overview.currentTasks')}
              actionLabel={t('overview.openBoard')}
              onAction={onOpenBoard}
            />
            <div className="workspace-compact-list">
              {unfinishedTasks.length ? (
                unfinishedTasks.slice(0, 4).map((task) => (
                  <button type="button" key={task.id} onClick={onOpenBoard}>
                    <span className="workspace-task-state" data-status={task.status ?? 'unknown'} />
                    <span>
                      <strong>{task.title ?? task.id}</strong>
                      <small>
                        {task.status ?? t('overview.unknown')} ·{' '}
                        {task.priority ?? t('overview.noPriority')}
                      </small>
                    </span>
                  </button>
                ))
              ) : (
                <OverviewEmpty
                  title={t('overview.noTasks')}
                  description={t('overview.noTasksDescription')}
                />
              )}
            </div>
          </section>

          <section className="workspace-overview-card workspace-evidence-card">
            <CardHeader icon={<ArchiveIcon />} title={t('overview.deliveryEvidence')} />
            <div className="workspace-evidence-stats">
              <div>
                <strong>{summary.artifacts}</strong>
                <span>{t('overview.artifacts')}</span>
              </div>
              <div>
                <strong>{summary.deliveries}</strong>
                <span>{t('overview.delivered')}</span>
              </div>
              <div>
                <strong>{messageCount}</strong>
                <span>{t('overview.messages')}</span>
              </div>
            </div>
            <Button variant="soft" size="2" onClick={onOpenReview}>
              <CheckCircledIcon /> {t('overview.inspectEvidence')}
            </Button>
          </section>

          <section className="workspace-overview-card workspace-recent-card">
            <CardHeader icon={<ChatBubbleIcon />} title={t('overview.recentConversations')} />
            <div className="workspace-compact-list">
              {conversations.length ? (
                conversations.slice(0, 4).map((conversation) => (
                  <button
                    type="button"
                    key={conversation.id}
                    onClick={() => onOpenConversation(conversation.id)}
                  >
                    <span className="workspace-conversation-dot" />
                    <span>
                      <strong>{conversation.title}</strong>
                      <small>{conversation.updated_at ?? conversation.created_at}</small>
                    </span>
                  </button>
                ))
              ) : (
                <OverviewEmpty
                  title={t('overview.noConversations')}
                  description={t('overview.noConversationsDescription')}
                />
              )}
            </div>
          </section>

          <section className="workspace-overview-card workspace-context-card">
            <CardHeader icon={<GearIcon />} title={t('overview.runtimeContext')} />
            <dl>
              <div>
                <dt>{t('overview.projectScope')}</dt>
                <dd>{projectName}</dd>
              </div>
              <div>
                <dt>{t('overview.sandbox')}</dt>
                <dd>{sandboxStatus}</dd>
              </div>
              <div>
                <dt>{t('overview.connection')}</dt>
                <dd>{connection}</dd>
              </div>
            </dl>
            <Button variant="soft" size="2" onClick={onOpenSettings}>
              {t('overview.configureRuntime')}
            </Button>
          </section>
        </div>
      </div>
    </section>
  );
}

function ExecutionMetric({
  label,
  value,
  detail,
  tone = 'neutral',
}: {
  label: string;
  value: number;
  detail: string;
  tone?: 'neutral' | 'warning';
}) {
  return (
    <div className="metric overview-metric workspace-execution-metric" data-tone={tone}>
      <Text size="1" color="gray">
        {label}
      </Text>
      <strong>{value}</strong>
      <small>{detail}</small>
    </div>
  );
}

function CardHeader({
  icon,
  title,
  actionLabel,
  onAction,
}: {
  icon: ReactNode;
  title: string;
  actionLabel?: string;
  onAction?: () => void;
}) {
  return (
    <header className="workspace-card-head">
      <span>{icon}</span>
      <strong>{title}</strong>
      {actionLabel && onAction ? (
        <button type="button" onClick={onAction}>
          {actionLabel} <ChevronRightIcon aria-hidden />
        </button>
      ) : null}
    </header>
  );
}

function OverviewEmpty({ title, description }: { title: string; description: string }) {
  return (
    <div className="workspace-overview-empty">
      <strong>{title}</strong>
      <span>{description}</span>
    </div>
  );
}

function rootGoalFromPlan(plan: PlanSnapshot | null): string | null {
  const value = plan?.root_goal;
  if (typeof value === 'string' && value.trim()) return value.trim();
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    const record = value as Record<string, unknown>;
    const title = record.title ?? record.content ?? record.goal;
    if (typeof title === 'string' && title.trim()) return title.trim();
  }
  return null;
}

function runBadgeColor(status: string | undefined) {
  if (status === 'needs_input' || status === 'needs_approval') return 'amber' as const;
  if (status === 'completed' || status === 'ready_review') return 'green' as const;
  if (status === 'failed' || status === 'interrupted' || status === 'disconnected') {
    return 'red' as const;
  }
  if (!status) return 'gray' as const;
  return 'blue' as const;
}
