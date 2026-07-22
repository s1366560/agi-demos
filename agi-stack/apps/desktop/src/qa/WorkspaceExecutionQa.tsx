import '@radix-ui/themes/styles.css';
import { Theme } from '@radix-ui/themes';
import React, { useEffect, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import { DesktopSidebar } from '../features/navigation/DesktopSidebar';
import { WorkspaceOverview } from '../features/workspace/WorkspaceOverview';
import {
  applyWorkspaceActivityStreamEvent,
  type WorkspaceLiveActivity,
} from '../features/workspace/workspaceActivityEventModel';
import { I18nProvider } from '../i18n';
import type {
  AgentConversation,
  CurrentUser,
  DesktopArtifactVersion,
  DesktopRun,
  PlanSnapshot,
  RuntimeNodeLoadState,
  WorkspaceSummary,
} from '../types';
import '../styles.css';
import './workspaceExecutionQa.css';

declare global {
  var __workspaceExecutionQaRoot: Root | undefined;
}

const now = '2026-07-13T10:42:00Z';

const workspaceActivityEvents = [
  {
    type: 'blackboard_post_created',
    data: {
      surface_boundary: 'owned',
      authority_class: 'authoritative',
      post: {
        id: 'post-release-readiness',
        workspace_id: 'desktop-client',
        title: 'Release readiness',
        content: 'Cloud conversation and event rendering verified.',
      },
    },
  },
  {
    type: 'topology_updated',
    data: {
      workspace_id: 'desktop-client',
      operation: 'node_created',
      node: {
        id: 'node-release-agent',
        workspace_id: 'desktop-client',
        title: 'Release Agent',
      },
    },
  },
];

function run(id: string, conversationId: string, status: DesktopRun['status']): DesktopRun {
  return {
    id,
    conversation_id: conversationId,
    project_id: 'northstar-project',
    plan_version_id: `plan-${conversationId}`,
    idempotency_key: `approval-${id}`,
    message_id: `message-${id}`,
    request_message: 'Execute the reviewed plan',
    status,
    revision: 4,
    created_at: now,
    updated_at: now,
    authorization_snapshot: {},
  };
}

const conversations: AgentConversation[] = [
  {
    id: 'conversation-1',
    project_id: 'northstar-project',
    tenant_id: 'northstar',
    user_id: 'alex',
    title: 'Fix flaky data-pipeline test',
    status: 'active',
    message_count: 24,
    created_at: now,
    updated_at: now,
    workspace_id: 'desktop-client',
    conversation_mode: 'code',
    agent_config: { capability_mode: 'code' },
    participant_agents: ['planner', 'coder'],
    metadata: { run: { status: 'running' } },
  },
  {
    id: 'conversation-2',
    project_id: 'northstar-project',
    tenant_id: 'northstar',
    user_id: 'alex',
    title: 'Review auth middleware refactor',
    status: 'active',
    message_count: 12,
    created_at: now,
    updated_at: '2026-07-13T10:10:00Z',
    workspace_id: 'desktop-client',
    conversation_mode: 'work',
    agent_config: { capability_mode: 'work' },
    participant_agents: ['researcher', 'reviewer'],
    metadata: { run: { status: 'needs_approval' } },
  },
  {
    id: 'conversation-3',
    project_id: 'northstar-project',
    tenant_id: 'northstar',
    user_id: 'alex',
    title: 'Add task search shortcuts',
    status: 'active',
    message_count: 8,
    created_at: now,
    updated_at: '2026-07-13T09:58:00Z',
    workspace_id: 'desktop-client',
    conversation_mode: 'code',
    agent_config: { capability_mode: 'code' },
    participant_agents: ['planner', 'coder'],
    metadata: { run: { status: 'ready_review' } },
  },
];

const reliabilityConversation: AgentConversation = {
  id: 'conversation-4',
  project_id: 'northstar-project',
  tenant_id: 'northstar',
  user_id: 'alex',
  title: 'Plan agent SDK upgrade',
  status: 'active',
  message_count: 17,
  created_at: now,
  updated_at: '2026-07-13T09:31:00Z',
  workspace_id: 'release-reliability',
  conversation_mode: 'code',
  agent_config: { capability_mode: 'code' },
  participant_agents: ['planner', 'coder'],
  metadata: { run: { status: 'needs_approval' } },
};

const workspaces: WorkspaceSummary[] = [
  {
    id: 'desktop-client',
    tenant_id: 'northstar',
    project_id: 'northstar-project',
    name: 'Desktop Client',
    description: '应用体验、前端与 Rust 运行时交付。',
    office_status: 'online',
    updated_at: now,
    metadata: { collaboration_mode: 'multi_agent_shared' },
  },
  {
    id: 'release-reliability',
    tenant_id: 'northstar',
    project_id: 'northstar-project',
    name: 'Release Reliability',
    description: '发布自动化、验证证据与恢复演练。',
    office_status: 'online',
    updated_at: '2026-07-13T09:31:00Z',
    metadata: { collaboration_mode: 'multi_agent_shared' },
  },
];

const conversationsByWorkspace: Record<string, AgentConversation[]> = {
  'desktop-client': conversations,
  'release-reliability': [reliabilityConversation],
};

const nodeState: RuntimeNodeLoadState = {
  projects: { 'northstar-project': { loading: false, error: null } },
  workspaces: Object.fromEntries(
    workspaces.map((workspace) => [workspace.id, { loading: false, error: null }]),
  ),
};

const currentUser: CurrentUser = {
  user_id: 'alex',
  email: 'alex@northstar.ai',
  name: 'Alex Chen',
  roles: ['owner'],
  is_active: true,
  created_at: now,
  profile: {},
};

const artifacts: DesktopArtifactVersion[] = [
  {
    id: 'artifact-1',
    artifact_id: 'workspace-design',
    source_artifact_id: 'workspace-design',
    conversation_id: 'conversation-1',
    run_id: 'run-1',
    version: 2,
    status: 'ready',
    revision: 4,
    filename: 'workspace-overview.md',
    mime_type: 'text/markdown',
    path: '/workspace/docs/workspace-overview.md',
    relative_path: 'docs/workspace-overview.md',
    bytes: 4920,
    sources: [],
    checks: [],
    created_at: now,
    updated_at: now,
  },
  {
    id: 'artifact-2',
    artifact_id: 'rust-contract',
    source_artifact_id: 'rust-contract',
    conversation_id: 'conversation-1',
    run_id: 'run-1',
    version: 1,
    status: 'approved',
    revision: 2,
    filename: 'workspace-projection.json',
    mime_type: 'application/json',
    path: '/workspace/evidence/workspace-projection.json',
    relative_path: 'evidence/workspace-projection.json',
    bytes: 2230,
    sources: [],
    checks: [],
    created_at: now,
    updated_at: now,
  },
];

const runOne = run('run-1', 'conversation-1', 'running');
const runTwo = run('run-2', 'conversation-2', 'needs_approval');
const runThree = run('run-3', 'conversation-3', 'ready_review');

const plan: PlanSnapshot = {
  workspace_id: 'desktop-client',
  project_id: 'northstar-project',
  plan: null,
  conversation_plans: [
    {
      conversation_id: 'conversation-1',
      title: conversations[0].title,
      capability_mode: 'code',
      current_mode: 'build',
      updated_at: now,
      plan: {
        id: 'plan-conversation-1',
        conversation_id: 'conversation-1',
        version: 3,
        status: 'approved',
        tasks: [],
        created_at: now,
        approved_at: now,
      },
      run: runOne,
      pending_hitl: [],
      artifacts,
      delivery: [],
    },
    {
      conversation_id: 'conversation-2',
      title: conversations[1].title,
      capability_mode: 'work',
      current_mode: 'build',
      updated_at: now,
      plan: {
        id: 'plan-conversation-2',
        conversation_id: 'conversation-2',
        version: 2,
        status: 'approved',
        tasks: [],
        created_at: now,
        approved_at: now,
      },
      run: runTwo,
      pending_hitl: [{ id: 'approval-1', conversation_id: 'conversation-2' }],
      artifacts: [],
      delivery: [],
    },
    {
      conversation_id: 'conversation-3',
      title: conversations[2].title,
      capability_mode: 'code',
      current_mode: 'build',
      updated_at: now,
      plan: {
        id: 'plan-conversation-3',
        conversation_id: 'conversation-3',
        version: 1,
        status: 'approved',
        tasks: [],
        created_at: now,
        approved_at: now,
      },
      run: runThree,
      pending_hitl: [],
      artifacts: [],
      delivery: [],
    },
  ],
  run_health: [runOne, runTwo, runThree],
  pending_hitl: [{ id: 'approval-1', conversation_id: 'conversation-2' }],
  artifact_index: artifacts,
  delivery: [
    {
      id: 'delivery-1',
      artifact_version_id: 'artifact-0',
      artifact_id: 'previous-evidence',
      conversation_id: 'conversation-3',
      destination: 'workspace-deliveries',
      receipt: {},
      idempotency_key: 'delivery-workspace-1',
      created_at: now,
    },
  ],
};

function WorkspaceExecutionQa() {
  const scenario = new URLSearchParams(window.location.search).get('scenario');
  const workspaceActivityEventMode =
    new URLSearchParams(window.location.search).get('workspace-activity-event') === '1';
  const [mode, setMode] = useState<'work' | 'code'>('work');
  const [liveActivity, setLiveActivity] = useState<WorkspaceLiveActivity[]>([]);
  const [selectedWorkspaceId, setSelectedWorkspaceId] = useState(workspaces[0].id);
  const [selectedConversationId, setSelectedConversationId] = useState<string | null>(null);
  const [expandedWorkspaceIds, setExpandedWorkspaceIds] = useState(
    () => new Set(workspaces.map((workspace) => workspace.id)),
  );
  const selectedWorkspace =
    workspaces.find((workspace) => workspace.id === selectedWorkspaceId) ?? workspaces[0];
  const selectedConversations = conversationsByWorkspace[selectedWorkspace.id] ?? [];
  const scenarioNodeState: RuntimeNodeLoadState =
    scenario === 'stale-project'
      ? {
          projects: {
            'northstar-project': { loading: false, error: '工作空间刷新失败，请重试。' },
          },
          workspaces: nodeState.workspaces,
        }
      : scenario === 'stale-sessions'
        ? {
            projects: nodeState.projects,
            workspaces: {
              ...nodeState.workspaces,
              'desktop-client': { loading: false, error: '会话刷新失败，请重试。' },
            },
          }
        : nodeState;

  const selectWorkspace = (workspaceId: string) => {
    setSelectedWorkspaceId(workspaceId);
    setSelectedConversationId(null);
    setExpandedWorkspaceIds((current) => new Set([...current, workspaceId]));
  };

  const selectConversation = (workspaceId: string, conversation: AgentConversation) => {
    setSelectedWorkspaceId(workspaceId);
    setSelectedConversationId(conversation.id);
    setExpandedWorkspaceIds((current) => new Set([...current, workspaceId]));
  };

  useEffect(() => {
    if (!workspaceActivityEventMode) return;
    const timer = window.setTimeout(() => {
      setLiveActivity((current) =>
        workspaceActivityEvents.reduce(
          (activities, event) =>
            applyWorkspaceActivityStreamEvent(activities, event, 'desktop-client').activities,
          current,
        ),
      );
    }, 600);
    return () => window.clearTimeout(timer);
  }, [workspaceActivityEventMode]);

  return (
    <Theme appearance="dark" accentColor="cyan" grayColor="slate" radius="medium" scaling="95%">
      <div className="workspace-execution-qa-shell">
        <DesktopSidebar
          activeSection={null}
          mode={mode}
          taskCount={8}
          tenantName="Northstar Labs"
          projectName="Desktop Client"
          user={currentUser}
          workspaces={workspaces}
          conversationsByWorkspace={conversationsByWorkspace}
          nodeState={scenarioNodeState}
          currentProjectId="northstar-project"
          currentWorkspaceId={selectedWorkspace.id}
          currentConversationId={selectedConversationId}
          workspaceTreeSelectionMode={selectedConversationId ? 'conversation' : 'overview'}
          expandedWorkspaceIds={expandedWorkspaceIds}
          newTaskDisabledReason={null}
          onModeChange={setMode}
          onNavigate={() => undefined}
          onToggleWorkspace={(workspaceId) =>
            setExpandedWorkspaceIds((current) => {
              const next = new Set(current);
              if (next.has(workspaceId)) next.delete(workspaceId);
              else next.add(workspaceId);
              return next;
            })
          }
          onRetryProject={() => undefined}
          onRetryWorkspace={() => undefined}
          onSelectWorkspace={(_projectId, workspaceId) => selectWorkspace(workspaceId)}
          onSelectConversation={(_projectId, workspaceId, conversation) =>
            selectConversation(workspaceId, conversation)
          }
          onNewTask={() => undefined}
          onOpenAccountSettings={() => undefined}
          onSwitchWorkspace={() => undefined}
          onSignOut={() => undefined}
        />
        <main>
          <WorkspaceOverview
            workspace={selectedWorkspace}
            project={{
              id: 'northstar-project',
              tenant_id: 'northstar',
              name: 'Desktop Client',
              stats: {
                memory_count: 248,
                node_count: 1842,
                storage_used: 641728512,
                recent_activity: [
                  { title: '定向测试套件已通过', detail: 'Code agent · 2 分钟前' },
                  { title: '桌面导航原型已更新', detail: 'Design agent · 11 分钟前' },
                  { title: 'Rust 运行时决策已记录', detail: 'Memory service · 24 分钟前' },
                ],
              },
            }}
            tenantName="Northstar Labs"
            workspaceAuthority={{ status: 'ready', items: workspaces, error: null }}
            conversations={selectedConversations}
            members={{
              status: 'ready',
              error: null,
              items: Array.from({ length: 8 }, (_, index) => ({
                id: `member-${index + 1}`,
                workspace_id: selectedWorkspace.id,
                user_id: `user-${index + 1}`,
                role: index === 0 ? 'owner' : 'viewer',
              })),
            }}
            agents={{
              status: 'ready',
              error: null,
              items: [
                {
                  id: 'binding-1',
                  workspace_id: selectedWorkspace.id,
                  agent_id: 'planner',
                  display_name: 'Planner',
                  is_active: true,
                },
                {
                  id: 'binding-2',
                  workspace_id: selectedWorkspace.id,
                  agent_id: 'coder',
                  display_name: 'Coder',
                  is_active: true,
                },
                {
                  id: 'binding-3',
                  workspace_id: selectedWorkspace.id,
                  agent_id: 'reviewer',
                  display_name: 'Reviewer',
                  is_active: true,
                },
                {
                  id: 'binding-4',
                  workspace_id: selectedWorkspace.id,
                  agent_id: 'researcher',
                  display_name: 'Researcher',
                  is_active: true,
                },
              ],
            }}
            plan={{
              ...plan,
              workspace_id: selectedWorkspace.id,
              root_goal: {
                title: '交付覆盖通用与编程场景的可靠桌面智能体工作空间。',
              },
            }}
            sandboxStatus="connected"
            liveActivity={liveActivity}
            newTaskDisabledReason={null}
            onNewTask={() => undefined}
            onRetryWorkspaces={() => undefined}
            onOpenConversation={(conversationId) => {
              const conversation = selectedConversations.find((item) => item.id === conversationId);
              if (conversation) selectConversation(selectedWorkspace.id, conversation);
            }}
            onOpenSettings={() => undefined}
          />
        </main>
      </div>
    </Theme>
  );
}

const root = document.getElementById('root');
if (!root) throw new Error('Missing #root container');

const qaRoot = globalThis.__workspaceExecutionQaRoot ?? createRoot(root);
globalThis.__workspaceExecutionQaRoot = qaRoot;

qaRoot.render(
  <React.StrictMode>
    <I18nProvider>
      <WorkspaceExecutionQa />
    </I18nProvider>
  </React.StrictMode>,
);
