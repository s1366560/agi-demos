import { Badge, Button, Flex, Heading, Progress, ScrollArea, Select, Text } from '@radix-ui/themes';
import { RowsIcon, ViewGridIcon } from '@radix-ui/react-icons';

import type { BoardMode, WorkspaceTask } from '../../types';

type BoardPanelProps = {
  tasks: WorkspaceTask[];
  boardMode: BoardMode;
  selectedTaskId: string;
  onBoardModeChange: (mode: BoardMode) => void;
  onSelectTask: (taskId: string) => void;
};

const lanes = ['planning', 'running', 'review', 'blocked', 'done'] as const;

export function BoardPanel({
  tasks,
  boardMode,
  selectedTaskId,
  onBoardModeChange,
  onSelectTask,
}: BoardPanelProps) {
  return (
    <section className="pane-shell board-shell">
      <header className="pane-head">
        <div>
          <Heading as="h2" size="3">
            Board
          </Heading>
          <Text size="1" color="gray">
            Workspace work items grouped by status and priority.
          </Text>
        </div>
        <Flex align="center" gap="2">
          <Button
            size="2"
            variant={boardMode === 'flow' ? 'solid' : 'surface'}
            onClick={() => onBoardModeChange('flow')}
          >
            <ViewGridIcon /> Flow
          </Button>
          <Button
            size="2"
            variant={boardMode === 'list' ? 'solid' : 'surface'}
            onClick={() => onBoardModeChange('list')}
          >
            <RowsIcon /> List
          </Button>
        </Flex>
      </header>
      {boardMode === 'flow' ? (
        <ScrollArea className="board-scroll">
          <div className="lane-grid">
            {lanes.map((lane) => {
              const laneTasks = tasks.filter((task) => taskLane(task) === lane);
              return (
                <section className="lane" key={lane}>
                  <Flex align="center" justify="between" className="lane-head">
                    <Text size="2" weight="bold">
                      {lane}
                    </Text>
                    <Badge variant="soft">{laneTasks.length}</Badge>
                  </Flex>
                  <div className="lane-list">
                    {laneTasks.map((task) => (
                      <TaskButton
                        key={task.id}
                        task={task}
                        selected={task.id === selectedTaskId}
                        onSelectTask={onSelectTask}
                      />
                    ))}
                  </div>
                </section>
              );
            })}
          </div>
        </ScrollArea>
      ) : (
        <ScrollArea className="board-scroll">
          <div className="task-table">
            <Flex align="center" justify="between">
              <Text size="1" color="gray" weight="bold">
                TASK LIST
              </Text>
              <Select.Root defaultValue="all">
                <Select.Trigger aria-label="Task filter" />
                <Select.Content>
                  <Select.Item value="all">all</Select.Item>
                  <Select.Item value="running">running</Select.Item>
                  <Select.Item value="review">review</Select.Item>
                  <Select.Item value="blocked">blocked</Select.Item>
                </Select.Content>
              </Select.Root>
            </Flex>
            {tasks.map((task) => (
              <button
                className={`task-row ${task.id === selectedTaskId ? 'selected' : ''}`}
                type="button"
                key={task.id}
                onClick={() => onSelectTask(task.id)}
              >
                <strong>{taskTitle(task)}</strong>
                <span>{task.status ?? 'open'}</span>
                <span>{task.owner ?? task.assignee_user_id ?? '-'}</span>
                <Badge color={statusColor(task.status)} variant="soft">
                  {taskLane(task)}
                </Badge>
              </button>
            ))}
          </div>
        </ScrollArea>
      )}
    </section>
  );
}

function TaskButton({
  task,
  selected,
  onSelectTask,
}: {
  task: WorkspaceTask;
  selected: boolean;
  onSelectTask: (taskId: string) => void;
}) {
  return (
    <button
      className={`task-card ${selected ? 'selected' : ''}`}
      type="button"
      onClick={() => onSelectTask(task.id)}
    >
      <div className="task-card-head">
        <strong>{taskTitle(task)}</strong>
        <Badge color={statusColor(task.status)} variant="soft">
          {task.status ?? 'open'}
        </Badge>
      </div>
      <Text size="1" color="gray">
        {task.summary ?? task.description ?? task.owner ?? task.assignee_user_id ?? 'No summary'}
      </Text>
      <Progress value={taskProgress(task)} />
    </button>
  );
}

function taskTitle(task: WorkspaceTask): string {
  return task.title ?? task.id;
}

function taskProgress(task: WorkspaceTask): number {
  if (typeof task.progress === 'number') return Math.max(0, Math.min(100, task.progress));
  const lane = taskLane(task);
  if (lane === 'done') return 100;
  if (lane === 'review') return 80;
  if (lane === 'running') return 48;
  if (lane === 'blocked') return 62;
  return 18;
}

function taskLane(task: WorkspaceTask): (typeof lanes)[number] {
  const status = (task.status ?? '').toLowerCase();
  if (['done', 'complete', 'completed', 'closed'].includes(status)) return 'done';
  if (['blocked', 'failed', 'error'].includes(status)) return 'blocked';
  if (['review', 'needs_review', 'verifying'].includes(status)) return 'review';
  if (['running', 'in_progress', 'active', 'executing'].includes(status)) return 'running';
  return 'planning';
}

function statusColor(status: string | undefined): 'gray' | 'blue' | 'amber' | 'green' | 'red' {
  const lane = taskLane({ id: '', status });
  if (lane === 'done') return 'green';
  if (lane === 'blocked') return 'red';
  if (lane === 'review') return 'amber';
  if (lane === 'running') return 'blue';
  return 'gray';
}
