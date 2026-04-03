import React, { useMemo, useState } from 'react';

import { useTranslation } from 'react-i18next';

import { Button, Input, Select, Switch, Tooltip } from 'antd';
import {
  AlertCircle,
  Ban,
  CheckCircle,
  ListTodo,
  PlayCircle,
  Plus,
} from 'lucide-react';

import { useWorkspaceAgents, useWorkspaceTasks } from '@/stores/workspace';

import { workspaceTaskService } from '@/services/workspaceService';

import { useLazyMessage } from '@/components/ui/lazyAntd';

import type { WorkspaceTaskStatus } from '@/types/workspace';

interface TaskBoardProps {
  workspaceId: string;
}

const PRIORITY_TONES: Record<string, string> = {
  P1: 'border-error-border bg-error-bg text-status-text-error dark:border-error-border-dark dark:bg-error-bg-dark dark:text-status-text-error-dark',
  P2: 'border-caution-border bg-caution-bg text-status-text-caution dark:border-caution-border-dark dark:bg-caution-bg-dark dark:text-status-text-caution-dark',
  P3: 'border-warning-border bg-warning-bg text-status-text-warning dark:border-warning-border-dark dark:bg-warning-bg-dark dark:text-status-text-warning-dark',
  P4: 'border-border-light bg-surface-light text-text-secondary dark:border-border-dark dark:bg-surface-dark dark:text-text-secondary',
};

const PRIORITY_RANK: Record<string, number> = {
  P1: 4,
  P2: 3,
  P3: 2,
  P4: 1,
};

const EFFORT_OPTIONS = [
  { label: 'S', value: 'S' },
  { label: 'M', value: 'M' },
  { label: 'L', value: 'L' },
  { label: 'XL', value: 'XL' },
];

const PRIORITY_OPTIONS = [
  { label: 'None', value: '' },
  { label: 'P1', value: 'P1' },
  { label: 'P2', value: 'P2' },
  { label: 'P3', value: 'P3' },
  { label: 'P4', value: 'P4' },
];

const COLUMN_CONFIG: {
  status: WorkspaceTaskStatus;
  icon: React.ReactNode;
  labelKey: string;
  fallback: string;
}[] = [
  {
    status: 'todo',
    icon: <ListTodo size={14} className="text-text-muted dark:text-text-muted" />,
    labelKey: 'workspaceDetail.taskBoard.statusTodo',
    fallback: 'To Do',
  },
  {
    status: 'in_progress',
    icon: <PlayCircle size={14} className="text-status-text-info dark:text-status-text-info-dark" />,
    labelKey: 'workspaceDetail.taskBoard.statusInProgress',
    fallback: 'In Progress',
  },
  {
    status: 'done',
    icon: (
      <CheckCircle
        size={14}
        className="text-status-text-success dark:text-status-text-success-dark"
      />
    ),
    labelKey: 'workspaceDetail.taskBoard.statusDone',
    fallback: 'Done',
  },
  {
    status: 'blocked',
    icon: <Ban size={14} className="text-status-text-error dark:text-status-text-error-dark" />,
    labelKey: 'workspaceDetail.taskBoard.statusBlocked',
    fallback: 'Blocked',
  },
];

export const TaskBoard: React.FC<TaskBoardProps> = ({ workspaceId }) => {
  const { t } = useTranslation();
  const message = useLazyMessage();
  const tasks = useWorkspaceTasks();
  const agents = useWorkspaceAgents();

  const [showArchived, setShowArchived] = useState(false);
  const [showAddForm, setShowAddForm] = useState(false);
  const [title, setTitle] = useState('');
  const [priority, setPriority] = useState<string>('');
  const [effort, setEffort] = useState<string>('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  const workspaceTasks = useMemo(() => {
    return tasks
      .filter((task) => task.workspace_id === workspaceId)
      .filter((task) => showArchived || !task.archived_at);
  }, [tasks, workspaceId, showArchived]);

  const columns = useMemo(() => {
    const grouped: Record<WorkspaceTaskStatus, typeof workspaceTasks> = {
      todo: [],
      in_progress: [],
      done: [],
      blocked: [],
    };

    workspaceTasks.forEach((task) => {
      const col = grouped[task.status];
      if (col) {
        col.push(task);
      }
    });

    for (const status of Object.keys(grouped) as WorkspaceTaskStatus[]) {
      grouped[status].sort((a, b) => {
        const rankA = PRIORITY_RANK[a.priority || ''] || 0;
        const rankB = PRIORITY_RANK[b.priority || ''] || 0;
        if (rankA !== rankB) return rankB - rankA;
        return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
      });
    }

    return grouped;
  }, [workspaceTasks]);

  const handleAddTask = async () => {
    const trimmedTitle = title.trim();
    if (!trimmedTitle) return;

    setIsSubmitting(true);
    try {
      const taskResponse = await workspaceTaskService.create(workspaceId, { title: trimmedTitle });
      if (priority || effort) {
        await workspaceTaskService.update(workspaceId, taskResponse.id, {
          ...(priority ? { priority } : {}),
          ...(effort ? { estimated_effort: effort } : {}),
        });
      }
      setTitle('');
      setPriority('');
      setEffort('');
      setShowAddForm(false);
    } catch {
      message?.error(t('workspaceDetail.taskBoard.createFailed'));
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleStatusChange = async (taskId: string, newStatus: WorkspaceTaskStatus) => {
    try {
      await workspaceTaskService.update(workspaceId, taskId, { status: newStatus });
    } catch {
      message?.error(t('workspaceDetail.taskBoard.updateStatusFailed'));
    }
  };

  const agentOptions = useMemo(() => {
    const options = agents.map((agent) => ({
      label: agent.display_name || agent.agent_id,
      value: agent.id || agent.agent_id,
    }));
    return [{ label: t('workspaceDetail.taskBoard.unassigned'), value: '' }, ...options];
  }, [agents, t]);

  const handleAgentAssign = async (taskId: string, agentId: string) => {
    try {
      if (agentId) {
        await workspaceTaskService.assignToAgent(workspaceId, taskId, agentId);
      } else {
        await workspaceTaskService.unassignAgent(workspaceId, taskId);
      }
    } catch {
      message?.error(t('workspaceDetail.taskBoard.assignFailed'));
    }
  };

  const statusOptions = useMemo(
    () =>
      COLUMN_CONFIG.map((col) => ({
        label: (
          <span className="flex items-center gap-1.5">
            {col.icon}
            {t(col.labelKey, col.fallback)}
          </span>
        ),
        value: col.status,
      })),
    [t]
  );

  return (
    <section>
      <div className="mb-4 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-text-primary dark:text-text-inverse">
          {t('workspaceDetail.taskBoard.title')}
        </h3>
        <div className="flex items-center gap-3">
          <label className="flex cursor-pointer items-center gap-1.5 text-xs text-text-secondary dark:text-text-muted">
            {t('workspaceDetail.taskBoard.showArchived', 'Show archived')}
            <Switch
              size="small"
              checked={showArchived}
              onChange={setShowArchived}
            />
          </label>
          <Button
            type="text"
            size="small"
            icon={<Plus size={14} />}
            onClick={() => {
              setShowAddForm(!showAddForm);
            }}
            className="text-xs text-text-secondary hover:text-text-primary dark:text-text-muted dark:hover:text-text-inverse"
          >
            {t('workspaceDetail.taskBoard.add')}
          </Button>
        </div>
      </div>

      {showAddForm && (
        <div className="mb-4 flex items-end gap-2 rounded-xl border border-border-light bg-surface-light p-3 dark:border-border-dark dark:bg-surface-dark">
          <Input
            aria-label={t('workspaceDetail.taskBoard.taskTitle', 'Task title')}
            placeholder={t('workspaceDetail.taskBoard.taskTitlePlaceholder')}
            value={title}
            onChange={(event) => {
              setTitle(event.target.value);
            }}
            onPressEnter={() => {
              void handleAddTask();
            }}
            className="flex-1"
            size="small"
          />
          <Select
            aria-label={t('workspaceDetail.taskBoard.priority', 'Priority')}
            options={PRIORITY_OPTIONS}
            value={priority}
            onChange={setPriority}
            placeholder={t('workspaceDetail.taskBoard.priority')}
            className="w-24"
            size="small"
          />
          <Select
            aria-label={t('workspaceDetail.taskBoard.effort', 'Effort')}
            options={EFFORT_OPTIONS}
            value={effort}
            onChange={setEffort}
            placeholder={t('workspaceDetail.taskBoard.effort')}
            className="w-20"
            size="small"
            allowClear
          />
          <Button
            type="primary"
            size="small"
            icon={<Plus size={14} />}
            onClick={() => {
              void handleAddTask();
            }}
            loading={isSubmitting}
            disabled={!title.trim()}
          >
            {t('workspaceDetail.taskBoard.add')}
          </Button>
        </div>
      )}

      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        {COLUMN_CONFIG.map((col) => {
          const colTasks = columns[col.status];
          return (
            <div
              key={col.status}
              className="flex min-h-[200px] flex-col rounded-xl border border-border-light bg-surface-muted/60 dark:border-border-dark dark:bg-surface-dark-alt/60"
            >
              <div className="flex items-center gap-2 border-b border-border-light px-3 py-2.5 dark:border-border-dark">
                {col.icon}
                <span className="text-xs font-semibold text-text-primary dark:text-text-inverse">
                  {t(col.labelKey, col.fallback)}
                </span>
                <span className="ml-auto text-xs tabular-nums text-text-muted dark:text-text-muted">
                  ({colTasks.length})
                </span>
              </div>

              <div className="flex-1 space-y-2 overflow-y-auto p-2">
                {colTasks.length === 0 ? (
                  <div className="flex h-full min-h-[80px] items-center justify-center">
                    <span className="text-xs text-text-muted/60 dark:text-text-muted/40">
                      --
                    </span>
                  </div>
                ) : (
                  colTasks.map((task) => {
                    const isDone = task.status === 'done';
                    const isBlocked = task.status === 'blocked';
                    const priorityTone =
                      PRIORITY_TONES[task.priority || ''] ??
                      'border-border-light bg-surface-light text-text-secondary dark:border-border-dark dark:bg-surface-dark dark:text-text-secondary';

                    return (
                      <article
                        key={task.id}
                        className={`rounded-lg border border-border-light bg-surface-light p-2.5 shadow-sm transition hover:border-border-separator dark:border-border-dark dark:bg-surface-dark ${
                          isDone ? 'opacity-60' : ''
                        }`}
                      >
                        <div className="mb-1.5 flex flex-wrap items-center gap-1.5">
                          {task.priority && (
                            <span
                              className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase ${priorityTone}`}
                            >
                              {task.priority}
                            </span>
                          )}
                          {task.estimated_effort && (
                            <span className="rounded-full border border-border-light bg-surface-muted px-2 py-0.5 text-[10px] font-medium text-text-secondary dark:border-border-dark dark:bg-background-dark dark:text-text-secondary">
                              {task.estimated_effort}
                            </span>
                          )}
                          {isBlocked && (
                            <Tooltip
                              title={
                                task.blocker_reason ||
                                t('workspaceDetail.taskBoard.taskIsBlocked', 'Task is blocked')
                              }
                            >
                              <span className="inline-flex items-center gap-0.5 rounded-full border border-error-border bg-error-bg px-1.5 py-0.5 text-[10px] font-medium text-status-text-error dark:border-error-border-dark dark:bg-error-bg-dark dark:text-status-text-error-dark">
                                <AlertCircle size={10} />
                              </span>
                            </Tooltip>
                          )}
                        </div>

                        <h4
                          className={`text-xs font-semibold leading-snug text-text-primary dark:text-text-inverse ${
                            isDone ? 'line-through decoration-border-separator' : ''
                          }`}
                        >
                          {task.title}
                        </h4>

                        {task.description && (
                          <p className="mt-1 line-clamp-2 text-[11px] leading-4 text-text-secondary dark:text-text-muted">
                            {task.description}
                          </p>
                        )}

                        {isBlocked && task.blocker_reason && (
                          <p className="mt-1 line-clamp-2 text-[11px] leading-4 text-status-text-error dark:text-status-text-error-dark">
                            {task.blocker_reason}
                          </p>
                        )}

                        <div className="mt-2 flex items-center gap-1.5">
                          <Select
                            aria-label={t('workspaceDetail.taskBoard.assignee', 'Assignee')}
                            size="small"
                            value={task.assignee_agent_id || ''}
                            options={agentOptions}
                            onChange={(value) => {
                              void handleAgentAssign(task.id, value);
                            }}
                            className="min-w-0 flex-1"
                            variant="borderless"
                          />
                          <Select
                            aria-label={t('workspaceDetail.taskBoard.status', 'Status')}
                            size="small"
                            value={task.status}
                            options={statusOptions}
                            onChange={(value) => {
                              void handleStatusChange(task.id, value as WorkspaceTaskStatus);
                            }}
                            className="min-w-0 flex-1"
                            variant="borderless"
                            {...(isBlocked ? { status: 'error' } : {})}
                          />
                        </div>
                      </article>
                    );
                  })
                )}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
};
