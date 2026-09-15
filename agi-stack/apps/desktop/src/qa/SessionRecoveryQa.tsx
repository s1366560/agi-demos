import '@radix-ui/themes/styles.css';
import React, { useEffect } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Theme } from '@radix-ui/themes';
import {
  ChatBubbleIcon,
  CodeIcon,
  CubeIcon,
  GearIcon,
  GridIcon,
  HomeIcon,
  PlusIcon,
} from '@radix-ui/react-icons';

import { SessionContextRail } from '../features/session/SessionContextRail';
import { SessionWorkspace } from '../features/session/SessionWorkspace';
import type { SessionDetailViewModel } from '../features/session/sessionViewModel';
import { I18nProvider } from '../i18n';
import '../styles/global.css';
import './sessionSteeringQa.css';
import './sessionRecoveryQa.css';

declare global {
  var __sessionRecoveryQaRoot: Root | undefined;
}

const viewModel: SessionDetailViewModel = {
  id: 'conversation-desktop-recovery',
  title: 'Session interaction redesign',
  summary: 'Restore the session shell and preserve the last authoritative checkpoint.',
  workspaceLabel: 'Desktop Client',
  status: 'disconnected',
  executionAuthorityKind: 'desktop_run',
  capabilityMode: 'code',
  executionMode: 'build',
  stage: 'verify',
  conversationMode: 'single_agent',
  participantCount: 2,
  linkedTaskId: 'workspace-task-session-redesign',
  environmentLabel: 'Isolated worktree',
  branchLabel: 'codex/session-interaction-redesign',
  modelLabel: 'GPT-5.5',
  permissionLabel: 'Full access',
  elapsedLabel: '00:42:18',
  usageLabel: '$1.84',
  taskCount: 5,
  eventCount: 28,
  hasPlan: true,
  planStatus: 'approved',
  artifactCount: 4,
  sourceCount: 0,
  verificationCount: 3,
  toolActivityCount: 12,
  failedToolActivityCount: 0,
  observedToolActivityCount: 12,
  observedFailedToolActivityCount: 0,
  runId: 'run-desktop-session-42',
  runRevision: 7,
  attemptNumber: null,
  workerAgentId: null,
  leaderAgentId: null,
  error: null,
  lastHeartbeatAt: '2026-07-14T08:42:00Z',
  runActions: ['reconnect', 'fork', 'cancel'],
};

// prototype mission-control refactor 2026-09 (phase 5a): optional harness
// states for header + context-rail screenshots. `?rail=1` mounts the right
// context rail next to the session workspace; `?status=` overrides the run
// status so the running / needs-input anatomies can be captured without a
// runtime. Default (no params) behavior is unchanged.
const qaParams = new URLSearchParams(window.location.search);
const qaStatus = qaParams.get('status');
const qaRail = qaParams.get('rail') === '1';

const railViewModel: SessionDetailViewModel =
  qaStatus === 'running'
    ? {
        ...viewModel,
        status: 'running',
        runActions: ['pause', 'cancel'],
        error: null,
      }
    : qaStatus === 'needs_input'
      ? {
          ...viewModel,
          status: 'needs_input',
          runActions: ['cancel'],
          error: null,
        }
      : qaStatus === 'ready_review'
        ? {
            ...viewModel,
            status: 'ready_review',
            runActions: ['approve', 'request_changes'],
            error: null,
          }
        : viewModel;

function SessionRecoveryQa() {
  useEffect(() => {
    if (qaRail) return;
    const frame = requestAnimationFrame(() => {
      document.querySelector<HTMLButtonElement>('.session-fork-recovery-trigger')?.click();
    });
    return () => cancelAnimationFrame(frame);
  }, []);

  return (
    <Theme appearance="dark" accentColor="cyan" grayColor="slate" radius="medium" scaling="95%">
      <div
        className={`session-steering-qa-shell session-recovery-qa-shell${qaRail ? ' has-context-rail' : ''}`}
      >
        <aside className="session-steering-qa-rail">
          <div className="session-steering-qa-brand"><CubeIcon /><strong>MemStack</strong></div>
          <button type="button"><PlusIcon /> New task</button>
          <nav>
            <button type="button"><HomeIcon /> Home</button>
            <button type="button"><GridIcon /> My work</button>
          </nav>
          <section>
            <span>WORKSPACE</span>
            <button type="button"><CubeIcon /> Desktop Client</button>
            <button type="button" className="selected">
              <ChatBubbleIcon /> Session interaction redesign
            </button>
          </section>
          <button type="button"><GearIcon /> Settings</button>
        </aside>
        <main>
          <SessionWorkspace
            viewModel={railViewModel}
            runActionPending={null}
            liveConnected={qaStatus === 'running'}
            liveError={qaStatus === 'running' ? null : 'Runtime heartbeat expired'}
            onRunAction={() => undefined}
            onOpenCanvas={() => undefined}
            thread={
              <div className="session-recovery-qa-thread">
                <article className="from-user">
                  <b>You</b>
                  <p>Rework the session detail experience and verify the recovery boundary.</p>
                </article>
                <article className="from-agent">
                  <b>Agent</b>
                  <p>
                    The implementation and checks completed, but the runtime heartbeat was lost
                    before review.
                  </p>
                </article>
                <section>
                  <CodeIcon />
                  <span>
                    <strong>Verification interrupted</strong>
                    <small>Last confirmed at revision r7</small>
                  </span>
                </section>
              </div>
            }
          />
        </main>
        {qaRail ? (
          <div className="session-recovery-qa-context-rail">
            <SessionContextRail
              viewModel={railViewModel}
              runActionPending={null}
              onRunAction={() => undefined}
              onOpenCanvas={() => undefined}
            />
          </div>
        ) : null}
      </div>
    </Theme>
  );
}

const container = document.getElementById('root');
if (!container) throw new Error('Missing root element');
globalThis.__sessionRecoveryQaRoot ??= createRoot(container);
globalThis.__sessionRecoveryQaRoot.render(
  <I18nProvider>
    <SessionRecoveryQa />
  </I18nProvider>,
);
