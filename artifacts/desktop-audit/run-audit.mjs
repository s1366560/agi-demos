// Runtime capability audit: drives the real desktop sidecar end-to-end.
// Usage: node run-audit.mjs [stage ...]   (default: all stages)
// Writes logs/audit.log and prints a verdict summary as JSON at the end.
import { appendFile } from 'node:fs/promises';
import { SidecarHarness } from './lib/harness.mjs';
import { MockLlmServer } from './lib/mock-llm.mjs';

const LOG = new URL('./logs/audit.log', import.meta.url).pathname;
const RESULTS = new URL('./logs/results.json', import.meta.url).pathname;
const only = process.argv.slice(2);

const harness = new SidecarHarness({ logPath: LOG });
const results = {};
let mock = null;
let mockHandler = () => ({ kind: 'text', text: 'mock llm default reply' });

function isDecideCall(body) {
  const text = (body.messages ?? []).map((m) => m.content ?? '').join('\n');
  return text.includes('Goal:') && text.includes('Round:');
}

async function stage(name, fn) {
  if (only.length > 0 && !only.includes(name)) {
    results[name] = { verdict: 'SKIPPED' };
    return;
  }
  const started = Date.now();
  try {
    const detail = await fn();
    results[name] = { verdict: 'WORKS', detail, ms: Date.now() - started };
    console.log(`[WORKS] ${name} (${results[name].ms}ms)`);
  } catch (error) {
    results[name] = {
      verdict: 'BROKEN',
      error: String(error?.message ?? error),
      ms: Date.now() - started,
    };
    console.log(`[BROKEN] ${name}: ${results[name].error}`);
  }
}

const sleep = (ms) => new Promise((resolvePromise) => setTimeout(resolvePromise, ms));

// ---------------------------------------------------------------- Cap 1
async function cap1Workspace() {
  const { context } = harness.session;
  const tenants = await harness.http('/api/v1/tenants');
  const projects = await harness.http('/api/v1/projects');
  if (!tenants.tenants?.length) throw new Error('no tenants returned');
  if (!projects.projects?.length) throw new Error('no projects returned');

  const scope = `/api/v1/tenants/${context.tenant_id}/projects/${context.project_id}`;
  const before = await harness.http(`${scope}/workspaces`);
  const created = await harness.http(`${scope}/workspaces`, {
    method: 'POST',
    body: {
      name: `audit-workspace-${Date.now()}`,
      description: 'runtime capability audit workspace',
    },
  });
  const workspaceId = created.id ?? created.workspace_id ?? created.workspace?.id;
  if (!workspaceId) {
    throw new Error(`workspace create returned no id: ${JSON.stringify(created).slice(0, 300)}`);
  }
  const after = await harness.http(`${scope}/workspaces`);
  const listed = JSON.stringify(after);
  if (!listed.includes(workspaceId)) {
    throw new Error('created workspace not present in list (persistence failure)');
  }
  const taskSession = await harness.http(`${scope}/task-sessions`, {
    method: 'POST',
    body: {
      idempotency_key: `audit-task-session-${Date.now()}`,
      workspace: { kind: 'existing', workspace_id: workspaceId },
      conversation: { title: 'audit task session', capability_mode: 'work' },
      initial_message: { content: 'verify workspace-core bridge persistence' },
    },
  });
  const taskSessionId =
    taskSession.task_session_id ??
    taskSession.id ??
    taskSession.conversation?.id ??
    taskSession.conversation_id;
  return {
    tenants: tenants.total ?? tenants.tenants.length,
    projects: projects.total ?? projects.projects.length,
    workspacesBefore: before.items?.length ?? before.workspaces?.length ?? null,
    workspaceId,
    taskSessionId: taskSessionId ?? null,
    taskSessionRaw: taskSessionId ? undefined : JSON.stringify(taskSession).slice(0, 300),
  };
}

// ---------------------------------------------------------------- Cap 3
async function cap3LlmProvider() {
  mock = await new MockLlmServer((body, index) => mockHandler(body, index)).start();
  const created = await harness.http('/api/v1/llm-providers/', {
    method: 'POST',
    body: {
      name: 'audit-mock-llm',
      provider_type: 'openai_compatible',
      base_url: mock.baseUrl,
      auth_method: 'none',
      llm_model: 'mock-model',
      allowed_models: ['mock-model'],
      is_active: true,
    },
  });
  const providerId = created.id;
  if (!providerId) throw new Error(`provider create returned no id: ${JSON.stringify(created)}`);
  const selected = await harness.http(
    `/api/v1/llm-providers/${providerId}/runtime-selection`,
    { method: 'PUT', body: { expected_revision: created.revision ?? 0 } },
  );
  const providers = await harness.http('/api/v1/llm-providers/');
  const listed = providers.find((p) => p.id === providerId);
  if (!listed) throw new Error('provider missing from list after create');
  const health = await harness.rawFetch(
    `/api/v1/llm-providers/${providerId}/health-check`,
    { method: 'POST', body: { expected_revision: created.revision ?? 0 } },
  );
  harness._providerId = providerId;
  return {
    providerId,
    runtimeSelected:
      selected.runtime_selected === true ||
      listed.runtime_selected === true ||
      listed.selected === true,
    runtimeState: listed.runtime_state ?? listed.health_status ?? null,
    healthCheck: { status: health.status, body: health.text.slice(0, 200) },
  };
}

// ---------------------------------------------------------- conversation
async function createConversation(title, agentConfig = {}) {
  const conversation = await harness.http('/api/v1/agent/conversations', {
    method: 'POST',
    body: {
      project_id: harness.session.context.project_id,
      title,
      agent_config: agentConfig,
    },
  });
  if (!conversation.id) {
    throw new Error(`conversation create returned no id: ${JSON.stringify(conversation)}`);
  }
  return conversation;
}

async function runWsTurn(conversationId, message, extra = {}, timeoutMs = 90_000) {
  const { ws, events, waitFor } = await harness.openAgentWs();
  const start = events.length;
  try {
    ws.send(
      JSON.stringify({
        type: 'send_message',
        conversation_id: conversationId,
        project_id: harness.session.context.project_id,
        message,
        message_id: `audit-msg-${Date.now()}`,
        ...extra,
      }),
    );
    await waitFor((e) => e?.type === 'ack' && e?.action === 'send_message', 15_000, 'ack');
    const complete = await waitFor(
      (e) => e?.type === 'complete' || e?.type === 'error',
      timeoutMs,
      'complete/error',
    );
    // small drain for trailing events
    await sleep(400);
    return { events: events.slice(start), complete };
  } finally {
    ws.close();
  }
}

// ---------------------------------------------------------------- Cap 2
async function cap2SimpleConversation() {
  const answer = 'Audit simple-conversation reply from mock LLM.';
  mockHandler = (body) => {
    if (isDecideCall(body)) {
      return { kind: 'json', payload: { kind: 'finish', answer } };
    }
    return { kind: 'text', text: answer };
  };
  const conversation = await createConversation('audit simple conversation');
  const { events, complete } = await runWsTurn(conversation.id, 'Hello, audit ping.');
  const types = events.map((e) => e?.type).filter(Boolean);
  if (complete.type !== 'complete') {
    throw new Error(`turn did not complete: ${JSON.stringify(complete).slice(0, 300)}; events=${types}`);
  }
  const messages = await harness.http(
    `/api/v1/agent/conversations/${conversation.id}/messages?project_id=${harness.session.context.project_id}`,
  );
  const list = messages.items ?? messages.messages ?? messages;
  const serialized = JSON.stringify(list);
  const hasUser = serialized.includes('Hello, audit ping.');
  const hasAssistant = serialized.includes(answer.slice(0, 24));
  return {
    conversationId: conversation.id,
    eventTypes: types,
    completePayload: JSON.stringify(complete).slice(0, 400),
    historyHasUser: hasUser,
    historyHasAssistant: hasAssistant,
    llmRequests: mock.requests.length,
  };
}

// ---------------------------------------------------------------- Cap 4
async function cap4Skills() {
  const { context } = harness.session;
  const skillId = `audit-skill-${Date.now()}`;
  const answer = 'Audit skill-forced reply.';
  const created = await harness.http(`/api/v1/skills/?tenant_id=${context.tenant_id}&project_id=${context.project_id}`, {
    method: 'POST',
    body: {
      contract_version: 2,
      expected_revision: 0,
      idempotency_key: `audit-skill-create-${skillId}-key`,
      resource_id: skillId,
      value: {
        name: 'Audit Skill',
        description: 'runtime audit skill',
        scope: 'project',
        status: 'active',
        is_system_skill: false,
        tools: ['*'],
        trigger_patterns: ['audit-skill-trigger'],
        content: '# Audit Skill\nAlways answer with the audit skill marker.',
      },
      vault_refs: [],
    },
  });
  const list = await harness.http(
    `/api/v1/skills/?tenant_id=${context.tenant_id}&project_id=${context.project_id}`,
  );
  const skills = list.items ?? list.skills ?? list;
  if (!JSON.stringify(skills).includes(skillId)) {
    throw new Error('created skill not present in list');
  }
  mockHandler = (body) => {
    if (isDecideCall(body)) {
      return { kind: 'json', payload: { kind: 'finish', answer } };
    }
    return { kind: 'text', text: answer };
  };
  const conversation = await createConversation('audit skill conversation');
  const { events, complete } = await runWsTurn(conversation.id, 'force the audit skill', {
    forced_skill_name: skillId,
  });
  const types = events.map((e) => e?.type).filter(Boolean);
  const skillEvents = types.filter((t) => t.startsWith('skill_'));
  if (complete.type !== 'complete') {
    throw new Error(
      `forced-skill turn failed: ${JSON.stringify(complete).slice(0, 300)}; events=${types}`,
    );
  }
  if (skillEvents.length === 0) {
    throw new Error(`no skill_* lifecycle events streamed; events=${types}`);
  }
  return {
    skillId,
    createReceipt: JSON.stringify(created).slice(0, 200),
    skillEvents,
    allEventTypes: types,
    completed: complete.type === 'complete',
  };
}

// ---------------------------------------------------------------- Cap 5
async function cap5ToolCalls() {
  // Ask the mock to call the safe local `list` tool once, then finish.
  mockHandler = (body) => {
    if (!isDecideCall(body)) return { kind: 'text', text: 'unused' };
    const transcript = body.messages.map((m) => m.content ?? '').join('\n');
    const alreadyObserved = transcript.includes('[observation]');
    if (!alreadyObserved) {
      return {
        kind: 'json',
        payload: { kind: 'call_tool', tool: 'list', input_json: { path: '.' } },
      };
    }
    return {
      kind: 'json',
      payload: { kind: 'finish', answer: 'Audit tool-call run finished after list.' },
    };
  };
  const conversation = await createConversation('audit tool-call conversation', {
    capability_mode: 'work',
  });
  const { events, complete } = await runWsTurn(conversation.id, 'List the workspace directory.');
  const types = events.map((e) => e?.type).filter(Boolean);
  const actEvents = events.filter((e) => e?.type === 'act');
  const observeEvents = events.filter((e) => e?.type === 'observe');
  const observePayload = JSON.stringify(observeEvents).slice(0, 400);
  return {
    eventTypes: types,
    actCount: actEvents.length,
    observeCount: observeEvents.length,
    observePayload,
    completed: complete.type === 'complete',
    completePayload: JSON.stringify(complete).slice(0, 300),
  };
}

// ---------------------------------------------------------------- Cap 6
async function cap6AgentSubagent() {
  const { context } = harness.session;
  const stamp = Date.now();
  const agentId = `audit-agent-${stamp}`;
  const subagentId = `audit-subagent-${stamp}`;
  const agent = await harness.http(
    `/api/v1/agent/definitions?tenant_id=${context.tenant_id}&project_id=${context.project_id}`,
    {
      method: 'POST',
      body: {
        contract_version: 2,
        expected_revision: 0,
        idempotency_key: `audit-agent-create-${agentId}-key`,
        resource_id: agentId,
        value: {
          name: 'Audit Agent',
          description: 'runtime audit agent',
          source: 'local',
          status: 'active',
          enabled: true,
          system_prompt: 'You are the audit parent agent.',
          allowed_tools: ['list', 'read'],
          allowed_skills: [],
          allowed_mcp_servers: [],
          can_spawn: true,
          spawn_policy: { allowed_subagents: [subagentId] },
        },
        vault_refs: [],
      },
    },
  );
  const subagent = await harness.http(
    `/api/v1/subagents/?tenant_id=${context.tenant_id}&project_id=${context.project_id}`,
    {
      method: 'POST',
      body: {
        contract_version: 2,
        expected_revision: 0,
        idempotency_key: `audit-subagent-create-${subagentId}-key`,
        resource_id: subagentId,
        value: {
          id: subagentId,
          tenant_id: context.tenant_id,
          project_id: context.project_id,
          name: subagentId,
          display_name: 'Audit Subagent',
          system_prompt: 'You are the audit subagent. Finish immediately.',
          enabled: true,
          status: 'active',
          source: 'database',
          allowed_tools: ['list'],
          allowed_skills: [],
          allowed_mcp_servers: [],
        },
        vault_refs: [],
      },
    },
  );
  const agents = await harness.http(
    `/api/v1/agent/definitions?tenant_id=${context.tenant_id}&project_id=${context.project_id}`,
  );
  const subagents = await harness.http(
    `/api/v1/subagents/?tenant_id=${context.tenant_id}&project_id=${context.project_id}`,
  );
  if (!JSON.stringify(agents).includes(agentId)) throw new Error('agent missing from list');
  if (!JSON.stringify(subagents).includes(subagentId)) throw new Error('subagent missing from list');

  // Phase 1 (Plan mode): the mock submits a plan, which terminates the run.
  mockHandler = (body) => {
    if (!isDecideCall(body)) return { kind: 'text', text: 'unused' };
    return {
      kind: 'json',
      payload: {
        kind: 'call_tool',
        tool: 'submit_plan',
        input_json: {
          tasks: [
            { content: 'Delegate the audit readiness check', priority: 'high' },
            { content: 'Report the delegated result', priority: 'medium' },
          ],
        },
      },
    };
  };
  const conversation = await createConversation('audit agent conversation', {
    selected_agent_id: agentId,
  });
  const planTurn = await runWsTurn(conversation.id, 'Plan the audit delegation.', {
    agent_id: agentId,
  });
  if (planTurn.complete.type !== 'complete') {
    throw new Error(
      `plan turn failed: ${JSON.stringify(planTurn.complete).slice(0, 300)}; events=${planTurn.events.map((e) => e?.type)}`,
    );
  }
  const session = await harness.http(
    `/api/v1/agent/conversations/${conversation.id}/session?tenant_id=${context.tenant_id}&project_id=${context.project_id}`,
  );
  const currentPlan =
    session.currentPlan ?? session.current_plan ?? session.session?.current_plan;
  if (!currentPlan?.id) {
    throw new Error(`no current plan in session projection: ${JSON.stringify(session).slice(0, 400)}`);
  }

  // Phase 2 (Build mode): approve the plan; the build run must offer the
  // `subagent` delegation tool, and the mock delegates to the audit subagent.
  mockHandler = (body) => {
    if (!isDecideCall(body)) return { kind: 'text', text: 'unused' };
    const transcript = body.messages.map((m) => m.content ?? '').join('\n');
    const toolsMatch = transcript.match(/Available tools: \[([^\]]*)\]/);
    const tools = toolsMatch?.[1] ?? '';
    const alreadyObserved = transcript.includes('[observation]');
    if (tools.includes('subagent') && !alreadyObserved) {
      return {
        kind: 'json',
        payload: {
          kind: 'call_tool',
          tool: 'subagent',
          input_json: { subagent_id: subagentId, task: 'report audit readiness' },
        },
      };
    }
    const answer = alreadyObserved
      ? 'Parent run finished after delegation.'
      : 'Subagent audit report ready.';
    return { kind: 'json', payload: { kind: 'finish', answer } };
  };
  // Subscribe before approving so the build run's events are captured.
  const { ws, events, waitFor } = await harness.openAgentWs();
  const start = events.length;
  let complete;
  try {
    ws.send(JSON.stringify({ type: 'subscribe', conversation_id: conversation.id }));
    await waitFor((e) => e?.type === 'ack' && e?.action === 'subscribe', 15_000, 'subscribe ack');
    await harness.http('/api/v1/agent/plans/approve-and-start', {
      method: 'POST',
      body: {
        conversation_id: conversation.id,
        project_id: context.project_id,
        plan_version_id: currentPlan.id,
        expected_plan_version: currentPlan.version ?? 1,
        permission_profile: 'full_access',
        message: 'Plan approved. Execute the audit delegation now.',
        message_id: `audit-approve-${Date.now()}`,
        idempotency_key: `audit-approve-${conversation.id}`,
      },
    });
    complete = await waitFor(
      (e) => e?.type === 'complete' || e?.type === 'error',
      90_000,
      'build run complete/error',
    );
    await sleep(400);
  } finally {
    ws.close();
  }
  const runEvents = events.slice(start);
  const types = runEvents.map((e) => e?.type).filter(Boolean);
  const subagentEvents = types.filter((t) => t.startsWith('subagent'));
  const decideRequests = mock.requests
    .filter((r) => isDecideCall(r))
    .map((r) => {
      const text = r.messages.map((m) => m.content ?? '').join('\n');
      return text.match(/Available tools: \[[^\]]*\]/)?.[0] ?? 'no-tools-line';
    });
  if (complete.type !== 'complete') {
    throw new Error(
      `delegation turn failed: ${JSON.stringify(complete).slice(0, 300)}; events=${types}`,
    );
  }
  if (subagentEvents.length === 0) {
    throw new Error(
      `no subagent_* lifecycle events streamed; events=${types}; decideTools=${JSON.stringify(decideRequests)}`,
    );
  }
  return {
    agentId,
    subagentId,
    agentReceipt: JSON.stringify(agent).slice(0, 150),
    subagentReceipt: JSON.stringify(subagent).slice(0, 150),
    subagentEvents,
    allEventTypes: types,
    completed: complete.type === 'complete',
    completePayload: JSON.stringify(complete).slice(0, 300),
  };
}

// ---------------------------------------------------------------- Cap 7
async function cap7Plugins() {
  const distribution = await harness.invoke('platform_plugin_renderer_distribution_current_v2');
  const delivery = await harness.invoke('platform_plugin_renderer_delivery_current_v2', {
    owner_id: 'audit-renderer',
  });
  const v1 = await harness.rawFetch('/api/v1/platform-plugins', { method: 'GET' });
  const v1channels = await harness.rawFetch(
    `/api/v1/channels/tenants/${harness.session.context.tenant_id}/plugins`,
    { method: 'GET' },
  );
  const marketplace = await harness.rawFetch('/api/v1/plugin-marketplace/packages', {
    method: 'GET',
  });
  return {
    rendererDistribution: {
      source: distribution?.source,
      schemaVersion: distribution?.snapshot?.schema_version,
    },
    rendererDelivery: JSON.stringify(delivery).slice(0, 200),
    v1Status: { status: v1.status, body: v1.text.slice(0, 160) },
    v1ChannelStatus: { status: v1channels.status, body: v1channels.text.slice(0, 160) },
    marketplaceV2: { status: marketplace.status, body: marketplace.text.slice(0, 300) },
  };
}

// ---------------------------------------------------------------- main
try {
  await harness.start();
  await harness.createSession();
  await stage('cap1_workspace', cap1Workspace);
  await stage('cap3_llm_provider', cap3LlmProvider);
  const llmReady = results.cap3_llm_provider?.verdict === 'WORKS';
  if (llmReady) {
    await stage('cap2_simple_conversation', cap2SimpleConversation);
    await stage('cap4_skills', cap4Skills);
    await stage('cap5_tool_calls', cap5ToolCalls);
    await stage('cap6_agent_subagent', cap6AgentSubagent);
  } else {
    for (const name of ['cap2_simple_conversation', 'cap4_skills', 'cap5_tool_calls', 'cap6_agent_subagent']) {
      results[name] = { verdict: 'BLOCKED', error: 'LLM provider stage failed' };
    }
  }
  await stage('cap7_plugins', cap7Plugins);
} finally {
  await mock?.stop();
  await harness.stop();
}
await appendFile(RESULTS, `${JSON.stringify({ at: new Date().toISOString(), results })}\n`);
console.log('\n=== VERDICTS ===');
for (const [name, result] of Object.entries(results)) {
  console.log(`${result.verdict.padEnd(8)} ${name}`);
}
