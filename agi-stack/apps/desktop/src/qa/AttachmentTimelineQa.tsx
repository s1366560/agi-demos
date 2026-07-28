import '@radix-ui/themes/styles.css';
import React, { useMemo, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Button, Theme } from '@radix-ui/themes';

import { AgentTimeline } from '../features/chat/ChatTimeline';
import {
  mergeAgentSendAcknowledgement,
  mergeConversationTimelineItems,
} from '../features/chat/chatTimelineModel';
import { timelineMessageAttachments } from '../features/chat/messageAttachmentModel';
import { ToastProvider } from '../features/feedback/ToastCenter';
import { I18nProvider } from '../i18n';
import type { AgentTimelineItem, ConversationTimelineState } from '../types';
import '../styles.css';
import '../features/chat/ChatPanel.css';

declare global {
  var __attachmentTimelineQaRoot: Root | undefined;
}

type QaPhase = 'optimistic' | 'authoritative' | 'history' | 'malformed';

const QA_BASE_TIME_MS = Date.now();

const FILES = [
  {
    filename: 'roadmap.pdf',
    sandbox_path: '/workspace/uploads/roadmap.pdf',
    mime_type: 'application/pdf',
    size_bytes: 1536,
  },
  {
    filename: 'diagram.png',
    sandbox_path: '/workspace/uploads/diagram.png',
    mime_type: 'image/png',
    size_bytes: 2_621_440,
  },
];

const OPTIMISTIC: AgentTimelineItem = {
  id: 'optimistic-user-qa-attachment',
  type: 'user_message',
  role: 'user',
  message_id: 'qa-attachment-request',
  content: 'Review these attachments.',
  eventTimeUs: QA_BASE_TIME_MS * 1000,
  eventCounter: 0,
  timestamp: QA_BASE_TIME_MS,
  metadata: { optimistic: true, fileMetadata: FILES },
};

const AUTHORITATIVE: AgentTimelineItem = {
  id: 'history-user-qa-attachment',
  type: 'user_message',
  role: 'user',
  message_id: 'qa-attachment-execution',
  executionMessageId: 'qa-attachment-execution',
  content: 'Review these attachments.',
  eventTimeUs: QA_BASE_TIME_MS * 1000 + 1,
  eventCounter: 1,
  timestamp: QA_BASE_TIME_MS,
  metadata: { source: 'history', file_metadata: FILES },
  payload: { fileMetadata: FILES },
};

const MALFORMED: AgentTimelineItem = {
  id: 'history-user-qa-malformed-attachment',
  type: 'user_message',
  role: 'user',
  message_id: 'qa-malformed-attachment',
  content: 'Only the valid structured attachment should render.',
  eventTimeUs: QA_BASE_TIME_MS * 1000 + 2,
  eventCounter: 2,
  timestamp: QA_BASE_TIME_MS,
  metadata: {
    fileMetadata: [
      null,
      { filename: '', mime_type: 'application/pdf', size_bytes: 4 },
      { filename: 'missing-size.bin', mime_type: 'application/octet-stream' },
      { filename: 'invalid-size.bin', mime_type: 'application/octet-stream', size_bytes: -1 },
      {
        filename: 'opaque.custom',
        mime_type: 'application/x-opaque',
        size_bytes: 2048,
      },
    ],
  },
};

const ASSISTANT: AgentTimelineItem = {
  id: 'qa-attachment-assistant',
  type: 'assistant_message',
  role: 'assistant',
  message_id: 'qa-attachment-answer',
  content: 'The attachments are available to the conversation.',
  eventTimeUs: QA_BASE_TIME_MS * 1000 + 3,
  eventCounter: 3,
  timestamp: QA_BASE_TIME_MS,
};

function stateFor(items: AgentTimelineItem[]): ConversationTimelineState {
  return {
    conversationId: 'attachment-timeline-qa',
    items: [...items, ASSISTANT],
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

function AttachmentTimelineQa() {
  const [phase, setPhase] = useState<QaPhase>('optimistic');
  const [items, setItems] = useState<AgentTimelineItem[]>([OPTIMISTIC]);
  const state = useMemo(() => stateFor(items), [items]);
  const attachmentCount = useMemo(
    () => items.reduce((count, item) => count + timelineMessageAttachments(item).length, 0),
    [items],
  );

  const replaceWithAuthoritative = () => {
    const acknowledged = mergeAgentSendAcknowledgement(
      [OPTIMISTIC],
      'qa-attachment-request',
      'qa-attachment-execution',
    );
    setItems(mergeConversationTimelineItems(acknowledged, [AUTHORITATIVE]));
    setPhase('authoritative');
  };

  return (
    <main className="session-workspace-thread" style={{ minHeight: '100vh', padding: 24 }}>
      <section
        className="pane-shell chat-shell session-chat-narrative"
        style={{ maxWidth: 900, minHeight: 620, margin: '0 auto' }}
      >
        <header style={{ display: 'flex', flexWrap: 'wrap', gap: 10, padding: 16 }}>
          <Button
            type="button"
            onClick={() => {
              setItems([OPTIMISTIC]);
              setPhase('optimistic');
            }}
          >
            Optimistic echo
          </Button>
          <Button type="button" onClick={replaceWithAuthoritative}>
            Replace with live authority
          </Button>
          <Button
            type="button"
            onClick={() => {
              setItems([AUTHORITATIVE]);
              setPhase('history');
            }}
          >
            Reopen history
          </Button>
          <Button
            type="button"
            onClick={() => {
              setItems([MALFORMED]);
              setPhase('malformed');
            }}
          >
            Malformed metadata
          </Button>
          <span data-testid="attachment-qa-phase">{phase}</span>
          <span data-testid="attachment-qa-count">{attachmentCount} attachments</span>
          <span data-testid="attachment-qa-users">
            {items.filter((item) => item.role === 'user').length} user rows
          </span>
        </header>
        <div className="message-scroll">
          <div className="message-stack" data-testid="attachment-timeline">
            <AgentTimeline
              state={state}
              expandedItems={{}}
              onToggleItem={() => undefined}
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
  if (!globalThis.__attachmentTimelineQaRoot) {
    globalThis.__attachmentTimelineQaRoot = createRoot(container);
  }
  globalThis.__attachmentTimelineQaRoot.render(
    <React.StrictMode>
      <I18nProvider>
        <ToastProvider>
          <Theme appearance="dark" accentColor="cyan" grayColor="slate" radius="medium">
            <AttachmentTimelineQa />
          </Theme>
        </ToastProvider>
      </I18nProvider>
    </React.StrictMode>,
  );
}

mount();
