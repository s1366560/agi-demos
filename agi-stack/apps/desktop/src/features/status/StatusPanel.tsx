import { Badge, Flex, Heading, ScrollArea, Tabs, Text } from '@radix-ui/themes';

import type {
  AgentWsEvent,
  DesktopServiceResponse,
  LocalMemoryResult,
  PlanSnapshot,
  ProjectSandbox,
  StatusTab,
  TerminalServiceResponse,
  WorkspaceTask,
} from '../../types';
import { MemoryPanel } from '../memory/MemoryPanel';
import { SandboxPanel } from '../sandbox/SandboxPanel';

type StatusPanelProps = {
  selectedTask: WorkspaceTask | null;
  plan: PlanSnapshot | null;
  events: AgentWsEvent[];
  wsConnected: boolean;
  tab: StatusTab;
  sandbox: ProjectSandbox | null;
  desktop: DesktopServiceResponse | null;
  desktopFrameUrl: string | null;
  terminal: TerminalServiceResponse | null;
  terminalConnected: boolean;
  terminalError: string | null;
  terminalLines: string[];
  terminalInput: string;
  sandboxBusy: boolean;
  sandboxDisabledReason: string | null;
  memoryProjectId: string;
  memoryContent: string;
  memoryQuery: string;
  tauriAvailable: boolean;
  memoryBusy: boolean;
  memoryResult: LocalMemoryResult | null;
  onTabChange: (tab: StatusTab) => void;
  onTerminalInputChange: (value: string) => void;
  onEnsureSandbox: () => void;
  onStartDesktop: () => void;
  onStartTerminal: () => void;
  onSendTerminalInput: () => void;
  onClearTerminal: () => void;
  onMemoryContentChange: (value: string) => void;
  onMemoryQueryChange: (value: string) => void;
  onMemoryIngest: () => void;
  onMemorySearch: () => void;
  onMemorySemanticSearch: () => void;
};

export function StatusPanel(props: StatusPanelProps) {
  return (
    <section className="pane-shell status-shell">
      <header className="pane-head">
        <div>
          <Heading as="h2" size="3">
            Status
          </Heading>
          <Text size="1" color="gray">
            Plan, sandbox, local memory, and progress updates.
          </Text>
        </div>
        <Badge color={props.wsConnected ? 'green' : 'gray'} variant="soft">
          {props.wsConnected ? 'Live' : 'Idle'}
        </Badge>
      </header>

      <Tabs.Root value={props.tab} onValueChange={(value) => props.onTabChange(value as StatusTab)}>
        <Tabs.List className="status-tab-list">
          <Tabs.Trigger value="overview">Overview</Tabs.Trigger>
          <Tabs.Trigger value="plan">Plan</Tabs.Trigger>
          <Tabs.Trigger value="sandbox">Sandbox</Tabs.Trigger>
          <Tabs.Trigger value="memory">Memory</Tabs.Trigger>
          <Tabs.Trigger value="events">Events</Tabs.Trigger>
        </Tabs.List>
        <ScrollArea className="status-scroll">
          <Tabs.Content value="overview">
            <div className="inspector-stack">
              <TaskSummary task={props.selectedTask} />
              <div className="metric-grid">
                <Metric label="Plan keys" value={String(Object.keys(props.plan ?? {}).length)} />
                <Metric label="Events" value={String(props.events.length)} />
                <Metric label="Sandbox" value={props.sandbox?.status ?? 'not loaded'} />
                <Metric label="Terminal" value={props.terminalConnected ? 'connected' : 'idle'} />
              </div>
            </div>
          </Tabs.Content>
          <Tabs.Content value="plan">
            <div className="inspector-stack">
              <pre className="json-output">
                {props.plan ? JSON.stringify(props.plan, null, 2) : 'No plan snapshot loaded.'}
              </pre>
            </div>
          </Tabs.Content>
          <Tabs.Content value="sandbox">
            <div className="inspector-stack">
              <SandboxPanel
                sandbox={props.sandbox}
                desktop={props.desktop}
                desktopFrameUrl={props.desktopFrameUrl}
                terminal={props.terminal}
                terminalConnected={props.terminalConnected}
                terminalError={props.terminalError}
                terminalLines={props.terminalLines}
                terminalInput={props.terminalInput}
                busy={props.sandboxBusy}
                disabledReason={props.sandboxDisabledReason}
                onTerminalInputChange={props.onTerminalInputChange}
                onEnsureSandbox={props.onEnsureSandbox}
                onStartDesktop={props.onStartDesktop}
                onStartTerminal={props.onStartTerminal}
                onSendTerminalInput={props.onSendTerminalInput}
                onClearTerminal={props.onClearTerminal}
              />
            </div>
          </Tabs.Content>
          <Tabs.Content value="memory">
            <div className="inspector-stack">
              <MemoryPanel
                projectId={props.memoryProjectId}
                content={props.memoryContent}
                query={props.memoryQuery}
                tauriAvailable={props.tauriAvailable}
                busy={props.memoryBusy}
                result={props.memoryResult}
                onContentChange={props.onMemoryContentChange}
                onQueryChange={props.onMemoryQueryChange}
                onIngest={props.onMemoryIngest}
                onSearch={props.onMemorySearch}
                onSemanticSearch={props.onMemorySemanticSearch}
              />
            </div>
          </Tabs.Content>
          <Tabs.Content value="events">
            <div className="event-list">
              {props.events.length === 0 ? (
                <Text size="2" color="gray">
                  No live updates yet.
                </Text>
              ) : (
                props.events.map((event, index) => (
                  <article className="event-row" key={`${event.type ?? 'event'}-${index}`}>
                    <Flex align="center" justify="between" gap="2" mb="1">
                      <Text size="2" weight="bold">
                        {String(event.type ?? event.event_type ?? 'event')}
                      </Text>
                      <Badge color="gray" variant="soft">
                        #{props.events.length - index}
                      </Badge>
                    </Flex>
                    <pre>{JSON.stringify(event, null, 2)}</pre>
                  </article>
                ))
              )}
            </div>
          </Tabs.Content>
        </ScrollArea>
      </Tabs.Root>
    </section>
  );
}

function TaskSummary({ task }: { task: WorkspaceTask | null }) {
  if (!task) {
    return (
      <div className="approval-callout">
        <Text size="2" color="gray">
          Select a task to inspect status and metadata.
        </Text>
      </div>
    );
  }

  return (
    <div className="approval-callout">
      <Flex align="center" justify="between" gap="2">
        <Text size="2" weight="bold">
          {task.title ?? task.id}
        </Text>
        <Badge color={task.status === 'blocked' ? 'red' : 'amber'} variant="soft">
          {task.status ?? 'open'}
        </Badge>
      </Flex>
      <Text as="p" size="2" color="gray">
        {task.summary ?? task.description ?? 'No task summary.'}
      </Text>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric">
      <Text size="1" color="gray">
        {label}
      </Text>
      <Text size="2" weight="bold">
        {value}
      </Text>
    </div>
  );
}
