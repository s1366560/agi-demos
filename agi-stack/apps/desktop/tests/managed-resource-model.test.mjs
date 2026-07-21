import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  filterManagedResources,
  managedResourceAction,
  managedResourceManagementAllowed,
  managedResourceSnapshotIsCurrent,
  managedResourceCapabilityGroups,
  managedResourceFacts,
  managedResourceView,
  resolveManagedResourceSelection,
  resourceIsActive,
} = require('/tmp/agistack-desktop-test-dist/src/features/settings/managedResourceModel.js');

const skill = {
  id: 'research',
  name: 'Research',
  description: 'Collect cited evidence',
  status: 'active',
  scope: 'tenant',
  tools: ['search', 'read'],
  current_version: 3,
  is_system_skill: false,
  updated_at: '2026-07-14T02:00:00Z',
};

const plugin = {
  id: 'runtime/github',
  name: 'GitHub',
  source: 'marketplace',
  package: '@memstack/github',
  version: '2.1.0',
  kind: 'mcp',
  enabled: true,
  discovered: true,
  providers: ['github'],
  skills: ['pull-request-review'],
  channel_types: ['issues'],
  tool_definitions: [{ name: 'list_pull_requests' }, {}, { name: '' }],
};

const agent = {
  id: 'agent-reviewer',
  name: 'reviewer',
  display_name: 'Review guardian',
  system_prompt: 'SECRET INTERNAL POLICY TOKEN',
  enabled: true,
  status: 'active',
  model: 'openai/gpt-5.5',
  project_id: 'project-a',
  allowed_tools: ['read', 'git_diff'],
  allowed_skills: ['pull-request-review'],
  allowed_mcp_servers: ['github'],
  fallback_models: ['anthropic/claude-opus-4.1'],
};

const subagent = {
  id: 'subagent-reviewer',
  tenant_id: 'tenant-a',
  project_id: 'project-a',
  name: 'release-reviewer',
  display_name: 'Release reviewer',
  system_prompt: 'SECRET SUBAGENT POLICY',
  trigger: {
    description: 'Review release readiness',
    keywords: ['release', 'readiness'],
    examples: ['Review this release'],
  },
  model: 'openai/gpt-5.5',
  enabled: true,
  source: 'database',
  allowed_tools: ['read', 'git_diff'],
  allowed_skills: ['pull-request-review'],
  allowed_mcp_servers: ['github'],
  fallback_models: ['anthropic/claude-opus-4.1'],
  total_invocations: 18,
  success_rate: 0.94,
  avg_execution_time_ms: 1250,
  updated_at: '2026-07-21T02:00:00Z',
};

test('managed resource activity follows explicit structural status fields', () => {
  assert.equal(resourceIsActive('skills', skill), true);
  assert.equal(resourceIsActive('skills', { ...skill, status: 'deprecated' }), false);
  assert.equal(resourceIsActive('plugins', plugin), true);
  assert.equal(resourceIsActive('plugins', { ...plugin, discovered: false }), false);
  assert.equal(resourceIsActive('agents', agent), true);
  assert.equal(resourceIsActive('agents', { ...agent, enabled: false, status: 'active' }), false);
  assert.equal(
    resourceIsActive('agents', { ...agent, enabled: undefined, status: 'disabled' }),
    false,
  );
  assert.equal(resourceIsActive('subagents', subagent), true);
  assert.equal(resourceIsActive('subagents', { ...subagent, enabled: false }), false);
});

test('search uses only declared public fields and never hidden prompt or arbitrary JSON', () => {
  const agents = [agent];
  assert.equal(filterManagedResources('agents', agents, 'guardian', 'all').length, 1);
  assert.equal(filterManagedResources('agents', agents, 'gpt-5.5', 'all').length, 1);
  assert.equal(filterManagedResources('agents', agents, 'git_diff', 'all').length, 1);
  assert.equal(filterManagedResources('agents', agents, 'SECRET INTERNAL', 'all').length, 0);
  assert.equal(
    filterManagedResources('agents', [{ ...agent, unknown_private: 'needle' }], 'needle', 'all')
      .length,
    0,
  );
  assert.equal(filterManagedResources('subagents', [subagent], 'readiness', 'all').length, 1);
  assert.equal(filterManagedResources('subagents', [subagent], 'SECRET SUBAGENT', 'all').length, 0);
});

test('list filtering classifies non-effective resources as attention', () => {
  const plugins = [plugin, { ...plugin, id: 'offline', name: 'Offline', discovered: false }];
  assert.deepEqual(
    filterManagedResources('plugins', plugins, '', 'active').map((item) => item.id),
    ['runtime/github'],
  );
  assert.deepEqual(
    filterManagedResources('plugins', plugins, '', 'attention').map((item) => item.id),
    ['offline'],
  );
});

test('resource views do not invent versions, packages, tools, or agent descriptions', () => {
  assert.deepEqual(managedResourceView('skills', { ...skill, current_version: undefined }), {
    id: 'research',
    title: 'Research',
    description: 'Collect cited evidence',
    meta: [
      { kind: 'text', value: 'tenant' },
      { kind: 'tool_count', count: 2 },
    ],
    status: 'active',
  });
  assert.deepEqual(
    managedResourceView('plugins', {
      ...plugin,
      package: undefined,
      version: undefined,
      tool_definitions: [{}],
    }),
    {
      id: 'runtime/github',
      title: 'GitHub',
      description: 'mcp',
      meta: [{ kind: 'text', value: 'marketplace' }],
      status: 'active',
    },
  );
  assert.deepEqual(managedResourceView('agents', agent), {
    id: 'agent-reviewer',
    title: 'Review guardian',
    description: '',
    meta: [
      { kind: 'text', value: 'reviewer' },
      { kind: 'text', value: 'openai/gpt-5.5' },
      { kind: 'tool_count', count: 2 },
      { kind: 'skill_count', count: 1 },
    ],
    status: 'active',
  });
  assert.deepEqual(managedResourceView('subagents', subagent), {
    id: 'subagent-reviewer',
    title: 'Release reviewer',
    description: 'Review release readiness',
    meta: [
      { kind: 'text', value: 'release-reviewer' },
      { kind: 'text', value: 'openai/gpt-5.5' },
      { kind: 'tool_count', count: 2 },
      { kind: 'skill_count', count: 1 },
    ],
    status: 'active',
  });
});

test('facts and capability groups are separated and derive only from response fields', () => {
  assert.deepEqual(managedResourceFacts('plugins', plugin), [
    { key: 'source', value: 'marketplace' },
    { key: 'package', value: '@memstack/github' },
    { key: 'version', value: '2.1.0' },
    { key: 'kind', value: 'mcp' },
    { key: 'discovery', value: 'discovered' },
  ]);
  assert.deepEqual(managedResourceCapabilityGroups('plugins', plugin), [
    { key: 'tools', values: ['list_pull_requests'] },
    { key: 'providers', values: ['github'] },
    { key: 'skills', values: ['pull-request-review'] },
    { key: 'channels', values: ['issues'] },
  ]);
  assert.deepEqual(managedResourceCapabilityGroups('agents', agent), [
    { key: 'tools', values: ['read', 'git_diff'] },
    { key: 'skills', values: ['pull-request-review'] },
    { key: 'mcpServers', values: ['github'] },
    { key: 'fallbackModels', values: ['anthropic/claude-opus-4.1'] },
  ]);
  assert.deepEqual(managedResourceFacts('subagents', subagent), [
    { key: 'model', value: 'openai/gpt-5.5' },
    { key: 'project', value: 'project-a' },
    { key: 'source', value: 'database' },
    { key: 'updatedAt', value: '2026-07-21T02:00:00Z' },
  ]);
  assert.deepEqual(managedResourceCapabilityGroups('subagents', subagent), [
    { key: 'tools', values: ['read', 'git_diff'] },
    { key: 'skills', values: ['pull-request-review'] },
    { key: 'mcpServers', values: ['github'] },
    { key: 'fallbackModels', values: ['anthropic/claude-opus-4.1'] },
  ]);
});

test('selection falls back deterministically after filtering or refresh', () => {
  assert.equal(resolveManagedResourceSelection([skill, { ...skill, id: 'two' }], 'two')?.id, 'two');
  assert.equal(resolveManagedResourceSelection([skill], 'missing')?.id, 'research');
  assert.equal(resolveManagedResourceSelection([], 'research'), null);
});

test('resource snapshots fail closed across section and project context switches', () => {
  assert.equal(
    managedResourceSnapshotIsCurrent(
      'skills',
      'cloud:tenant-a:project-a',
      'skills',
      'cloud:tenant-a:project-a',
    ),
    true,
  );
  assert.equal(
    managedResourceSnapshotIsCurrent(
      'plugins',
      'cloud:tenant-a:project-a',
      'skills',
      'cloud:tenant-a:project-a',
    ),
    false,
  );
  assert.equal(
    managedResourceSnapshotIsCurrent(
      'skills',
      'cloud:tenant-a:project-b',
      'skills',
      'cloud:tenant-a:project-a',
    ),
    false,
  );
});

test('status actions honor permission and immutable system resources', () => {
  assert.deepEqual(managedResourceAction('skills', skill, true, 'cloud'), {
    kind: 'set_skill_status',
    nextActive: false,
  });
  assert.deepEqual(managedResourceAction('plugins', plugin, true, 'cloud'), {
    kind: 'set_plugin_enabled',
    nextActive: false,
  });
  assert.deepEqual(managedResourceAction('agents', agent, true, 'cloud'), {
    kind: 'set_agent_enabled',
    nextActive: false,
  });
  assert.deepEqual(managedResourceAction('subagents', subagent, true, 'cloud'), {
    kind: 'set_subagent_enabled',
    nextActive: false,
  });
  assert.equal(
    managedResourceAction('skills', { ...skill, is_system_skill: true }, true, 'cloud'),
    null,
  );
  assert.equal(
    managedResourceAction(
      'skills',
      { ...skill, scope: 'system', is_system_skill: false },
      true,
      'cloud',
    ),
    null,
  );
  assert.deepEqual(
    managedResourceAction('plugins', { ...plugin, source: 'builtin' }, true, 'cloud'),
    { kind: 'set_plugin_enabled', nextActive: false },
  );
  assert.equal(
    managedResourceAction('plugins', { ...plugin, source: 'builtin' }, true, 'local'),
    null,
  );
  assert.equal(
    managedResourceAction('agents', { ...agent, id: 'builtin:all-access' }, true, 'cloud'),
    null,
  );
  assert.equal(managedResourceAction('agents', agent, false, 'cloud'), null);
  assert.equal(
    managedResourceAction('subagents', { ...subagent, source: 'filesystem' }, true, 'cloud'),
    null,
  );
});

test('resource management permissions match local and cloud endpoint allow-lists', () => {
  assert.equal(managedResourceManagementAllowed('local', ['owner'], 'agents', agent), true);
  assert.equal(managedResourceManagementAllowed('local', ['member'], 'skills', skill), false);
  assert.equal(managedResourceManagementAllowed('cloud', ['owner'], 'plugins', plugin), true);
  assert.equal(managedResourceManagementAllowed('cloud', ['owner'], 'agents', agent), true);
  assert.equal(managedResourceManagementAllowed('cloud', ['owner'], 'subagents', subagent), true);
  assert.equal(managedResourceManagementAllowed('cloud', ['member'], 'subagents', subagent), false);
  assert.equal(
    managedResourceManagementAllowed('cloud', ['member'], 'skills', {
      ...skill,
      scope: 'project',
    }),
    true,
  );
  assert.equal(managedResourceManagementAllowed('cloud', ['member'], 'skills', skill), false);
});
