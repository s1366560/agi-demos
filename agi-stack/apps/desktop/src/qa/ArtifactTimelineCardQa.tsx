import '@radix-ui/themes/styles.css';
import { useMemo, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Button, Theme } from '@radix-ui/themes';

import { AgentTimeline } from '../features/chat/ChatTimeline';
import { I18nProvider } from '../i18n';
import type { AgentTimelineItem, ConversationTimelineState } from '../types';
import '../styles.css';
import '../features/chat/ChatPanel.css';

declare global {
  var __artifactTimelineCardQaRoot: Root | undefined;
}

type QaView = 'created' | 'ready-image' | 'error' | 'unsafe' | 'broken-image';
type QaAppearance = 'dark' | 'light';

function fixture(view: QaView): AgentTimelineItem {
  const origin = window.location.origin;
  const common = {
    id: `artifact-${view}`,
    type: 'artifact_created',
    artifactId: `artifact-${view}`,
    eventTimeUs: Date.now() * 1_000,
    eventCounter: 1,
    timestamp: Date.now(),
  };
  if (view === 'ready-image') {
    return {
      ...common,
      filename: 'memstack-preview.png',
      mimeType: 'image/png',
      category: 'image',
      sizeBytes: 28_672,
      sourceTool: 'export_artifact',
      url: `${origin}/icon-512.png`,
      previewUrl: `${origin}/icon-512.png`,
    };
  }
  if (view === 'broken-image') {
    return {
      ...common,
      filename: 'missing-preview.png',
      mimeType: 'image/png',
      category: 'image',
      sizeBytes: 900,
      url: `${origin}/missing-artifact-preview.png`,
      previewUrl: `${origin}/missing-artifact-preview.png`,
    };
  }
  if (view === 'error') {
    return {
      ...common,
      filename: 'broken-archive.zip',
      mimeType: 'application/zip',
      category: 'archive',
      sizeBytes: 19_200,
      url: 'https://artifacts.example/broken-archive.zip',
      error: 'Upload checksum mismatch',
    };
  }
  if (view === 'unsafe') {
    return {
      ...common,
      filename: 'unsafe-preview',
      mimeType: 'image/png',
      category: 'image',
      url: 'javascript:alert(1)',
    };
  }
  return {
    ...common,
    payload: {
      artifact_id: 'artifact-created',
      filename: 'release-notes.md',
      mime_type: 'text/markdown',
      category: 'document',
      size_bytes: 2_048,
      source_tool: 'export_artifact',
    },
  };
}

function timelineState(item: AgentTimelineItem): ConversationTimelineState {
  return {
    conversationId: 'artifact-card-qa',
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

function ArtifactTimelineCardQa() {
  const [view, setView] = useState<QaView>('created');
  const [appearance, setAppearance] = useState<QaAppearance>('dark');
  const [narrow, setNarrow] = useState(false);
  const state = useMemo(() => timelineState(fixture(view)), [view]);

  return (
    <Theme appearance={appearance} accentColor="cyan" grayColor="slate" radius="medium">
      <main className="session-workspace-thread" style={{ minHeight: '100vh', padding: 24 }}>
        <section
          className="pane-shell chat-shell session-chat-narrative"
          data-testid="artifact-card-qa-shell"
          style={{
            width: narrow ? 360 : undefined,
            maxWidth: narrow ? 360 : 900,
            minHeight: 520,
            margin: '0 auto',
          }}
        >
          <header style={{ display: 'flex', flexWrap: 'wrap', gap: 10, padding: 16 }}>
            <Button type="button" onClick={() => setView('created')}>
              Created
            </Button>
            <Button type="button" onClick={() => setView('ready-image')}>
              Ready image
            </Button>
            <Button type="button" onClick={() => setView('error')}>
              Error
            </Button>
            <Button type="button" onClick={() => setView('unsafe')}>
              Unsafe URL
            </Button>
            <Button type="button" onClick={() => setView('broken-image')}>
              Broken image
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
            <span data-testid="artifact-card-qa-view">{view}</span>
            <span data-testid="artifact-card-qa-appearance">{appearance}</span>
            <span data-testid="artifact-card-qa-width">{narrow ? 'narrow' : 'wide'}</span>
          </header>
          <div className="message-scroll">
            <div className="message-stack">
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
    </Theme>
  );
}

function mount() {
  const container = document.getElementById('root');
  if (!container) return;
  if (!globalThis.__artifactTimelineCardQaRoot) {
    globalThis.__artifactTimelineCardQaRoot = createRoot(container);
  }
  globalThis.__artifactTimelineCardQaRoot.render(
    <I18nProvider>
      <ArtifactTimelineCardQa />
    </I18nProvider>,
  );
}

mount();
