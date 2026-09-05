import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';
const require = createRequire(import.meta.url);
const { createDesktopChatComposerCatalogClientV2 } = require('/tmp/agistack-desktop-test-dist/src/features/chat/desktopChatComposerCatalogClientV2.js');
const { DEFAULT_CONFIG } = require('/tmp/agistack-desktop-test-dist/src/types.js');

function fixture(overrides = {}) {
  const calls = [];
  const result = Object.freeze({ items: [], total: 0 });
  const config = { ...DEFAULT_CONFIG, mode: 'cloud', tenantId: 'tenant-1', projectId: 'project-1', workspaceId: 'workspace-1' };
  const record = (name, value = []) => async (...args) => { calls.push({ name, args }); return value; };
  const input = {
    config,
    projectSandboxUploadOperationsV2: { uploadSandboxFile: record('upload', { sandbox_path: '/workspace/input/proof.txt' }) },
    workspaceRosterOperationsV2: { listWorkspaceAgents: record('roster') },
    pluginMarketplaceOperationsV2: { listMarketplacePlugins: record('plugins') },
    tenantAgentDefinitionsOperationsV2: { loadTenantAgentDefinitions: record('agents') },
    tenantSkillDefinitionsOperationsV2: { loadTenantSkillDefinitions: record('skills') },
    tenantSubAgentDefinitionsOperationsV2: { loadTenantSubAgentDefinitions: record('subagents') },
    tenantPromptTemplatesOperationsV2: {
      listTenantPromptTemplates: record('prompts'),
      createTenantPromptTemplate: record('create-prompt'),
      deleteTenantPromptTemplate: record('delete-prompt'),
    },
    workspaceConversationCatalogOperationsV2: { listConversations: record('conversations', result) },
    newTaskFlowOperationsV2: { bindOperation(boundConfig) {
      calls.push({ name: 'history-bind', args: [boundConfig] });
      return { getConversationMessages: record('messages', result) };
    } },
    ...overrides,
  };
  return { input, calls, result, client: createDesktopChatComposerCatalogClientV2(input) };
}

test('chat comparison preserves project, legacy workspace and options filters with signals', async () => {
  const { client, calls, result, input } = fixture();
  const signal = new AbortController().signal;
  input.config.tenantId = 'replaced-tenant';
  input.config.projectId = 'replaced-project';
  assert.equal(await client.listConversations(), result);
  await client.listConversations('project-2', ' workspace-2 ', signal);
  await client.listConversations('project-3', null, signal);
  await client.listConversations('project-4', { workspaceId: null, unboundOnly: true, signal });
  await client.listConversations('project-5', { workspaceId: 'workspace-5', unboundOnly: true, signal });
  assert.deepEqual(calls.map(({ args: [value] }) => ({
    tenant: value.config.tenantId, project: value.config.projectId,
    workspace: value.workspaceId, unbound: value.unboundOnly, signal: value.signal,
  })), [
    { tenant: 'tenant-1', project: 'project-1', workspace: null, unbound: false, signal: undefined },
    { tenant: 'tenant-1', project: 'project-2', workspace: 'workspace-2', unbound: false, signal },
    { tenant: 'tenant-1', project: 'project-3', workspace: null, unbound: false, signal },
    { tenant: 'tenant-1', project: 'project-4', workspace: null, unbound: true, signal },
    // Conflicting filters reach the authority unchanged so it can reject the protocol combination.
    { tenant: 'tenant-1', project: 'project-5', workspace: 'workspace-5', unbound: true, signal },
  ]);
});

test('chat message comparison binds V2 history with frozen config and exact cursor options', async () => {
  const { client, calls, input, result } = fixture();
  input.config.tenantId = 'replaced-tenant';
  const options = { limit: 150, beforeTimeUs: 900, beforeCounter: 3, signal: new AbortController().signal };
  assert.equal(await client.getConversationMessages('conversation-2', 'project-2', options), result);
  assert.equal(calls[0].name, 'history-bind');
  assert.equal(calls[0].args[0].tenantId, 'tenant-1');
  assert.equal(Object.isFrozen(calls[0].args[0]), true);
  assert.deepEqual(calls[1], { name: 'messages', args: ['conversation-2', 'project-2', options] });
});

test('chat catalog and upload delegate to required operations without constructing static HTTP clients', async () => {
  const { client, calls } = fixture();
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => { throw new Error('unexpected static HTTP bypass'); };
  const signal = new AbortController().signal;
  try {
    await client.listWorkspaceAgents(signal);
    await client.listMarketplacePlugins(signal);
    await client.listManagedAgents(signal);
    await client.listManagedSkills(signal);
    await client.listManagedSubAgents(signal);
    await client.listPromptTemplates('tenant-1', signal);
    const file = { name: 'proof.txt', type: 'text/plain', size: 1, arrayBuffer: async () => new Uint8Array([1]).buffer };
    await client.uploadSandboxFile(file, signal);
    assert.deepEqual(calls.map(({ name }) => name), ['roster', 'plugins', 'agents', 'skills', 'subagents', 'prompts', 'upload']);
    for (const call of calls) {
      if (call.name === 'plugins') { assert.equal(call.args[0].tenantId, 'tenant-1'); assert.equal(call.args[1], signal); }
      else { assert.equal(call.args[0].config.tenantId, 'tenant-1'); assert.equal(call.args[0].signal, signal); }
    }
    assert.equal(calls.at(-1).args[0].file, file);
  } finally { globalThis.fetch = originalFetch; }
});

test('chat authority rejections propagate without a static fallback', async () => {
  const failure = new Error('generation service lease rejected');
  const { client } = fixture({
    workspaceRosterOperationsV2: { listWorkspaceAgents: async () => { throw failure; } },
    pluginMarketplaceOperationsV2: { listMarketplacePlugins: async () => { throw failure; } },
    workspaceConversationCatalogOperationsV2: { listConversations: async () => { throw failure; } },
    newTaskFlowOperationsV2: { bindOperation() { return { getConversationMessages: async () => { throw failure; } }; } },
  });
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => { throw new Error('unexpected fallback fetch'); };
  try {
    for (const invoke of [() => client.listWorkspaceAgents(), () => client.listMarketplacePlugins(), () => client.listConversations(), () => client.getConversationMessages('conversation-1')]) {
      await assert.rejects(invoke, (error) => error === failure);
    }
  } finally { globalThis.fetch = originalFetch; }
});

test('unconfigured chat composition stays lazy until an operation is requested', () => {
  const { client, calls } = fixture({
    config: { ...DEFAULT_CONFIG, tenantId: '', projectId: '', workspaceId: '' },
    newTaskFlowOperationsV2: { bindOperation() { throw new Error('must not bind before a history request'); } },
  });
  assert.equal(Object.isFrozen(client), true);
  assert.equal(typeof client.uploadSandboxFile, 'function');
  assert.deepEqual(calls, []);
});
