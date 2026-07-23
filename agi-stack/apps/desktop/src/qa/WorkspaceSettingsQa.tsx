import '@radix-ui/themes/styles.css';
import { useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Button, Theme } from '@radix-ui/themes';

import { DesktopApiError } from '../api/client';
import type { WorkspaceUpdateInput } from '../api/client';
import { WorkspaceSettingsDialog } from '../features/workspace/WorkspaceSettingsDialog';
import { WorkspaceSettingsScopeChangedError } from '../features/workspace/workspaceSettingsModel';
import type { WorkspaceSettingsScope } from '../features/workspace/workspaceSettingsModel';
import { I18nProvider } from '../i18n';
import type { WorkspaceSummary } from '../types';
import '../styles.css';
import './workspaceSettingsQa.css';

declare global {
  var __workspaceSettingsQaRoot: Root | undefined;
}

type WorkspaceSettingsQaMode = 'success' | 'duplicate' | 'error' | 'scope-change';

const SCOPE: WorkspaceSettingsScope = {
  tenantId: 'tenant-workspace-settings-qa',
  projectId: 'project-workspace-settings-qa',
  workspaceId: 'workspace-settings-qa',
  epoch: 5,
  contextRevision: 9,
};

const INITIAL_WORKSPACE: WorkspaceSummary = {
  id: SCOPE.workspaceId,
  tenant_id: SCOPE.tenantId,
  project_id: SCOPE.projectId,
  name: 'Desktop parity workspace',
  description: 'Verify workspace settings against the hosted Web contract.',
  is_archived: false,
  metadata: {
    source: 'desktop-qa',
    workspace_use_case: 'general',
    workspace_type: 'general',
    collaboration_mode: 'multi_agent_shared',
    agent_conversation_mode: 'multi_agent_shared',
    autonomy_profile: {
      workspace_type: 'general',
      completion_policy: { minimum_verification_grade: 'pass' },
    },
    unknown_extension: { preserved: true },
  },
  office_status: 'idle',
  created_at: '2026-07-23T00:00:00Z',
  updated_at: '2026-07-23T00:00:00Z',
};

function WorkspaceSettingsQa() {
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<WorkspaceSettingsQaMode>('success');
  const [workspace, setWorkspace] = useState<WorkspaceSummary>(INITIAL_WORKSPACE);
  const [status, setStatus] = useState('Ready for workspace settings QA.');

  const saveWorkspace = async (
    input: WorkspaceUpdateInput,
    submittedScope: WorkspaceSettingsScope,
    signal: AbortSignal,
  ): Promise<WorkspaceSummary> => {
    document.documentElement.dataset.qaWorkspaceSettingsRequest = JSON.stringify({
      input,
      submittedScope,
    });
    setStatus(`Submitted ${input.name} in ${mode} mode.`);
    await delay(mode === 'scope-change' ? 450 : 160, signal);
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
    if (mode === 'scope-change') throw new WorkspaceSettingsScopeChangedError();
    const updated: WorkspaceSummary = {
      ...workspace,
      name: input.name,
      description: input.description,
      is_archived: input.isArchived,
      metadata: input.metadata,
      updated_at: new Date().toISOString(),
    };
    setWorkspace(updated);
    setStatus(`Saved ${updated.name}.`);
    document.documentElement.dataset.qaWorkspaceSettingsSaved = updated.name ?? '';
    return updated;
  };

  return (
    <Theme appearance="dark" accentColor="cyan" grayColor="slate" radius="medium" scaling="95%">
      <main className="workspace-settings-qa-shell">
        <header>
          <div>
            <span>Desktop parity QA</span>
            <h1>Workspace settings</h1>
            <p>
              Exercise hydration, validation, operating model metadata, archive, reset, failures,
              and late-scope protection.
            </p>
          </div>
          <Button onClick={() => setOpen(true)}>Open workspace settings</Button>
        </header>
        <nav aria-label="Workspace settings QA mode">
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
        <section className="workspace-settings-qa-projection">
          <div>
            <small>Current projection</small>
            <strong>{workspace.name}</strong>
            <span>{workspace.description}</span>
          </div>
          <dl>
            <div>
              <dt>Lifecycle</dt>
              <dd>{workspace.is_archived ? 'Archived' : 'Active'}</dd>
            </div>
            <div>
              <dt>Use case</dt>
              <dd>{String(workspace.metadata?.workspace_use_case ?? '—')}</dd>
            </div>
            <div>
              <dt>Collaboration</dt>
              <dd>{String(workspace.metadata?.collaboration_mode ?? '—')}</dd>
            </div>
            <div>
              <dt>Unknown metadata</dt>
              <dd>
                {workspace.metadata?.unknown_extension ? 'Preserved' : 'Missing'}
              </dd>
            </div>
          </dl>
        </section>
        <section className="workspace-settings-qa-status" aria-live="polite">
          <strong>QA status</strong>
          <span>{status}</span>
        </section>
        <WorkspaceSettingsDialog
          open={open}
          workspace={workspace}
          scope={SCOPE}
          onOpenChange={setOpen}
          onSave={saveWorkspace}
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
        reject(new DOMException('Workspace settings request aborted', 'AbortError'));
      },
      { once: true },
    );
  });
}

localStorage.setItem('agistack.desktop.locale', 'en');
const container = document.getElementById('root');
if (!container) throw new Error('Missing root element');
globalThis.__workspaceSettingsQaRoot ??= createRoot(container);
globalThis.__workspaceSettingsQaRoot.render(
  <I18nProvider>
    <WorkspaceSettingsQa />
  </I18nProvider>,
);
