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
  managedResourceFactValueKey,
  managedResourceView,
  resolveManagedResourceSelection,
  resourceIsActive,
  resourceIsImmutable,
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
  id: 'github@2.1.0',
  name: 'github',
  plugin_id: 'github',
  publisher: 'MemStack Labs',
  source: 'marketplace-v2',
  package: 'plugins/github',
  version: '2.1.0',
  kind: 'bundle-v2',
  install_status: 'installed',
  security_scan_status: 'passed',
  revoked: false,
  enabled: true,
  discovered: true,
  targets: ['python', 'desktop-renderer'],
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
  assert.equal(resourceIsActive('plugins', { ...plugin, revoked: true }), false);
  assert.equal(resourceIsActive('agents', agent), true);
  assert.equal(resourceIsActive('agents', { ...agent, enabled: false, status: 'active' }), false);
  assert.equal(
    resourceIsActive('agents', { ...agent, enabled: undefined, status: 'disabled' }),
    false,
  );
  assert.equal(resourceIsActive('subagents', subagent), true);
  assert.equal(resourceIsActive('subagents', { ...subagent, enabled: false }), false);
});

test('revoked installed plugins can be uninstalled without becoming runnable', () => {
  const revoked = { ...plugin, revoked: true };
  for (const mode of ['local', 'cloud']) {
    assert.equal(resourceIsImmutable('plugins', revoked, mode), false);
    assert.equal(resourceIsActive('plugins', revoked), false);
    assert.equal(managedResourceAction('plugins', revoked, true, mode), null);
    assert.equal(
      resourceIsImmutable('plugins', { ...revoked, install_status: 'uninstalled' }, mode),
      true,
    );
  }
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
  const plugins = [
    plugin,
    {
      ...plugin,
      id: 'offline@2.1.0',
      name: 'offline',
      install_status: 'uninstalled',
      enabled: false,
    },
  ];
  assert.deepEqual(
    filterManagedResources('plugins', plugins, '', 'active').map((item) => item.id),
    ['github@2.1.0'],
  );
  assert.deepEqual(
    filterManagedResources('plugins', plugins, '', 'attention').map((item) => item.id),
    ['offline@2.1.0'],
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
      publisher: '',
      package: '',
      targets: [],
    }),
    {
      id: 'github@2.1.0',
      title: 'github',
      description: 'bundle-v2',
      meta: [
        { kind: 'text', value: 'marketplace-v2' },
        { kind: 'version', value: '2.1.0' },
      ],
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
    { key: 'source', value: 'marketplace-v2' },
    { key: 'publisher', value: 'MemStack Labs' },
    { key: 'version', value: '2.1.0' },
    { key: 'installStatus', value: 'installed' },
    { key: 'revocationStatus', value: 'notRevoked' },
    { key: 'securityScan', value: 'passed' },
  ]);
  assert.deepEqual(managedResourceCapabilityGroups('plugins', plugin), [
    { key: 'targets', values: ['python', 'desktop-renderer'] },
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
  assert.equal(managedResourceAction('plugins', plugin, true, 'cloud'), null);
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
  assert.equal(managedResourceAction('plugins', plugin, true, 'local'), null);
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
  assert.equal(managedResourceManagementAllowed('cloud', ['owner'], 'plugins', plugin), false);
  assert.equal(managedResourceManagementAllowed('cloud', ['admin'], 'plugins', plugin, false), false);
  assert.equal(managedResourceManagementAllowed('cloud', ['member'], 'plugins', plugin, true), true);
  assert.equal(managedResourceManagementAllowed('local', ['owner'], 'plugins', plugin), true);
  assert.equal(managedResourceManagementAllowed('local', ['member'], 'plugins', plugin, true), false);
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

test('catalog history keeps independent install and revocation facts with explicit localized states', () => {
  const history = { ...plugin, install_status: 'uninstalled', revoked: true };
  const facts = managedResourceFacts('plugins', history);
  assert.ok(facts.some((fact) => fact.key === 'installStatus' && fact.value === 'uninstalled'));
  assert.ok(facts.some((fact) => fact.key === 'revocationStatus' && fact.value === 'revoked'));
  assert.equal(resourceIsActive('plugins', history), false);
  assert.deepEqual(filterManagedResources('plugins', [history], '', 'all'), [history]);
  for (const status of ['installed', 'uninstalled', 'verified']) {
    assert.equal(managedResourceFactValueKey('installStatus', status), `settings.pluginInstallStatus.${status}`);
  }
  for (const status of ['revoked', 'notRevoked']) {
    assert.equal(managedResourceFactValueKey('revocationStatus', status), `settings.pluginRevocationStatus.${status}`);
  }
  for (const status of [null, '', 'future-status']) {
    assert.equal(managedResourceFactValueKey('installStatus', status), 'settings.pluginInstallStatus.unknown');
    assert.equal(managedResourceFactValueKey('revocationStatus', status), 'settings.pluginRevocationStatus.unknown');
  }
  assert.equal(managedResourceFactValueKey('publisher', 'Example'), null);
});
