import '@radix-ui/themes/styles.css';
import React, { useMemo, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Button, Theme } from '@radix-ui/themes';

import { AgentTimeline } from '../features/chat/ChatTimeline';
import { isTimelineItemInitiallyExpanded } from '../features/chat/chatTimelinePresentation';
import { aggregateStructuredToolSources } from '../features/chat/toolSourceAggregationModel';
import { ToastProvider } from '../features/feedback/ToastCenter';
import { I18nProvider } from '../i18n';
import type { AgentTimelineItem, ConversationTimelineState } from '../types';
import '../styles/global.css';
import '../features/chat/ChatPanel.css';

declare global {
  var __aggregatedSourcesQaRoot: Root | undefined;
}

type QaMode = 'multiple' | 'single' | 'unmarked';

function timelineItem(
  id: string,
  type: string,
  eventCounter: number,
  details: Partial<AgentTimelineItem> = {},
): AgentTimelineItem {
  const timestamp = Date.now() + eventCounter;
  return {
    id,
    type,
    eventCounter,
    eventTimeUs: timestamp * 1000,
    timestamp,
    ...details,
  };
}

const USER_ITEM = timelineItem('qa-source-user', 'user_message', 1, {
  role: 'user',
  content: 'Compare the structured sources.',
});

const FIRST_CALL = [
  timelineItem('qa-source-act-1', 'act', 2, {
    toolName: 'opaque-provider-a',
    display: { kind: 'search', title: 'Search documentation' },
  }),
  timelineItem('qa-source-observe-1', 'observe', 3, {
    toolName: 'opaque-provider-a',
    toolOutput: {
      results: [
        {
          title: 'OpenAI documentation',
          url: 'https://www.openai.com/docs/',
          snippet: 'Primary product documentation.',
          score: 0.94,
        },
        {
          title: 'Protocol guide',
          url: 'https://example.com/protocol',
          snippet: 'A stable protocol reference.',
        },
      ],
    },
  }),
];

const SECOND_CALL = [
  timelineItem('qa-source-act-2', 'act', 4, {
    toolName: 'opaque-provider-b',
    display: { kind: 'search', title: 'Search project knowledge' },
  }),
  timelineItem('qa-source-observe-2', 'observe', 5, {
    toolName: 'opaque-provider-b',
    toolOutput: {
      sources: [
        {
          title: 'OpenAI documentation duplicate',
          url: 'https://openai.com/docs#overview',
        },
        {
          title: 'Workspace handbook',
          source_type: 'rag',
          provider_label: 'Project knowledge',
          snippet: 'Internal guidance selected by structured metadata.',
        },
      ],
    },
  }),
];

const UNMARKED_CALLS = [
  timelineItem('qa-unmarked-act-1', 'act', 2, {
    toolName: 'search_keyword_is_not_authority',
  }),
  timelineItem('qa-unmarked-observe-1', 'observe', 3, {
    toolOutput: {
      results: [{ title: 'Unmarked result', url: 'https://example.com/unmarked-a' }],
    },
  }),
  timelineItem('qa-unmarked-act-2', 'act', 4, {
    toolName: 'rag_keyword_is_not_authority',
  }),
  timelineItem('qa-unmarked-observe-2', 'observe', 5, {
    toolOutput: {
      results: [{ title: 'Unmarked result two', url: 'https://example.com/unmarked-b' }],
    },
  }),
];

const ASSISTANT_ITEM = timelineItem('qa-source-assistant', 'assistant_message', 6, {
  role: 'assistant',
  content: 'The structured source comparison is ready.',
});

function itemsForMode(mode: QaMode): AgentTimelineItem[] {
  if (mode === 'single') return [USER_ITEM, ...FIRST_CALL, ASSISTANT_ITEM];
  if (mode === 'unmarked') return [USER_ITEM, ...UNMARKED_CALLS, ASSISTANT_ITEM];
  return [USER_ITEM, ...FIRST_CALL, ...SECOND_CALL, ASSISTANT_ITEM];
}

function timelineState(items: AgentTimelineItem[]): ConversationTimelineState {
  return {
    conversationId: 'aggregated-sources-qa',
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

function AggregatedSourcesQa() {
  const [mode, setMode] = useState<QaMode>('multiple');
  const [expandedItems, setExpandedItems] = useState<Record<string, boolean>>({});
  const items = useMemo(() => itemsForMode(mode), [mode]);
  const aggregation = useMemo(() => aggregateStructuredToolSources(items), [items]);
  const state = useMemo(() => timelineState(items), [items]);

  return (
    <main className="session-workspace-thread" style={{ minHeight: '100vh', padding: 24 }}>
      <section
        className="pane-shell chat-shell session-chat-narrative"
        style={{ maxWidth: 900, minHeight: 680, margin: '0 auto' }}
      >
        <header style={{ display: 'flex', flexWrap: 'wrap', gap: 10, padding: 16 }}>
          <Button type="button" onClick={() => setMode('multiple')}>
            Multiple structured calls
          </Button>
          <Button type="button" onClick={() => setMode('single')}>
            Single structured call
          </Button>
          <Button type="button" onClick={() => setMode('unmarked')}>
            Unmarked result arrays
          </Button>
          <span data-testid="source-qa-authority">{items.length} authoritative events</span>
          <span data-testid="source-qa-model">
            {aggregation
              ? `${aggregation.sourceCount} sources from ${aggregation.callCount} calls`
              : 'no aggregation'}
          </span>
        </header>
        <div className="message-scroll">
          <div className="message-stack" data-testid="aggregated-sources-timeline">
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
  if (!globalThis.__aggregatedSourcesQaRoot) {
    globalThis.__aggregatedSourcesQaRoot = createRoot(container);
  }
  globalThis.__aggregatedSourcesQaRoot.render(
    <React.StrictMode>
      <I18nProvider>
        <ToastProvider>
          <Theme appearance="dark" accentColor="cyan" grayColor="slate" radius="medium">
            <AggregatedSourcesQa />
          </Theme>
        </ToastProvider>
      </I18nProvider>
    </React.StrictMode>,
  );
}

mount();
