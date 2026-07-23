import '@radix-ui/themes/styles.css';
import { useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Button, Theme } from '@radix-ui/themes';

import { DesktopApiError } from '../api/client';
import type { WorkspaceCreateInput } from '../api/client';
import { WorkspaceCreateDialog } from '../features/workspace/WorkspaceCreateDialog';
import { WorkspaceCreateScopeChangedError } from '../features/workspace/workspaceCreateModel';
import type { WorkspaceCreateScope } from '../features/workspace/workspaceCreateModel';
import { I18nProvider } from '../i18n';
import '../styles.css';
import './workspaceCreateQa.css';

declare global {
  var __workspaceCreateQaRoot: Root | undefined;
}

type WorkspaceCreateQaMode = 'success' | 'duplicate' | 'error' | 'scope-change';

const SCOPE: WorkspaceCreateScope = {
  tenantId: 'tenant-workspace-create-qa',
  projectId: 'project-workspace-create-qa',
  epoch: 4,
  contextRevision: 7,
};

function WorkspaceCreateQa() {
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<WorkspaceCreateQaMode>('success');
  const [status, setStatus] = useState('Ready for workspace creation QA.');

  const createWorkspace = async (
    input: WorkspaceCreateInput,
    submittedScope: WorkspaceCreateScope,
    signal: AbortSignal,
  ) => {
    document.documentElement.dataset.qaWorkspaceRequest = JSON.stringify({
      input,
      submittedScope,
    });
    setStatus(`Submitted ${input.name} in ${mode} mode.`);
    await delay(mode === 'scope-change' ? 450 : 120, signal);
    if (mode === 'duplicate') {
      setMode('success');
      throw new DesktopApiError('Duplicate workspace', 409, {
        code: 'workspace_name_conflict',
      });
    }
    if (mode === 'error') {
      setMode('success');
      throw new DesktopApiError('QA workspace failure', 503, {
        code: 'qa_workspace_failure',
      });
    }
    if (mode === 'scope-change') throw new WorkspaceCreateScopeChangedError();
    document.documentElement.dataset.qaWorkspaceCreated = input.name;
    setStatus(`Created ${input.name}.`);
  };

  return (
    <Theme appearance="dark" accentColor="cyan" grayColor="slate" radius="medium" scaling="95%">
      <main className="workspace-create-qa-shell">
        <header>
          <div>
            <span>Desktop parity QA</span>
            <h1>Standalone workspace creation</h1>
            <p>Exercise the Web-equivalent fields, validation, errors, retry, and success flow.</p>
          </div>
          <Button onClick={() => setOpen(true)}>Open create dialog</Button>
        </header>
        <nav aria-label="Workspace creation QA mode">
          {(['success', 'duplicate', 'error', 'scope-change'] as const).map((nextMode) => (
            <button
              type="button"
              key={nextMode}
              className={mode === nextMode ? 'selected' : ''}
              aria-pressed={mode === nextMode}
              onClick={() => setMode(nextMode)}
            >
              {nextMode}
            </button>
          ))}
        </nav>
        <section className="workspace-create-qa-status" aria-live="polite">
          <strong>QA status</strong>
          <span>{status}</span>
        </section>
        <WorkspaceCreateDialog
          open={open}
          projectName="Desktop Parity Project"
          scope={SCOPE}
          onOpenChange={setOpen}
          onCreate={createWorkspace}
        />
      </main>
    </Theme>
  );
}

function delay(milliseconds: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const timer = window.setTimeout(resolve, milliseconds);
    signal.addEventListener(
      'abort',
      () => {
        window.clearTimeout(timer);
        reject(new DOMException('Workspace creation aborted', 'AbortError'));
      },
      { once: true },
    );
  });
}

localStorage.setItem('agistack.desktop.locale', 'en');
const container = document.getElementById('root');
if (!container) throw new Error('Missing root element');
globalThis.__workspaceCreateQaRoot ??= createRoot(container);
globalThis.__workspaceCreateQaRoot.render(
  <I18nProvider>
    <WorkspaceCreateQa />
  </I18nProvider>,
);
