import '@radix-ui/themes/styles.css';
import { useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Button, Theme } from '@radix-ui/themes';

import { DesktopApiError } from '../api/client';
import type {
  WorkspaceMemberRole,
  WorkspaceUpdateInput,
} from '../api/client';
import { WorkspaceSettingsDialog } from '../features/workspace/WorkspaceSettingsDialog';
import {
  removeWorkspaceMemberByUserId,
  upsertWorkspaceMember,
} from '../features/workspace/workspaceMembersModel';
import { WorkspaceSettingsScopeChangedError } from '../features/workspace/workspaceSettingsModel';
import type { WorkspaceSettingsScope } from '../features/workspace/workspaceSettingsModel';
import { I18nProvider } from '../i18n';
import type {
  WorkspaceMemberSummary,
  WorkspaceSummary,
} from '../types';
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

const ACTOR_USER_ID = 'workspace-owner-qa';

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

const INITIAL_MEMBERS: WorkspaceMemberSummary[] = [
  {
    id: 'workspace-member-owner',
    workspace_id: SCOPE.workspaceId,
    user_id: ACTOR_USER_ID,
    user_email: 'owner@example.test',
    role: 'owner',
    created_at: '2026-07-23T00:00:00Z',
  },
  {
    id: 'workspace-member-viewer',
    workspace_id: SCOPE.workspaceId,
    user_id: 'workspace-viewer-qa',
    user_email: 'viewer@example.test',
    role: 'viewer',
    created_at: '2026-07-23T00:00:00Z',
  },
];

function WorkspaceSettingsQa() {
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<WorkspaceSettingsQaMode>('success');
  const [workspace, setWorkspace] = useState<WorkspaceSummary>(INITIAL_WORKSPACE);
  const [members, setMembers] =
    useState<WorkspaceMemberSummary[]>(INITIAL_MEMBERS);
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

  const addMember = async (
    userId: string,
    role: WorkspaceMemberRole,
    _submittedScope: WorkspaceSettingsScope,
    signal: AbortSignal,
  ): Promise<WorkspaceMemberSummary> => {
    setStatus(`Adding member ${userId} in ${mode} mode.`);
    await memberMutationDelay(mode, signal);
    const member: WorkspaceMemberSummary = {
      id: `workspace-member-${members.length + 1}`,
      workspace_id: SCOPE.workspaceId,
      user_id: userId,
      user_email: null,
      role,
      invited_by: ACTOR_USER_ID,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };
    setMembers((current) => upsertWorkspaceMember(current, member));
    setStatus(`Added ${userId} as ${role}.`);
    return member;
  };

  const updateMemberRole = async (
    userId: string,
    role: WorkspaceMemberRole,
    _submittedScope: WorkspaceSettingsScope,
    signal: AbortSignal,
  ): Promise<WorkspaceMemberSummary> => {
    setStatus(`Updating member ${userId} in ${mode} mode.`);
    await memberMutationDelay(mode, signal);
    const current = members.find((member) => member.user_id === userId);
    if (!current) {
      throw new DesktopApiError('QA member missing', 404, {
        code: 'qa_member_missing',
      });
    }
    const updated = { ...current, role, updated_at: new Date().toISOString() };
    setMembers((items) => upsertWorkspaceMember(items, updated));
    setStatus(`Updated ${userId} to ${role}.`);
    return updated;
  };

  const removeMember = async (
    userId: string,
    _submittedScope: WorkspaceSettingsScope,
    signal: AbortSignal,
  ): Promise<void> => {
    setStatus(`Removing member ${userId} in ${mode} mode.`);
    await memberMutationDelay(mode, signal);
    setMembers((current) =>
      removeWorkspaceMemberByUserId(current, userId),
    );
    setStatus(`Removed ${userId}.`);
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
            <div>
              <dt>Member count</dt>
              <dd>{members.length}</dd>
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
          members={{ status: 'ready', items: members, error: null }}
          actorUserId={ACTOR_USER_ID}
          scope={SCOPE}
          onOpenChange={setOpen}
          onSave={saveWorkspace}
          onAddMember={addMember}
          onUpdateMemberRole={updateMemberRole}
          onRemoveMember={removeMember}
        />
      </main>
    </Theme>
  );
}

async function memberMutationDelay(
  mode: WorkspaceSettingsQaMode,
  signal: AbortSignal,
) {
  await delay(mode === 'scope-change' ? 450 : 160, signal);
  if (mode === 'duplicate') {
    throw new DesktopApiError('Duplicate workspace member', 409, {
      code: 'workspace_member_conflict',
    });
  }
  if (mode === 'error') {
    throw new DesktopApiError('QA workspace member failure', 503, {
      code: 'qa_workspace_member_failure',
    });
  }
  if (mode === 'scope-change') {
    throw new WorkspaceSettingsScopeChangedError();
  }
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
