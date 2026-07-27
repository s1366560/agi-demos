import '@radix-ui/themes/styles.css';
import { useMemo, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Button, Theme } from '@radix-ui/themes';

import { AgentTimeline } from '../features/chat/ChatTimeline';
import { WorkspaceTranscriptMessage } from '../features/chat/ChatTranscript';
import { I18nProvider } from '../i18n';
import { ToastProvider } from '../features/feedback/ToastCenter';
import type { AgentTimelineItem, ConversationTimelineState, WorkspaceMessage } from '../types';
import '../styles.css';
import '../features/chat/ChatPanel.css';

declare global {
  var __assistantArtifactReferencesQaRoot: Root | undefined;
}

type QaView = 'timeline' | 'workspace' | 'artifact-only';
type QaAppearance = 'dark' | 'light';

const REFERENCES = [
  {
    object_key: 'exports/release-notes.pdf',
    url: 'https://artifacts.example/release-notes.pdf',
    mime_type: 'application/pdf',
    size_bytes: 2_621_440,
  },
  {
    url: 'http://127.0.0.1:8000/api/v1/artifacts/verification/download',
    size_bytes: 512,
  },
  {
    object_key: 'exports/release-notes.pdf',
    url: 'https://artifacts.example/release-notes.pdf',
    mime_type: 'application/pdf',
    size_bytes: 2_621_440,
  },
  {
    object_key: 'unsafe.html',
    url: 'javascript:alert(1)',
  },
];

function timelineState(artifactOnly: boolean): ConversationTimelineState {
  const item: AgentTimelineItem = {
    id: artifactOnly ? 'artifact-only-agent' : 'artifact-agent',
    type: 'assistant_message',
    role: 'assistant',
    content: artifactOnly ? '' : 'Delivery completed with structured artifacts.',
    artifacts: REFERENCES,
    metadata: {
      executionSummary: {
        step_count: 3,
        artifact_count: 2,
        call_count: 1,
      },
    },
    timestamp: Date.now(),
    eventTimeUs: Date.now() * 1_000,
    eventCounter: 1,
  };
  return {
    conversationId: 'artifact-reference-qa',
    items: [item],
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

const workspaceMessage: WorkspaceMessage = {
  id: 'workspace-artifact-agent',
  workspace_id: 'workspace-artifact-qa',
  sender_type: 'agent',
  content: 'Workspace delivery completed.',
  metadata: { artifacts: REFERENCES },
  created_at: new Date().toISOString(),
};

function AssistantArtifactReferencesQa() {
  const [view, setView] = useState<QaView>('timeline');
  const [appearance, setAppearance] = useState<QaAppearance>('dark');
  const [narrow, setNarrow] = useState(false);
  const state = useMemo(() => timelineState(view === 'artifact-only'), [view]);

  return (
    <Theme appearance={appearance} accentColor="cyan" grayColor="slate" radius="medium">
      <main className="session-workspace-thread" style={{ minHeight: '100vh', padding: 24 }}>
        <section
          className="pane-shell chat-shell session-chat-narrative"
          data-testid="artifact-reference-qa-shell"
          style={{
            width: narrow ? 360 : undefined,
            maxWidth: narrow ? 360 : 900,
            minHeight: 540,
            margin: '0 auto',
          }}
        >
          <header style={{ display: 'flex', flexWrap: 'wrap', gap: 10, padding: 16 }}>
            <Button type="button" onClick={() => setView('timeline')}>
              Agent timeline
            </Button>
            <Button type="button" onClick={() => setView('workspace')}>
              Workspace message
            </Button>
            <Button type="button" onClick={() => setView('artifact-only')}>
              Artifact-only
            </Button>
            <Button
              type="button"
              onClick={() =>
                setAppearance((current) => (current === 'dark' ? 'light' : 'dark'))
              }
            >
              Toggle theme
            </Button>
            <Button type="button" onClick={() => setNarrow((current) => !current)}>
              Toggle narrow
            </Button>
            <span data-testid="artifact-reference-qa-view">{view}</span>
            <span data-testid="artifact-reference-qa-appearance">{appearance}</span>
            <span data-testid="artifact-reference-qa-width">{narrow ? 'narrow' : 'wide'}</span>
          </header>
          <div className="message-scroll">
            <div className="message-stack">
              {view === 'workspace' ? (
                <WorkspaceTranscriptMessage message={workspaceMessage} />
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
  if (!globalThis.__assistantArtifactReferencesQaRoot) {
    globalThis.__assistantArtifactReferencesQaRoot = createRoot(container);
  }
  globalThis.__assistantArtifactReferencesQaRoot.render(
    <I18nProvider>
      <ToastProvider>
        <AssistantArtifactReferencesQa />
      </ToastProvider>
    </I18nProvider>,
  );
}

mount();
