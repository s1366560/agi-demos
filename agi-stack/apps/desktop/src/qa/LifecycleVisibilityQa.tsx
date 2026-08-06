import '@radix-ui/themes/styles.css';
import React, { useMemo, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Button, Theme } from '@radix-ui/themes';

import { AgentTimeline } from '../features/chat/ChatTimeline';
import { timelineItemsForDisplay } from '../features/chat/chatTimelineModel';
import { isTimelineItemInitiallyExpanded } from '../features/chat/chatTimelinePresentation';
import { ToastProvider } from '../features/feedback/ToastCenter';
import { I18nProvider } from '../i18n';
import type { AgentTimelineItem, ConversationTimelineState } from '../types';
import '../styles/global.css';
import '../features/chat/ChatPanel.css';

declare global {
  var __lifecycleVisibilityQaRoot: Root | undefined;
}

const L4_AGENT_STATE_TYPES = [
  'agent_spawned',
  'agent_message_sent',
  'agent_message_received',
  'agent_completed',
  'agent_stopped',
] as const;

function timelineItem(
  id: string,
  type: string,
  eventCounter: number,
  content?: string,
): AgentTimelineItem {
  const timestamp = Date.now() + eventCounter;
  return {
    id,
    type,
    eventCounter,
    eventTimeUs: timestamp * 1000,
    timestamp,
    ...(content ? { content } : {}),
  } as AgentTimelineItem;
}

function lifecycleBurst(prefix: string, startCounter: number): AgentTimelineItem[] {
  return L4_AGENT_STATE_TYPES.map((type, index) => ({
    ...timelineItem(`${prefix}-${type}`, type, startCounter + index),
    payload: {
      agent_name: 'General Agent',
      from_agent_name: 'General Agent',
      to_agent_name: 'General Agent',
      message_preview: 'Internal lifecycle state',
    },
  }));
}

const HISTORY_ITEMS: AgentTimelineItem[] = [
  {
    ...timelineItem('qa-user', 'user_message', 1, 'hi'),
    role: 'user',
  },
  ...lifecycleBurst('history', 2),
  {
    ...timelineItem(
      'qa-assistant',
      'assistant_message',
      7,
      '你好！有什么可以帮你的吗？',
    ),
    role: 'assistant',
  },
];

function timelineState(items: AgentTimelineItem[]): ConversationTimelineState {
  return {
    conversationId: 'lifecycle-visibility-qa',
    items,
    approvalRequests: [],
    artifactVersions: [],
    artifactDeliveries: [],
    toolInvocations: [],
    loading: false,
    loadingEarlier: false,
    error: null,
    hasMore: false,
    firstCursor: null,
    lastCursor: null,
  };
}

function LifecycleVisibilityQa() {
  const [items, setItems] = useState(HISTORY_ITEMS);
  const [expandedItems, setExpandedItems] = useState<Record<string, boolean>>({});
  const visibleItems = useMemo(() => timelineItemsForDisplay(items), [items]);
  const visibleMessageIds = visibleItems
    .filter((item) => item.type === 'user_message' || item.type === 'assistant_message')
    .map((item) => item.id);
  const state = useMemo(() => timelineState(items), [items]);

  return (
    <main className="session-workspace-thread" style={{ minHeight: '100vh', padding: 24 }}>
      <section
        className="pane-shell chat-shell session-chat-narrative"
        style={{ maxWidth: 860, minHeight: 620, margin: '0 auto' }}
      >
        <header style={{ display: 'flex', gap: 12, alignItems: 'center', padding: 16 }}>
          <Button
            type="button"
            onClick={() => {
              setItems((current) => [
                ...current,
                ...lifecycleBurst(`live-${current.length}`, current.length + 1),
              ]);
            }}
          >
            Replay live lifecycle burst
          </Button>
          <span data-testid="authoritative-count">{items.length} authoritative events</span>
          <span data-testid="visible-message-order">{visibleMessageIds.join(' → ')}</span>
        </header>
        <div className="message-scroll">
          <div className="message-stack" data-testid="lifecycle-visible-timeline">
            <AgentTimeline
              state={state}
              expandedItems={expandedItems}
              onToggleItem={(item) =>
                setExpandedItems((current) => ({
                  ...current,
                  [item.id]: !(
                    current[item.id] ?? isTimelineItemInitiallyExpanded(item)
                  ),
                }))
              }
              onLoadEarlier={() => undefined}
              onShowEarlier={() => undefined}
              earlierRenderAllowance={0}
              onRetry={() => undefined}
              onRespondToHitl={() => Promise.resolve()}
              respondableHitlRequestIds={[]}
              activityPresence="recorded"
            />
          </div>
        </div>
      </section>
    </main>
  );
}

function mount() {
  const container = document.getElementById('root');
  if (!container) return;
  if (!globalThis.__lifecycleVisibilityQaRoot) {
    globalThis.__lifecycleVisibilityQaRoot = createRoot(container);
  }
  globalThis.__lifecycleVisibilityQaRoot.render(
    <React.StrictMode>
      <I18nProvider>
        <ToastProvider>
          <Theme appearance="dark" accentColor="cyan" grayColor="slate" radius="medium">
            <LifecycleVisibilityQa />
          </Theme>
        </ToastProvider>
      </I18nProvider>
    </React.StrictMode>,
  );
}

mount();
