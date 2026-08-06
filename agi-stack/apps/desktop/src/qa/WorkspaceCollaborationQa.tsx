import '@radix-ui/themes/styles.css';
import { Theme } from '@radix-ui/themes';
import { createRoot, type Root } from 'react-dom/client';

import { WorkspaceCollaborationCanvas } from '../features/workspace/WorkspaceCollaborationCanvas';
import type {
  WorkspaceCollaborationClient,
  WorkspaceCollaborationSurface,
  WorkspaceSurfaceMutation,
  WorkspaceSurfaceState,
} from '../features/workspace/workspaceCollaborationClient';
import { I18nProvider } from '../i18n';
import '../styles/global.css';
import './parityRuntimeQa.css';

declare global {
  var __workspaceCollaborationQaRoot: Root | undefined;
}

const workspaceId = 'workspace-parity-qa';
type WorkspaceQaState = 'ready' | 'loading' | 'empty' | 'stale' | 'error';
const requestedState = new URLSearchParams(window.location.search).get('state');
const qaState: WorkspaceQaState =
  requestedState === 'loading' ||
  requestedState === 'empty' ||
  requestedState === 'stale' ||
  requestedState === 'error'
    ? requestedState
    : 'ready';

const surfaceData: Record<WorkspaceCollaborationSurface, Record<string, unknown>> = {
  goals: {
    objectives: [
      {
        id: 'objective-1',
        title: 'Desktop and Web parity',
        description: 'Ship authority-backed collaboration surfaces.',
      },
    ],
    tasks: [
      {
        id: 'task-1',
        title: 'Verify reconnect recovery',
        status: 'in_progress',
      },
      {
        id: 'task-2',
        title: 'Publish release evidence',
        status: 'review',
      },
    ],
  },
  discussion: {
    posts: [
      {
        id: 'post-1',
        title: 'Canonical authority',
        author_name: 'Workspace owner',
        content: 'Mutation acknowledgements always trigger a canonical refetch.',
        is_pinned: true,
        replies: [{ id: 'reply-1', content: 'Confirmed in the Desktop fixture.' }],
      },
    ],
  },
  status: {
    diagnostics: { title: 'Runtime health', status: 'ready' },
    metrics: [{ id: 'metric-1', title: 'Active sessions', value: '3' }],
  },
  collaboration: {
    agents: [{ id: 'agent-1', name: 'Parity agent', status: 'working' }],
    activity: [{ id: 'activity-1', title: 'Canonical refetch', status: 'complete' }],
  },
  members: {
    members: [
      { id: 'member-1', user_id: 'owner@example.com', display_name: 'Owner', role: 'owner' },
      { id: 'member-2', user_id: 'reviewer@example.com', display_name: 'Reviewer', role: 'member' },
    ],
  },
  genes: {
    genes: [
      { id: 'gene-1', name: 'Quality gate', description: 'Requires native proof.', is_active: true },
    ],
  },
  files: {
    files: [
      { id: 'file-1', filename: 'parity-report.md', path: '/workspace/parity-report.md' },
    ],
  },
  notes: {
    workspace: {
      name: 'Desktop parity',
      description: 'Notes are a derived projection of workspace authority.',
    },
    objectives: [{ id: 'note-objective-1', title: 'No inferred capability' }],
    pinned_posts: [{ id: 'note-post-1', title: 'Release proof stays pending' }],
  },
  topology: {
    nodes: [
      { id: 'node-1', label: 'Desktop' },
      { id: 'node-2', label: 'Cloud authority' },
    ],
    edges: [{ id: 'edge-1', title: 'Desktop to cloud authority' }],
  },
  settings: {
    workspace: {
      id: workspaceId,
      name: 'Desktop parity workspace',
      description: 'A fixture for all ten collaboration tabs.',
    },
  },
};

function snapshot(
  surface: WorkspaceCollaborationSurface,
  revision = 7,
  status: WorkspaceQaState = qaState,
): WorkspaceSurfaceState {
  if (status === 'loading') {
    return {
      workspace_id: workspaceId,
      surface,
      authority: 'cloud',
      status,
      revision: null,
      cursor: null,
      data: null,
      reason_code: null,
    };
  }
  return {
    workspace_id: workspaceId,
    surface,
    authority: 'cloud',
    status,
    revision,
    cursor: `surface:${surface}:revision:${revision}`,
    data: status === 'empty' ? {} : surfaceData[surface],
    reason_code:
      status === 'error'
        ? 'workspace_surface_load_failed'
        : status === 'stale'
          ? 'workspace_surface_cursor_gap'
          : null,
  };
}

let revision = 7;
const client: WorkspaceCollaborationClient = {
  async getSurface(_workspaceId, surface) {
    return snapshot(surface, revision);
  },
  async refetchAuthority(_workspaceId, surface) {
    return snapshot(surface, revision, qaState === 'stale' ? 'ready' : qaState);
  },
  async mutateSurface(
    _workspaceId: string,
    surface: WorkspaceCollaborationSurface,
    mutation: WorkspaceSurfaceMutation,
  ) {
    if (mutation.expected_revision !== revision) {
      throw new Error('workspace_revision_conflict');
    }
    revision += 1;
    return snapshot(surface, revision);
  },
};

function WorkspaceCollaborationQa() {
  return (
    <Theme accentColor="cyan" grayColor="slate" radius="medium" scaling="95%">
      <main className="parity-runtime-qa">
        <header data-qa-state={qaState}>
          <div>
            <h1>Workspace Collaboration</h1>
            <p>
              Ten authority-backed surfaces with keyboard tabs, revision-guarded mutations,
              and canonical refetch.
            </p>
          </div>
        </header>
        <div className="parity-runtime-qa__surface">
          <WorkspaceCollaborationCanvas workspaceId={workspaceId} client={client} />
        </div>
      </main>
    </Theme>
  );
}

const container = document.getElementById('root');
if (!container) throw new Error('Missing root element');
globalThis.__workspaceCollaborationQaRoot ??= createRoot(container);
globalThis.__workspaceCollaborationQaRoot.render(
  <I18nProvider>
    <WorkspaceCollaborationQa />
  </I18nProvider>,
);
