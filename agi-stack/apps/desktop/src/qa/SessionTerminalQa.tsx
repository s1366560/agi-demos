import '@radix-ui/themes/styles.css';
import React, { useState } from 'react';
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

import { SessionTerminalCanvas } from '../features/session/SessionTerminalCanvas';
import type { TerminalBindingState } from '../features/session/sessionTerminalModel';
import { I18nProvider } from '../i18n';
import type { DesktopRun, TerminalServiceResponse } from '../types';
import '../styles.css';
import './sessionSteeringQa.css';
import './sessionTerminalQa.css';

declare global {
  var __sessionTerminalQaRoot: Root | undefined;
}

const run: DesktopRun = {
  id: 'run-desktop-session-42',
  conversation_id: 'conversation-desktop-session',
  project_id: 'local-project',
  plan_version_id: 'plan-version-7',
  idempotency_key: 'run-key-42',
  message_id: 'run-message-42',
  request_message: 'Implement authoritative terminal lifecycle',
  status: 'running',
  revision: 7,
  permission_profile: 'full_access',
  authorization_snapshot: {},
  created_at: '2026-07-13T10:00:00Z',
  updated_at: '2026-07-13T10:20:00Z',
  environment: {
    id: 'environment-worktree-42',
    kind: 'worktree',
    label: 'Isolated worktree',
    workspace_path: '/workspace/.agistack-worktrees/desktop-session-42',
    repository_root: '/workspace/memstack',
    branch: 'agistack/desktop-session-42',
    base_commit: '8f19c6e',
    source_run_id: null,
    created_at: '2026-07-13T10:00:00Z',
  },
};

const terminal: TerminalServiceResponse = {
  success: true,
  session_id: 'local-terminal-7f54cc1c',
  project_id: run.project_id,
  conversation_id: run.conversation_id,
  run_id: run.id,
  run_revision: run.revision,
  environment_id: run.environment?.id,
  cwd: run.environment?.workspace_path,
  environment: run.environment,
  resumable: false,
  created_at: '2026-07-13T10:20:00Z',
  expires_at: '2026-07-13T10:20:30Z',
};

const lines = [
  '[connected] session=local-terminal-7f54cc1c 120x32\r\n',
  '$ cargo test terminal_grant_is_single_use\r\n',
  'running 1 test\r\n',
  'test terminal_grant_is_single_use ... ok\r\n',
  '\r\n',
  'test result: ok. 1 passed; 0 failed\r\n',
  '$ ',
];

function SessionTerminalQa() {
  const [binding, setBinding] = useState<TerminalBindingState>('connected');
  return (
    <Theme appearance="dark" accentColor="cyan" grayColor="slate" radius="medium" scaling="95%">
      <div className="session-steering-qa-shell">
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
            <button type="button" className="selected"><ChatBubbleIcon /> Terminal authority</button>
          </section>
          <button type="button"><GearIcon /> Settings</button>
        </aside>
        <main>
          <header className="session-steering-qa-titlebar">
            <div><CodeIcon /><span><strong>Terminal authority</strong><small>Code · Build · Running</small></span></div>
            <dl>
              <div><dt>Environment</dt><dd>Worktree</dd></div>
              <div><dt>Branch</dt><dd>agistack/desktop-session-42</dd></div>
              <div><dt>Run</dt><dd>run-desk · r7</dd></div>
            </dl>
          </header>
          <div className="session-terminal-qa-content">
            <section className="session-terminal-qa-thread">
              <header><strong>Conversation</strong><small>Current run narrative</small></header>
              <article><b>You</b><p>Bind every shell to the exact approved Run and revision.</p></article>
              <article><b>agent</b><p>The terminal grant is active in the isolated worktree.</p></article>
            </section>
            <main className="session-terminal-qa-canvas">
              <nav aria-label="Terminal QA states">
                {(['connected', 'stale', 'closed', 'error'] as TerminalBindingState[]).map(
                  (state) => (
                    <button
                      type="button"
                      className={binding === state ? 'selected' : ''}
                      onClick={() => setBinding(state)}
                      key={state}
                    >
                      {state}
                    </button>
                  ),
                )}
              </nav>
              <SessionTerminalCanvas
                terminal={terminal}
                binding={binding}
                error={binding === 'error' ? 'terminal_authority_revoked' : null}
                lines={binding === 'stale' ? [] : lines}
                busy={false}
                currentRun={run}
                onStart={() => setBinding('connecting')}
              />
            </main>
          </div>
        </main>
      </div>
    </Theme>
  );
}

const container = document.getElementById('root');
if (!container) throw new Error('Missing root element');
globalThis.__sessionTerminalQaRoot ??= createRoot(container);
globalThis.__sessionTerminalQaRoot.render(
  <I18nProvider>
    <SessionTerminalQa />
  </I18nProvider>,
);
