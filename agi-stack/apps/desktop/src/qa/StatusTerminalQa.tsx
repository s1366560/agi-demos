import '@radix-ui/themes/styles.css';
import React, { useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Theme } from '@radix-ui/themes';

import { StatusPanel } from '../features/status/StatusPanel';
import type { TerminalBindingState } from '../features/session/sessionTerminalModel';
import { I18nProvider } from '../i18n';
import type { StatusTab, TerminalServiceResponse } from '../types';
import '../styles.css';
import './statusTerminalQa.css';

declare global {
  var __statusTerminalQaRoot: Root | undefined;
}

const terminal: TerminalServiceResponse = {
  success: true,
  session_id: 'local-terminal-7f54cc1c',
  project_id: 'local-project',
  conversation_id: 'conversation-desktop-session',
  run_id: 'run-desktop-session-42',
  run_revision: 7,
  environment_id: 'environment-worktree-42',
  cwd: '/workspace/.agistack-worktrees/desktop-session-42',
  resumable: false,
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

function StatusTerminalQa() {
  const [tab, setTab] = useState<StatusTab>('sandbox');
  const [binding, setBinding] = useState<TerminalBindingState>('connected');
  return (
    <Theme appearance="dark" accentColor="cyan" grayColor="slate" radius="medium" scaling="95%">
      <main className="status-terminal-qa-shell">
        <nav aria-label="Terminal binding QA states">
          {(['connected', 'connecting', 'stale', 'closed', 'error'] as TerminalBindingState[]).map(
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
        <StatusPanel
          selectedTask={null}
          plan={null}
          events={[]}
          wsConnected
          tab={tab}
          sandbox={{
            sandbox_id: 'sandbox-local-project',
            project_id: 'local-project',
            status: 'running',
            is_healthy: true,
          }}
          desktop={null}
          desktopFrameUrl={null}
          terminal={terminal}
          terminalBinding={binding}
          terminalError={binding === 'error' ? 'terminal_authority_revoked' : null}
          terminalLines={binding === 'stale' ? [] : lines}
          terminalInput="cargo test"
          sandboxBusy={false}
          sandboxDisabledReason={null}
          memoryProjectId="local-project"
          memoryContent=""
          memoryQuery=""
          tauriAvailable
          memoryBusy={false}
          memoryResult={null}
          onTabChange={setTab}
          onTerminalInputChange={() => {}}
          onEnsureSandbox={() => {}}
          onStartDesktop={() => {}}
          onStartTerminal={() => setBinding('connecting')}
          onSendTerminalInput={() => {}}
          onClearTerminal={() => {}}
          onMemoryContentChange={() => {}}
          onMemoryQueryChange={() => {}}
          onMemoryIngest={() => {}}
          onMemorySearch={() => {}}
          onMemorySemanticSearch={() => {}}
        />
      </main>
    </Theme>
  );
}

const container = document.getElementById('root');
if (!container) throw new Error('Missing root element');
globalThis.__statusTerminalQaRoot ??= createRoot(container);
globalThis.__statusTerminalQaRoot.render(
  <I18nProvider>
    <StatusTerminalQa />
  </I18nProvider>,
);
