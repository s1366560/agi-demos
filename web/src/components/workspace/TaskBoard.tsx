import React, { useMemo, useState } from 'react';

import { ExclamationCircleOutlined, UserOutlined } from '@ant-design/icons';
import { Avatar, Button, Input, List, Select, Space, Tag, Tooltip, Typography } from 'antd';
import { useShallow } from 'zustand/react/shallow';

import { useWorkspaceStore } from '@/stores/workspace';

import { workspaceTaskService } from '@/services/workspaceService';

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

const STATUS_OPTIONS: { label: string; value: WorkspaceTaskStatus }[] = [
  { label: 'To Do', value: 'todo' },
  { label: 'In Progress', value: 'in_progress' },
  { label: 'Blocked', value: 'blocked' },
  { label: 'Done', value: 'done' },
];

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
  const { tasks, agents } = useWorkspaceStore(
    useShallow((state) => ({
      tasks: state.tasks,
      agents: state.agents,
    }))
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
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleStatusChange = async (taskId: string, newStatus: WorkspaceTaskStatus) => {
    try {
      await workspaceTaskService.update(workspaceId, taskId, { status: newStatus });
    } catch (err) {
      console.error('Failed to update status', err);
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
    }
  };

  const agentOptions = useMemo(() => {
    const opts = agents.map((agent) => ({
      label: agent.display_name || agent.agent_id,
      value: agent.id || agent.agent_id,
    }));
    return [{ label: 'Unassigned', value: '' }, ...opts];
  }, [agents]);

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <Typography.Title level={4} className="mb-4 mt-0">
        Task Board
      </Typography.Title>

      <Space.Compact className="mb-4 flex w-full">
        <Input
          placeholder="Task title..."
          value={title}
          onChange={(e) => { setTitle(e.target.value); }}
          onPressEnter={() => {
            void handleAddTask();
          }}
          style={{ flex: 1 }}
        />
        <Select
          options={PRIORITY_OPTIONS}
          value={priority}
          onChange={setPriority}
          placeholder="Priority"
          style={{ width: 100 }}
        />
        <Select
          options={EFFORT_OPTIONS}
          value={effort}
          onChange={setEffort}
          placeholder="Effort"
          style={{ width: 80 }}
          allowClear
        />
        <Button
          type="primary"
          onClick={() => {
            void handleAddTask();
          }}
          loading={isSubmitting}
          disabled={!title.trim()}
        >
          Add
        </Button>
      </Space.Compact>

      <List
        dataSource={sortedTasks}
        renderItem={(task: WorkspaceTask) => {
          const isDone = task.status === 'done';
          const isBlocked = task.status === 'blocked';
          const pColor = PRIORITY_COLORS[task.priority || ''] || 'default';

          return (
            <List.Item className="border-b last:border-b-0 border-slate-100 hover:bg-slate-50 transition-colors">
              <div
                className={`flex w-full items-center justify-between gap-4 ${isDone ? 'opacity-50 grayscale' : ''}`}
              >
                <div className="flex flex-1 items-center gap-2 overflow-hidden">
                  <Tag color={pColor} className="m-0 min-w-[32px] text-center">
                    {task.priority || '-'}
                  </Tag>

                  {isBlocked && (
                    <Tooltip title={task.blocker_reason || 'Task is blocked'}>
                      <ExclamationCircleOutlined className="text-red-500" />
                    </Tooltip>
                  )}

                  <Typography.Text className="truncate flex-1" delete={isDone}>
                    {task.title}
                  </Typography.Text>

                  {task.estimated_effort && (
                    <Tag className="m-0 rounded-full border-slate-200 text-xs">
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
                    suffixIcon={
                      task.assignee_agent_id ? (
                        <Avatar
                          size="small"
                          icon={<UserOutlined />}
                          className="bg-blue-100 text-blue-500 scale-50"
                        />
                      ) : null
                    }
                  />

                  <Select
                    size="small"
                    value={task.status}
                    options={STATUS_OPTIONS}
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
