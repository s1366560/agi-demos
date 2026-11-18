import '@radix-ui/themes/styles.css';
import '../src/styles/global.css';
import '../src/features/session/SessionWorkspace.css';
import React, { Profiler } from 'react';
import { createRoot } from 'react-dom/client';
import { Theme } from '@radix-ui/themes';

import * as timeline from '../src/features/chat/appTimelineEventModel';
import { ChatPanel } from '../src/features/chat/ChatPanel';
import { ToastProvider } from '../src/features/feedback/ToastCenter';
import { I18nProvider } from '../src/i18n';
import { DesktopRendererAuthorityContextV2 } from '../src/plugins/desktopRendererAuthorityStateV2';
import { unavailableVoiceSessionOperationsQa } from '../src/qa/voiceSessionOperationsQa';
import type { AgentTimelineItem } from '../src/types';

const noop = () => {};
const emptyList = async () => [];
const api = {
  listWorkspaceAgents: emptyList,
  listManagedAgents: emptyList,
  listManagedSkills: emptyList,
  createPromptTemplate: async () => {
    throw new Error('Unavailable in transcript QA');
  },
  deletePromptTemplate: async () => {},
  listManagedSubAgents: emptyList,
  listMarketplacePlugins: emptyList,
  listPromptTemplates: emptyList,
};
const authority = {
  status: 'ready' as const,
  navigationArtifactIds: [],
  navigationDiscoveryRouteIds: [],
  navigationRouteIds: [],
  routeArtifactIds: [],
  routeArtifacts: [],
  routeIds: [],
  slotDefinitions: [],
  uiSlotArtifactIds: [],
  shortcutIds: ['conversation-search'],
};
const root = createRoot(document.getElementById('root')!);
const epoch = 1_800_000_000_000;
function item(n: number, type: string, extra: Partial<AgentTimelineItem>): AgentTimelineItem {
  return {
    id: 'item-' + n,
    eventCounter: n,
    eventTimeUs: (epoch + n) * 1000,
    timestamp: epoch + n,
    type,
    ...extra,
  };
}
function history(count: number, start = 0) {
  return Array.from({ length: count }, (_, i) => {
    const n = i + start;
    const user = n % 2 === 0;
    return item(n, user ? 'user_message' : 'assistant_message', {
      role: user ? 'user' : 'assistant',
      content: 'History entry ' + n + ' with some stable text.',
      ...(user
        ? {}
        : {
            content:
              'Paragraph ' + n + ' before the reading anchor.\n\nReference paragraph ' + n + '.',
          }),
    });
  });
}

let items = history(48);
let eventSequence = 200;
let conversationId = 'thread';
let catalogLoaded = false;
let hasMore = false;
let loadingEarlier = false;
const stats = { commits: 0, renderMs: 0 };
const transcript = {
  reset(count = 48, more = false, scope = 'thread') {
    conversationId = scope;
    items = history(count);
    hasMore = more;
    loadingEarlier = false;
    render();
  },
  event(type: string, data: Record<string, unknown>) {
    const counter = ++eventSequence;
    items = timeline.mergeLiveTimelineEvent(items, {
      type,
      data,
      conversation_id: conversationId,
      message_id: 'replay',
      counter,
      time_us: (epoch + counter) * 1000,
    });
    render();
  },
  append(type: string, extra: Partial<AgentTimelineItem>) {
    const n = (items.at(-1)?.eventCounter ?? 0) + 1;
    items = [...items, item(n, type, extra)];
    render();
  },
  edit(id: string, extra: Partial<AgentTimelineItem>) {
    items = items.map((previous) => (previous.id === id ? { ...previous, ...extra } : previous));
    render();
  },
  promoteDraft() {
    const persisted = item(++eventSequence, 'assistant_message', {
      id: 'persisted-response',
      role: 'assistant',
      message_id: 'replay',
      content: 'Final paragraph',
    });
    // The baseline client called mergeTimelineItems for history pages.
    const mergePage = timeline.mergeTimelineHistory ?? timeline.mergeTimelineItems;
    items = mergePage([persisted], items);
    render();
  },
  refreshConversationCatalog() {
    catalogLoaded = true;
    render();
  },
  finishPage() {
    if (!loadingEarlier) throw new Error('Expected a history load initiated by the viewport');
    items = [...history(16, -16), ...items];
    hasMore = false;
    loadingEarlier = false;
    render();
  },
  get loadingEarlier() {
    return loadingEarlier;
  },
  stats,
};
const shellProps = {
  api,
  messages: [],
  agentTaskSignals: [],
  sessionTitle: 'Review',
  scopeLabel: 'Project',
  activityPresence: 'live' as const,
  activityStructuredEvidence: null,
  composerVariant: 'session' as const,
  sending: false,
  disabledReason: null,
  activeWorkflowTarget: 'plan' as const,
  runInputDelivery: null,
  runInputDeliveryOptions: [],
  runInputs: [],
  runInputsLoading: false,
  runInputsError: null,
  promotingRunInputId: null,
  runInputAuthorityRunId: null,
  references: [],
  onRunInputDeliveryChange: noop,
  onPromoteRunInput: noop,
  onRemoveReference: noop,
  onSend: noop,
  onRefresh: noop,
  onLoadEarlier: () => {
    loadingEarlier = true;
    render();
  },
  onRespondToHitl: async () => {},
  respondableHitlRequestIds: [],
  onWorkflowSelect: noop,
  onOpenCommands: noop,
  imagePreviewClient: null,
  voiceSessionOperations: unavailableVoiceSessionOperationsQa,
};
function render() {
  root.render(
    <Theme appearance="light">
      <I18nProvider>
        <ToastProvider>
          <DesktopRendererAuthorityContextV2.Provider value={authority}>
            <main className="session-workspace-thread" style={{ height: '100vh' }}>
              <div className="desktop-conversation-surface">
                <Profiler
                  id="panel"
                  onRender={(_id, _phase, ms) => {
                    stats.commits++;
                    stats.renderMs += ms;
                  }}
                >
                  <ChatPanel
                    {...shellProps}
                    composerResetKey={conversationId}
                    selectedConversationId={conversationId}
                    conversations={catalogLoaded ? [{
                      id: conversationId, tenant_id: 'tenant', project_id: 'project',
                      user_id: 'reader', title: 'Review', status: 'active',
                      message_count: items.length, created_at: new Date(epoch).toISOString(),
                    }] : []}
                    timelineState={{
                      conversationId,
                      items,
                      approvalRequests: [],
                      artifactVersions: [],
                      artifactDeliveries: [],
                      toolInvocations: [],
                      loading: false,
                      loadingEarlier,
                      error: null,
                      hasMore,
                      firstCursor: null,
                      lastCursor: null,
                    }}
                  />
                </Profiler>
              </div>
            </main>
          </DesktopRendererAuthorityContextV2.Provider>
        </ToastProvider>
      </I18nProvider>
    </Theme>,
  );
}
Object.assign(window, { transcript });
render();
