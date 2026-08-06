import '@radix-ui/themes/styles.css';
import { useMemo, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Button, Theme } from '@radix-ui/themes';

import { AgentTimeline } from '../features/chat/ChatTimeline';
import { WorkspaceTranscriptMessage } from '../features/chat/ChatTranscript';
import { I18nProvider } from '../i18n';
import { ToastProvider } from '../features/feedback/ToastCenter';
import type {
  AgentTimelineItem,
  ConversationTimelineState,
  WorkspaceMessage,
} from '../types';
import '../styles/global.css';
import '../features/chat/ChatPanel.css';

declare global {
  var __forcedSkillMessageBadgeQaRoot: Root | undefined;
}

type QaAppearance = 'dark' | 'light';
type QaPhase = 'optimistic' | 'history';

const unsafeLookingSkill = '<img src=x onerror=alert(1)>';
const longSkill =
  'release-readiness-with-a-deliberately-long-structured-skill-name-for-layout-verification';

function timelineItems(phase: QaPhase): AgentTimelineItem[] {
  const metadataKey = phase === 'optimistic' ? 'forcedSkillName' : 'forced_skill_name';
  return [
    {
      id: 'normal-user-message',
      type: 'user_message',
      role: 'user',
      content: 'Normal',
      eventTimeUs: 1_000_000,
      eventCounter: 1,
    },
    {
      id: 'forced-user-message',
      type: 'user_message',
      role: 'user',
      content: 'Forced skill',
      eventTimeUs: 2_000_000,
      eventCounter: 2,
      metadata: { [metadataKey]: 'source-research', optimistic: phase === 'optimistic' },
    },
    {
      id: 'long-user-message',
      type: 'user_message',
      role: 'user',
      content: 'Long skill',
      eventTimeUs: 3_000_000,
      eventCounter: 3,
      metadata: { forcedSkillName: longSkill },
    },
    {
      id: 'unsafe-looking-user-message',
      type: 'user_message',
      role: 'user',
      content: 'Unsafe-looking',
      eventTimeUs: 4_000_000,
      eventCounter: 4,
      metadata: { forcedSkillName: unsafeLookingSkill },
    },
    {
      id: 'attachment-user-message',
      type: 'user_message',
      role: 'user',
      content: 'Attachment',
      eventTimeUs: 5_000_000,
      eventCounter: 5,
      metadata: {
        forcedSkillName: 'document-review',
        fileMetadata: [
          {
            filename: 'release-plan.pdf',
            sandbox_path: '/workspace/input/release-plan.pdf',
            mime_type: 'application/pdf',
            size_bytes: 24_576,
          },
        ],
      },
    },
  ];
}

function timelineState(phase: QaPhase): ConversationTimelineState {
  return {
    conversationId: 'forced-skill-badge-qa',
    items: timelineItems(phase),
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
  id: 'workspace-history-message',
  workspace_id: 'workspace-forced-skill-qa',
  sender_type: 'user',
  content: 'Workspace history',
  metadata: { forced_skill_name: 'workspace-audit' },
};

function ForcedSkillMessageBadgeQa() {
  const [appearance, setAppearance] = useState<QaAppearance>('dark');
  const [phase, setPhase] = useState<QaPhase>('optimistic');
  const [narrow, setNarrow] = useState(false);
  const state = useMemo(() => timelineState(phase), [phase]);

  return (
    <Theme appearance={appearance} accentColor="cyan" grayColor="slate" radius="medium">
      <main className="session-workspace-thread" style={{ minHeight: '100vh', padding: 24 }}>
        <section
          className="pane-shell chat-shell session-chat-narrative"
          data-testid="forced-skill-message-badge-qa-shell"
          style={{
            width: narrow ? 360 : undefined,
            maxWidth: narrow ? 360 : 900,
            minHeight: 660,
            margin: '0 auto',
          }}
        >
          <header style={{ display: 'flex', flexWrap: 'wrap', gap: 10, padding: 16 }}>
            <Button type="button" onClick={() => setPhase('optimistic')}>
              Optimistic
            </Button>
            <Button type="button" onClick={() => setPhase('history')}>
              History replacement
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
            <span data-testid="forced-skill-qa-phase">{phase}</span>
            <span data-testid="forced-skill-qa-appearance">{appearance}</span>
            <span data-testid="forced-skill-qa-width">{narrow ? 'narrow' : 'wide'}</span>
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
              <WorkspaceTranscriptMessage message={workspaceMessage} />
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
  if (!globalThis.__forcedSkillMessageBadgeQaRoot) {
    globalThis.__forcedSkillMessageBadgeQaRoot = createRoot(container);
  }
  globalThis.__forcedSkillMessageBadgeQaRoot.render(
    <I18nProvider>
      <ToastProvider>
        <ForcedSkillMessageBadgeQa />
      </ToastProvider>
    </I18nProvider>,
  );
}

mount();
