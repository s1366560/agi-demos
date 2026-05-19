import { useEffect, useRef, useState } from 'react';

import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';

import { Button, message } from 'antd';
import {
  ChevronDown,
  ChevronUp,
  Check,
  CheckCircle2,
  CircleDashed,
  Copy,
  GitBranchPlus,
  LoaderCircle,
  Orbit,
  PlayCircle,
  Sparkles,
  Target,
  Users,
  Zap,
} from 'lucide-react';

import { workspaceAutonomyService } from '@/services/workspaceService';

import { buildAgentWorkspacePath } from '@/utils/agentWorkspacePath';
import {
  getPendingLeaderAdjudicationSummary,
  getTaskAttemptConversationId,
  getTaskAttemptNumber,
} from '@/utils/workspaceTaskProjection';

import { ObjectiveList } from '@/components/workspace/objectives/ObjectiveList';
import { TaskBoard } from '@/components/workspace/TaskBoard';

import { HostedProjectionBadge } from '../HostedProjectionBadge';

import type { CyberObjective, WorkspaceAgent, WorkspaceTask } from '@/types/workspace';

import type { TFunction } from 'i18next';

export interface GoalsTabProps {
  objectives: CyberObjective[];
  tasks: WorkspaceTask[];
  agents?: WorkspaceAgent[] | undefined;
  completionRatio: number;
  workspaceId: string;
  tenantId?: string | undefined;
  projectId?: string | undefined;
  onDeleteObjective: (objectiveId: string) => void;
  onProjectObjective: (objectiveId: string) => void;
  onCreateObjective: () => void;
}

interface ObjectiveExecutionFeedback {
  objectiveId: string;
  objectiveTitle: string;
  objectiveCreatedAt: string;
  rootTask: WorkspaceTask | null;
  rootStatus: WorkspaceTask['status'] | 'missing';
  childCount: number;
  assignedCount: number;
  inProgressCount: number;
  doneCount: number;
  blockedCount: number;
  stageLabel: string;
  helperText: string;
  accentClassName: string;
  pulse: boolean;
}

interface FeedbackTimelineStep {
  id: string;
  label: string;
  helper: string;
  state: 'complete' | 'current' | 'upcoming';
}

interface FeedbackLogEntry {
  id: string;
  label: string;
  timestamp: string;
  emphasis?: boolean;
}

interface ChildTaskLogEntry {
  childTaskId: string;
  title: string;
  assigneeLabel: string;
  workerLabel: string | null;
  status: WorkspaceTask['status'];
  pendingAdjudication: boolean;
  reportTypeLabel: string;
  events: FeedbackLogEntry[];
  conversationId?: string | undefined;
  attemptNumber?: number | undefined;
}

interface ChildTaskLogCardProps {
  child: ChildTaskLogEntry;
  expanded: boolean;
  filterMode: 'latest' | 'all';
  onToggle: () => void;
  onJump: () => void;
  conversationHref?: string | undefined;
}

function resolveAssigneeLabel(
  task: Pick<WorkspaceTask, 'workspace_agent_id' | 'assignee_agent_id' | 'assignee_user_id'>,
  agents: WorkspaceAgent[],
  unassignedLabel: string
): string {
  const bindingId = task.workspace_agent_id;
  if (bindingId) {
    const binding = agents.find((agent) => agent.id === bindingId);
    if (binding) {
      return binding.display_name || binding.label || binding.agent_id || binding.id;
    }
  }

  const assignedAgentId = task.assignee_agent_id;
  if (assignedAgentId) {
    const binding = agents.find((agent) => agent.agent_id === assignedAgentId);
    if (binding) {
      return binding.display_name || binding.label || binding.agent_id || binding.id;
    }
    return assignedAgentId;
  }

  return task.assignee_user_id ?? unassignedLabel;
}

function getObjectiveExecutionFeedback(
  objective: CyberObjective,
  tasks: WorkspaceTask[],
  t: TFunction
): ObjectiveExecutionFeedback {
  const rootTask = tasks.find((task) => task.metadata.objective_id === objective.id) ?? null;
  const rootStatus = rootTask?.status ?? 'missing';
  const childTasks = rootTask
    ? tasks.filter((task) => task.metadata.root_goal_task_id === rootTask.id)
    : [];
  const assignedCount = childTasks.filter((task) =>
    Boolean(task.assignee_agent_id || task.assignee_user_id)
  ).length;
  const inProgressCount = childTasks.filter((task) => task.status === 'in_progress').length;
  const doneCount = childTasks.filter((task) => task.status === 'done').length;
  const blockedCount = childTasks.filter((task) => task.status === 'blocked').length;

  if (!rootTask) {
    return {
      objectiveId: objective.id,
      objectiveTitle: objective.title,
      objectiveCreatedAt: objective.created_at,
      rootTask: null,
      rootStatus,
      childCount: 0,
      assignedCount: 0,
      inProgressCount: 0,
      doneCount: 0,
      blockedCount: 0,
      stageLabel: t('blackboard.executionFeedback.stage.waitingRoot', 'Waiting for root task'),
      helperText: t(
        'blackboard.executionFeedback.helper.waitingRoot',
        'The objective is created. Sisyphus is being triggered to project it as a root task.'
      ),
      accentClassName:
        'border-primary/30 bg-primary/5 text-primary dark:border-primary-300/30 dark:bg-primary-300/10 dark:text-primary-100',
      pulse: true,
    };
  }

  if (childTasks.length === 0) {
    return {
      objectiveId: objective.id,
      objectiveTitle: objective.title,
      objectiveCreatedAt: objective.created_at,
      rootTask,
      rootStatus,
      childCount: 0,
      assignedCount: 0,
      inProgressCount: 0,
      doneCount: 0,
      blockedCount: 0,
      stageLabel:
        rootStatus === 'in_progress'
          ? t(
              'blackboard.executionFeedback.stage.rootReadyWaitingChildren',
              'Root task created, waiting for decomposition'
            )
          : t('blackboard.executionFeedback.stage.rootReady', 'Root task created'),
      helperText: t(
        'blackboard.executionFeedback.helper.rootReady',
        'The next step is task decomposition. Child task assignment and execution progress will appear here live.'
      ),
      accentClassName:
        'border-info-border bg-info-bg text-status-text-info dark:border-info-border-dark dark:bg-info-bg-dark dark:text-status-text-info-dark',
      pulse: rootStatus !== 'done',
    };
  }

  if (blockedCount > 0) {
    return {
      objectiveId: objective.id,
      objectiveTitle: objective.title,
      objectiveCreatedAt: objective.created_at,
      rootTask,
      rootStatus,
      childCount: childTasks.length,
      assignedCount,
      inProgressCount,
      doneCount,
      blockedCount,
      stageLabel: t('blackboard.executionFeedback.stage.blocked', 'Execution blocked'),
      helperText: t(
        'blackboard.executionFeedback.helper.blocked',
        '{{count}} child task(s) are blocked. Review blockers and the leader summary in the task board.',
        { count: blockedCount }
      ),
      accentClassName:
        'border-error-border bg-error-bg text-status-text-error dark:border-error-border-dark dark:bg-error-bg-dark dark:text-status-text-error-dark',
      pulse: false,
    };
  }

  if (inProgressCount > 0) {
    return {
      objectiveId: objective.id,
      objectiveTitle: objective.title,
      objectiveCreatedAt: objective.created_at,
      rootTask,
      rootStatus,
      childCount: childTasks.length,
      assignedCount,
      inProgressCount,
      doneCount,
      blockedCount,
      stageLabel: t('blackboard.executionFeedback.stage.running', 'Running'),
      helperText: t(
        'blackboard.executionFeedback.helper.running',
        '{{running}} child task(s) are running. {{done}}/{{total}} are done.',
        { running: inProgressCount, done: doneCount, total: childTasks.length }
      ),
      accentClassName:
        'border-success-border bg-success-bg text-status-text-success dark:border-success-border-dark dark:bg-success-bg-dark dark:text-status-text-success-dark',
      pulse: true,
    };
  }

  if (assignedCount > 0 && doneCount === childTasks.length) {
    return {
      objectiveId: objective.id,
      objectiveTitle: objective.title,
      objectiveCreatedAt: objective.created_at,
      rootTask,
      rootStatus,
      childCount: childTasks.length,
      assignedCount,
      inProgressCount,
      doneCount,
      blockedCount,
      stageLabel: t('blackboard.executionFeedback.stage.childrenDone', 'Child tasks complete'),
      helperText: t(
        'blackboard.executionFeedback.helper.childrenDone',
        'Waiting for the root task to summarize, verify, and advance the final state.'
      ),
      accentClassName:
        'border-success-border bg-success-bg text-status-text-success dark:border-success-border-dark dark:bg-success-bg-dark dark:text-status-text-success-dark',
      pulse: false,
    };
  }

  return {
    objectiveId: objective.id,
    objectiveTitle: objective.title,
    objectiveCreatedAt: objective.created_at,
    rootTask,
    rootStatus,
    childCount: childTasks.length,
    assignedCount,
    inProgressCount,
    doneCount,
    blockedCount,
    stageLabel:
      assignedCount > 0
        ? t('blackboard.executionFeedback.stage.assigned', 'Decomposed and assigned')
        : t(
            'blackboard.executionFeedback.stage.waitingAssignment',
            'Decomposed, waiting assignment'
          ),
    helperText:
      assignedCount > 0
        ? t(
            'blackboard.executionFeedback.helper.assigned',
            '{{assigned}}/{{total}} child task(s) are assigned and waiting for worker execution.',
            { assigned: assignedCount, total: childTasks.length }
          )
        : t(
            'blackboard.executionFeedback.helper.waitingAssignment',
            '{{total}} child task(s) have been created and are waiting for leader assignment.',
            { total: childTasks.length }
          ),
    accentClassName:
      'border-caution-border bg-caution-bg text-status-text-caution dark:border-caution-border-dark dark:bg-caution-bg-dark dark:text-status-text-caution-dark',
    pulse: false,
  };
}

function buildExecutionTimeline(
  item: ObjectiveExecutionFeedback,
  t: TFunction
): FeedbackTimelineStep[] {
  const rootReady = item.rootTask !== null;
  const childReady = item.childCount > 0;
  const assignmentReady = item.assignedCount > 0;
  const executionActive = item.inProgressCount > 0 || item.doneCount > 0 || item.blockedCount > 0;
  const completed =
    item.childCount > 0 && item.doneCount === item.childCount && item.blockedCount === 0;

  return [
    {
      id: 'objective',
      label: t('blackboard.executionFeedback.timeline.objective', 'Objective created'),
      helper: t(
        'blackboard.executionFeedback.timeline.objectiveHelper',
        'The user submitted the objective on the central blackboard.'
      ),
      state: 'complete',
    },
    {
      id: 'root',
      label: t('blackboard.executionFeedback.timeline.root', 'Create root task'),
      helper: rootReady
        ? t(
            'blackboard.executionFeedback.timeline.rootReady',
            'Sisyphus has an actionable root task.'
          )
        : t(
            'blackboard.executionFeedback.timeline.rootWaiting',
            'Waiting for the root task projection.'
          ),
      state: rootReady ? 'complete' : 'current',
    },
    {
      id: 'children',
      label: t('blackboard.executionFeedback.timeline.children', 'Decompose child tasks'),
      helper: childReady
        ? t(
            'blackboard.executionFeedback.timeline.childrenReady',
            '{{count}} child task(s) have been decomposed.',
            { count: item.childCount }
          )
        : t(
            'blackboard.executionFeedback.timeline.childrenWaiting',
            'Waiting for the leader to decompose tasks.'
          ),
      state: childReady ? 'complete' : rootReady ? 'current' : 'upcoming',
    },
    {
      id: 'assignment',
      label: t('blackboard.executionFeedback.timeline.assignment', 'Assign to agents'),
      helper: assignmentReady
        ? t(
            'blackboard.executionFeedback.timeline.assignmentReady',
            '{{count}} child task(s) have been assigned.',
            { count: item.assignedCount }
          )
        : childReady
          ? t(
              'blackboard.executionFeedback.timeline.assignmentWaiting',
              'Waiting for the leader to finish assignment.'
            )
          : t(
              'blackboard.executionFeedback.timeline.assignmentUpcoming',
              'Assignment starts after decomposition.'
            ),
      state: assignmentReady ? 'complete' : childReady ? 'current' : 'upcoming',
    },
    {
      id: 'execution',
      label: completed
        ? t('blackboard.executionFeedback.timeline.executionComplete', 'Execution complete')
        : t('blackboard.executionFeedback.timeline.executionProgress', 'Execution progress'),
      helper: completed
        ? t(
            'blackboard.executionFeedback.timeline.executionCompleteHelper',
            'All child tasks are done. Waiting for the root task to summarize.'
          )
        : executionActive
          ? t(
              'blackboard.executionFeedback.timeline.executionActive',
              '{{running}} running, {{done}} done.',
              { running: item.inProgressCount, done: item.doneCount }
            )
          : t(
              'blackboard.executionFeedback.timeline.executionUpcoming',
              'Live execution progress appears after assignment.'
            ),
      state: completed
        ? 'complete'
        : executionActive
          ? 'current'
          : assignmentReady
            ? 'current'
            : 'upcoming',
    },
  ];
}

function formatEventTimestamp(value: string, locale: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return new Intl.DateTimeFormat(locale === 'zh-CN' ? 'zh-CN' : 'en-US', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date);
}

function buildExecutionEventLog(
  item: ObjectiveExecutionFeedback,
  tasks: WorkspaceTask[],
  t: TFunction,
  locale: string
): FeedbackLogEntry[] {
  const entries: FeedbackLogEntry[] = [
    {
      id: `objective-${item.objectiveId}`,
      label: t('blackboard.executionFeedback.events.objectiveCreated', 'Objective created'),
      timestamp: formatEventTimestamp(item.objectiveCreatedAt, locale),
    },
  ];

  if (item.rootTask) {
    entries.push({
      id: `root-${item.rootTask.id}`,
      label: t('blackboard.executionFeedback.events.rootCreated', 'Root task created'),
      timestamp: formatEventTimestamp(item.rootTask.created_at, locale),
    });
  }

  const childTasks = item.rootTask
    ? tasks.filter((task) => task.metadata.root_goal_task_id === item.rootTask?.id)
    : [];
  if (childTasks.length > 0) {
    const firstChildCreatedAt = [...childTasks].sort((left, right) =>
      left.created_at.localeCompare(right.created_at)
    )[0]?.created_at;
    if (firstChildCreatedAt) {
      entries.push({
        id: `children-${item.objectiveId}`,
        label: t(
          'blackboard.executionFeedback.events.childrenCreated',
          '{{count}} child task(s) created',
          { count: childTasks.length }
        ),
        timestamp: formatEventTimestamp(firstChildCreatedAt, locale),
      });
    }
  }

  if (item.assignedCount > 0) {
    const assignedTasks = childTasks.filter((task) =>
      Boolean(task.assignee_agent_id || task.assignee_user_id)
    );
    const assignmentTimestamp = [...assignedTasks]
      .map((task) => task.updated_at ?? task.created_at)
      .sort()[0];
    if (assignmentTimestamp) {
      entries.push({
        id: `assigned-${item.objectiveId}`,
        label: t(
          'blackboard.executionFeedback.events.assigned',
          '{{count}} child task(s) assigned',
          { count: item.assignedCount }
        ),
        timestamp: formatEventTimestamp(assignmentTimestamp, locale),
      });
    }
  }

  if (item.inProgressCount > 0) {
    const inProgressTasks = childTasks.filter((task) => task.status === 'in_progress');
    const executionTimestamp = [...inProgressTasks]
      .map((task) => task.updated_at ?? task.created_at)
      .sort()[0];
    if (executionTimestamp) {
      entries.push({
        id: `running-${item.objectiveId}`,
        label: t('blackboard.executionFeedback.events.running', '{{count}} child task(s) running', {
          count: item.inProgressCount,
        }),
        timestamp: formatEventTimestamp(executionTimestamp, locale),
        emphasis: true,
      });
    }
  } else if (item.doneCount > 0 && item.doneCount === item.childCount) {
    const completionTimestamp = [...childTasks]
      .map((task) => task.completed_at ?? task.updated_at ?? task.created_at)
      .sort()
      .slice(-1)[0];
    if (completionTimestamp) {
      entries.push({
        id: `done-${item.objectiveId}`,
        label: t('blackboard.executionFeedback.events.allDone', 'All child tasks complete'),
        timestamp: formatEventTimestamp(completionTimestamp, locale),
        emphasis: true,
      });
    }
  }

  if (item.blockedCount > 0) {
    const blockedTimestamp = childTasks
      .filter((task) => task.status === 'blocked')
      .map((task) => task.updated_at ?? task.created_at)
      .sort()
      .slice(-1)[0];
    if (blockedTimestamp) {
      entries.push({
        id: `blocked-${item.objectiveId}`,
        label: t('blackboard.executionFeedback.events.blocked', '{{count}} child task(s) blocked', {
          count: item.blockedCount,
        }),
        timestamp: formatEventTimestamp(blockedTimestamp, locale),
        emphasis: true,
      });
    }
  }

  return entries.slice(-5).reverse();
}

function buildChildTaskLogs(
  item: ObjectiveExecutionFeedback,
  tasks: WorkspaceTask[],
  agents: WorkspaceAgent[],
  t: TFunction,
  locale: string
): ChildTaskLogEntry[] {
  if (!item.rootTask) {
    return [];
  }

  return tasks
    .filter((task) => task.metadata.root_goal_task_id === item.rootTask?.id)
    .sort((left, right) => left.created_at.localeCompare(right.created_at))
    .map((task) => {
      const adjudication = getPendingLeaderAdjudicationSummary(task, agents);
      const events: FeedbackLogEntry[] = [
        {
          id: `${task.id}-created`,
          label: t('blackboard.executionFeedback.child.created', 'Child task created'),
          timestamp: formatEventTimestamp(task.created_at, locale),
        },
      ];

      const assignmentTimestamp = task.updated_at ?? task.created_at;
      if (task.assignee_agent_id || task.assignee_user_id) {
        const assigneeLabel = resolveAssigneeLabel(
          task,
          agents,
          t('workspaceDetail.taskBoard.unassigned', 'Unassigned')
        );
        events.push({
          id: `${task.id}-assigned`,
          label: t('blackboard.executionFeedback.child.assignedTo', 'Assigned to {{name}}', {
            name: assigneeLabel,
          }),
          timestamp: formatEventTimestamp(assignmentTimestamp, locale),
        });
      }

      if (task.status === 'in_progress') {
        events.push({
          id: `${task.id}-running`,
          label: t('blackboard.executionFeedback.child.running', 'Started running'),
          timestamp: formatEventTimestamp(task.updated_at ?? task.created_at, locale),
          emphasis: true,
        });
      }

      if (task.status === 'done') {
        events.push({
          id: `${task.id}-done`,
          label: t('blackboard.executionFeedback.child.done', 'Execution complete'),
          timestamp: formatEventTimestamp(
            task.completed_at ?? task.updated_at ?? task.created_at,
            locale
          ),
          emphasis: true,
        });
      }

      if (task.status === 'blocked') {
        events.push({
          id: `${task.id}-blocked`,
          label: task.blocker_reason
            ? t('blackboard.executionFeedback.child.blockedWithReason', 'Blocked: {{reason}}', {
                reason: task.blocker_reason,
              })
            : t('blackboard.executionFeedback.child.blocked', 'Blocked'),
          timestamp: formatEventTimestamp(task.updated_at ?? task.created_at, locale),
          emphasis: true,
        });
      }

      const conversationId = getTaskAttemptConversationId(task);
      const attemptNumber = getTaskAttemptNumber(task);

      return {
        childTaskId: task.id,
        title: task.title,
        assigneeLabel: resolveAssigneeLabel(
          task,
          agents,
          t('workspaceDetail.taskBoard.unassigned', 'Unassigned')
        ),
        workerLabel: adjudication.workerLabel,
        status: task.status,
        pendingAdjudication: adjudication.pending,
        reportTypeLabel: adjudication.reportTypeLabel,
        events: events.reverse(),
        conversationId,
        attemptNumber,
      };
    });
}

function ChildTaskLogCard({
  child,
  expanded,
  filterMode,
  onToggle,
  onJump,
  conversationHref,
}: ChildTaskLogCardProps) {
  const { t } = useTranslation();
  const [copiedEventId, setCopiedEventId] = useState<string | null>(null);
  const latestEventRef = useRef<HTMLDivElement | null>(null);
  const visibleEvents = filterMode === 'all' ? child.events : child.events.slice(0, 1);

  useEffect(() => {
    if (!expanded || !latestEventRef.current) {
      return;
    }
    latestEventRef.current.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }, [expanded, filterMode, child.childTaskId]);

  const handleCopySnapshot = async (entry: FeedbackLogEntry) => {
    const snapshot = [
      `task_id: ${child.childTaskId}`,
      `title: ${child.title}`,
      `assignee: ${child.assigneeLabel}`,
      ...(child.workerLabel ? [`worker: ${child.workerLabel}`] : []),
      `status: ${child.status}`,
      ...(child.pendingAdjudication ? ['pending_adjudication: true'] : []),
      ...(child.attemptNumber ? [`attempt: ${String(child.attemptNumber)}`] : []),
      `event: ${entry.label}`,
      `timestamp: ${entry.timestamp}`,
    ].join('\n');

    try {
      await navigator.clipboard.writeText(snapshot);
      setCopiedEventId(entry.id);
      window.setTimeout(() => {
        setCopiedEventId((current) => (current === entry.id ? null : current));
      }, 1600);
    } catch {
      setCopiedEventId(null);
    }
  };

  const statusTone =
    child.status === 'done'
      ? 'border-success-border/60 bg-success-bg text-status-text-success dark:border-success-border-dark/60 dark:bg-success-bg-dark dark:text-status-text-success-dark'
      : child.status === 'in_progress'
        ? 'border-primary/40 bg-primary/10 text-primary dark:border-primary-300/40 dark:bg-primary-300/10 dark:text-primary-100'
        : child.status === 'blocked'
          ? 'border-error-border/60 bg-error-bg text-status-text-error dark:border-error-border-dark/60 dark:bg-error-bg-dark dark:text-status-text-error-dark'
          : 'border-caution-border/60 bg-caution-bg text-status-text-caution dark:border-caution-border-dark/60 dark:bg-caution-bg-dark dark:text-status-text-caution-dark';

  return (
    <div className="rounded-lg border border-current/10 bg-white/40 p-3 dark:bg-black/10">
      <div className="flex items-start justify-between gap-3">
        <button
          type="button"
          onClick={onToggle}
          className="flex min-w-0 flex-1 items-center gap-2 text-left"
        >
          {expanded ? (
            <ChevronUp size={14} aria-hidden="true" />
          ) : (
            <ChevronDown size={14} aria-hidden="true" />
          )}
          <div className="min-w-0">
            <div className="truncate text-xs font-semibold">{child.title}</div>
            <div className="mt-1 flex flex-wrap items-center gap-2">
              <span
                className={`rounded-full border px-2 py-0.5 text-[10px] font-medium ${statusTone}`}
              >
                {child.status}
              </span>
              <span className="rounded-full border border-current/15 px-2 py-0.5 text-[10px] opacity-80">
                {child.assigneeLabel}
              </span>
              {child.workerLabel && child.workerLabel !== child.assigneeLabel && (
                <span className="rounded-full border border-primary/20 bg-primary/10 px-2 py-0.5 text-[10px] font-medium text-primary dark:border-primary-300/20 dark:bg-primary-300/10 dark:text-primary-100">
                  {t('blackboard.executionFeedback.child.worker', 'Worker')} {child.workerLabel}
                </span>
              )}
              {child.pendingAdjudication && (
                <span className="rounded-full border border-info-border bg-info-bg px-2 py-0.5 text-[10px] font-medium text-status-text-info dark:border-info-border-dark dark:bg-info-bg-dark dark:text-status-text-info-dark">
                  {t(
                    'blackboard.executionFeedback.child.pendingAdjudication',
                    'Pending adjudication'
                  )}
                  {child.reportTypeLabel ? ` · ${child.reportTypeLabel}` : ''}
                </span>
              )}
            </div>
          </div>
        </button>
        <div className="flex shrink-0 items-center gap-1.5">
          <button
            type="button"
            onClick={onJump}
            className="rounded-md border border-current/15 px-2 py-1 text-[10px] font-medium opacity-80 transition hover:bg-white/40 dark:hover:bg-black/10"
          >
            {t('blackboard.executionFeedback.controls.jumpToTaskBoard', 'Jump to task board')}
          </button>
          {conversationHref && (child.status === 'in_progress' || child.status === 'done') && (
            <Link
              to={conversationHref}
              className="rounded-md border border-primary/40 bg-primary/10 px-2 py-1 text-[10px] font-medium text-primary transition hover:bg-primary/20 dark:border-primary-300/40 dark:bg-primary-300/10 dark:text-primary-100 dark:hover:bg-primary-300/20"
              title={child.attemptNumber ? `Attempt #${String(child.attemptNumber)}` : undefined}
            >
              {t(
                'blackboard.executionFeedback.controls.jumpToConversation',
                'Jump to conversation'
              )}
              {child.attemptNumber ? ` #${String(child.attemptNumber)}` : ''}
            </Link>
          )}
        </div>
      </div>
      {expanded && (
        <div className="mt-3 space-y-2">
          {visibleEvents.map((entry, index) => (
            <div
              key={entry.id}
              ref={index === 0 ? latestEventRef : null}
              className={`flex items-center justify-between gap-3 rounded-md px-2 py-1.5 text-[11px] ${
                index === 0
                  ? 'border border-primary/20 bg-primary/10 dark:border-primary-300/20 dark:bg-primary-300/10'
                  : entry.emphasis
                    ? 'bg-white/60 dark:bg-black/15'
                    : 'bg-transparent'
              }`}
            >
              <span className="truncate">
                {index === 0
                  ? t('blackboard.executionFeedback.events.latest', 'Latest: {{label}}', {
                      label: entry.label,
                    })
                  : entry.label}
              </span>
              <div className="flex items-center gap-2">
                <span className="shrink-0 font-medium opacity-70">{entry.timestamp}</span>
                <button
                  type="button"
                  onClick={() => {
                    void handleCopySnapshot(entry);
                  }}
                  className="inline-flex items-center gap-1 rounded-md border border-current/15 px-2 py-1 text-[10px] font-medium opacity-80 transition hover:bg-white/40 dark:hover:bg-black/10"
                >
                  {copiedEventId === entry.id ? (
                    <>
                      <Check size={12} aria-hidden="true" />{' '}
                      {t('blackboard.executionFeedback.controls.copied', 'Copied')}
                    </>
                  ) : (
                    <>
                      <Copy size={12} aria-hidden="true" />{' '}
                      {t('blackboard.executionFeedback.controls.copySnapshot', 'Copy snapshot')}
                    </>
                  )}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function getTimelineIcon(step: FeedbackTimelineStep): React.ReactNode {
  if (step.state === 'complete') {
    return <CheckCircle2 size={16} aria-hidden="true" />;
  }
  if (step.state === 'current') {
    if (step.id === 'execution') {
      return <LoaderCircle size={16} className="motion-safe:animate-spin" aria-hidden="true" />;
    }
    return <Orbit size={16} aria-hidden="true" />;
  }
  switch (step.id) {
    case 'root':
      return <Target size={16} aria-hidden="true" />;
    case 'children':
      return <GitBranchPlus size={16} aria-hidden="true" />;
    case 'assignment':
      return <Users size={16} aria-hidden="true" />;
    default:
      return <CircleDashed size={16} aria-hidden="true" />;
  }
}

function getTimelineTone(step: FeedbackTimelineStep): string {
  if (step.state === 'complete') {
    return 'border-success-border/60 bg-success-bg text-status-text-success dark:border-success-border-dark/60 dark:bg-success-bg-dark dark:text-status-text-success-dark';
  }
  if (step.state === 'current') {
    return 'border-primary/40 bg-primary/10 text-primary dark:border-primary-300/40 dark:bg-primary-300/10 dark:text-primary-100';
  }
  return 'border-border-light bg-surface-muted/70 text-text-muted dark:border-border-dark dark:bg-surface-dark-alt/70 dark:text-text-muted';
}

export function GoalsTab({
  objectives,
  tasks,
  agents = [],
  workspaceId,
  tenantId,
  projectId,
  onDeleteObjective,
  onProjectObjective,
  onCreateObjective,
}: GoalsTabProps) {
  const { t, i18n } = useTranslation();
  const [expandedObjectiveIds, setExpandedObjectiveIds] = useState<Record<string, boolean>>({});
  const [expandedChildTaskIds, setExpandedChildTaskIds] = useState<Record<string, boolean>>({});
  const [eventFilterByObjectiveId, setEventFilterByObjectiveId] = useState<
    Record<string, 'latest' | 'all'>
  >({});
  const [autonomyTicking, setAutonomyTicking] = useState(false);
  const locale = i18n.resolvedLanguage || i18n.language || 'en-US';

  const handleRunAutonomy = async (force: boolean) => {
    setAutonomyTicking(true);
    try {
      const result = await workspaceAutonomyService.tick(workspaceId, { force });
      if (result.triggered) {
        message.success(
          t(
            'blackboard.autonomy.success',
            'Autonomy triggered. The leader will advance the next step.'
          )
        );
      } else if (result.reason === 'cooling_down') {
        message.info(
          t(
            'blackboard.autonomy.coolingDown',
            'Cooling down. Hold Shift and click again to force a tick.'
          )
        );
      } else if (result.reason === 'no_open_root') {
        message.info(
          t('blackboard.autonomy.noOpenRoot', 'This workspace has no open goal to progress.')
        );
      } else if (result.reason === 'no_root_needs_progress') {
        message.info(t('blackboard.autonomy.stable', 'All goals are stable right now.'));
      } else {
        message.warning(
          t('blackboard.autonomy.noop', 'Autonomy was not triggered: {{reason}}', {
            reason: result.reason || 'unknown',
          })
        );
      }
    } catch (err) {
      const description = err instanceof Error ? err.message : String(err);
      message.error(
        t('blackboard.autonomy.failed', 'Failed to start autonomy: {{description}}', {
          description,
        })
      );
    } finally {
      setAutonomyTicking(false);
    }
  };
  const executionFeedback = objectives
    .map((objective) => getObjectiveExecutionFeedback(objective, tasks, t))
    .sort((left, right) => {
      const leftRootTime = left.rootTask?.created_at ?? '';
      const rightRootTime = right.rootTask?.created_at ?? '';
      return (
        rightRootTime.localeCompare(leftRootTime) ||
        right.objectiveTitle.localeCompare(left.objectiveTitle)
      );
    });

  const toggleDetailedLog = (objectiveId: string) => {
    setExpandedObjectiveIds((current) => ({
      ...current,
      [objectiveId]: !current[objectiveId],
    }));
  };

  const isChildLogExpanded = (childTaskId: string, status: WorkspaceTask['status']) =>
    expandedChildTaskIds[childTaskId] ?? status === 'in_progress';

  const toggleChildLog = (childTaskId: string, status: WorkspaceTask['status']) => {
    setExpandedChildTaskIds((current) => ({
      ...current,
      [childTaskId]: !isChildLogExpanded(childTaskId, status),
    }));
  };

  const jumpToTaskBoardCard = (taskId: string) => {
    const element = document.getElementById(`workspace-task-${taskId}`);
    if (!element) {
      return;
    }
    element.scrollIntoView({ behavior: 'smooth', block: 'center' });
    element.classList.add(
      'ring-2',
      'ring-primary',
      'bg-primary/10',
      'transition-[color,background-color,border-color,box-shadow,opacity]',
      'duration-300'
    );
    window.setTimeout(() => {
      element.classList.remove(
        'ring-2',
        'ring-primary',
        'bg-primary/10',
        'transition-[color,background-color,border-color,box-shadow,opacity]',
        'duration-300'
      );
    }, 1600);
  };

  return (
    <div className="min-w-0 space-y-6">
      <ObjectiveList
        objectives={objectives}
        tasks={tasks}
        onDelete={onDeleteObjective}
        onProject={onProjectObjective}
        onCreate={onCreateObjective}
      />

      <section className="flex items-center justify-between gap-3 rounded-lg border border-border-light bg-surface-light px-4 py-3 dark:border-border-dark dark:bg-surface-dark">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-text-primary dark:text-text-inverse">
            {t('blackboard.autonomy.title', 'Autonomy')}
          </h3>
          <p className="mt-0.5 text-[11px] text-text-secondary dark:text-text-muted">
            {t(
              'blackboard.autonomy.description',
              'Ask the leader to inspect workspace state and advance the next step. Shift-click bypasses cooldown.'
            )}
          </p>
        </div>
        <Button
          size="small"
          type="primary"
          icon={<Zap size={14} />}
          loading={autonomyTicking}
          onClick={(event) => {
            const force = event.shiftKey;
            void handleRunAutonomy(force);
          }}
        >
          {t('blackboard.autonomy.run', 'Run autonomy')}
        </Button>
      </section>

      {executionFeedback.length > 0 && (
        <section className="min-w-0 space-y-3 overflow-hidden rounded-lg border border-border-light bg-surface-light p-4 dark:border-border-dark dark:bg-surface-dark">
          <div className="flex items-center gap-2">
            <Sparkles size={16} className="text-primary dark:text-primary-200" />
            <h3 className="text-sm font-semibold text-text-primary dark:text-text-inverse">
              {t('blackboard.executionFeedback.title', 'Orchestration feedback')}
            </h3>
          </div>
          <HostedProjectionBadge
            labelKey="blackboard.executionFeedbackSurfaceHint"
            fallbackLabel="workspace objective and task projection"
          />
          <div className="grid min-w-0 gap-3 lg:grid-cols-2">
            {executionFeedback.map((item) => (
              <article
                key={item.objectiveId}
                className={`min-w-0 overflow-hidden rounded-lg border px-4 py-3 transition-colors duration-200 ${item.accentClassName} ${item.pulse ? 'shadow-[0_0_0_1px_rgba(99,102,241,0.08),0_12px_32px_-24px_rgba(99,102,241,0.45)]' : ''}`}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="text-xs font-semibold uppercase tracking-wide opacity-80">
                      {item.stageLabel}
                    </div>
                    <div className="mt-1 break-words text-sm font-semibold">
                      {item.objectiveTitle}
                    </div>
                    <p className="mt-1 break-words text-xs leading-5 opacity-90">
                      {item.helperText}
                    </p>
                  </div>
                  <div className="mt-0.5 flex items-center gap-1">
                    {item.rootStatus === 'missing' ? (
                      <LoaderCircle
                        size={16}
                        className={item.pulse ? 'animate-spin' : undefined}
                        aria-label={t(
                          'blackboard.executionFeedback.aria.waiting',
                          'Orchestration waiting'
                        )}
                      />
                    ) : item.inProgressCount > 0 ? (
                      <PlayCircle
                        size={16}
                        aria-label={t(
                          'blackboard.executionFeedback.aria.running',
                          'Orchestration running'
                        )}
                      />
                    ) : item.doneCount > 0 && item.doneCount === item.childCount ? (
                      <CheckCircle2
                        size={16}
                        aria-label={t(
                          'blackboard.executionFeedback.aria.complete',
                          'Orchestration complete'
                        )}
                      />
                    ) : (
                      <Orbit
                        size={16}
                        aria-label={t(
                          'blackboard.executionFeedback.aria.active',
                          'Orchestration active'
                        )}
                      />
                    )}
                  </div>
                </div>

                <div className="mt-3 flex flex-wrap gap-2 text-[11px]">
                  <span className="rounded-full border border-current/15 bg-white/50 px-2 py-1 dark:bg-black/10">
                    root: {item.rootStatus === 'missing' ? 'pending' : item.rootStatus}
                  </span>
                  <span className="rounded-full border border-current/15 bg-white/50 px-2 py-1 dark:bg-black/10">
                    child: {item.childCount}
                  </span>
                  <span className="rounded-full border border-current/15 bg-white/50 px-2 py-1 dark:bg-black/10">
                    <Users size={12} className="mr-1 inline-flex" />
                    assigned {item.assignedCount}
                  </span>
                  <span className="rounded-full border border-current/15 bg-white/50 px-2 py-1 dark:bg-black/10">
                    running {item.inProgressCount}
                  </span>
                  <span className="rounded-full border border-current/15 bg-white/50 px-2 py-1 dark:bg-black/10">
                    done {item.doneCount}
                  </span>
                </div>

                <div className="mt-4 grid gap-2">
                  {buildExecutionTimeline(item, t).map((step, index, steps) => (
                    <div key={step.id} className="flex items-start gap-3">
                      <div className="flex flex-col items-center">
                        <div
                          className={`flex h-8 w-8 items-center justify-center rounded-full border ${getTimelineTone(step)}`}
                        >
                          {getTimelineIcon(step)}
                        </div>
                        {index < steps.length - 1 && (
                          <div
                            className={`mt-1 h-6 w-px ${
                              step.state === 'complete'
                                ? 'bg-success-border dark:bg-success-border-dark'
                                : 'bg-border-light dark:bg-border-dark'
                            }`}
                          />
                        )}
                      </div>
                      <div className="min-w-0 flex-1 pb-2">
                        <div className="text-xs font-semibold">{step.label}</div>
                        <div className="mt-1 text-[11px] leading-5 opacity-80">{step.helper}</div>
                      </div>
                    </div>
                  ))}
                </div>

                <div className="mt-4 rounded-lg border border-current/10 bg-white/30 p-3 dark:bg-black/10">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div className="text-[11px] font-semibold uppercase tracking-wide opacity-75">
                      {t('blackboard.executionFeedback.eventLogTitle', 'Event stream log')}
                    </div>
                    <div className="flex items-center gap-2">
                      <div className="inline-flex rounded-md border border-current/15 p-0.5 text-[10px] font-medium opacity-80">
                        <button
                          type="button"
                          onClick={() => {
                            setEventFilterByObjectiveId((current) => ({
                              ...current,
                              [item.objectiveId]: 'latest',
                            }));
                          }}
                          className={`rounded px-2 py-1 transition ${
                            (eventFilterByObjectiveId[item.objectiveId] ?? 'latest') === 'latest'
                              ? 'bg-white/70 dark:bg-black/20'
                              : ''
                          }`}
                        >
                          {t('blackboard.executionFeedback.controls.latestOnly', 'Latest')}
                        </button>
                        <button
                          type="button"
                          onClick={() => {
                            setEventFilterByObjectiveId((current) => ({
                              ...current,
                              [item.objectiveId]: 'all',
                            }));
                          }}
                          className={`rounded px-2 py-1 transition ${
                            (eventFilterByObjectiveId[item.objectiveId] ?? 'latest') === 'all'
                              ? 'bg-white/70 dark:bg-black/20'
                              : ''
                          }`}
                        >
                          {t('blackboard.executionFeedback.controls.viewAll', 'All events')}
                        </button>
                      </div>
                      <button
                        type="button"
                        onClick={() => {
                          toggleDetailedLog(item.objectiveId);
                        }}
                        className="inline-flex items-center gap-1 rounded-md border border-current/15 px-2 py-1 text-[11px] font-medium opacity-80 transition hover:bg-white/40 dark:hover:bg-black/10"
                      >
                        {expandedObjectiveIds[item.objectiveId] ? (
                          <>
                            {t('blackboard.executionFeedback.controls.collapseLog', 'Collapse log')}{' '}
                            <ChevronUp size={14} />
                          </>
                        ) : (
                          <>
                            {t('blackboard.executionFeedback.controls.expandLog', 'Expand log')}{' '}
                            <ChevronDown size={14} />
                          </>
                        )}
                      </button>
                    </div>
                  </div>
                  <div className="mt-3 space-y-2">
                    {buildExecutionEventLog(item, tasks, t, locale).map((entry) => (
                      <div
                        key={entry.id}
                        className={`flex items-center justify-between gap-3 rounded-md px-2 py-1.5 text-[11px] transition-colors duration-200 ${
                          entry.emphasis ? 'bg-white/60 dark:bg-black/15' : 'bg-transparent'
                        }`}
                      >
                        <span className="truncate">{entry.label}</span>
                        <span className="shrink-0 font-medium opacity-70">{entry.timestamp}</span>
                      </div>
                    ))}
                  </div>

                  {expandedObjectiveIds[item.objectiveId] && (
                    <div className="mt-4 space-y-3 border-t border-current/10 pt-4">
                      {buildChildTaskLogs(item, tasks, agents, t, locale).length === 0 ? (
                        <div className="rounded-lg bg-white/40 px-3 py-2 text-[11px] opacity-80 dark:bg-black/10">
                          {t(
                            'blackboard.executionFeedback.emptyChildEvents',
                            'No child task detail events yet.'
                          )}
                        </div>
                      ) : (
                        buildChildTaskLogs(item, tasks, agents, t, locale).map((child) => {
                          const conversationHref =
                            child.conversationId && tenantId
                              ? buildAgentWorkspacePath({
                                  tenantId,
                                  conversationId: child.conversationId,
                                  projectId,
                                  workspaceId,
                                })
                              : undefined;
                          return (
                            <ChildTaskLogCard
                              key={child.childTaskId}
                              child={child}
                              expanded={isChildLogExpanded(child.childTaskId, child.status)}
                              filterMode={eventFilterByObjectiveId[item.objectiveId] ?? 'latest'}
                              onToggle={() => {
                                toggleChildLog(child.childTaskId, child.status);
                              }}
                              onJump={() => {
                                jumpToTaskBoardCard(child.childTaskId);
                              }}
                              conversationHref={conversationHref}
                            />
                          );
                        })
                      )}
                    </div>
                  )}
                </div>

                {item.rootTask &&
                  typeof item.rootTask.metadata.goal_progress_summary === 'string' && (
                    <div className="mt-3 break-words rounded-lg border border-current/10 bg-white/40 px-3 py-2 text-[11px] opacity-90 dark:bg-black/10">
                      {item.rootTask.metadata.goal_progress_summary}
                    </div>
                  )}
              </article>
            ))}
          </div>
        </section>
      )}

      <TaskBoard workspaceId={workspaceId} showAutonomyAction={false} />
    </div>
  );
}
