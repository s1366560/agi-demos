import '@radix-ui/themes/styles.css';
import React, { useEffect } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Theme } from '@radix-ui/themes';
import {
  ChatBubbleIcon,
  CodeIcon,
  CubeIcon,
  FileTextIcon,
  GearIcon,
  GridIcon,
  HomeIcon,
  PlusIcon,
} from '@radix-ui/react-icons';

import { SessionWorkspace } from '../features/session/SessionWorkspace';
import type { SessionDetailViewModel } from '../features/session/sessionViewModel';
import { I18nProvider } from '../i18n';
import '../styles.css';
import './sessionSteeringQa.css';
import './sessionRecoveryQa.css';

declare global {
  var __sessionRecoveryQaRoot: Root | undefined;
}

const viewModel: SessionDetailViewModel = {
  id: 'conversation-desktop-recovery',
  title: 'Session interaction redesign',
  workspaceLabel: 'Desktop Client',
  status: 'disconnected',
  capabilityMode: 'code',
  executionMode: 'build',
  stage: 'verify',
  environmentLabel: 'Isolated worktree',
  branchLabel: 'codex/session-interaction-redesign',
  modelLabel: 'GPT-5.5',
  permissionLabel: 'Full access',
  elapsedLabel: '00:42:18',
  usageLabel: '$1.84',
  taskCount: 5,
  eventCount: 28,
  hasPlan: true,
  runId: 'run-desktop-session-42',
  runRevision: 7,
  error: null,
  lastHeartbeatAt: '2026-07-14T08:42:00Z',
};

function SessionRecoveryQa() {
  useEffect(() => {
    const frame = requestAnimationFrame(() => {
      document.querySelector<HTMLButtonElement>('.session-fork-recovery-trigger')?.click();
    });
    return () => cancelAnimationFrame(frame);
  }, []);

  return (
    <Theme appearance="dark" accentColor="cyan" grayColor="slate" radius="medium" scaling="95%">
      <div className="session-steering-qa-shell session-recovery-qa-shell">
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
            viewModel={viewModel}
            runActionPending={null}
            liveConnected={false}
            liveError="Runtime heartbeat expired"
            onRunAction={() => undefined}
            onOpenCanvas={() => undefined}
            onCloseCanvas={() => undefined}
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
            canvas={
              <div className="session-recovery-qa-canvas">
                <header>
                  <FileTextIcon />
                  <span>
                    <strong>Run evidence</strong>
                    <small>Last verified snapshot</small>
                  </span>
                </header>
                <dl>
                  <div><dt>Changes</dt><dd>4 files · +92 −18</dd></div>
                  <div><dt>Checks</dt><dd>109 UI · 71 Rust</dd></div>
                  <div><dt>Base</dt><dd>8f19c6e</dd></div>
                </dl>
              </div>
            }
          />
        </main>
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
