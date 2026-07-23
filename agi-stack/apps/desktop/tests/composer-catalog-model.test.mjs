import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import test from 'node:test';

const require = createRequire(import.meta.url);
const {
  loadComposerCatalog,
  unboundComposerCatalogClient,
} = require('/tmp/agistack-desktop-test-dist/src/features/chat/composerCatalogModel.js');

test('unbound composer catalog skips workspace agents and loads every project catalog', async () => {
  const calls = [];
  const client = {
    listWorkspaceAgents: async () => {
      calls.push('workspace-agents');
      return [{ id: 'wrong-scope' }];
    },
    listManagedAgents: async () => {
      calls.push('agents');
      return [{ id: 'agent-1' }];
    },
    listManagedSkills: async () => {
      calls.push('skills');
      return [{ id: 'skill-1' }];
    },
    listManagedPlugins: async () => {
      calls.push('plugins');
      return [{ id: 'plugin-1' }];
    },
    listManagedSubAgents: async () => {
      calls.push('subagents');
      return [{ id: 'subagent-1' }];
    },
  };

  const catalog = await loadComposerCatalog(unboundComposerCatalogClient(client));

  assert.deepEqual(calls.sort(), ['agents', 'plugins', 'skills', 'subagents']);
  assert.deepEqual(catalog, {
    workspaceAgents: [],
    agents: [{ id: 'agent-1' }],
    skills: [{ id: 'skill-1' }],
    plugins: [{ id: 'plugin-1' }],
    subagents: [{ id: 'subagent-1' }],
  });
});

test('composer catalog keeps workspace scope behavior for bound clients', async () => {
  const catalog = await loadComposerCatalog({
    listWorkspaceAgents: async () => [{ id: 'binding-1' }],
    listManagedAgents: async () => [],
    listManagedSkills: async () => [],
    listManagedPlugins: async () => [],
  });

  assert.deepEqual(catalog.workspaceAgents, [{ id: 'binding-1' }]);
  assert.deepEqual(catalog.subagents, []);
});
