import '@radix-ui/themes/styles.css';
import { Theme } from '@radix-ui/themes';
import { useMemo, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import { MyWorkQueue } from '../features/my-work/MyWorkQueue';
import { DesktopSidebar } from '../features/navigation/DesktopSidebar';
import {
  NewThreadComposer,
  type NewThreadComposerInput,
} from '../features/task/NewThreadComposer';
import { I18nProvider } from '../i18n';
import type {
  AgentCapabilityMode,
  AgentConversation,
  CurrentUser,
  ProjectWorkItem,
  RuntimeNodeLoadState,
  WorkspaceAgentPolicy,
  WorkspaceSummary,
} from '../types';
import type { WorkspaceRuntimeModelOption } from '../features/settings/workspaceRuntimeProviderModel';
import '../styles.css';
import './missionControlQa.css';

declare global {
  var __missionControlQaRoot: Root | undefined;
}

const now = '2026-07-20T09:40:00Z';
const projectId = 'project-desktop-client';
const workspaceId = 'workspace-desktop-client';

const workspaces: WorkspaceSummary[] = [
  {
    id: workspaceId,
    tenant_id: 'tenant-northstar',
    project_id: projectId,
    name: 'Desktop Client',
    description: 'Mission Control client and runtime delivery.',
    office_status: 'online',
    updated_at: now,
    metadata: { collaboration_mode: 'multi_agent_shared' },
  },
  {
    id: 'workspace-release-reliability',
    tenant_id: 'tenant-northstar',
    project_id: projectId,
    name: 'Release Reliability',
    description: 'Release automation and recovery evidence.',
    office_status: 'online',
    updated_at: '2026-07-20T09:22:00Z',
    metadata: { collaboration_mode: 'multi_agent_shared' },
  },
];

const conversations: AgentConversation[] = [
  {
    id: 'conversation-policy',
    project_id: projectId,
    tenant_id: 'tenant-northstar',
    workspace_id: workspaceId,
    user_id: 'alex',
    title: 'Unify workspace agent policy',
    summary: 'Applying the approved runtime snapshot.',
    status: 'active',
    message_count: 18,
    created_at: now,
    updated_at: now,
    conversation_mode: 'code',
    current_mode: 'build',
    agent_config: { capability_mode: 'code' },
    participant_agents: [],
    metadata: { run: { status: 'running' } },
  },
  {
    id: 'conversation-permission',
    project_id: projectId,
    tenant_id: 'tenant-northstar',
    workspace_id: workspaceId,
    user_id: 'alex',
    title: 'Review workspace tool grant',
    summary: 'Waiting for permission review.',
    status: 'active',
    message_count: 11,
    created_at: now,
    updated_at: '2026-07-20T09:31:00Z',
    conversation_mode: 'work',
    current_mode: 'build',
    agent_config: { capability_mode: 'work' },
    participant_agents: [],
    metadata: { run: { status: 'needs_approval' } },
  },
  {
    id: 'conversation-plan',
    project_id: projectId,
    tenant_id: 'tenant-northstar',
    workspace_id: workspaceId,
    user_id: 'alex',
    title: 'Version the execution plan',
    summary: 'Plan v3 is ready to review.',
    status: 'active',
    message_count: 7,
    created_at: now,
    updated_at: '2026-07-20T09:10:00Z',
    conversation_mode: 'code',
    current_mode: 'plan',
    agent_config: { capability_mode: 'code' },
    participant_agents: [],
    metadata: { run: { status: 'ready_review' } },
  },
];

const releaseConversation: AgentConversation = {
  ...conversations[2],
  id: 'conversation-migration',
  workspace_id: 'workspace-release-reliability',
  title: 'Verify SQLite v19 migration',
  summary: 'Queued behind native regression tests.',
  updated_at: '2026-07-20T08:48:00Z',
  current_mode: 'plan',
  metadata: { run: { status: 'queued' } },
};

const conversationsByWorkspace: Record<string, AgentConversation[]> = {
  [workspaceId]: conversations,
  'workspace-release-reliability': [releaseConversation],
};

const nodeState: RuntimeNodeLoadState = {
  projects: { [projectId]: { loading: false, error: null } },
  workspaces: Object.fromEntries(
    workspaces.map((workspace) => [workspace.id, { loading: false, error: null }]),
  ),
};

const user: CurrentUser = {
  user_id: 'alex',
  email: 'alex@northstar.ai',
  name: 'Alex Chen',
  roles: ['owner'],
  is_active: true,
  created_at: now,
  profile: {},
};

const policy: WorkspaceAgentPolicy = {
  tenant_id: 'tenant-northstar',
  project_id: projectId,
  workspace_id: workspaceId,
  revision: 7,
  roles: {
    default: { provider_id: 'openai', model_id: 'gpt-5.6-terra' },
    fast: { provider_id: 'openai', model_id: 'gpt-5.6-terra' },
    coding: { provider_id: 'openai', model_id: 'gpt-5.6-sol' },
    vision: { provider_id: 'openai', model_id: 'gpt-5.6-terra' },
  },
  fallbacks: [],
  reasoning_effort: 'medium',
  permission_mode: 'ask',
  capability_version: 'workspace-agent-policy-v2',
  updated_at: now,
};

const modelOptions: WorkspaceRuntimeModelOption[] = [
  {
    value: JSON.stringify(['openai', 'gpt-5.6-terra']),
    providerId: 'openai',
    providerLabel: 'OpenAI',
    modelId: 'gpt-5.6-terra',
    selected: true,
  },
  {
    value: JSON.stringify(['openai', 'gpt-5.6-sol']),
    providerId: 'openai',
    providerLabel: 'OpenAI',
    modelId: 'gpt-5.6-sol',
    selected: false,
  },
];

function workItem(
  id: string,
  title: string,
  group: ProjectWorkItem['group'],
  status: ProjectWorkItem['status'],
  requiredAction: ProjectWorkItem['required_action'],
  progress: number,
  summary: string,
  phase: string,
  capabilityMode: AgentCapabilityMode,
): ProjectWorkItem {
  return {
    id: `workspace_attempt:${id}`,
    authority_kind: 'workspace_attempt',
    authority_id: id,
    run_id: null,
    conversation_id: `conversation-${id}`,
    workspace_id: workspaceId,
    workspace_name: 'Desktop Client',
    project_id: projectId,
    title,
    capability_mode: capabilityMode,
    group,
    status,
    required_action: requiredAction,
    revision: null,
    permission_profile: null,
    attempt_number: 1,
    environment: null,
    error: null,
    created_at: '2026-07-20T08:00:00Z',
    updated_at: now,
    last_heartbeat_at: null,
    summary,
    phase,
    progress,
  };
}

const myWorkItems: ProjectWorkItem[] = [
  workItem(
    'permission',
    'Review workspace tool grant',
    'needs_approval',
    'needs_approval',
    'review_approval',
    50,
    'write_file requests workspace-wide approval.',
    'Confirm permission scope',
    'work',
  ),
  workItem(
    'policy',
    'Unify workspace agent policy',
    'running',
    'running',
    'observe',
    66,
    'Runtime is using policy revision 7.',
    'Apply the runtime snapshot',
    'code',
  ),
  workItem(
    'migration',
    'Verify SQLite v19 migration',
    'running',
    'queued',
    'observe',
    20,
    'Queued behind native runtime regression tests.',
    'Run restart coverage',
    'code',
  ),
  workItem(
    'plan',
    'Version the execution plan',
    'ready_review',
    'ready_review',
    'review_result',
    100,
    'Plan v3 preserves task metadata and evidence.',
    'Review plan v3',
    'code',
  ),
];

function MissionControlQa() {
  const initialView = new URLSearchParams(window.location.search).get('view');
  const [view, setView] = useState<'home' | 'my-work'>(
    initialView === 'my-work' ? 'my-work' : 'home',
  );
  const [mode, setMode] = useState<AgentCapabilityMode>('work');
  const [expandedWorkspaceIds, setExpandedWorkspaceIds] = useState(
    () => new Set(workspaces.map((workspace) => workspace.id)),
  );
  const currentWorkspace = workspaces[0];
  const recentConversations = useMemo(
    () => conversationsByWorkspace[currentWorkspace.id] ?? [],
    [currentWorkspace.id],
  );

  const recordCreate = (input: NewThreadComposerInput) => {
    document.documentElement.dataset.qaCreate = JSON.stringify(input);
  };

  return (
    <I18nProvider>
      <Theme appearance="dark" accentColor="cyan" grayColor="slate" radius="medium" scaling="95%">
        <div className="mission-control-qa-shell">
          <DesktopSidebar
            activeSection={view === 'my-work' ? 'my-work' : 'home'}
            taskCount={myWorkItems.length}
            tenantName="Northstar Labs"
            projectName="Desktop Client"
            user={user}
            workspaces={workspaces}
            conversationsByWorkspace={conversationsByWorkspace}
            nodeState={nodeState}
            currentProjectId={projectId}
            currentWorkspaceId={workspaceId}
            currentConversationId={null}
            workspaceTreeSelectionMode="none"
            expandedWorkspaceIds={expandedWorkspaceIds}
            newTaskDisabledReason={null}
            onNavigate={(section) => {
              if (section === 'my-work') setView('my-work');
              if (section === 'home') setView('home');
            }}
            onToggleWorkspace={(targetWorkspaceId) =>
              setExpandedWorkspaceIds((current) => {
                const next = new Set(current);
                if (next.has(targetWorkspaceId)) next.delete(targetWorkspaceId);
                else next.add(targetWorkspaceId);
                return next;
              })
            }
            onRetryProject={() => undefined}
            onRetryWorkspace={() => undefined}
            onSelectWorkspace={() => undefined}
            onSelectConversation={() => undefined}
            onNewTask={() => setView('home')}
            onOpenAccountSettings={() => undefined}
            onSwitchWorkspace={() => undefined}
            onSignOut={() => undefined}
          />
          <div className="mission-control-qa-main">
            {view === 'home' ? (
              <NewThreadComposer
                workspace={currentWorkspace}
                conversations={recentConversations}
                mode={mode}
                policy={policy}
                modelOptions={modelOptions.map((option) => ({
                  ...option,
                  selected:
                    option.modelId === (mode === 'code' ? 'gpt-5.6-sol' : 'gpt-5.6-terra'),
                }))}
                canManagePolicy
                loadingPolicy={false}
                compatibilityMode={false}
                disabledReason={null}
                creating={false}
                error={null}
                onModeChange={setMode}
                onCreate={recordCreate}
                onOpenThread={() => undefined}
              />
            ) : (
              <MyWorkQueue
                items={myWorkItems}
                error={null}
                loading={false}
                mode={mode}
                projectName="Desktop Client"
                workspaceLabels={{ [workspaceId]: 'Desktop Client' }}
                onRefresh={() => undefined}
                onOpenSession={() => undefined}
              />
            )}
          </div>
        </div>
      </Theme>
    </I18nProvider>
  );
}

try {
  window.localStorage.setItem('agistack.desktop.locale', 'en');
} catch {
  // The provider falls back to the browser locale when storage is unavailable.
}

const rootElement = document.getElementById('root');
if (!rootElement) throw new Error('Missing #root');
globalThis.__missionControlQaRoot?.unmount();
globalThis.__missionControlQaRoot = createRoot(rootElement);
globalThis.__missionControlQaRoot.render(<MissionControlQa />);
