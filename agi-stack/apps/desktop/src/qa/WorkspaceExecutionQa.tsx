import '@radix-ui/themes/styles.css';
import { Theme } from '@radix-ui/themes';
import {
  ChatBubbleIcon,
  CubeIcon,
  GearIcon,
  GridIcon,
  HomeIcon,
  MagnifyingGlassIcon,
  PlusIcon,
} from '@radix-ui/react-icons';
import React from 'react';
import { createRoot, type Root } from 'react-dom/client';

import { WorkspaceOverview } from '../features/workspace/WorkspaceOverview';
import { I18nProvider } from '../i18n';
import type {
  AgentConversation,
  DesktopArtifactVersion,
  DesktopRun,
  PlanSnapshot,
} from '../types';
import '../styles.css';
import './workspaceExecutionQa.css';

declare global {
  var __workspaceExecutionQaRoot: Root | undefined;
}

const now = '2026-07-13T10:42:00Z';

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
    conversation_mode: 'code',
    agent_config: { capability_mode: 'code' },
    participant_agents: ['planner', 'coder'],
    metadata: { run: { status: 'ready_review' } },
  },
];

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
  return (
    <Theme appearance="dark" accentColor="cyan" grayColor="slate" radius="medium" scaling="95%">
      <div className="workspace-execution-qa-shell">
        <aside className="workspace-execution-qa-sidebar">
          <div className="workspace-execution-qa-brand">
            <CubeIcon />
            <span>
              <strong>MemStack</strong>
              <small>智能体工作区</small>
            </span>
          </div>
          <button type="button" className="workspace-execution-qa-new">
            <PlusIcon /> 新建任务
          </button>
          <nav>
            <button type="button"><HomeIcon /> 首页</button>
            <button type="button"><GridIcon /> 我的工作 <em>3</em></button>
            <button type="button"><MagnifyingGlassIcon /> 搜索</button>
          </nav>
          <section>
            <span>工作空间</span>
            <button type="button" className="selected"><CubeIcon /> Desktop Client</button>
            {conversations.map((conversation) => (
              <button type="button" key={conversation.id}>
                <ChatBubbleIcon /> {conversation.title}
              </button>
            ))}
          </section>
          <button type="button" className="workspace-execution-qa-settings">
            <GearIcon /> 设置
          </button>
        </aside>
        <main>
          <WorkspaceOverview
            workspace={{
              id: 'desktop-client',
              project_id: 'northstar-project',
              name: 'Desktop Client',
              description: '应用体验、前端与 Rust 运行时交付。',
              office_status: 'online',
              updated_at: now,
              metadata: {
                collaboration_mode: 'multi_agent_shared',
              },
            }}
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
            conversations={conversations}
            members={{
              status: 'ready',
              error: null,
              items: Array.from({ length: 8 }, (_, index) => ({
                id: `member-${index + 1}`,
                workspace_id: 'desktop-client',
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
                  workspace_id: 'desktop-client',
                  agent_id: 'planner',
                  display_name: 'Planner',
                  is_active: true,
                },
                {
                  id: 'binding-2',
                  workspace_id: 'desktop-client',
                  agent_id: 'coder',
                  display_name: 'Coder',
                  is_active: true,
                },
                {
                  id: 'binding-3',
                  workspace_id: 'desktop-client',
                  agent_id: 'reviewer',
                  display_name: 'Reviewer',
                  is_active: true,
                },
                {
                  id: 'binding-4',
                  workspace_id: 'desktop-client',
                  agent_id: 'researcher',
                  display_name: 'Researcher',
                  is_active: true,
                },
              ],
            }}
            plan={{
              ...plan,
              root_goal: {
                title: '交付覆盖通用与编程场景的可靠桌面智能体工作空间。',
              },
            }}
            sandboxStatus="connected"
            newTaskDisabledReason={null}
            onNewTask={() => undefined}
            onOpenConversation={() => undefined}
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
