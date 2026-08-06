import '@radix-ui/themes/styles.css';
import React, { useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Button, Theme } from '@radix-ui/themes';

import { ThoughtTimelineCard } from '../features/chat/ThoughtTimelineCard';
import { I18nProvider } from '../i18n';
import type { AgentTimelineItem } from '../types';
import '../styles/global.css';
import '../features/chat/ChatPanel.css';

declare global {
  var __thoughtTimelineCardQaRoot: Root | undefined;
}

const timestamp = Date.now();

const completedThought = {
  id: 'thought-completed-qa',
  type: 'thought',
  content:
    'DESKTOP_THOUGHT_COMPLETED_QA\n\nInspect the structured event, preserve replay identity, and verify the final response.',
  timestamp,
  eventTimeUs: timestamp * 1000,
  eventCounter: 1,
} as AgentTimelineItem;

const streamingThought = {
  id: 'thought-streaming-qa',
  type: 'thought',
  content:
    'DESKTOP_THOUGHT_STREAMING_QA\n\nReviewing the current timeline and checking shared rendering behavior.',
  timestamp,
  eventTimeUs: timestamp * 1000,
  eventCounter: 2,
  metadata: { streaming: true },
} as AgentTimelineItem;

const emptyStreamingThought = {
  id: 'thought-empty-streaming-qa',
  type: 'thought',
  content: '',
  timestamp,
  eventTimeUs: timestamp * 1000,
  eventCounter: 3,
  metadata: { streaming: true },
} as AgentTimelineItem;

function ThoughtTimelineCardQa() {
  const [completedOpen, setCompletedOpen] = useState(true);
  const [streamingOpen, setStreamingOpen] = useState(true);
  const [emptyOpen, setEmptyOpen] = useState(true);
  const [narrow, setNarrow] = useState(false);

  return (
    <Theme appearance="dark" accentColor="cyan" grayColor="slate" radius="medium">
      <main className="session-workspace-thread" style={{ minHeight: '100vh', padding: 24 }}>
        <section
          className="pane-shell chat-shell session-chat-narrative"
          data-testid="thought-qa-shell"
          style={{
            width: narrow ? 360 : undefined,
            maxWidth: narrow ? 360 : 900,
            minHeight: 560,
            margin: '0 auto',
            padding: 16,
          }}
        >
          <header style={{ display: 'flex', gap: 10, marginBottom: 16 }}>
            <Button type="button" onClick={() => setNarrow((current) => !current)}>
              Toggle narrow
            </Button>
            <span data-testid="thought-qa-width">{narrow ? 'narrow' : 'wide'}</span>
          </header>
          <div className="agent-timeline" data-testid="thought-qa-cards">
            <ThoughtTimelineCard
              item={completedThought}
              expanded={completedOpen}
              onToggle={() => setCompletedOpen((current) => !current)}
            />
            <ThoughtTimelineCard
              item={streamingThought}
              expanded={streamingOpen}
              onToggle={() => setStreamingOpen((current) => !current)}
            />
            <ThoughtTimelineCard
              item={emptyStreamingThought}
              expanded={emptyOpen}
              onToggle={() => setEmptyOpen((current) => !current)}
            />
          </div>
        </section>
      </main>
    </Theme>
  );
}

function mount() {
  const container = document.getElementById('root');
  if (!container) return;
  if (!globalThis.__thoughtTimelineCardQaRoot) {
    globalThis.__thoughtTimelineCardQaRoot = createRoot(container);
  }
  globalThis.__thoughtTimelineCardQaRoot.render(
    <React.StrictMode>
      <I18nProvider>
        <ThoughtTimelineCardQa />
      </I18nProvider>
    </React.StrictMode>,
  );
}

mount();
