import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  applyRuntimeServerPreset,
  runtimeTransportIdentityChanged,
  updateRuntimeConnectionConfig,
} = require(
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

test('connection recovery preserves governed settings while isolating transport credentials', () => {
  const apiKeyUpdate = updateRuntimeConnectionConfig(governedConfig, 'apiKey', 'new-session-key');
  assert.equal(apiKeyUpdate.apiKey, 'new-session-key');

  const sameOriginPath = updateRuntimeConnectionConfig(
    governedConfig,
    'apiBaseUrl',
    'http://127.0.0.1:8088/api/v2',
  );
  assert.equal(sameOriginPath.apiKey, governedConfig.apiKey);
  assert.equal(sameOriginPath.localApiToken, governedConfig.localApiToken);

  const crossOrigin = updateRuntimeConnectionConfig(
    governedConfig,
    'apiBaseUrl',
    'https://desktop.example',
  );
  assert.equal(crossOrigin.apiKey, '');
  assert.equal(crossOrigin.localApiToken, '');

  const modeChange = updateRuntimeConnectionConfig(governedConfig, 'mode', 'cloud');
  assert.equal(modeChange.apiKey, '');
  assert.equal(modeChange.localApiToken, '');

  const invalidTransientUrl = updateRuntimeConnectionConfig(
    governedConfig,
    'apiBaseUrl',
    'http://',
  );
  assert.equal(invalidTransientUrl.apiKey, '');
  assert.equal(invalidTransientUrl.localApiToken, '');

  const invalidSourceToNewOrigin = updateRuntimeConnectionConfig(
    { ...governedConfig, apiBaseUrl: 'http://', apiKey: governedConfig.apiKey },
    'apiBaseUrl',
    'https://new-runtime.example',
  );
  assert.equal(invalidSourceToNewOrigin.apiKey, '');
  assert.equal(invalidSourceToNewOrigin.localApiToken, '');

  for (const updated of [apiKeyUpdate, sameOriginPath, crossOrigin, modeChange]) {
    for (const governedField of [
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

test('server presets atomically select the compatible transport mode', () => {
  const python = applyRuntimeServerPreset(governedConfig, {
    apiBaseUrl: 'http://127.0.0.1:8000',
    mode: 'cloud',
  });
  assert.equal(python.apiBaseUrl, 'http://127.0.0.1:8000');
  assert.equal(python.mode, 'cloud');
  assert.equal(python.localApiToken, '');
  assert.equal(python.apiKey, '');
  assert.equal(python.llmApiKey, governedConfig.llmApiKey);

  const rust = applyRuntimeServerPreset(python, {
    apiBaseUrl: 'http://127.0.0.1:8088',
    mode: 'local',
  });
  assert.equal(rust.apiBaseUrl, 'http://127.0.0.1:8088');
  assert.equal(rust.mode, 'local');
  assert.equal(rust.apiKey, '');
});

test('runtime transport identity is based on mode and normalized origin', () => {
  assert.equal(
    runtimeTransportIdentityChanged(governedConfig, {
      ...governedConfig,
      apiBaseUrl: 'http://127.0.0.1:8088/api/v2',
    }),
    false,
  );
  assert.equal(
    runtimeTransportIdentityChanged(governedConfig, {
      ...governedConfig,
      apiBaseUrl: 'http://localhost:8088',
    }),
    true,
  );
  assert.equal(
    runtimeTransportIdentityChanged(governedConfig, { ...governedConfig, mode: 'cloud' }),
    true,
  );
  assert.equal(
    runtimeTransportIdentityChanged(governedConfig, {
      ...governedConfig,
      apiBaseUrl: 'http://',
    }),
    true,
  );
  assert.equal(
    runtimeTransportIdentityChanged(
      { ...governedConfig, apiBaseUrl: 'http://' },
      { ...governedConfig, apiBaseUrl: 'https://new-runtime.example' },
    ),
    true,
  );
  assert.equal(
    runtimeTransportIdentityChanged(
      { ...governedConfig, apiBaseUrl: 'file:///tmp/runtime-a' },
      { ...governedConfig, apiBaseUrl: 'file:///tmp/runtime-b' },
    ),
    true,
  );
});
