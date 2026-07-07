import '@radix-ui/themes/styles.css';
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Command } from 'cmdk';
import {
  Badge,
  Box,
  Button,
  Flex,
  Heading,
  IconButton,
  Progress,
  ScrollArea,
  Select,
  Separator,
  Tabs,
  Text,
  TextArea,
  TextField,
  Theme,
  Tooltip,
} from '@radix-ui/themes';
import {
  ActivityLogIcon,
  ArchiveIcon,
  BarChartIcon,
  ChatBubbleIcon,
  CheckCircledIcon,
  ChevronDownIcon,
  ClipboardIcon,
  CodeIcon,
  Cross2Icon,
  DashboardIcon,
  DesktopIcon,
  DotsHorizontalIcon,
  DragHandleDots2Icon,
  FileTextIcon,
  GearIcon,
  GridIcon,
  KeyboardIcon,
  LapTimerIcon,
  LightningBoltIcon,
  MagnifyingGlassIcon,
  MixerHorizontalIcon,
  PinTopIcon,
  ReloadIcon,
  RowsIcon,
  RocketIcon,
  ViewGridIcon,
} from '@radix-ui/react-icons';
import './styles.css';

type PaneKey = 'chat' | 'board' | 'status';
type PresetKey = 'balanced' | 'focus' | 'review' | 'compact';
type InspectorTab = 'overview' | 'evidence' | 'logs' | 'terminal';
type BoardMode = 'flow' | 'list';
type RuntimeMode = 'local' | 'cloud';
type TaskStatus = 'planning' | 'running' | 'review' | 'done' | 'blocked';

type Task = {
  id: string;
  title: string;
  owner: string;
  lane: 'Planning' | 'Running' | 'Review' | 'Done';
  status: TaskStatus;
  progress: number;
  files: number;
  summary: string;
};

type Message = {
  id: string;
  speaker: string;
  tone: 'agent' | 'runtime' | 'user';
  time: string;
  body: string;
};

const panes: PaneKey[] = ['chat', 'board', 'status'];
const lanes: Task['lane'][] = ['Planning', 'Running', 'Review', 'Done'];

const presetWidths: Record<PresetKey, Record<PaneKey, number>> = {
  balanced: { chat: 34, board: 43, status: 23 },
  focus: { chat: 58, board: 42, status: 0 },
  review: { chat: 25, board: 38, status: 37 },
  compact: { chat: 48, board: 52, status: 0 },
};

const initialTasks: Task[] = [
  {
    id: 'clarify',
    title: '需求澄清',
    owner: 'Metis',
    lane: 'Planning',
    status: 'done',
    progress: 100,
    files: 3,
    summary: '产品边界、成功标准、桌面端工作区模型已确认。',
  },
  {
    id: 'migrate',
    title: '数据迁移',
    owner: 'Executor',
    lane: 'Running',
    status: 'running',
    progress: 68,
    files: 8,
    summary: '本地 SQLite device store 正在同步客户知识库索引。',
  },
  {
    id: 'validate',
    title: '校验脚本',
    owner: 'Verifier',
    lane: 'Running',
    status: 'running',
    progress: 42,
    files: 5,
    summary: '回归脚本已启动，等待桌面 shell smoke evidence。',
  },
  {
    id: 'approve',
    title: '审批发布',
    owner: 'Human',
    lane: 'Review',
    status: 'review',
    progress: 88,
    files: 2,
    summary: '发布前需要确认迁移结果、校验日志和回滚计划。',
  },
  {
    id: 'docs',
    title: '文档生成',
    owner: 'Writer',
    lane: 'Done',
    status: 'done',
    progress: 100,
    files: 4,
    summary: '变更摘要、操作记录和交付说明已生成。',
  },
];

const initialMessages: Message[] = [
  {
    id: 'm1',
    speaker: 'Orchestrator',
    tone: 'agent',
    time: '10:24',
    body: '已将“客户知识库上线”拆成规划、迁移、校验、审批和文档五个阶段。当前阻塞在发布审批。',
  },
  {
    id: 'm2',
    speaker: 'Runtime',
    tone: 'runtime',
    time: '10:25',
    body: 'Local sandbox 已连接。SQLite memory store 可用，MCP 工具集已加载。',
  },
  {
    id: 'm3',
    speaker: 'Tiejun',
    tone: 'user',
    time: '10:27',
    body: '保持 Chat、Board、Status 三个工作模块可定义布局，随时收起和展开。',
  },
];

const statusColor: Record<TaskStatus, 'blue' | 'amber' | 'green' | 'red' | 'gray'> = {
  planning: 'blue',
  running: 'blue',
  review: 'amber',
  done: 'green',
  blocked: 'red',
};

function App() {
  const [runtimeMode, setRuntimeMode] = useState<RuntimeMode>('local');
  const [activeNav, setActiveNav] = useState('HM');
  const [preset, setPreset] = useState<PresetKey>('balanced');
  const [visible, setVisible] = useState<Record<PaneKey, boolean>>({
    chat: true,
    board: true,
    status: true,
  });
  const [widths, setWidths] = useState<Record<PaneKey, number>>(presetWidths.balanced);
  const [boardMode, setBoardMode] = useState<BoardMode>('flow');
  const [taskFilter, setTaskFilter] = useState<TaskStatus | 'all'>('all');
  const [tasks, setTasks] = useState<Task[]>(initialTasks);
  const [selectedTaskId, setSelectedTaskId] = useState('approve');
  const [inspectorTab, setInspectorTab] = useState<InspectorTab>('overview');
  const [messages, setMessages] = useState<Message[]>(initialMessages);
  const [commandText, setCommandText] = useState('');
  const [memoryContent, setMemoryContent] = useState('Local-first desktop workspace layout preference');
  const [memoryQuery, setMemoryQuery] = useState('desktop layout');
  const [memoryOutput, setMemoryOutput] = useState('Ready.');
  const [terminalLines, setTerminalLines] = useState([
    '$ agi task run customer-kb --local',
    '[ok] sqlite device store opened',
    '[run] migration batch 42/60',
    '[wait] human approval gate',
  ]);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const workspaceRef = useRef<HTMLDivElement | null>(null);

  const selectedTask = useMemo(
    () => tasks.find((task) => task.id === selectedTaskId) ?? tasks[0],
    [selectedTaskId, tasks],
  );
  const visibleTasks = useMemo(
    () => tasks.filter((task) => taskFilter === 'all' || task.status === taskFilter),
    [taskFilter, tasks],
  );
  const collapsedPanes = panes.filter((pane) => !visible[pane]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key.toLowerCase() === 'k' && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        setPaletteOpen((open) => !open);
      }
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, []);

  const appendTerminal = (line: string) => {
    setTerminalLines((current) => [...current, line]);
  };

  const applyPreset = (nextPreset: PresetKey) => {
    setPreset(nextPreset);
    setWidths(presetWidths[nextPreset]);
    setVisible({
      chat: presetWidths[nextPreset].chat > 0,
      board: presetWidths[nextPreset].board > 0,
      status: presetWidths[nextPreset].status > 0,
    });
    appendTerminal(`[layout] preset ${nextPreset} applied`);
  };

  const togglePane = (pane: PaneKey, force?: boolean) => {
    setVisible((current) => {
      const shouldShow = force ?? !current[pane];
      if (!shouldShow && Object.values(current).filter(Boolean).length === 1) return current;
      return { ...current, [pane]: shouldShow };
    });
    setWidths((current) => {
      if (force && current[pane] < 8) return { ...current, [pane]: 28 };
      return current;
    });
  };

  const startResize = (left: PaneKey, right: PaneKey, event: React.PointerEvent) => {
    if (!visible[left] || !visible[right]) return;
    const startX = event.clientX;
    const workspaceWidth = workspaceRef.current?.getBoundingClientRect().width ?? 1;
    const startLeft = widths[left];
    const startRight = widths[right];
    const onMove = (moveEvent: PointerEvent) => {
      const delta = ((moveEvent.clientX - startX) / workspaceWidth) * 100;
      const nextLeft = Math.max(18, Math.min(startLeft + startRight - 18, startLeft + delta));
      const nextRight = Math.max(18, startLeft + startRight - nextLeft);
      setWidths((current) => ({ ...current, [left]: nextLeft, [right]: nextRight }));
    };
    const onUp = () => {
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
      appendTerminal('[layout] pane split updated');
    };
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp, { once: true });
  };

  const approveTask = () => {
    setTasks((current) =>
      current.map((task) =>
        task.id === selectedTask.id
          ? { ...task, status: 'done', progress: 100, lane: 'Done' }
          : task,
      ),
    );
    appendTerminal('[ok] approval gate passed');
  };

  const requestChanges = () => {
    setTasks((current) =>
      current.map((task) =>
        task.id === selectedTask.id ? { ...task, status: 'blocked', progress: 88 } : task,
      ),
    );
    appendTerminal('[blocked] changes requested by reviewer');
  };

  const sendCommand = () => {
    const trimmed = commandText.trim();
    if (!trimmed) return;
    setMessages((current) => [
      ...current,
      { id: `u-${Date.now()}`, speaker: 'Tiejun', tone: 'user', time: 'now', body: trimmed },
      {
        id: `a-${Date.now()}`,
        speaker: 'Orchestrator',
        tone: 'agent',
        time: 'streaming',
        body: '已保存新的 Radix 桌面布局，并把模块状态同步到 workspace profile。',
      },
    ]);
    setCommandText('');
    appendTerminal('[layout] radix workspace profile updated');
  };

  const invokeMemory = async (kind: 'ingest' | 'search') => {
    const invoke = window.__TAURI__?.core?.invoke;
    try {
      if (kind === 'ingest') {
        if (invoke) {
          const value = await invoke('ingest', {
            projectId: 'p1',
            authorId: 'desktop-u1',
            content: memoryContent,
          });
          setMemoryOutput(`Ingested\n${JSON.stringify(JSON.parse(String(value)), null, 2)}`);
        } else {
          setMemoryOutput(
            `Mock ingest\n${JSON.stringify(
              { id: 'local-memory-1', content: memoryContent, project: 'p1' },
              null,
              2,
            )}`,
          );
        }
      } else if (invoke) {
        const value = await invoke('search', { projectId: 'p1', q: memoryQuery, limit: 10 });
        setMemoryOutput(`Search\n${JSON.stringify(JSON.parse(String(value)), null, 2)}`);
      } else {
        setMemoryOutput(
          `Mock search\n${JSON.stringify([{ id: 'local-memory-1', score: 0.84, q: memoryQuery }], null, 2)}`,
        );
      }
    } catch (error) {
      setMemoryOutput(`Error: ${String(error)}`);
    }
  };

  const navItems = [
    { id: 'HM', label: 'Home', icon: <DashboardIcon /> },
    { id: 'AI', label: 'Agents', icon: <ChatBubbleIcon /> },
    { id: 'FL', label: 'Flow', icon: <ViewGridIcon /> },
    { id: 'DB', label: 'Memory', icon: <ArchiveIcon /> },
    { id: 'TM', label: 'Terminal', icon: <CodeIcon /> },
    { id: 'PL', label: 'Plugins', icon: <GridIcon /> },
    { id: 'ST', label: 'Settings', icon: <GearIcon /> },
  ];

  return (
    <Theme appearance="dark" accentColor="cyan" grayColor="slate" radius="medium" scaling="95%">
      <div className="app-shell">
        <header className="titlebar">
          <div className="window-dots" aria-hidden="true">
            <span />
            <span />
            <span />
          </div>
          <div className="brand-lockup">
            <div className="brand-mark">As</div>
            <div className="brand-copy">
              <Text as="div" weight="bold" size="3">
                agi-stack
              </Text>
              <Text as="div" size="1" color="gray">
                Radix desktop client
              </Text>
            </div>
          </div>
          <Button variant="surface" color="gray" highContrast>
            Local Lab / 客户知识库
            <Badge color="cyan" variant="soft">
              v0.2
            </Badge>
            <ChevronDownIcon />
          </Button>
          <button className="command-trigger" type="button" onClick={() => setPaletteOpen(true)}>
            <MagnifyingGlassIcon />
            <span>Command, Agent, Memory, Terminal...</span>
            <kbd>Cmd K</kbd>
          </button>
          <Flex align="center" gap="2" ml="auto">
            <Button
              variant={runtimeMode === 'local' ? 'solid' : 'soft'}
              size="2"
              onClick={() => {
                setRuntimeMode('local');
                appendTerminal('[runtime] switched to local');
              }}
            >
              Local
            </Button>
            <Button
              variant={runtimeMode === 'cloud' ? 'solid' : 'soft'}
              size="2"
              onClick={() => {
                setRuntimeMode('cloud');
                appendTerminal('[runtime] switched to cloud');
              }}
            >
              Cloud
            </Button>
            <div className="token-meter">
              <Text size="1" color="gray">
                Token
              </Text>
              <span />
            </div>
            <Tooltip content="Runtime healthy">
              <IconButton variant="surface" color="gray" aria-label="Runtime healthy">
                <CheckCircledIcon />
              </IconButton>
            </Tooltip>
          </Flex>
        </header>

        <section className="desktop-body">
          <nav className="activity-rail" aria-label="primary desktop navigation">
            {navItems.map((item) => (
              <Tooltip key={item.id} content={item.label} side="right">
                <IconButton
                  aria-label={item.label}
                  variant={activeNav === item.id ? 'solid' : 'ghost'}
                  color={activeNav === item.id ? 'cyan' : 'gray'}
                  onClick={() => setActiveNav(item.id)}
                >
                  {item.icon}
                </IconButton>
              </Tooltip>
            ))}
          </nav>

          <aside className="workspace-dock">
            <section className="dock-head">
              <Text size="1" weight="bold" color="gray">
                WORKSPACE
              </Text>
              <div className="workspace-card">
                <Flex align="center" justify="between">
                <Heading as="h2" size="3">本地实验室</Heading>
                  <Badge color="green" variant="soft">
                    open
                  </Badge>
                </Flex>
                <Text size="1" color="gray">
                  SQLite device store / customer-kb
                </Text>
              </div>
            </section>
            <ScrollArea className="dock-list">
              {[
                ['客户知识库上线', 'Agent workflow / 5 tasks', 'review', 'amber'],
                ['销售数据分析', 'Memory sync / 12 sources', 'run', 'blue'],
                ['产品文档生成', 'Writer agent / queued', 'ready', 'green'],
              ].map(([title, subtitle, state, color]) => (
                <button className="dock-row" type="button" key={title}>
                  <span>
                    <strong>{title}</strong>
                    <Text size="1" color="gray">
                      {subtitle}
                    </Text>
                  </span>
                  <Badge color={color as 'amber' | 'blue' | 'green'} variant="soft">
                    {state}
                  </Badge>
                </button>
              ))}
            </ScrollArea>
            <section className="runtime-stack">
              <Text size="1" weight="bold" color="gray">
                RUNTIME STACK
              </Text>
              {[
                ['SQLite', 'open'],
                ['Docker', 'ready'],
                ['Ray', '4 actors'],
                ['MCP', '12 tools'],
              ].map(([name, value]) => (
                <Flex align="center" justify="between" key={name}>
                  <Text size="1" color="gray">
                    {name}
                  </Text>
                  <Text size="1" weight="bold">
                    {value}
                  </Text>
                </Flex>
              ))}
            </section>
          </aside>

          <main className="workbench">
            <section className="layout-toolbar">
              <Box>
                <Heading as="h1" size="3">Radix Dock 布局</Heading>
                <Text size="1" color="gray">
                  Chat / Board / Status 使用 Radix Themes 控件，Command Palette 由 cmdk 驱动。
                </Text>
              </Box>
              <Flex align="center" gap="3">
                <Flex align="center" gap="1" className="preset-group">
                  {(['balanced', 'focus', 'review', 'compact'] as PresetKey[]).map((item) => (
                    <Button
                      key={item}
                      size="2"
                      variant={preset === item ? 'solid' : 'soft'}
                      onClick={() => applyPreset(item)}
                    >
                      {item[0].toUpperCase() + item.slice(1)}
                    </Button>
                  ))}
                </Flex>
                <Separator orientation="vertical" />
                <Flex align="center" gap="1">
                  {panes.map((pane) => (
                    <Button
                      key={pane}
                      size="2"
                      variant={visible[pane] ? 'solid' : 'outline'}
                      color={visible[pane] ? 'cyan' : 'gray'}
                      onClick={() => togglePane(pane)}
                    >
                      {pane}
                    </Button>
                  ))}
                </Flex>
              </Flex>
            </section>

            <section className="pane-stage" ref={workspaceRef}>
              {visible.chat && (
                <Pane title="Chat" subtitle="multi-agent command thread" width={widths.chat}>
                  <ChatPane
                    messages={messages}
                    commandText={commandText}
                    setCommandText={setCommandText}
                    sendCommand={sendCommand}
                    collapse={() => togglePane('chat', false)}
                  />
                </Pane>
              )}
              {visible.chat && visible.board && <Resizer onPointerDown={(event) => startResize('chat', 'board', event)} />}
              {visible.board && (
                <Pane title="Board" subtitle="dockable workflow surface" width={widths.board}>
                  <BoardPane
                    boardMode={boardMode}
                    setBoardMode={setBoardMode}
                    taskFilter={taskFilter}
                    setTaskFilter={setTaskFilter}
                    tasks={visibleTasks}
                    selectedTaskId={selectedTaskId}
                    setSelectedTaskId={setSelectedTaskId}
                  />
                </Pane>
              )}
              {visible.board && visible.status && <Resizer onPointerDown={(event) => startResize('board', 'status', event)} />}
              {visible.status && (
                <Pane title="Status" subtitle="approval, evidence, terminal" width={widths.status}>
                  <StatusPane
                    selectedTask={selectedTask}
                    tab={inspectorTab}
                    setTab={setInspectorTab}
                    approveTask={approveTask}
                    requestChanges={requestChanges}
                    terminalLines={terminalLines}
                    memoryContent={memoryContent}
                    setMemoryContent={setMemoryContent}
                    memoryQuery={memoryQuery}
                    setMemoryQuery={setMemoryQuery}
                    memoryOutput={memoryOutput}
                    invokeMemory={invokeMemory}
                    collapse={() => togglePane('status', false)}
                  />
                </Pane>
              )}
              {collapsedPanes.length > 0 && (
                <div className="restore-dock">
                  {collapsedPanes.map((pane) => (
                    <Button key={pane} size="2" variant="surface" onClick={() => togglePane(pane, true)}>
                      Restore {pane}
                    </Button>
                  ))}
                </div>
              )}
            </section>
          </main>
        </section>

        <footer className="statusbar">
          <span>
            <CheckCircledIcon /> SQLite open
          </span>
          <span>Docker ready</span>
          <span>Ray 4 actors</span>
          <span>MCP 12 tools</span>
          <span>branch main</span>
          <span>latency 24ms</span>
          <span>cost $0.31</span>
          <span>tokens 18.4k</span>
          <strong>drag pane edges / Cmd K for commands</strong>
        </footer>

        <CommandPalette
          open={paletteOpen}
          setOpen={setPaletteOpen}
          applyPreset={applyPreset}
          togglePane={togglePane}
          setInspectorTab={setInspectorTab}
          setBoardMode={setBoardMode}
          approveTask={approveTask}
        />
      </div>
    </Theme>
  );
}

function Pane({
  title,
  subtitle,
  width,
  children,
}: {
  title: string;
  subtitle: string;
  width: number;
  children: React.ReactNode;
}) {
  return (
    <section className="pane-shell" style={{ flexBasis: `${width}%` }}>
      <header className="pane-head">
        <Box>
          <Heading as="h2" size="3">{title}</Heading>
          <Text size="1" color="gray">
            {subtitle}
          </Text>
        </Box>
        <Flex gap="1">
          <Tooltip content="Pin pane">
            <IconButton size="1" variant="surface" aria-label={`Pin ${title}`}>
              <PinTopIcon />
            </IconButton>
          </Tooltip>
          <Tooltip content="More actions">
            <IconButton size="1" variant="surface" aria-label={`${title} more actions`}>
              <DotsHorizontalIcon />
            </IconButton>
          </Tooltip>
        </Flex>
      </header>
      {children}
    </section>
  );
}

function Resizer({ onPointerDown }: { onPointerDown: (event: React.PointerEvent) => void }) {
  return (
    <button className="pane-resizer" type="button" aria-label="Resize pane" onPointerDown={onPointerDown}>
      <DragHandleDots2Icon />
    </button>
  );
}

function ChatPane({
  messages,
  commandText,
  setCommandText,
  sendCommand,
  collapse,
}: {
  messages: Message[];
  commandText: string;
  setCommandText: (value: string) => void;
  sendCommand: () => void;
  collapse: () => void;
}) {
  return (
    <div className="chat-pane">
      <Flex align="center" gap="2" className="agent-strip">
        {[
          ['Orchestrator', 'green'],
          ['Executor', 'blue'],
          ['Verifier', 'amber'],
          ['Writer', 'gray'],
        ].map(([agent, color]) => (
          <Badge key={agent} color={color as 'green' | 'blue' | 'amber' | 'gray'} variant="soft" size="2">
            {agent}
          </Badge>
        ))}
        <Tooltip content="Collapse Chat">
          <IconButton ml="auto" size="1" variant="ghost" aria-label="Collapse Chat" onClick={collapse}>
            <Cross2Icon />
          </IconButton>
        </Tooltip>
      </Flex>
      <ScrollArea className="message-scroll">
        <div className="message-stack">
          {messages.map((message) => (
            <article className={`message ${message.tone}`} key={message.id}>
              <Flex align="center" justify="between" mb="2">
                <Text size="2" weight="bold">
                  {message.speaker}
                </Text>
                <Text size="1" color="gray">
                  {message.time}
                </Text>
              </Flex>
              <Text size="2" color="gray">
                {message.body}
              </Text>
            </article>
          ))}
          <div className="tool-call">
            <span>memory.ingest customer onboarding notes</span>
            <Badge color="green" variant="soft">
              done
            </Badge>
          </div>
          <div className="tool-call">
            <span>terminal.run cargo test desktop_core_round_trip</span>
            <Badge color="blue" variant="soft">
              running
            </Badge>
          </div>
        </div>
      </ScrollArea>
      <div className="composer">
        <Flex align="center" gap="2" mb="2">
          <Button size="1" variant="surface">
            <RocketIcon /> /plan
          </Button>
          <Button size="1" variant="surface">
            <ClipboardIcon /> attach
          </Button>
          <Select.Root defaultValue="gpt-5.5">
            <Select.Trigger aria-label="model" />
            <Select.Content>
              <Select.Item value="gpt-5.5">gpt-5.5</Select.Item>
              <Select.Item value="local-agent">local-agent</Select.Item>
            </Select.Content>
          </Select.Root>
        </Flex>
        <TextArea
          value={commandText}
          onChange={(event) => setCommandText(event.target.value)}
          placeholder="输入命令，让 Agent 规划、执行、检查或调整 Radix Dock 布局..."
          onKeyDown={(event) => {
            if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) sendCommand();
          }}
        />
        <Flex align="center" justify="between" mt="2">
          <Text size="1" color="gray">
            Cmd + Enter send / local-first workspace
          </Text>
          <Button size="2" onClick={sendCommand}>
            Send
          </Button>
        </Flex>
      </div>
    </div>
  );
}

function BoardPane({
  boardMode,
  setBoardMode,
  taskFilter,
  setTaskFilter,
  tasks,
  selectedTaskId,
  setSelectedTaskId,
}: {
  boardMode: BoardMode;
  setBoardMode: (mode: BoardMode) => void;
  taskFilter: TaskStatus | 'all';
  setTaskFilter: (filter: TaskStatus | 'all') => void;
  tasks: Task[];
  selectedTaskId: string;
  setSelectedTaskId: (id: string) => void;
}) {
  return (
    <div className="board-pane">
      <Flex align="center" justify="between" className="board-toolbar">
        <Flex gap="1">
          <Button size="2" variant={boardMode === 'flow' ? 'solid' : 'soft'} onClick={() => setBoardMode('flow')}>
            <ViewGridIcon /> Flow
          </Button>
          <Button size="2" variant={boardMode === 'list' ? 'solid' : 'soft'} onClick={() => setBoardMode('list')}>
            <RowsIcon /> List
          </Button>
        </Flex>
        <Select.Root value={taskFilter} onValueChange={(value) => setTaskFilter(value as TaskStatus | 'all')}>
          <Select.Trigger aria-label="task filter" />
          <Select.Content>
            <Select.Item value="all">全部任务</Select.Item>
            <Select.Item value="running">运行</Select.Item>
            <Select.Item value="review">评审</Select.Item>
            <Select.Item value="done">完成</Select.Item>
            <Select.Item value="blocked">受阻</Select.Item>
          </Select.Content>
        </Select.Root>
      </Flex>
      {boardMode === 'flow' ? (
        <ScrollArea className="board-scroll">
          <div className="lane-grid">
            {lanes.map((lane) => {
              const laneTasks = tasks.filter((task) => task.lane === lane);
              return (
                <section className="lane" key={lane}>
                  <Flex align="center" justify="between" className="lane-head">
                    <Text size="2" weight="bold" color="gray">
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
                        onSelect={() => setSelectedTaskId(task.id)}
                      />
                    ))}
                  </div>
                </section>
              );
            })}
          </div>
        </ScrollArea>
      ) : (
        <ScrollArea className="list-scroll">
          <div className="task-table">
            {tasks.map((task) => (
              <button
                className={task.id === selectedTaskId ? 'task-row selected' : 'task-row'}
                key={task.id}
                type="button"
                onClick={() => setSelectedTaskId(task.id)}
                data-task={task.id}
              >
                <strong>{task.title}</strong>
                <span>{task.owner}</span>
                <span>{task.progress}%</span>
                <span>{task.files} files</span>
              </button>
            ))}
          </div>
        </ScrollArea>
      )}
    </div>
  );
}

function TaskButton({ task, selected, onSelect }: { task: Task; selected: boolean; onSelect: () => void }) {
  return (
    <button className={selected ? 'task-card selected' : 'task-card'} type="button" onClick={onSelect} data-task={task.id}>
      <Flex align="center" justify="between">
        <Text size="2" weight="bold">
          {task.title}
        </Text>
        <Badge color={statusColor[task.status]} variant="soft">
          {task.status}
        </Badge>
      </Flex>
      <Text size="1" color="gray">
        {task.owner} / {task.files} files
      </Text>
      <Progress value={task.progress} />
      <Flex align="center" justify="between">
        <Text size="1" color="gray">
          {task.progress}%
        </Text>
        <Text size="1" color="gray">
          {task.summary}
        </Text>
      </Flex>
    </button>
  );
}

function StatusPane({
  selectedTask,
  tab,
  setTab,
  approveTask,
  requestChanges,
  terminalLines,
  memoryContent,
  setMemoryContent,
  memoryQuery,
  setMemoryQuery,
  memoryOutput,
  invokeMemory,
  collapse,
}: {
  selectedTask: Task;
  tab: InspectorTab;
  setTab: (tab: InspectorTab) => void;
  approveTask: () => void;
  requestChanges: () => void;
  terminalLines: string[];
  memoryContent: string;
  setMemoryContent: (value: string) => void;
  memoryQuery: string;
  setMemoryQuery: (value: string) => void;
  memoryOutput: string;
  invokeMemory: (kind: 'ingest' | 'search') => void;
  collapse: () => void;
}) {
  return (
    <div className="status-pane">
      <Flex align="center" justify="between" className="status-task">
        <Box>
          <Text as="div" size="2" weight="bold">
            {selectedTask.title}
          </Text>
          <Text as="div" size="1" color="gray">
            {selectedTask.owner}
          </Text>
        </Box>
        <Tooltip content="Collapse Status">
          <IconButton size="1" variant="ghost" aria-label="Collapse Status" onClick={collapse}>
            <Cross2Icon />
          </IconButton>
        </Tooltip>
      </Flex>
      <Tabs.Root value={tab} onValueChange={(value) => setTab(value as InspectorTab)}>
        <Tabs.List>
          <Tabs.Trigger value="overview">概览</Tabs.Trigger>
          <Tabs.Trigger value="evidence">证据</Tabs.Trigger>
          <Tabs.Trigger value="logs">日志</Tabs.Trigger>
          <Tabs.Trigger value="terminal">终端</Tabs.Trigger>
        </Tabs.List>
      </Tabs.Root>
      <ScrollArea className="inspector-scroll">
        {tab === 'overview' && (
          <div className="inspector-stack">
            <section className="approval-callout">
              <Flex align="center" gap="2" mb="2">
                <LightningBoltIcon />
                <Text weight="bold">需要人工审批</Text>
              </Flex>
              <Text size="2" color="gray">
                {selectedTask.summary} 批准后将继续生成发布包。
              </Text>
              <Flex gap="2" mt="3">
                <Button onClick={approveTask}>
                  <CheckCircledIcon /> 批准发布
                </Button>
                <Button color="gray" variant="surface" onClick={requestChanges}>
                  要求修改
                </Button>
              </Flex>
            </section>
            <div className="metric-grid">
              <Metric label="Progress" value={`${selectedTask.progress}%`} />
              <Metric label="Files" value={String(selectedTask.files)} />
              <Metric label="Runtime" value="Local" />
              <Metric label="Cost" value="$0.18" />
            </div>
            <section className="memory-smoke">
              <Text size="1" weight="bold" color="gray">
                LOCAL MEMORY SMOKE
              </Text>
              <TextField.Root value={memoryContent} onChange={(event) => setMemoryContent(event.target.value)} />
              <Button variant="surface" onClick={() => invokeMemory('ingest')}>
                Ingest
              </Button>
              <TextField.Root value={memoryQuery} onChange={(event) => setMemoryQuery(event.target.value)} />
              <Button variant="surface" onClick={() => invokeMemory('search')}>
                Search
              </Button>
              <pre>{memoryOutput}</pre>
            </section>
          </div>
        )}
        {tab === 'evidence' && (
          <div className="artifact-list">
            {['migration-report.html', 'schema-diff.sql', 'rollback-plan.md'].map((artifact) => (
              <div className="artifact" key={artifact}>
                <FileTextIcon />
                <Text size="2" weight="bold">
                  {artifact}
                </Text>
                <Badge color="green" variant="soft">
                  ready
                </Badge>
              </div>
            ))}
          </div>
        )}
        {tab === 'logs' && (
          <div className="artifact-list">
            {[
              ['10:24', 'Planner created workflow'],
              ['10:28', 'Executor ran migration'],
              ['10:31', 'Verifier requested approval'],
            ].map(([time, entry]) => (
              <div className="artifact" key={entry}>
                <LapTimerIcon />
                <Text size="2" weight="bold">
                  {time}
                </Text>
                <Text size="2" color="gray">
                  {entry}
                </Text>
              </div>
            ))}
          </div>
        )}
        {tab === 'terminal' && (
          <pre className="terminal-log">
            {terminalLines.map((line) => (
              <span key={line}>{line}</span>
            ))}
          </pre>
        )}
      </ScrollArea>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric">
      <Text size="1" color="gray" weight="bold">
        {label}
      </Text>
      <Text as="div" size="5" weight="bold">
        {value}
      </Text>
    </div>
  );
}

function CommandPalette({
  open,
  setOpen,
  applyPreset,
  togglePane,
  setInspectorTab,
  setBoardMode,
  approveTask,
}: {
  open: boolean;
  setOpen: (open: boolean) => void;
  applyPreset: (preset: PresetKey) => void;
  togglePane: (pane: PaneKey, force?: boolean) => void;
  setInspectorTab: (tab: InspectorTab) => void;
  setBoardMode: (mode: BoardMode) => void;
  approveTask: () => void;
}) {
  const run = (action: () => void) => {
    action();
    setOpen(false);
  };

  return (
    <Command.Dialog open={open} onOpenChange={setOpen} label="Global Command Menu">
      <div className="cmdk-header">
        <MagnifyingGlassIcon />
        <Command.Input placeholder="Search commands, panes, tasks, memory..." />
        <kbd>Esc</kbd>
      </div>
      <Command.List>
        <Command.Empty>No matching command.</Command.Empty>
        <Command.Group heading="Layout">
          <Command.Item value="balanced layout" onSelect={() => run(() => applyPreset('balanced'))}>
            <MixerHorizontalIcon /> Balanced layout
          </Command.Item>
          <Command.Item value="focus chat layout" onSelect={() => run(() => applyPreset('focus'))}>
            <ChatBubbleIcon /> Focus chat
          </Command.Item>
          <Command.Item value="review status layout" onSelect={() => run(() => applyPreset('review'))}>
            <ActivityLogIcon /> Review status
          </Command.Item>
          <Command.Item value="compact layout" onSelect={() => run(() => applyPreset('compact'))}>
            <DesktopIcon /> Compact layout
          </Command.Item>
        </Command.Group>
        <Command.Group heading="Panes">
          <Command.Item value="show chat" onSelect={() => run(() => togglePane('chat', true))}>
            <ChatBubbleIcon /> Show Chat
          </Command.Item>
          <Command.Item value="show board" onSelect={() => run(() => togglePane('board', true))}>
            <BarChartIcon /> Show Board
          </Command.Item>
          <Command.Item value="show status" onSelect={() => run(() => togglePane('status', true))}>
            <ActivityLogIcon /> Show Status
          </Command.Item>
        </Command.Group>
        <Command.Group heading="Workflow">
          <Command.Item value="board list" onSelect={() => run(() => setBoardMode('list'))}>
            <RowsIcon /> Switch Board to List
          </Command.Item>
          <Command.Item value="terminal tab" onSelect={() => run(() => setInspectorTab('terminal'))}>
            <CodeIcon /> Open Terminal
          </Command.Item>
          <Command.Item value="approve selected task" onSelect={() => run(approveTask)}>
            <CheckCircledIcon /> Approve selected task
          </Command.Item>
        </Command.Group>
        <Command.Group heading="References">
          <Command.Item value="radix themes" onSelect={() => run(() => window.open('https://www.radix-ui.com/themes/docs/overview/getting-started', '_blank'))}>
            <KeyboardIcon /> Radix Themes getting started
          </Command.Item>
        </Command.Group>
      </Command.List>
    </Command.Dialog>
  );
}

createRoot(document.getElementById('root')!).render(<App />);
