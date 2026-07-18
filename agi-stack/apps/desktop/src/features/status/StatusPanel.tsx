import { useMemo } from 'react';
import { Badge, Flex, Heading, ScrollArea, Tabs, Text } from '@radix-ui/themes';

import { useI18n } from '../../i18n';
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
import type { TerminalBindingState } from '../session/sessionTerminalModel';

const MAX_RENDERED_EVENTS = 50;

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
  terminalBinding: TerminalBindingState;
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
  const { t } = useI18n();
  // Events arrive newest-first and the rAF-batched array identity changes at most
  // once per frame, so serialize the rendered rows only when the buffer changes.
  const renderedEvents = useMemo(
    () =>
      props.events
        .slice(0, MAX_RENDERED_EVENTS)
        .map((event, index) => ({
          event,
          badge: props.events.length - index,
          key: `${event.type ?? 'event'}-${index}`,
          detail: JSON.stringify(event, null, 2),
        })),
    [props.events],
  );
  const terminalStatus =
    props.terminalBinding === 'connected'
      ? t('session.terminalConnected')
      : props.terminalBinding === 'connecting'
        ? t('session.terminalConnecting')
        : props.terminalBinding === 'closed'
          ? t('session.terminalClosed')
          : props.terminalBinding === 'stale'
            ? t('session.terminalStale')
            : props.terminalBinding === 'error'
              ? t('session.terminalError')
              : t('session.terminalIdle');
  return (
    <section className="pane-shell status-shell">
      <header className="pane-head">
        <div>
          <Heading as="h2" size="3">
            {t('status.title')}
          </Heading>
          <Text size="1" color="gray">
            {t('status.description')}
          </Text>
        </div>
        <Badge
          color={props.wsConnected ? 'green' : 'gray'}
          variant="soft"
          role="status"
          aria-live="polite"
        >
          {props.wsConnected ? t('status.live') : t('status.idle')}
        </Badge>
      </header>

      <Tabs.Root value={props.tab} onValueChange={(value) => props.onTabChange(value as StatusTab)}>
        <Tabs.List className="status-tab-list">
          <Tabs.Trigger value="overview">{t('status.overview')}</Tabs.Trigger>
          <Tabs.Trigger value="plan">{t('status.plan')}</Tabs.Trigger>
          <Tabs.Trigger value="sandbox">{t('status.sandbox')}</Tabs.Trigger>
          <Tabs.Trigger value="memory">{t('status.memory')}</Tabs.Trigger>
          <Tabs.Trigger value="events">{t('status.events')}</Tabs.Trigger>
        </Tabs.List>
        <ScrollArea className="status-scroll">
          <Tabs.Content value="overview">
            <div className="inspector-stack">
              <TaskSummary task={props.selectedTask} />
              <div className="metric-grid">
                <Metric label={t('status.planKeys')} value={String(Object.keys(props.plan ?? {}).length)} />
                <Metric label={t('status.events')} value={String(props.events.length)} />
                <Metric
                  label={t('status.sandbox')}
                  value={props.sandbox?.status ?? t('status.notLoaded')}
                />
                <Metric label={t('status.terminal')} value={terminalStatus} />
              </div>
            </div>
          </Tabs.Content>
          <Tabs.Content value="plan">
            <div className="inspector-stack">
              <pre className="json-output">
                {props.plan ? JSON.stringify(props.plan, null, 2) : t('status.noPlanSnapshot')}
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
                terminalBinding={props.terminalBinding}
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
                  {t('status.noLiveUpdates')}
                </Text>
              ) : (
                <>
                  {props.events.length > renderedEvents.length ? (
                    <Text size="1" color="gray">
                      {t('status.eventsShowingLatest', {
                        shown: renderedEvents.length,
                        total: props.events.length,
                      })}
                    </Text>
                  ) : null}
                  {renderedEvents.map((row) => (
                    <article className="event-row" key={row.key}>
                      <Flex align="center" justify="between" gap="2" mb="1">
                        <Text size="2" weight="bold">
                          {String(row.event.type ?? row.event.event_type ?? 'event')}
                        </Text>
                        <Badge color="gray" variant="soft">
                          #{row.badge}
                        </Badge>
                      </Flex>
                      <pre>{row.detail}</pre>
                    </article>
                  ))}
                </>
              )}
            </div>
          </Tabs.Content>
        </ScrollArea>
      </Tabs.Root>
    </section>
  );
}

function TaskSummary({ task }: { task: WorkspaceTask | null }) {
  const { t } = useI18n();
  if (!task) {
    return (
      <div className="approval-callout">
        <Text size="2" color="gray">
          {t('status.selectTask')}
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
          {task.status ?? t('status.open')}
        </Badge>
      </Flex>
      <Text as="p" size="2" color="gray">
        {task.summary ?? task.description ?? t('status.noTaskSummary')}
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
