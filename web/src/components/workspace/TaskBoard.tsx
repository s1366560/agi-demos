import React, { useMemo, useState } from 'react';

import { useTranslation } from 'react-i18next';

import { Avatar, Button, Input, List, Select, Tag, Tooltip, Typography } from 'antd';
import { AlertCircle, User, ListTodo, PlayCircle, CheckCircle, Ban } from 'lucide-react';
import { useShallow } from 'zustand/react/shallow';

import { useWorkspaceStore } from '@/stores/workspace';

import { workspaceTaskService } from '@/services/workspaceService';

import { useLazyMessage } from '@/components/ui/lazyAntd';

import type { WorkspaceTask, WorkspaceTaskStatus } from '@/types/workspace';

interface TaskBoardProps {
  workspaceId: string;
}

const PRIORITY_COLORS: Record<string, string> = {
  P1: '#ff4d4f',
  P2: '#fa8c16',
  P3: '#faad14',
  P4: '#8c8c8c',
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

export const TaskBoard: React.FC<TaskBoardProps> = ({ workspaceId }) => {
  const { t } = useTranslation();
  const message = useLazyMessage();
  const { tasks, agents } = useWorkspaceStore(
    useShallow((state) => ({
      tasks: state.tasks,
      agents: state.agents,
    }))
  );

  const statusOptions = useMemo(
    () => [
      { label: <span className="flex items-center gap-1.5"><ListTodo size={14} className="text-slate-400" /> {t('workspaceDetail.taskBoard.statusTodo')}</span>, value: 'todo' },
      { label: <span className="flex items-center gap-1.5"><PlayCircle size={14} className="text-blue-500" /> {t('workspaceDetail.taskBoard.statusInProgress')}</span>, value: 'in_progress' },
      { label: <span className="flex items-center gap-1.5"><Ban size={14} className="text-red-500" /> {t('workspaceDetail.taskBoard.statusBlocked')}</span>, value: 'blocked' },
      { label: <span className="flex items-center gap-1.5"><CheckCircle size={14} className="text-green-500" /> {t('workspaceDetail.taskBoard.statusDone')}</span>, value: 'done' },
    ],
    [t]
  );

  const [title, setTitle] = useState('');
  const [priority, setPriority] = useState<string>('');
  const [effort, setEffort] = useState<string>('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  const sortedTasks = useMemo(() => {
    return [...tasks].sort((a, b) => {
      if (a.status === 'blocked' && b.status !== 'blocked') return -1;
      if (b.status === 'blocked' && a.status !== 'blocked') return 1;

      const rankA = PRIORITY_RANK[a.priority || ''] || 0;
      const rankB = PRIORITY_RANK[b.priority || ''] || 0;
      if (rankA !== rankB) return rankB - rankA;

      return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
    });
  }, [tasks]);

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
    } catch (err) {
      console.error('Failed to create task', err);
      message?.error(t('workspaceDetail.taskBoard.createFailed'));
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleStatusChange = async (taskId: string, newStatus: WorkspaceTaskStatus) => {
    try {
      await workspaceTaskService.update(workspaceId, taskId, { status: newStatus });
    } catch (err) {
      console.error('Failed to update status', err);
      message?.error(t('workspaceDetail.taskBoard.updateStatusFailed'));
    }
  };

  const handleAgentAssign = async (taskId: string, agentId: string) => {
    try {
      if (agentId) {
        await workspaceTaskService.assignToAgent(workspaceId, taskId, agentId);
      } else {
        await workspaceTaskService.unassignAgent(workspaceId, taskId);
      }
    } catch (err) {
      console.error('Failed to assign agent', err);
      message?.error(t('workspaceDetail.taskBoard.assignFailed'));
    }
  };

  const agentOptions = useMemo(() => {
    const opts = agents.map((agent) => ({
      label: agent.display_name || agent.agent_id,
      value: agent.id || agent.agent_id,
    }));
    return [{ label: t('workspaceDetail.taskBoard.unassigned'), value: '' }, ...opts];
  }, [agents, t]);

  return (
    <div className="rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-4 transition-colors duration-200">
      <Typography.Title level={4} className="mb-4 mt-0">
        {t('workspaceDetail.taskBoard.title')}
      </Typography.Title>

      <div className="mb-4 flex flex-col sm:flex-row gap-2 w-full">
        <Input
          placeholder={t('workspaceDetail.taskBoard.taskTitlePlaceholder')}
          value={title}
          onChange={(e) => { setTitle(e.target.value); }}
          onPressEnter={() => {
            void handleAddTask();
          }}
          className="flex-1"
        />
        <Select
          options={PRIORITY_OPTIONS}
          value={priority}
          onChange={setPriority}
          placeholder={t('workspaceDetail.taskBoard.priority')}
          className="w-full sm:w-[100px]"
        />
        <Select
          options={EFFORT_OPTIONS}
          value={effort}
          onChange={setEffort}
          placeholder={t('workspaceDetail.taskBoard.effort')}
          className="w-full sm:w-[80px]"
          allowClear
        />
        <Button
          type="primary"
          onClick={() => {
            void handleAddTask();
          }}
          loading={isSubmitting}
          disabled={!title.trim()}
          className="w-full sm:w-auto"
        >
          {t('workspaceDetail.taskBoard.add')}
        </Button>
      </div>

      <List
        dataSource={sortedTasks}
        renderItem={(task: WorkspaceTask) => {
          const isDone = task.status === 'done';
          const isBlocked = task.status === 'blocked';
          const pColor = PRIORITY_COLORS[task.priority || ''] || 'default';

          return (
            <List.Item className="border-b last:border-b-0 border-slate-100 dark:border-slate-700/50 hover:bg-slate-50 dark:hover:bg-slate-700 transition-colors">
              <div
                className={`flex w-full items-center justify-between gap-4 ${isDone ? 'opacity-50 grayscale' : ''}`}
              >
                <div className="flex flex-1 items-center gap-2 overflow-hidden">
                  <Tag color={pColor} className="m-0 min-w-8 text-center">
                    {task.priority || '-'}
                  </Tag>

                  {isBlocked && (
                    <Tooltip title={task.blocker_reason || t('workspaceDetail.taskBoard.taskIsBlocked')}>
                      <AlertCircle size={14} className="text-red-500" />
                    </Tooltip>
                  )}

                  <Typography.Text className="truncate flex-1" delete={isDone}>
                    {task.title}
                  </Typography.Text>

                  {task.estimated_effort && (
                    <Tag className="m-0 rounded-full border-slate-200 dark:border-slate-700 text-xs">
                      {task.estimated_effort}
                    </Tag>
                  )}
                </div>

                <div className="flex items-center gap-3">
                  <Select
                    size="small"
                    value={task.assignee_agent_id || ''}
                    options={agentOptions}
                    onChange={(val) => {
                      void handleAgentAssign(task.id, val);
                    }}
                    style={{ width: 140 }}
                    placeholder="Assignee"
                    suffix={
                      task.assignee_agent_id ? (
                        <Avatar
                          size="small"
                          icon={<User size={12} />}
                          className="bg-blue-100 text-blue-500 scale-50"
                        />
                      ) : null
                    }
                  />

                  <Select
                    size="small"
                    value={task.status}
                    options={statusOptions}
                    onChange={(val) => {
                      void handleStatusChange(task.id, val as WorkspaceTaskStatus);
                    }}
                    style={{ width: 110 }}
                    {...(isBlocked ? { status: 'error' } : {})}
                  />
                </div>
              </div>
            </List.Item>
          );
        }}
      />
    </div>
  );
};
