import { useEffect, useRef, useState } from 'react';

import { Link } from 'react-router-dom';

import { App, Button } from 'antd';
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

import type { CyberObjective, WorkspaceAgent, WorkspaceTask } from '@/types/workspace';

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
  agents: WorkspaceAgent[]
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

  return task.assignee_user_id ?? '未分配';
}

function getObjectiveExecutionFeedback(
  objective: CyberObjective,
  tasks: WorkspaceTask[]
): ObjectiveExecutionFeedback {
  const rootTask = tasks.find((task) => task.metadata.objective_id === objective.id) ?? null;
  const rootStatus = rootTask?.status ?? 'missing';
  const childTasks = rootTask
    ? tasks.filter((task) => task.metadata.root_goal_task_id === rootTask.id)
    : [];
  const assignedCount = childTasks.filter(
    (task) => Boolean(task.assignee_agent_id || task.assignee_user_id)
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
      stageLabel: '等待 root task',
      helperText: '目标已创建，正在触发 Sisyphus 接管并投影为 root task。',
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
      stageLabel: rootStatus === 'in_progress' ? '已生成 root task，等待拆解' : '已生成 root task',
      helperText:
        '现在应该进入任务拆解阶段；一旦 child task 创建出来，这里会实时显示分配和执行进度。',
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
      stageLabel: '执行受阻',
      helperText: `${String(blockedCount)} 个 child task 已阻塞，请查看任务板中的 blocker 与 leader 汇总状态。`,
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
      stageLabel: '执行中',
      helperText: `${String(inProgressCount)} 个 child task 正在执行，${String(doneCount)}/${String(childTasks.length)} 已完成。`,
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
      stageLabel: '子任务已完成',
      helperText: '等待 root task 汇总、验收并推进最终状态。',
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
    stageLabel: assignedCount > 0 ? '已拆解并分配' : '已拆解，等待分配',
    helperText:
      assignedCount > 0
        ? `${String(assignedCount)}/${String(childTasks.length)} 个 child task 已分配，等待 worker 开工。`
        : `已生成 ${String(childTasks.length)} 个 child task，等待 leader 完成任务分配。`,
    accentClassName:
      'border-caution-border bg-caution-bg text-status-text-caution dark:border-caution-border-dark dark:bg-caution-bg-dark dark:text-status-text-caution-dark',
    pulse: false,
  };
}

function buildExecutionTimeline(
  item: ObjectiveExecutionFeedback
): FeedbackTimelineStep[] {
  const rootReady = item.rootTask !== null;
  const childReady = item.childCount > 0;
  const assignmentReady = item.assignedCount > 0;
  const executionActive = item.inProgressCount > 0 || item.doneCount > 0 || item.blockedCount > 0;
  const completed = item.childCount > 0 && item.doneCount === item.childCount && item.blockedCount === 0;

  return [
    {
      id: 'objective',
      label: '目标已创建',
      helper: '用户已在中央黑板提交目标。',
      state: 'complete',
    },
    {
      id: 'root',
      label: '生成 root task',
      helper: rootReady ? 'Sisyphus 已获得可接管的 root。' : '等待 root task 投影完成。',
      state: rootReady ? 'complete' : 'current',
    },
    {
      id: 'children',
      label: '拆解 child tasks',
      helper: childReady ? `已拆解 ${String(item.childCount)} 个 child task。` : '等待 leader 进行任务拆解。',
      state: childReady ? 'complete' : rootReady ? 'current' : 'upcoming',
    },
    {
      id: 'assignment',
      label: '分配给 agents',
      helper: assignmentReady
        ? `已分配 ${String(item.assignedCount)} 个 child task。`
        : childReady
          ? '等待 leader 完成分配。'
          : '拆解完成后进入分配阶段。',
      state: assignmentReady ? 'complete' : childReady ? 'current' : 'upcoming',
    },
    {
      id: 'execution',
      label: completed ? '执行完成' : '执行推进',
      helper: completed
        ? '所有 child task 已完成，等待 root 汇总收口。'
        : executionActive
          ? `运行中 ${String(item.inProgressCount)}，完成 ${String(item.doneCount)}。`
          : '分配完成后会实时显示执行进度。',
      state: completed ? 'complete' : executionActive ? 'current' : assignmentReady ? 'current' : 'upcoming',
    },
  ];
}

function formatEventTimestamp(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date);
}

function buildExecutionEventLog(item: ObjectiveExecutionFeedback, tasks: WorkspaceTask[]): FeedbackLogEntry[] {
  const entries: FeedbackLogEntry[] = [
    {
      id: `objective-${item.objectiveId}`,
      label: '目标已创建',
      timestamp: formatEventTimestamp(item.objectiveCreatedAt),
    },
  ];

  if (item.rootTask) {
    entries.push({
      id: `root-${item.rootTask.id}`,
      label: 'root task 已生成',
      timestamp: formatEventTimestamp(item.rootTask.created_at),
    });
  }

  const childTasks = item.rootTask
    ? tasks.filter((task) => task.metadata.root_goal_task_id === item.rootTask?.id)
    : [];
  if (childTasks.length > 0) {
    const firstChildCreatedAt = [...childTasks]
      .sort((left, right) => left.created_at.localeCompare(right.created_at))[0]?.created_at;
    if (firstChildCreatedAt) {
      entries.push({
        id: `children-${item.objectiveId}`,
        label: `已拆解 ${String(childTasks.length)} 个 child task`,
        timestamp: formatEventTimestamp(firstChildCreatedAt),
      });
    }
  }

  if (item.assignedCount > 0) {
    const assignedTasks = childTasks.filter(
      (task) => Boolean(task.assignee_agent_id || task.assignee_user_id)
    );
    const assignmentTimestamp = [...assignedTasks]
      .map((task) => task.updated_at ?? task.created_at)
      .sort()[0];
    if (assignmentTimestamp) {
      entries.push({
        id: `assigned-${item.objectiveId}`,
        label: `已分配 ${String(item.assignedCount)} 个 child task`,
        timestamp: formatEventTimestamp(assignmentTimestamp),
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
        label: `${String(item.inProgressCount)} 个 child task 进入执行中`,
        timestamp: formatEventTimestamp(executionTimestamp),
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
        label: '所有 child task 已完成',
        timestamp: formatEventTimestamp(completionTimestamp),
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
        label: `${String(item.blockedCount)} 个 child task 进入阻塞`,
        timestamp: formatEventTimestamp(blockedTimestamp),
        emphasis: true,
      });
    }
  }

  return entries.slice(-5).reverse();
}

function buildChildTaskLogs(
  item: ObjectiveExecutionFeedback,
  tasks: WorkspaceTask[],
  agents: WorkspaceAgent[]
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
          label: 'child task 已创建',
          timestamp: formatEventTimestamp(task.created_at),
        },
      ];

      const assignmentTimestamp = task.updated_at ?? task.created_at;
      if (task.assignee_agent_id || task.assignee_user_id) {
        events.push({
          id: `${task.id}-assigned`,
          label: `已分配给 ${resolveAssigneeLabel(task, agents)}`,
          timestamp: formatEventTimestamp(assignmentTimestamp),
        });
      }

      if (task.status === 'in_progress') {
        events.push({
          id: `${task.id}-running`,
          label: '进入执行中',
          timestamp: formatEventTimestamp(task.updated_at ?? task.created_at),
          emphasis: true,
        });
      }

      if (task.status === 'done') {
        events.push({
          id: `${task.id}-done`,
          label: '执行完成',
          timestamp: formatEventTimestamp(task.completed_at ?? task.updated_at ?? task.created_at),
          emphasis: true,
        });
      }

      if (task.status === 'blocked') {
        events.push({
          id: `${task.id}-blocked`,
          label: `进入阻塞${task.blocker_reason ? `：${task.blocker_reason}` : ''}`,
          timestamp: formatEventTimestamp(task.updated_at ?? task.created_at),
          emphasis: true,
        });
      }

      const conversationId = getTaskAttemptConversationId(task);
      const attemptNumber = getTaskAttemptNumber(task);

      return {
        childTaskId: task.id,
        title: task.title,
        assigneeLabel: resolveAssigneeLabel(task, agents),
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
    <div className="rounded-xl border border-current/10 bg-white/40 p-3 dark:bg-black/10">
      <div className="flex items-start justify-between gap-3">
        <button type="button" onClick={onToggle} className="flex min-w-0 flex-1 items-center gap-2 text-left">
          {expanded ? <ChevronUp size={14} aria-hidden="true" /> : <ChevronDown size={14} aria-hidden="true" />}
          <div className="min-w-0">
            <div className="truncate text-xs font-semibold">{child.title}</div>
            <div className="mt-1 flex flex-wrap items-center gap-2">
              <span className={`rounded-full border px-2 py-0.5 text-[10px] font-medium ${statusTone}`}>
                {child.status}
              </span>
              <span className="rounded-full border border-current/15 px-2 py-0.5 text-[10px] opacity-80">
                {child.assigneeLabel}
              </span>
              {child.workerLabel && child.workerLabel !== child.assigneeLabel && (
                <span className="rounded-full border border-primary/20 bg-primary/10 px-2 py-0.5 text-[10px] font-medium text-primary dark:border-primary-300/20 dark:bg-primary-300/10 dark:text-primary-100">
                  Worker {child.workerLabel}
                </span>
              )}
              {child.pendingAdjudication && (
                <span className="rounded-full border border-info-border bg-info-bg px-2 py-0.5 text-[10px] font-medium text-status-text-info dark:border-info-border-dark dark:bg-info-bg-dark dark:text-status-text-info-dark">
                  Pending adjudication
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
            跳转到任务板
          </button>
          {conversationHref && (child.status === 'in_progress' || child.status === 'done') && (
            <Link
              to={conversationHref}
              className="rounded-md border border-primary/40 bg-primary/10 px-2 py-1 text-[10px] font-medium text-primary transition hover:bg-primary/20 dark:border-primary-300/40 dark:bg-primary-300/10 dark:text-primary-100 dark:hover:bg-primary-300/20"
              title={child.attemptNumber ? `Attempt #${String(child.attemptNumber)}` : undefined}
            >
              跳转到会话
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
              className={`flex items-center justify-between gap-3 rounded-lg px-2 py-1.5 text-[11px] ${
                index === 0
                  ? 'border border-primary/20 bg-primary/10 dark:border-primary-300/20 dark:bg-primary-300/10'
                  : entry.emphasis
                    ? 'bg-white/60 dark:bg-black/15'
                    : 'bg-transparent'
              }`}
            >
              <span className="truncate">{index === 0 ? `最新：${entry.label}` : entry.label}</span>
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
                      <Check size={12} aria-hidden="true" /> 已复制
                    </>
                  ) : (
                    <>
                      <Copy size={12} aria-hidden="true" /> 复制快照
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
    return <Orbit size={16} className="motion-safe:animate-pulse" aria-hidden="true" />;
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
  const { message } = App.useApp();
  const [expandedObjectiveIds, setExpandedObjectiveIds] = useState<Record<string, boolean>>({});
  const [expandedChildTaskIds, setExpandedChildTaskIds] = useState<Record<string, boolean>>({});
  const [eventFilterByObjectiveId, setEventFilterByObjectiveId] = useState<
    Record<string, 'latest' | 'all'>
  >({});
  const [autonomyTicking, setAutonomyTicking] = useState(false);

  const handleRunAutonomy = async (force: boolean) => {
    setAutonomyTicking(true);
    try {
      const result = await workspaceAutonomyService.tick(workspaceId, { force });
      if (result.triggered) {
        message.success('已触发自治：Leader 将推进下一步');
      } else if (result.reason === 'cooling_down') {
        message.info('冷却中（60s 内已触发过）。按住 Shift 再点可强制触发。');
      } else if (result.reason === 'no_open_root') {
        message.info('当前工作区没有进行中的 goal，无需触发。');
      } else if (result.reason === 'no_root_needs_progress') {
        message.info('所有 goal 都处于稳定状态，暂无需推进。');
      } else {
        message.warning(`未触发：${result.reason || 'unknown'}`);
      }
    } catch (err) {
      const description = err instanceof Error ? err.message : String(err);
      message.error(`启动自治失败：${description}`);
    } finally {
      setAutonomyTicking(false);
    }
  };
  const executionFeedback = objectives
    .map((objective) => getObjectiveExecutionFeedback(objective, tasks))
    .sort((left, right) => {
      const leftRootTime = left.rootTask?.created_at ?? '';
      const rightRootTime = right.rootTask?.created_at ?? '';
      return rightRootTime.localeCompare(leftRootTime) || right.objectiveTitle.localeCompare(left.objectiveTitle);
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
    element.classList.add('ring-2', 'ring-primary', 'bg-primary/10', 'transition-all', 'duration-300');
    window.setTimeout(() => {
      element.classList.remove(
        'ring-2',
        'ring-primary',
        'bg-primary/10',
        'transition-all',
        'duration-300'
      );
    }, 1600);
  };

  return (
    <div className="space-y-6">
      <ObjectiveList
        objectives={objectives}
        tasks={tasks}
        onDelete={onDeleteObjective}
        onProject={onProjectObjective}
        onCreate={onCreateObjective}
      />

      <section className="flex items-center justify-between gap-3 rounded-xl border border-border-light bg-surface-light px-4 py-3 dark:border-border-dark dark:bg-surface-dark">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-text-primary dark:text-text-inverse">
            自主推进
          </h3>
          <p className="mt-0.5 text-[11px] text-text-secondary dark:text-text-muted">
            触发 Leader 检查工作区状态并推进下一步（Shift+Click 绕过冷却）。
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
          Run Autonomy
        </Button>
      </section>

      {executionFeedback.length > 0 && (
        <section className="space-y-3 rounded-xl border border-border-light bg-surface-light p-4 dark:border-border-dark dark:bg-surface-dark">
          <div className="flex items-center gap-2">
            <Sparkles size={16} className="text-primary dark:text-primary-200" />
            <h3 className="text-sm font-semibold text-text-primary dark:text-text-inverse">
              自动编排反馈
            </h3>
          </div>
          <div className="grid gap-3 lg:grid-cols-2">
            {executionFeedback.map((item) => (
              <article
                key={item.objectiveId}
                className={`rounded-xl border px-4 py-3 transition-all duration-300 ${item.accentClassName} ${item.pulse ? 'motion-safe:shadow-[0_0_0_1px_rgba(99,102,241,0.12),0_12px_32px_-20px_rgba(99,102,241,0.5)]' : ''}`}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="text-xs font-semibold uppercase tracking-wide opacity-80">
                      {item.stageLabel}
                    </div>
                    <div className="mt-1 text-sm font-semibold">{item.objectiveTitle}</div>
                    <p className="mt-1 text-xs leading-5 opacity-90">{item.helperText}</p>
                  </div>
                  <div className="mt-0.5 flex items-center gap-1">
                    {item.rootStatus === 'missing' ? (
                      <LoaderCircle
                        size={16}
                        className={item.pulse ? 'animate-spin' : undefined}
                        aria-label="orchestration-waiting"
                      />
                    ) : item.inProgressCount > 0 ? (
                      <PlayCircle
                        size={16}
                        className={item.pulse ? 'animate-pulse' : undefined}
                        aria-label="orchestration-running"
                      />
                    ) : item.doneCount > 0 && item.doneCount === item.childCount ? (
                      <CheckCircle2 size={16} aria-label="orchestration-complete" />
                    ) : (
                      <Orbit size={16} aria-label="orchestration-active" />
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
                  {buildExecutionTimeline(item).map((step, index, steps) => (
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

                <div className="mt-4 rounded-xl border border-current/10 bg-white/30 p-3 dark:bg-black/10">
                  <div className="flex items-center justify-between gap-3">
                    <div className="text-[11px] font-semibold uppercase tracking-wide opacity-75">
                      事件流日志
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
                          只看最新事件
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
                          查看全部事件
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
                            收起详细日志 <ChevronUp size={14} />
                          </>
                        ) : (
                          <>
                            展开详细日志 <ChevronDown size={14} />
                          </>
                        )}
                      </button>
                    </div>
                  </div>
                  <div className="mt-3 space-y-2">
                    {buildExecutionEventLog(item, tasks).map((entry) => (
                      <div
                        key={entry.id}
                        className={`flex items-center justify-between gap-3 rounded-lg px-2 py-1.5 text-[11px] transition-all duration-300 ${
                          entry.emphasis
                            ? 'bg-white/60 dark:bg-black/15 motion-safe:animate-pulse'
                            : 'bg-transparent'
                        }`}
                      >
                        <span className="truncate">{entry.label}</span>
                        <span className="shrink-0 font-medium opacity-70">{entry.timestamp}</span>
                      </div>
                    ))}
                  </div>

                  {expandedObjectiveIds[item.objectiveId] && (
                    <div className="mt-4 space-y-3 border-t border-current/10 pt-4">
                      {buildChildTaskLogs(item, tasks, agents).length === 0 ? (
                        <div className="rounded-lg bg-white/40 px-3 py-2 text-[11px] opacity-80 dark:bg-black/10">
                          还没有 child task 详细事件。
                        </div>
                      ) : (
                        buildChildTaskLogs(item, tasks, agents).map((child) => {
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
                  <div className="mt-3 rounded-lg border border-current/10 bg-white/40 px-3 py-2 text-[11px] opacity-90 dark:bg-black/10">
                    {item.rootTask.metadata.goal_progress_summary}
                  </div>
                )}
              </article>
            ))}
          </div>
        </section>
      )}

      <TaskBoard workspaceId={workspaceId} />
    </div>
  );
}
