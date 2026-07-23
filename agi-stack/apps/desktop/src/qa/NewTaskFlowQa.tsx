import '@radix-ui/themes/styles.css';
import { useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import {
  NewTaskFlow,
  type NewTaskAgentTurnInput,
  type NewTaskSession,
} from '../features/task/NewTaskFlow';
import { I18nProvider } from '../i18n';
import type {
  AgentConversation,
  AgentPlanTask,
  DesktopPlanVersion,
  DesktopRuntimeConfig,
  WorkspaceMessage,
  WorkspaceSummary,
} from '../types';
import '../styles.css';

declare global {
  var __newTaskFlowQaRoot: Root | undefined;
  var __newTaskFlowQaRequests: Array<{ method: string; path: string; body: unknown }> | undefined;
}

const now = '2026-07-18T10:30:00.000Z';
const workspace: WorkspaceSummary = {
  id: 'workspace-retention',
  tenant_id: 'northstar',
  project_id: 'product-strategy',
  name: 'Q4 customer retention experiments',
  description:
    'Create a leadership-ready brief that recommends three measurable retention experiments for Q4.',
  status: 'active',
  is_archived: false,
  created_at: now,
  updated_at: now,
  metadata: {
    source: 'desktop',
    use_case: 'general',
    collaboration_mode: 'multi_agent_shared',
  },
};

const conversation: AgentConversation = {
  id: 'conversation-retention',
  project_id: 'product-strategy',
  tenant_id: 'northstar',
  workspace_id: workspace.id,
  user_id: 'alex',
  title: 'Q4 customer retention experiments',
  status: 'active',
  message_count: 1,
  created_at: now,
  updated_at: now,
  conversation_mode: 'workspace',
  current_mode: 'plan',
  agent_config: {
    selected_agent_id: 'builtin:all-access',
    capability_mode: 'work',
  },
  participant_agents: [],
  metadata: {},
};

const tasks: AgentPlanTask[] = [
  {
    id: 'plan-task-1',
    conversation_id: conversation.id,
    content: 'Collect the strongest customer signals',
    status: 'pending',
    priority: 'high',
    order_index: 0,
    created_at: now,
    updated_at: now,
  },
  {
    id: 'plan-task-2',
    conversation_id: conversation.id,
    content: 'Identify retention opportunities',
    status: 'pending',
    priority: 'high',
    order_index: 1,
    created_at: now,
    updated_at: now,
  },
  {
    id: 'plan-task-3',
    conversation_id: conversation.id,
    content: 'Design three experiment candidates',
    status: 'pending',
    priority: 'medium',
    order_index: 2,
    created_at: now,
    updated_at: now,
  },
  {
    id: 'plan-task-4',
    conversation_id: conversation.id,
    content: 'Draft the leadership brief',
    status: 'pending',
    priority: 'medium',
    order_index: 3,
    created_at: now,
    updated_at: now,
  },
];

const planVersion: DesktopPlanVersion = {
  id: 'plan-retention',
  conversation_id: conversation.id,
  version: 1,
  status: 'draft',
  tasks,
  created_at: now,
  approved_at: null,
};

const initialMessage: WorkspaceMessage = {
  id: 'workspace-message-objective',
  workspace_id: workspace.id,
  content:
    'Create a leadership-ready brief that recommends three measurable retention experiments for Q4, grounded in customer interviews and product data.',
  sender_type: 'human',
  sender_id: 'alex',
  parent_message_id: null,
  mentions: [],
  metadata: {
    source: 'task_session',
    conversation_id: conversation.id,
  },
  created_at: now,
};

const config: DesktopRuntimeConfig = {
  apiBaseUrl: 'http://qa.memstack.local',
  deviceAuthorizationBaseUrl: 'http://qa.memstack.local',
  apiKey: 'qa-session',
  localApiToken: 'qa-launch-capability',
  tenantId: 'northstar',
  projectId: 'product-strategy',
  workspaceId: '',
  mode: 'local',
  workspaceRoot: '/workspace/product-strategy',
};

let planningTurnAcceptedAt = 0;
let taskSessionPostCount = 0;
let firstTaskSessionBody: string | null = null;
let approvalPostCount = 0;
let persistedSessionCount = 0;
let readySessionCount = 0;
let agentTurnCount = 0;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function contractFailure(detail: string): Response {
  document.documentElement.dataset.qaContractErrors = detail;
  return json({ detail }, 422);
}

function hasExpectedAuth(init?: RequestInit): boolean {
  const headers = new Headers(init?.headers);
  return (
    headers.get('authorization') === 'Bearer qa-session' &&
    headers.get('x-agistack-launch') === 'qa-launch-capability' &&
    headers.get('content-type') === 'application/json'
  );
}

type QaTaskSessionBody = {
  idempotency_key: string;
  workspace: { kind: 'create'; name: string; description?: string };
  conversation: { title: string; capability_mode: 'work' | 'code' };
  initial_message: { content: string };
};

function validTaskSessionBody(body: unknown): body is QaTaskSessionBody {
  if (!isRecord(body)) return false;
  const workspaceBody = body.workspace;
  const conversationBody = body.conversation;
  const initialMessageBody = body.initial_message;
  return (
    typeof body.idempotency_key === 'string' &&
    body.idempotency_key.startsWith('desktop-task-session-') &&
    isRecord(workspaceBody) &&
    workspaceBody.kind === 'create' &&
    typeof workspaceBody.name === 'string' &&
    workspaceBody.name.trim().length > 0 &&
    isRecord(conversationBody) &&
    typeof conversationBody.title === 'string' &&
    (conversationBody.capability_mode === 'work' || conversationBody.capability_mode === 'code') &&
    isRecord(initialMessageBody) &&
    typeof initialMessageBody.content === 'string' &&
    initialMessageBody.content.trim().length > 0
  );
}

function json(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function requestBody(init?: RequestInit): unknown {
  if (typeof init?.body !== 'string' || init.body.length === 0) return null;
  try {
    return JSON.parse(init.body);
  } catch {
    return init.body;
  }
}

window.fetch = async (input, init) => {
  const requestUrl =
    typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
  const url = new URL(requestUrl);
  const method = init?.method ?? 'GET';
  const body = requestBody(init);
  globalThis.__newTaskFlowQaRequests ??= [];
  globalThis.__newTaskFlowQaRequests.push({ method, path: url.pathname, body });
  if (globalThis.__newTaskFlowQaRequests.length > 200) {
    globalThis.__newTaskFlowQaRequests.splice(
      1,
      globalThis.__newTaskFlowQaRequests.length - 200,
    );
  }
  document.documentElement.dataset.qaRequests = globalThis.__newTaskFlowQaRequests
    .map((request) => `${request.method} ${request.path}`)
    .join('|');

  if (
    url.pathname ===
      '/api/v1/tenants/northstar/projects/product-strategy/task-sessions' &&
    method === 'POST'
  ) {
    taskSessionPostCount += 1;
    document.documentElement.dataset.qaTaskSessionPosts = String(taskSessionPostCount);
    if (!hasExpectedAuth(init) || !validTaskSessionBody(body)) {
      return contractFailure('The task session request did not match the production contract.');
    }
    const serializedBody = JSON.stringify(body);
    if (taskSessionPostCount === 1) {
      firstTaskSessionBody = serializedBody;
      throw new TypeError('Failed to fetch');
    }
    if (taskSessionPostCount !== 2 || serializedBody !== firstTaskSessionBody) {
      return contractFailure('The task session retry changed its idempotent request.');
    }
    await new Promise((resolve) => window.setTimeout(resolve, 600));
    return json({
      replayed: false,
      workspace: {
        ...workspace,
        name: body.workspace.name,
        description: body.workspace.description,
      },
      conversation: {
        ...conversation,
        title: body.conversation.title,
        agent_config: {
          ...conversation.agent_config,
          capability_mode: body.conversation.capability_mode,
        },
      },
      initial_message: {
        ...initialMessage,
        content: body.initial_message.content,
      },
    });
  }

  if (url.pathname.endsWith('/workspaces') && method === 'POST') return json(workspace);
  if (url.pathname === '/api/v1/agent/conversations' && method === 'POST') {
    return json({ ...conversation, workspace_id: null });
  }
  if (url.pathname.endsWith(`/agent/conversations/${conversation.id}/mode`)) {
    return json(conversation);
  }
  if (url.pathname === '/api/v1/agent/plan/mode' && method === 'POST') {
    if (!body || typeof body !== 'object' || !('conversation_id' in body)) {
      return json({ detail: 'conversation_id is required' }, 422);
    }
    return json({ conversation_id: conversation.id, mode: 'plan', switched_at: now });
  }
  if (url.pathname.endsWith(`/workspaces/${workspace.id}/messages`) && method === 'POST') {
    return json(initialMessage);
  }
  if (
    url.pathname === `/api/v1/agent/plan/tasks/${conversation.id}` &&
    method === 'GET'
  ) {
    const planReady =
      planningTurnAcceptedAt > 0 && Date.now() - planningTurnAcceptedAt >= 1_200;
    return json({
      conversation_id: conversation.id,
      tasks: planReady ? tasks : [],
      total_count: planReady ? tasks.length : 0,
      approval: { kind: 'versioned_atomic', plan_version: planReady ? planVersion : null },
      plan_version: planReady ? planVersion : null,
    });
  }

  if (url.pathname === '/api/v1/agent/plans/approve-and-start' && method === 'POST') {
    approvalPostCount += 1;
    document.documentElement.dataset.qaApprovalPosts = String(approvalPostCount);
    if (approvalPostCount !== 1) {
      return contractFailure('The immutable plan version was approved more than once.');
    }
    if (!hasExpectedAuth(init) || !isRecord(body)) {
      return contractFailure('The approval request did not include the production authority.');
    }
    if (
      body.conversation_id !== conversation.id ||
      body.project_id !== config.projectId ||
      body.plan_version_id !== planVersion.id ||
      body.expected_plan_version !== planVersion.version ||
      !['read_only', 'workspace_write', 'full_access'].includes(
        String(body.permission_profile),
      ) ||
      !isRecord(body.environment) ||
      !['local', 'worktree'].includes(String(body.environment.kind)) ||
      typeof body.message_id !== 'string' ||
      !body.message_id.startsWith('desktop-build-') ||
      typeof body.idempotency_key !== 'string' ||
      !body.idempotency_key.startsWith('desktop-plan-approval-')
    ) {
      return contractFailure('The approval request was not bound to the previewed plan version.');
    }
    return json({
      queued: true,
      created: true,
      conversation: { ...conversation, current_mode: 'build' },
      plan_version: { ...planVersion, status: 'approved', approved_at: now },
      run: {
        id: 'run-retention',
        conversation_id: conversation.id,
        project_id: config.projectId,
        status: 'queued',
        revision: 1,
        created_at: now,
        updated_at: now,
      },
    });
  }

  return json({ detail: `Unhandled QA route: ${method} ${url.pathname}` }, 404);
};

document.documentElement.dataset.qaRuntimeErrors = '';
document.documentElement.dataset.qaContractErrors = '';
document.documentElement.dataset.qaTaskSessionPosts = '0';
document.documentElement.dataset.qaApprovalPosts = '0';
window.addEventListener('error', (event) => {
  document.documentElement.dataset.qaRuntimeErrors = event.message || 'window error';
});
window.addEventListener('unhandledrejection', (event) => {
  document.documentElement.dataset.qaRuntimeErrors = String(event.reason ?? 'unhandled rejection');
});

try {
  window.localStorage.setItem('agistack.desktop.locale', 'en');
} catch {
  // The provider falls back to the browser locale when storage is unavailable.
}

function NewTaskFlowQa() {
  const [open, setOpen] = useState(true);

  const runAgentTurn = async (input: NewTaskAgentTurnInput) => {
    agentTurnCount += 1;
    document.documentElement.dataset.qaAgentTurns = `${agentTurnCount}:${input.conversationId}`;
    planningTurnAcceptedAt = Date.now();
    return 'acknowledged' as const;
  };

  const persistSession = (session: NewTaskSession) => {
    persistedSessionCount += 1;
    document.documentElement.dataset.qaSessionPersisted =
      `${persistedSessionCount}:${session.conversation.id}`;
  };

  const activateSession = (session: NewTaskSession) => {
    readySessionCount += 1;
    document.documentElement.dataset.qaSessionReady =
      `${readySessionCount}:${session.conversation.id}:${session.conversation.current_mode ?? 'plan'}`;
  };

  return (
    <I18nProvider>
      <div aria-hidden style={{ width: '100%', height: '100%', background: '#070c12' }} />
      <NewTaskFlow
        open={open}
        config={config}
        actorId={conversation.user_id}
        workspaceAuthority={{ status: 'ready', items: [], error: null }}
        preferredKind="general"
        onClose={() => {
          document.documentElement.dataset.qaCloseCount = String(
            Number(document.documentElement.dataset.qaCloseCount ?? '0') + 1,
          );
          setOpen(false);
        }}
        onSessionPersisted={persistSession}
        onSessionReady={activateSession}
        onRunAgentTurn={runAgentTurn}
        onOpenRuntimeSettings={() => undefined}
        onError={(message) => {
          document.documentElement.dataset.qaFlowError = message ?? '';
        }}
      />
    </I18nProvider>
  );
}

const rootElement = document.getElementById('root');
if (!rootElement) throw new Error('Missing #root');
globalThis.__newTaskFlowQaRoot?.unmount();
globalThis.__newTaskFlowQaRoot = createRoot(rootElement);
globalThis.__newTaskFlowQaRoot.render(<NewTaskFlowQa />);
