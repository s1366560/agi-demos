import '@radix-ui/themes/styles.css';
import React, { useCallback, useMemo, useRef, useState } from 'react';
import { ChatBubbleIcon, CubeIcon, ExclamationTriangleIcon } from '@radix-ui/react-icons';
import { Button, Theme } from '@radix-ui/themes';
import { createRoot, type Root } from 'react-dom/client';

import { ChatPanel } from '../features/chat/ChatPanel';
import type { ComposerCatalogClient } from '../features/chat/composerCatalogModel';
import { I18nProvider } from '../i18n';
import type {
  AgentConversation,
  AgentTimelineItem,
  ConversationTimelineState,
  RuntimeMode,
} from '../types';
import '../styles.css';
import './sessionSteeringQa.css';

declare global {
  var __conversationSummaryQaRoot: Root | undefined;
}

const qaApi: ComposerCatalogClient = {
  listWorkspaceAgents: async () => [],
  listManagedAgents: async () => [],
  listManagedSkills: async () => [],
  listManagedPlugins: async () => [],
  listManagedSubAgents: async () => [],
};

const initialConversations: AgentConversation[] = [
  {
    id: 'conversation-summary',
    project_id: 'project-summary',
    tenant_id: 'tenant-summary',
    user_id: 'user-summary',
    title: 'Authoritative summary',
    status: 'active',
    message_count: 2,
    created_at: '2026-07-26T08:00:00Z',
    workspace_id: 'workspace-summary',
    summary:
      'This structured server summary records the current objective, confirmed decisions, active implementation scope, verification evidence, and the next safe action. It is intentionally long enough to exercise expansion without deriving anything from rendered message text.',
  },
  {
    id: 'conversation-empty-summary',
    project_id: 'project-summary',
    tenant_id: 'tenant-summary',
    user_id: 'user-summary',
    title: 'No summary',
    status: 'active',
    message_count: 1,
    created_at: '2026-07-26T08:05:00Z',
    workspace_id: 'workspace-summary',
    summary: null,
  },
];

function timelineFor(conversation: AgentConversation): ConversationTimelineState {
  const item: AgentTimelineItem = {
    id: `${conversation.id}-user`,
    type: 'user_message',
    role: 'user',
    content: `Timeline content for ${conversation.title}.`,
    timestamp: Date.now(),
    eventTimeUs: Date.now() * 1_000,
    eventCounter: 1,
  };
  return {
    conversationId: conversation.id,
    items: [item],
    approvalRequests: [],
    artifactVersions: [],
    artifactDeliveries: [],
    toolInvocations: [],
    loading: false,
    loadingEarlier: false,
    error: null,
    hasMore: false,
    firstCursor: { timeUs: item.eventTimeUs, counter: item.eventCounter },
    lastCursor: { timeUs: item.eventTimeUs, counter: item.eventCounter },
  };
}

function ConversationSummaryQa() {
  const [conversations, setConversations] = useState(initialConversations);
  const [selectedConversationId, setSelectedConversationId] = useState(
    initialConversations[0].id,
  );
  const [runtimeMode, setRuntimeMode] = useState<RuntimeMode>('cloud');
  const [failNextRequest, setFailNextRequest] = useState(false);
  const [requestLog, setRequestLog] = useState('No summary request');
  const selectedConversationIdRef = useRef(selectedConversationId);
  const failNextRequestRef = useRef(false);
  const requestCountRef = useRef(0);
  selectedConversationIdRef.current = selectedConversationId;
  const selectedConversation =
    conversations.find((conversation) => conversation.id === selectedConversationId) ??
    conversations[0];
  const timelineState = useMemo(
    () => timelineFor(selectedConversation),
    [selectedConversation],
  );

  const selectConversation = useCallback((conversationId: string) => {
    selectedConversationIdRef.current = conversationId;
    setSelectedConversationId(conversationId);
  }, []);

  const regenerateConversationSummary = useCallback(
    async (conversationId: string) => {
      const requestPath = `/api/v1/agent/conversations/${encodeURIComponent(
        conversationId,
      )}/summary?project_id=project-summary`;
      setRequestLog(JSON.stringify({ method: 'POST', path: requestPath, status: 'pending' }));
      await new Promise((resolve) => window.setTimeout(resolve, 1_500));
      if (failNextRequestRef.current) {
        failNextRequestRef.current = false;
        setFailNextRequest(false);
        setRequestLog(JSON.stringify({ method: 'POST', path: requestPath, status: 'failed' }));
        throw new Error('Deterministic summary failure');
      }
      if (selectedConversationIdRef.current !== conversationId) {
        setRequestLog(JSON.stringify({ method: 'POST', path: requestPath, status: 'discarded' }));
        return;
      }
      requestCountRef.current += 1;
      setConversations((current) =>
        current.map((conversation) =>
          conversation.id === conversationId
            ? {
                ...conversation,
                summary: `Regenerated authoritative summary for request ${requestCountRef.current}.`,
              }
            : conversation,
        ),
      );
      setRequestLog(JSON.stringify({ method: 'POST', path: requestPath, status: 'complete' }));
    },
    [],
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
              <ChatBubbleIcon /> Conversation summary
            </button>
          </nav>
          <section>
            <span>Acceptance controls</span>
            <Button
              data-testid="select-summary-conversation"
              variant="soft"
              onClick={() => selectConversation(initialConversations[0].id)}
            >
              Select summary
            </Button>
            <Button
              data-testid="select-empty-conversation"
              variant="soft"
              onClick={() => selectConversation(initialConversations[1].id)}
            >
              Select no summary
            </Button>
            <Button
              data-testid="fail-next-summary"
              variant="soft"
              color={failNextRequest ? 'red' : 'gray'}
              onClick={() => {
                failNextRequestRef.current = true;
                setFailNextRequest(true);
              }}
            >
              <ExclamationTriangleIcon /> Fail next request
            </Button>
            <Button
              data-testid="summary-mode-cloud"
              variant="soft"
              onClick={() => setRuntimeMode('cloud')}
            >
              Cloud mode
            </Button>
            <Button
              data-testid="summary-mode-local"
              variant="soft"
              onClick={() => setRuntimeMode('local')}
            >
              Local mode
            </Button>
            <output data-testid="summary-selection">{selectedConversationId}</output>
            <output data-testid="summary-runtime-mode">{runtimeMode}</output>
            <output data-testid="summary-request-log">{requestLog}</output>
          </section>
        </aside>
        <main>
          <header className="session-steering-qa-titlebar">
            <div>
              <ChatBubbleIcon />
              <span>
                <strong>Conversation summary acceptance</strong>
                <small>Real ChatPanel · deterministic summary lifecycle</small>
              </span>
            </div>
          </header>
          <div className="session-steering-qa-content compose-ahead-qa-content">
            <ChatPanel
              api={qaApi}
              conversations={conversations}
              selectedConversationId={selectedConversation.id}
              messages={[]}
              timelineState={timelineState}
              agentTaskSignals={[]}
              workflowCounts={{ plan: 'ready' }}
              sessionTitle={selectedConversation.title}
              scopeLabel="Conversation summary parity fixture"
              turnCollapseRuntime={{
                mode: runtimeMode,
                apiBaseUrl: 'https://api.memstack.test',
                tenantId: 'tenant-summary',
                projectId: 'project-summary',
              }}
              composerVariant="session"
              composerResetKey={selectedConversation.id}
              activityPresence="recorded"
              activityStructuredEvidence={null}
              sending={false}
              disabledReason={null}
              activeWorkflowTarget="plan"
              modelLabel="gpt-5.5"
              selectedModelValue="gpt-5.5"
              runtimeTargetLabel="Cloud runtime"
              runtimeTargetOptions={['Cloud runtime']}
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
              onSend={() => undefined}
              onRegenerateConversationSummary={regenerateConversationSummary}
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
const qaRoot = globalThis.__conversationSummaryQaRoot ?? createRoot(root);
globalThis.__conversationSummaryQaRoot = qaRoot;
qaRoot.render(
  <React.StrictMode>
    <I18nProvider>
      <ConversationSummaryQa />
    </I18nProvider>
  </React.StrictMode>,
);
