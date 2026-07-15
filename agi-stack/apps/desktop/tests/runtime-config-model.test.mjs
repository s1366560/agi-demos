import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const { updateRuntimeConnectionConfig } = require(
  '/tmp/agistack-desktop-test-dist/src/features/runtime/runtimeConfigModel.js'
);

const governedConfig = {
  apiBaseUrl: 'http://127.0.0.1:8088',
  apiKey: 'session-key',
  localApiToken: 'launch-capability',
  tenantId: 'tenant-1',
  projectId: 'project-1',
  workspaceId: 'workspace-1',
  mode: 'local',
  llmProvider: 'openai',
  llmBaseUrl: 'https://llm.example/v1',
  llmModel: 'model-1',
  llmApiKey: 'provider-secret',
  workspaceRoot: '/workspace/root',
};

test('connection recovery updates only its selected transport field', () => {
  const cases = [
    ['apiBaseUrl', 'https://desktop.example'],
    ['apiKey', 'new-session-key'],
    ['mode', 'cloud'],
  ];

  for (const [field, value] of cases) {
    const updated = updateRuntimeConnectionConfig(governedConfig, field, value);

    assert.equal(updated[field], value);
    for (const governedField of [
      'localApiToken',
      'tenantId',
      'projectId',
      'workspaceId',
      'llmProvider',
      'llmBaseUrl',
      'llmModel',
      'llmApiKey',
      'workspaceRoot',
    ]) {
      assert.equal(updated[governedField], governedConfig[governedField]);
    }
  }
});
