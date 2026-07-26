import '@radix-ui/themes/styles.css';
import React, { useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Button, Theme } from '@radix-ui/themes';

import { WorkPlanTimelineCard } from '../features/chat/WorkPlanTimelineCard';
import { I18nProvider } from '../i18n';
import type { AgentTimelineItem } from '../types';
import '../styles.css';
import '../features/chat/ChatPanel.css';

declare global {
  var __workPlanTimelineCardQaRoot: Root | undefined;
}

const timestamp = Date.now();

const directWorkPlan = {
  id: 'work-plan-direct-qa',
  type: 'work_plan',
  eventTimeUs: timestamp * 1000,
  eventCounter: 1,
  timestamp,
  status: 'completed',
  steps: [
    {
      step_number: 1,
      description: '**DESKTOP_WORK_PLAN_DIRECT_QA** — inspect the structured event.',
      expected_output: 'A validated structured plan card.',
    },
    {
      step_number: 2,
      description: 'Verify the completed plan remains readable after replay.',
      expected_output: '',
    },
  ],
} as AgentTimelineItem;

const payloadWorkPlan = {
  id: 'work-plan-payload-qa',
  type: 'work_plan',
  eventTimeUs: timestamp * 1000,
  eventCounter: 2,
  timestamp,
  payload: {
    status: 'running',
    total_steps: 3,
    current_step: 2,
    steps: [
      {
        step_number: 1,
        description: 'Read the authoritative session state.',
        expected_output: 'Current session facts.',
      },
      {
        step_number: 2,
        description: '**DESKTOP_WORK_PLAN_PAYLOAD_QA** — render the active step.',
        expected_output: 'An accessible current-step marker.',
      },
      {
        step_number: 3,
        description: 'Complete the focused validation.',
        expected_output: 'Browser and native evidence.',
      },
      {
        step_number: 'invalid',
        description: 'This malformed step must not render.',
      },
    ],
  },
} as AgentTimelineItem;

function WorkPlanTimelineCardQa() {
  const [directOpen, setDirectOpen] = useState(true);
  const [payloadOpen, setPayloadOpen] = useState(true);
  const [narrow, setNarrow] = useState(false);

  return (
    <Theme appearance="dark" accentColor="cyan" grayColor="slate" radius="medium">
      <main className="session-workspace-thread" style={{ minHeight: '100vh', padding: 24 }}>
        <section
          className="pane-shell chat-shell session-chat-narrative"
          data-testid="work-plan-qa-shell"
          style={{
            width: narrow ? 360 : undefined,
            maxWidth: narrow ? 360 : 900,
            minHeight: 600,
            margin: '0 auto',
            padding: 16,
          }}
        >
          <header style={{ display: 'flex', gap: 10, marginBottom: 16 }}>
            <Button type="button" onClick={() => setNarrow((current) => !current)}>
              Toggle narrow
            </Button>
            <span data-testid="work-plan-qa-width">{narrow ? 'narrow' : 'wide'}</span>
          </header>
          <div className="agent-timeline" data-testid="work-plan-qa-cards">
            <WorkPlanTimelineCard
              item={directWorkPlan}
              expanded={directOpen}
              onToggle={() => setDirectOpen((current) => !current)}
            />
            <WorkPlanTimelineCard
              item={payloadWorkPlan}
              expanded={payloadOpen}
              onToggle={() => setPayloadOpen((current) => !current)}
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
  if (!globalThis.__workPlanTimelineCardQaRoot) {
    globalThis.__workPlanTimelineCardQaRoot = createRoot(container);
  }
  globalThis.__workPlanTimelineCardQaRoot.render(
    <React.StrictMode>
      <I18nProvider>
        <WorkPlanTimelineCardQa />
      </I18nProvider>
    </React.StrictMode>,
  );
}

mount();
