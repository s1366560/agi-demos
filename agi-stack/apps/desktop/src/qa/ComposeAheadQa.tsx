import '@radix-ui/themes/styles.css';
import React, { useCallback, useMemo, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { ChatBubbleIcon, CheckCircledIcon, ClockIcon, CubeIcon } from '@radix-ui/react-icons';
import { Button, Theme } from '@radix-ui/themes';

import { ChatPanel } from '../features/chat/ChatPanel';
import type { AgentTaskSignal } from '../features/chat/agentTaskSignalModel';
import type { ComposerCatalogClient } from '../features/chat/composerCatalogModel';
import { ToastProvider } from '../features/feedback/ToastCenter';
import { I18nProvider } from '../i18n';
import type {
  AgentConversation,
  AgentTimelineItem,
  AgentWsEvent,
  ComposerContextItem,
  ConversationTimelineState,
} from '../types';
import '../styles.css';
import './sessionSteeringQa.css';

declare global {
  var __composeAheadQaRoot: Root | undefined;
}

const qaApi: ComposerCatalogClient = {
  listWorkspaceAgents: async () => [],
  listManagedAgents: async () => [],
  listManagedSkills: async () => [],
  listManagedPlugins: async () => [],
  listManagedSubAgents: async () => [],
};

const conversation: AgentConversation = {
  id: 'conversation-compose-ahead',
  project_id: 'project-compose-ahead',
  tenant_id: 'tenant-compose-ahead',
  user_id: 'user-compose-ahead',
  title: 'Compose-ahead acceptance',
  status: 'active',
  message_count: 2,
  created_at: '2026-07-24T08:00:00Z',
  workspace_id: 'workspace-compose-ahead',
};

function timelineItem(
  partial: Partial<AgentTimelineItem> & { id: string; type: string },
): AgentTimelineItem {
  return {
    eventTimeUs: Date.now() * 1_000,
    eventCounter: 0,
    timestamp: Date.now(),
    ...partial,
  };
}

const initialItems: AgentTimelineItem[] = [
  timelineItem({
    id: 'compose-ahead-user-initial',
    type: 'user_message',
    role: 'user',
    content: 'Validate the current response before continuing with queued follow-ups.',
    eventCounter: 1,
  }),
  timelineItem({
    id: 'compose-ahead-assistant-initial',
    type: 'assistant_message',
    role: 'assistant',
    content: 'I am validating the active response. You can queue follow-up prompts now.',
    metadata: { streaming: true },
    eventCounter: 2,
  }),
];

function timelineState(items: AgentTimelineItem[]): ConversationTimelineState {
  return {
    conversationId: conversation.id,
    items,
    approvalRequests: [],
    artifactVersions: [],
    artifactDeliveries: [],
    toolInvocations: [],
    loading: false,
    loadingEarlier: false,
    error: null,
    hasMore: false,
    firstCursor: items[0]
      ? { timeUs: items[0].eventTimeUs, counter: items[0].eventCounter }
      : null,
    lastCursor: items.at(-1)
      ? {
          timeUs: items.at(-1)?.eventTimeUs ?? 0,
          counter: items.at(-1)?.eventCounter ?? 0,
        }
      : null,
  };
}

function ComposeAheadQa() {
  const [items, setItems] = useState<AgentTimelineItem[]>(initialItems);
  const [streaming, setStreaming] = useState(true);
  const [dispatches, setDispatches] = useState<string[]>([]);
  const [stopRequests, setStopRequests] = useState<string[]>([]);
  const [agentControlEvents, setAgentControlEvents] = useState<AgentWsEvent[]>([]);

  const signals = useMemo<AgentTaskSignal[]>(
    () =>
      streaming
        ? [
            {
              id: `compose-ahead-signal-${dispatches.length}`,
              content: 'Assistant response in progress',
              status: 'acknowledged',
              detail: 'Streaming a response for the selected conversation',
              createdAt: '2026-07-24T08:00:00Z',
              conversationId: conversation.id,
              messageId: `compose-ahead-assistant-${dispatches.length}`,
              eventType: 'text_delta',
            },
          ]
        : [],
    [dispatches.length, streaming],
  );

  const completeResponse = useCallback(() => {
    setStreaming(false);
    setItems((current) =>
      current.map((item, index) =>
        index === current.length - 1 && item.type === 'assistant_message'
          ? {
              ...item,
              content: `${item.content ?? ''} Response completed.`,
              metadata: { ...item.metadata, streaming: false },
            }
          : item,
      ),
    );
  }, []);

  const sendMessage = useCallback(
    (
      content: string,
      _contextItems: ComposerContextItem[],
      onWorkspaceMessageSaved?: () => void,
    ) => {
      const nextSequence = dispatches.length + 1;
      setDispatches((current) => [...current, content]);
      setItems((current) => [
        ...current,
        timelineItem({
          id: `compose-ahead-user-${nextSequence}`,
          type: 'user_message',
          role: 'user',
          content,
          eventCounter: current.length + 1,
        }),
        timelineItem({
          id: `compose-ahead-assistant-${nextSequence}`,
          type: 'assistant_message',
          role: 'assistant',
          content: `Processing queued follow-up ${nextSequence}: ${content}`,
          metadata: { streaming: true },
          eventCounter: current.length + 2,
        }),
      ]);
      setStreaming(true);
      onWorkspaceMessageSaved?.();
    },
    [dispatches.length],
  );

  const stopResponse = useCallback(
    (conversationId: string) => {
      setStopRequests((current) => [
        ...current,
        JSON.stringify({ type: 'stop_session', conversation_id: conversationId }),
      ]);
      window.setTimeout(() => {
        setAgentControlEvents([
          {
            type: 'ack',
            action: 'stop_session',
            conversation_id: conversationId,
          },
        ]);
        completeResponse();
      }, 400);
      return true;
    },
    [completeResponse],
  );

  return (
    <Theme appearance="dark" accentColor="cyan" grayColor="slate" radius="large">
      <div className="session-steering-qa-shell">
        <aside className="session-steering-qa-rail">
          <div className="session-steering-qa-brand">
            <CubeIcon />
            <strong>MemStack</strong>
          </div>
          <nav>
            <button type="button" className="selected">
              <ChatBubbleIcon /> Compose ahead
            </button>
          </nav>
          <section>
            <span>Acceptance controls</span>
            <Button
              data-testid="complete-response"
              variant="soft"
              color={streaming ? 'cyan' : 'green'}
              onClick={completeResponse}
              disabled={!streaming}
            >
              {streaming ? <ClockIcon /> : <CheckCircledIcon />}
              {streaming ? 'Complete current response' : 'Response complete'}
            </Button>
            <small data-testid="response-state">
              {streaming ? 'Streaming' : 'Terminal'} · dispatched {dispatches.length} · stopped{' '}
              {stopRequests.length}
            </small>
            <output data-testid="stop-log">{stopRequests.at(-1) ?? 'No stop request'}</output>
            <ol data-testid="dispatch-log">
              {dispatches.map((content, index) => (
                <li key={`${index}-${content}`}>
                  {index + 1}. {content}
                </li>
              ))}
            </ol>
          </section>
        </aside>
        <main>
          <header className="session-steering-qa-titlebar">
            <div>
              <ChatBubbleIcon />
              <span>
                <strong>Compose-ahead acceptance</strong>
                <small>Real ChatPanel · deterministic terminal cycles</small>
              </span>
            </div>
          </header>
          <div className="session-steering-qa-content compose-ahead-qa-content">
            <ChatPanel
              composeAheadFallbackAllowed
              api={qaApi}
              conversations={[conversation]}
              selectedConversationId={conversation.id}
              messages={[]}
              timelineState={timelineState(items)}
              agentTaskSignals={signals}
              workflowCounts={{ plan: 'ready' }}
              sessionTitle={conversation.title}
              scopeLabel="Compose-ahead parity fixture"
              composerVariant="session"
              composerResetKey={conversation.id}
              activityPresence={streaming ? 'live' : 'recorded'}
              activityStructuredEvidence={null}
              sending={false}
              disabledReason={null}
              agentControlEvents={agentControlEvents}
              activeWorkflowTarget="plan"
              modelLabel="gpt-5.5"
              selectedModelValue="gpt-5.5"
              runtimeTargetLabel="Local Rust Core"
              runtimeTargetOptions={['Local Rust Core']}
              runInputDelivery={null}
              runInputDeliveryOptions={[]}
              runInputs={[]}
              runInputsLoading={false}
              runInputsError={null}
              promotingRunInputId={null}
              runInputAuthorityRunId={null}
              references={[]}
              onRunInputDeliveryChange={() => undefined}
              onPromoteRunInput={() => undefined}
              onRemoveReference={() => undefined}
              onSend={sendMessage}
              onStopResponse={stopResponse}
              onRefresh={() => undefined}
              onLoadEarlier={() => undefined}
              onRespondToHitl={async () => undefined}
              respondableHitlRequestIds={[]}
              onWorkflowSelect={() => undefined}
              onRuntimeTargetChange={() => undefined}
              onOpenCommands={() => undefined}
            />
          </div>
        </main>
      </div>
    </Theme>
  );
}

const root = document.getElementById('root');
if (!root) throw new Error('Missing #root container');
const qaRoot = globalThis.__composeAheadQaRoot ?? createRoot(root);
globalThis.__composeAheadQaRoot = qaRoot;
qaRoot.render(
  <React.StrictMode>
    <I18nProvider>
      <ToastProvider>
        <ComposeAheadQa />
      </ToastProvider>
    </I18nProvider>
  </React.StrictMode>,
);
