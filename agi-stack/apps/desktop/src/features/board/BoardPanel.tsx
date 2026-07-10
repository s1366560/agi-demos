import { type CSSProperties, type FormEvent, useMemo, useState } from 'react';
import { Badge, Button, Flex, Heading, Progress, ScrollArea, Select, Text } from '@radix-ui/themes';
import {
  ArrowUpIcon,
  GridIcon,
  MixerHorizontalIcon,
  MinusIcon,
  PlusIcon,
  RowsIcon,
  ViewGridIcon,
  ViewHorizontalIcon,
} from '@radix-ui/react-icons';

import type { BoardMode, WorkspaceTask } from '../../types';

type BoardPanelProps = {
  tasks: WorkspaceTask[];
  boardMode: BoardMode;
  selectedTaskId: string;
  activeRunLabel?: string;
  activeRunTimeLabel?: string;
  commandDisabledReason?: string | null;
  commandSending?: boolean;
  runtimeTargetLabel?: string;
  runtimeTargetOptions?: string[];
  onBoardModeChange: (mode: BoardMode) => void;
  onSelectTask: (taskId: string, viewLabel?: string) => void;
  onOpenCommands: () => void;
  onRuntimeTargetChange?: (value: string) => void;
  onSubmitCommand: (command: string) => Promise<void> | void;
};

const lanes = ['planning', 'running', 'review', 'blocked', 'done'] as const;
const taskFilters = ['all', ...lanes] as const;
const runTimeTicks = ['00:00', '00:05', '00:10', '00:15', 'Now', '00:25', '00:30'];
const prototypeAgentOrder = ['Planner', 'Researcher', 'Executor', 'Verifier'];
type TaskFilter = (typeof taskFilters)[number];
type AgentLayout = 'lanes' | 'folders' | 'grid';
type BoardView = 'Timeline' | 'Swimlane' | 'Compact';
type LaneTone = (typeof lanes)[number];
type BoardLaneRow = {
  id: string;
  label: string;
  state: string;
  tone: LaneTone;
  tasks: WorkspaceTask[];
};

function boardRuntimeOptionLabel(option: string): string {
  return option === 'Staging Runtime' ? 'Remote staging' : option;
}

function boardTimeTickLabel(label: string): string {
  const trimmed = label.trim();
  return !trimmed || trimmed.toLowerCase() === 'never' ? '00:00' : trimmed;
}

export function BoardPanel({
  tasks,
  boardMode,
  selectedTaskId,
  activeRunLabel = 'Current run',
  activeRunTimeLabel = 'Now',
  commandDisabledReason,
  commandSending = false,
  runtimeTargetLabel = 'Local Rust Core',
  runtimeTargetOptions = ['Local Rust Core', 'Staging Runtime'],
  onBoardModeChange,
  onSelectTask,
  onOpenCommands,
  onRuntimeTargetChange,
  onSubmitCommand,
}: BoardPanelProps) {
  const [memoryScope, setMemoryScope] = useState('workspace');
  const [agentLayout, setAgentLayout] = useState<AgentLayout>('lanes');
  const [taskFilter, setTaskFilter] = useState<TaskFilter>('all');
  const [zoom, setZoom] = useState(100);
  const [boardView, setBoardView] = useState<BoardView>('Timeline');
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [showNowMarker, setShowNowMarker] = useState(true);
  const [showLaneCounts, setShowLaneCounts] = useState(true);
  const [showTaskProgress, setShowTaskProgress] = useState(true);
  const [command, setCommand] = useState('');
  const [model, setModel] = useState('OpenAI gpt-4o-mini');
  const usesTimelineTrack = boardView !== 'Compact';
  const useAgentLaneRows = usesTimelineTrack && agentLayout === 'lanes';
  const commandDisabled = Boolean(commandDisabledReason) || commandSending;
  const canSubmitCommand = !commandDisabled && Boolean(command.trim());
  const canZoomOut = zoom > 70;
  const canZoomIn = zoom < 140;
  const visibleTasks = useMemo(
    () => tasks.filter((task) => taskFilter === 'all' || taskLane(task) === taskFilter),
    [taskFilter, tasks],
  );
  const boardRows = useMemo(
    () => (useAgentLaneRows ? buildAgentLaneRows(visibleTasks) : buildStatusLaneRows(visibleTasks)),
    [useAgentLaneRows, visibleTasks],
  );
  const zoomValue = zoom / 100;
  const laneGridStyle = { '--board-zoom': String(zoomValue) } as CSSProperties;
  const boardTrackView = useAgentLaneRows ? 'swimlane' : boardView.toLowerCase();
  const modelOptions = ['OpenAI gpt-4o-mini', 'Local qwen-coder'];
  const runtimeOptions = Array.from(new Set([runtimeTargetLabel, ...runtimeTargetOptions]));
  const isolatedRunScopeLabel = `${activeRunLabel} (isolated)`;
  const currentTimeTickLabel = boardTimeTickLabel(activeRunTimeLabel);

  const submitCommand = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmed = command.trim();
    if (!trimmed || commandDisabled) return;
    setCommand('');
    await onSubmitCommand(trimmed);
  };

  return (
    <section className="pane-shell board-shell" aria-label="Run graph">
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
      <div className="board-toolbar" aria-label="Task board controls">
        <label className="board-control">
          <span>Memory scope</span>
          <select
            aria-label="Board memory scope"
            value={memoryScope}
            onChange={(event) => setMemoryScope(event.target.value)}
          >
            <option value="workspace">{isolatedRunScopeLabel}</option>
            <option value="project">Project memory</option>
            <option value="tenant">Tenant memory</option>
          </select>
        </label>
        <label className="board-control">
          <span>Agent layout</span>
          <div className="board-segmented" role="group" aria-label="Agent layout">
            <button
              type="button"
              className={agentLayout === 'lanes' ? 'active' : ''}
              aria-pressed={agentLayout === 'lanes'}
              aria-label="Use lane layout"
              onClick={() => setAgentLayout('lanes')}
            >
              <RowsIcon />
            </button>
            <button
              type="button"
              className={agentLayout === 'folders' ? 'active' : ''}
              aria-pressed={agentLayout === 'folders'}
              aria-label="Use folder layout"
              onClick={() => setAgentLayout('folders')}
            >
              <ViewHorizontalIcon />
            </button>
            <button
              type="button"
              className={agentLayout === 'grid' ? 'active' : ''}
              aria-pressed={agentLayout === 'grid'}
              aria-label="Use grid layout"
              onClick={() => setAgentLayout('grid')}
            >
              <GridIcon />
            </button>
          </div>
        </label>
        <label className="board-control">
          <span>Zoom</span>
          <div className="board-zoom-control">
            <button
              type="button"
              aria-label="Zoom task board out"
              disabled={!canZoomOut}
              onClick={() => setZoom((current) => Math.max(70, current - 10))}
            >
              <MinusIcon />
            </button>
            <strong>{zoom}%</strong>
            <button
              type="button"
              aria-label="Zoom task board in"
              disabled={!canZoomIn}
              onClick={() => setZoom((current) => Math.min(140, current + 10))}
            >
              <PlusIcon />
            </button>
          </div>
        </label>
        <label className="board-control">
          <span>View</span>
          <select
            aria-label="Task board view"
            value={boardView}
            onChange={(event) => setBoardView(event.target.value as BoardView)}
          >
            <option>Timeline</option>
            <option>Swimlane</option>
            <option>Compact</option>
          </select>
        </label>
        <label className="board-control">
          <span>Filter</span>
          <select
            aria-label="Task status filter"
            value={taskFilter}
            onChange={(event) => setTaskFilter(event.target.value as TaskFilter)}
          >
            {taskFilters.map((filter) => (
              <option key={filter} value={filter}>
                {filter}
              </option>
            ))}
          </select>
        </label>
        <button
          className={`board-settings-button ${settingsOpen ? 'active' : ''}`}
          type="button"
          aria-label="Timeline settings"
          aria-controls={settingsOpen ? 'task-board-settings-panel' : undefined}
          aria-expanded={settingsOpen}
          onClick={() => setSettingsOpen((open) => !open)}
        >
          <MixerHorizontalIcon />
        </button>
      </div>
      {settingsOpen ? (
        <div
          className="board-settings-panel"
          id="task-board-settings-panel"
          aria-label="Timeline settings"
        >
          <strong>Timeline settings</strong>
          <button
            type="button"
            className={showNowMarker ? 'active' : ''}
            aria-pressed={showNowMarker}
            onClick={() => setShowNowMarker((visible) => !visible)}
          >
            Now marker
          </button>
          <button
            type="button"
            className={showLaneCounts ? 'active' : ''}
            aria-pressed={showLaneCounts}
            onClick={() => setShowLaneCounts((visible) => !visible)}
          >
            Lane counts
          </button>
          <button
            type="button"
            className={showTaskProgress ? 'active' : ''}
            aria-pressed={showTaskProgress}
            onClick={() => setShowTaskProgress((visible) => !visible)}
          >
            Progress bars
          </button>
        </div>
      ) : null}
      <div className="board-status-line" aria-label="Task board state">
        <span>{visibleTasks.length} visible</span>
        <span>{boardView}</span>
        <span>{agentLayout}</span>
        <span>{memoryScope === 'workspace' ? isolatedRunScopeLabel : memoryScope}</span>
        <span>{showNowMarker ? 'now marker' : 'now hidden'}</span>
        <span>{showTaskProgress ? 'progress shown' : 'progress hidden'}</span>
      </div>
      {boardMode === 'flow' ? (
        <div
          className={`board-time-scale board-time-scale-${boardTrackView}`}
          aria-label="Run graph time scale"
          style={laneGridStyle}
        >
          {showNowMarker ? <div className="board-now-line" aria-hidden /> : null}
          {useAgentLaneRows || boardView === 'Swimlane' ? (
            <span className="board-time-scale-label">{useAgentLaneRows ? 'Agent' : 'Lane'}</span>
          ) : null}
          {runTimeTicks.map((tick) =>
            tick === 'Now' ? (
              <strong key={tick}>{currentTimeTickLabel}</strong>
            ) : (
              <span key={tick}>{tick}</span>
            ),
          )}
        </div>
      ) : null}
      {boardMode === 'flow' ? (
        <ScrollArea className="board-scroll">
          <div
            className={`lane-grid board-view-${boardTrackView} layout-${agentLayout} ${
              useAgentLaneRows ? 'agent-lane-grid' : ''
            }`}
            style={laneGridStyle}
          >
            {showNowMarker ? <div className="board-lane-now-line" aria-hidden /> : null}
            {boardRows.map((row) => {
              return (
                <section className="lane" key={row.id}>
                  <Flex align="center" justify="between" className="lane-head">
                    <span className="lane-head-copy">
                      <Text size="2" weight="bold">
                        {row.label}
                      </Text>
                      <span className="lane-state">
                        <i className={`lane-status-dot lane-status-${row.tone}`} aria-hidden />
                        {row.state}
                      </span>
                    </span>
                    {showLaneCounts ? <Badge variant="soft">{row.tasks.length}</Badge> : null}
                  </Flex>
                  <div className={`lane-list ${usesTimelineTrack ? 'lane-timeline-track' : ''}`}>
                    {row.tasks.map((task, taskIndex) => (
                      usesTimelineTrack ? (
                        <TimelineTaskButton
                          key={task.id}
                          task={task}
                          taskIndex={taskIndex}
                          selected={task.id === selectedTaskId}
                          viewLabel={boardView}
                          onSelectTask={onSelectTask}
                        />
                      ) : (
                        <TaskButton
                          key={task.id}
                          task={task}
                          selected={task.id === selectedTaskId}
                          showProgress={showTaskProgress}
                          viewLabel={boardView}
                          onSelectTask={onSelectTask}
                        />
                      )
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
              <Select.Root
                value={taskFilter}
                onValueChange={(value) => setTaskFilter(value as TaskFilter)}
              >
                <Select.Trigger aria-label="Task filter" />
                <Select.Content>
                  {taskFilters.map((filter) => (
                    <Select.Item key={filter} value={filter}>
                      {filter}
                    </Select.Item>
                  ))}
                </Select.Content>
              </Select.Root>
            </Flex>
            {visibleTasks.map((task) => (
              <button
                className={`task-row ${task.id === selectedTaskId ? 'selected' : ''}`}
                type="button"
                key={task.id}
                onClick={() => onSelectTask(task.id, 'List')}
              >
                <strong>{taskTitle(task)}</strong>
                <span>{task.status ?? 'open'}</span>
                <span>{task.owner ?? task.assignee_user_id ?? '-'}</span>
                <Badge color={statusColor(task.status)} variant="soft">
                  {taskLane(task)}
                </Badge>
              </button>
            ))}
            {!visibleTasks.length ? (
              <div className="task-empty-state">No tasks match the current board filter.</div>
            ) : null}
          </div>
        </ScrollArea>
      )}
      <form className="board-command-bar" aria-label="Run command bar" onSubmit={submitCommand}>
        <button
          className="board-command-slash"
          type="button"
          aria-label="Slash commands"
          title="Slash commands"
          onClick={onOpenCommands}
        >
          /
        </button>
        <input
          className="board-command-input"
          value={command}
          disabled={commandDisabled}
          aria-label="Run command"
          placeholder={commandDisabledReason ?? 'Steer this run or start a new task...'}
          onChange={(event) => setCommand(event.currentTarget.value)}
        />
        <div className="board-command-selects">
          <select
            aria-label="Model"
            value={model}
            disabled={commandSending}
            onChange={(event) => setModel(event.currentTarget.value)}
          >
            {modelOptions.map((option) => (
              <option key={option}>{option}</option>
            ))}
          </select>
          <select
            aria-label="Runtime target"
            value={runtimeTargetLabel}
            disabled={commandSending}
            onChange={(event) => onRuntimeTargetChange?.(event.currentTarget.value)}
          >
            {runtimeOptions.map((option) => (
              <option key={option} value={option}>
                {boardRuntimeOptionLabel(option)}
              </option>
            ))}
          </select>
        </div>
        <button
          className="board-command-send"
          type="submit"
          aria-label="Send command"
          disabled={!canSubmitCommand}
        >
          <ArrowUpIcon />
        </button>
      </form>
    </section>
  );
}

function TimelineTaskButton({
  task,
  taskIndex,
  selected,
  viewLabel,
  onSelectTask,
}: {
  task: WorkspaceTask;
  taskIndex: number;
  selected: boolean;
  viewLabel: string;
  onSelectTask: (taskId: string, viewLabel?: string) => void;
}) {
  const placement = taskTimelinePlacement(task);
  const lane = taskLane(task);
  const dashed = booleanMetadata(task, 'timeline_dashed');
  return (
    <button
      className={`task-timeline-pill ${selected ? 'selected' : ''} ${
        dashed ? 'task-timeline-dashed' : ''
      } task-timeline-${lane}`}
      type="button"
      style={{
        left: `${placement.left}%`,
        width: `${placement.width}%`,
        '--task-row': String(taskIndex % 4),
      } as CSSProperties}
      aria-label={`${taskTitle(task)} timeline task, ${task.status ?? lane}`}
      onClick={() => onSelectTask(task.id, viewLabel)}
    >
      <strong>{taskTitle(task)}</strong>
      <span>{task.status ?? lane}</span>
    </button>
  );
}

function TaskButton({
  task,
  selected,
  showProgress,
  viewLabel,
  onSelectTask,
}: {
  task: WorkspaceTask;
  selected: boolean;
  showProgress: boolean;
  viewLabel: string;
  onSelectTask: (taskId: string, viewLabel?: string) => void;
}) {
  return (
    <button
      className={`task-card ${selected ? 'selected' : ''}`}
      type="button"
      onClick={() => onSelectTask(task.id, viewLabel)}
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
      {showProgress ? <Progress value={taskProgress(task)} /> : null}
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

function taskTimelinePlacement(task: WorkspaceTask): { left: number; width: number } {
  const progress = taskProgress(task);
  const lane = taskLane(task);
  const defaultWidth = lane === 'done' ? 14 : lane === 'review' ? 18 : lane === 'running' ? 20 : 16;
  const width = clampTimelinePercent(numberMetadata(task, 'timeline_width') ?? defaultWidth, 10, 30);
  const metadataLeft = numberMetadata(task, 'timeline_left');
  if (typeof metadataLeft === 'number') {
    return { left: clampTimelinePercent(metadataLeft, 0, 100 - width), width };
  }
  const anchor =
    lane === 'planning'
      ? 14
      : lane === 'running'
        ? 34
        : lane === 'review'
          ? 58
          : lane === 'blocked'
            ? 52
            : 78;
  const progressOffset = Math.min(18, Math.max(0, progress - 18) * 0.18);
  return { left: clampTimelinePercent(anchor + progressOffset, 0, 100 - width), width };
}

function numberMetadata(task: WorkspaceTask, key: string): number | null {
  const value = task.metadata?.[key];
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function booleanMetadata(task: WorkspaceTask, key: string): boolean {
  return task.metadata?.[key] === true;
}

function clampTimelinePercent(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

function buildStatusLaneRows(tasks: WorkspaceTask[]): BoardLaneRow[] {
  return lanes.map((lane) => {
    const laneTasks = tasks.filter((task) => taskLane(task) === lane);
    return {
      id: `status:${lane}`,
      label: lane,
      state: laneStatusLabel(lane, laneTasks.length),
      tone: lane,
      tasks: laneTasks,
    };
  });
}

function buildAgentLaneRows(tasks: WorkspaceTask[]): BoardLaneRow[] {
  const grouped = new Map<string, WorkspaceTask[]>();
  tasks.forEach((task) => {
    const owner = taskOwner(task);
    grouped.set(owner, [...(grouped.get(owner) ?? []), task]);
  });
  const owners = [
    ...prototypeAgentOrder.filter((owner) => grouped.has(owner)),
    ...Array.from(grouped.keys())
      .filter((owner) => !prototypeAgentOrder.includes(owner))
      .sort((left, right) => left.localeCompare(right)),
  ];
  return owners.map((owner) => {
    const laneTasks = grouped.get(owner) ?? [];
    const state = agentLaneState(owner, laneTasks);
    return {
      id: `agent:${owner}`,
      label: owner,
      state,
      tone: agentLaneTone(state),
      tasks: laneTasks,
    };
  });
}

function taskOwner(task: WorkspaceTask): string {
  return stringMetadata(task, 'agent_lane') ?? task.owner ?? task.assignee_user_id ?? 'Agent';
}

function agentLaneState(owner: string, tasks: WorkspaceTask[]): string {
  const metadataState = tasks.map((task) => stringMetadata(task, 'agent_state')).find(Boolean);
  if (metadataState) return metadataState;
  if (!tasks.length) return 'Idle';
  if (tasks.some((task) => taskLane(task) === 'blocked')) return 'Blocked';
  if (tasks.some((task) => taskLane(task) === 'running')) {
    return owner === 'Executor' ? 'Working' : 'Active';
  }
  if (tasks.some((task) => taskLane(task) === 'review')) return 'Reviewing';
  if (tasks.some((task) => taskLane(task) === 'planning')) return 'Active';
  return 'Idle';
}

function agentLaneTone(state: string): LaneTone {
  const normalized = state.toLowerCase();
  if (normalized.includes('blocked') || normalized.includes('failed')) return 'blocked';
  if (normalized.includes('working') || normalized.includes('review')) return 'review';
  if (normalized.includes('active')) return 'running';
  if (normalized.includes('complete')) return 'done';
  return 'planning';
}

function taskLane(task: WorkspaceTask): (typeof lanes)[number] {
  const status = (task.status ?? '').toLowerCase();
  if (['done', 'complete', 'completed', 'closed'].includes(status)) return 'done';
  if (['blocked', 'failed', 'error'].includes(status)) return 'blocked';
  if (['review', 'needs_review', 'verifying'].includes(status)) return 'review';
  if (['running', 'in_progress', 'active', 'executing'].includes(status)) return 'running';
  return 'planning';
}

function laneStatusLabel(lane: (typeof lanes)[number], taskCount?: number): string {
  if (typeof taskCount === 'number' && taskCount > 0) {
    return `${taskCount} ${taskCount === 1 ? 'item' : 'items'}`;
  }
  if (lane === 'running') return 'Idle';
  if (lane === 'blocked') return 'Clear';
  if (lane === 'done') return 'No completions';
  return 'Waiting';
}

function stringMetadata(task: WorkspaceTask, key: string): string | null {
  const value = task.metadata?.[key];
  return typeof value === 'string' && value.trim() ? value : null;
}

function statusColor(status: string | undefined): 'gray' | 'blue' | 'amber' | 'green' | 'red' {
  const lane = taskLane({ id: '', status });
  if (lane === 'done') return 'green';
  if (lane === 'blocked') return 'red';
  if (lane === 'review') return 'amber';
  if (lane === 'running') return 'blue';
  return 'gray';
}
