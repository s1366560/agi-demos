import '@radix-ui/themes/styles.css';
import { useMemo, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Button, Theme } from '@radix-ui/themes';

import { AgentTimeline } from '../features/chat/ChatTimeline';
import { WorkspaceTranscriptMessage } from '../features/chat/ChatTranscript';
import { I18nProvider } from '../i18n';
import { ToastProvider } from '../features/feedback/ToastCenter';
import type { AgentTimelineItem, ConversationTimelineState, WorkspaceMessage } from '../types';
import '../styles/global.css';
import '../features/chat/ChatPanel.css';

declare global {
  var __markdownArtifactImageQaRoot: Root | undefined;
}

type QaAppearance = 'dark' | 'light';
type QaView = 'live-pending' | 'live-ready' | 'history' | 'unsafe' | 'non-image';

const sourcePath = '/workspace/output/routing-policy.png';
const markdown = `Generated image:\n\n![Routing policy](${sourcePath})`;

function artifactFor(view: QaView): AgentTimelineItem | null {
  if (view === 'live-pending' || view === 'history') return null;
  const url =
    view === 'unsafe'
      ? 'javascript:alert(1)'
      : `${window.location.origin}/qa/routing-policy-implementation-before.png`;
  return {
    id: `artifact-${view}`,
    type: 'artifact_ready',
    eventTimeUs: 2_000_000,
    eventCounter: 2,
    payload: {
      artifact_id: `artifact-${view}`,
      filename: 'routing-policy.png',
      source_path: sourcePath,
      mime_type: view === 'non-image' ? 'application/pdf' : 'image/png',
      size_bytes: 431_212,
      url,
      preview_url: url,
    },
  };
}

function timelineState(view: QaView): ConversationTimelineState {
  const item = artifactFor(view);
  const items: AgentTimelineItem[] = [
    {
      id: `assistant-${view}`,
      type: 'assistant_message',
      role: 'assistant',
      content: markdown,
      eventTimeUs: 1_000_000,
      eventCounter: 1,
    },
    ...(item ? [item] : []),
  ];
  return {
    conversationId: 'markdown-artifact-image-qa',
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

function historyMessage(): WorkspaceMessage {
  const url = `${window.location.origin}/qa/routing-policy-implementation-before.png`;
  return {
    id: 'workspace-history-image',
    workspace_id: 'markdown-artifact-image-qa',
    sender_type: 'agent',
    content: markdown,
    created_at: '2026-07-26T10:00:00Z',
    metadata: {
      artifacts: [
        {
          artifact_id: 'history-image',
          source_path: '~/output/routing-policy.png',
          mime_type: 'image/png',
          url,
          preview_url: url,
        },
      ],
    },
  };
}

function MarkdownArtifactImageQa() {
  const [appearance, setAppearance] = useState<QaAppearance>('dark');
  const [view, setView] = useState<QaView>('live-pending');
  const [narrow, setNarrow] = useState(false);
  const state = useMemo(() => timelineState(view), [view]);

  return (
    <Theme appearance={appearance} accentColor="cyan" grayColor="slate" radius="medium">
      <main className="session-workspace-thread" style={{ minHeight: '100vh', padding: 24 }}>
        <section
          className="pane-shell chat-shell session-chat-narrative"
          data-testid="markdown-artifact-image-qa-shell"
          style={{
            width: narrow ? 360 : undefined,
            maxWidth: narrow ? 360 : 900,
            minHeight: 660,
            margin: '0 auto',
          }}
        >
          <header style={{ display: 'flex', flexWrap: 'wrap', gap: 10, padding: 16 }}>
            <Button type="button" onClick={() => setView('live-pending')}>
              Live pending
            </Button>
            <Button type="button" onClick={() => setView('live-ready')}>
              Live ready
            </Button>
            <Button type="button" onClick={() => setView('history')}>
              History replay
            </Button>
            <Button type="button" onClick={() => setView('unsafe')}>
              Unsafe URL
            </Button>
            <Button type="button" onClick={() => setView('non-image')}>
              Non-image MIME
            </Button>
            <Button
              type="button"
              onClick={() => setAppearance((current) => (current === 'dark' ? 'light' : 'dark'))}
            >
              Toggle theme
            </Button>
            <Button type="button" onClick={() => setNarrow((current) => !current)}>
              Toggle narrow
            </Button>
            <span data-testid="markdown-image-qa-view">{view}</span>
            <span data-testid="markdown-image-qa-appearance">{appearance}</span>
            <span data-testid="markdown-image-qa-width">{narrow ? 'narrow' : 'wide'}</span>
          </header>
          <div className="message-scroll">
            <div className="message-stack">
              {view === 'history' ? (
                <WorkspaceTranscriptMessage message={historyMessage()} />
              ) : (
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
              )}
            </div>
          </div>
        </section>
      </main>
    </Theme>
  );
}

function mount() {
  const container = document.getElementById('root');
  if (!container) return;
  if (!globalThis.__markdownArtifactImageQaRoot) {
    globalThis.__markdownArtifactImageQaRoot = createRoot(container);
  }
  globalThis.__markdownArtifactImageQaRoot.render(
    <I18nProvider>
      <ToastProvider>
        <MarkdownArtifactImageQa />
      </ToastProvider>
    </I18nProvider>,
  );
}

mount();
