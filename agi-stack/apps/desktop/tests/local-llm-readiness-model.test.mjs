import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  isModelUnconfiguredError,
  localLlmProviderUsable,
  localLlmUnconfiguredFromProviders,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/chat/localLlmReadinessModel.js',
);

const usableProvider = {
  is_active: true,
  credential_configured: true,
  provider_type: 'openai',
  base_url: 'https://api.example.test/v1',
  llm_model: 'gpt-test',
};

test('a provider passes runtime admission only when active, bound, and credentialed', () => {
  assert.equal(localLlmProviderUsable(usableProvider), true);
  // auth_method "none" providers report credential_configured true sidecar-side.
  assert.equal(
    localLlmProviderUsable({ ...usableProvider, credential_configured: undefined }),
    true,
  );
  assert.equal(localLlmProviderUsable({ ...usableProvider, is_active: false }), false);
  assert.equal(localLlmProviderUsable({ ...usableProvider, credential_configured: false }), false);
  assert.equal(localLlmProviderUsable({ ...usableProvider, llm_model: null }), false);
  assert.equal(localLlmProviderUsable({ ...usableProvider, llm_model: '  ' }), false);
  assert.equal(localLlmProviderUsable({ ...usableProvider, base_url: '' }), false);
  assert.equal(localLlmProviderUsable({ ...usableProvider, provider_type: undefined }), false);
});

test('unconfigured means the catalog is known but no provider passes admission', () => {
  assert.equal(localLlmUnconfiguredFromProviders([]), true);
  assert.equal(localLlmUnconfiguredFromProviders([usableProvider]), false);
  assert.equal(
    localLlmUnconfiguredFromProviders([
      { ...usableProvider, is_active: false },
      usableProvider,
    ]),
    false,
  );
  assert.equal(
    localLlmUnconfiguredFromProviders([{ ...usableProvider, credential_configured: false }]),
    true,
  );
  // Unknown catalog state never blocks the composer.
  assert.equal(localLlmUnconfiguredFromProviders(null), false);
  assert.equal(localLlmUnconfiguredFromProviders(undefined), false);
});

test('the model_unconfigured protocol token is matched exactly, not by prose', () => {
  assert.equal(
    isModelUnconfiguredError(
      'llm error: model_unconfigured: configure a local LLM provider before starting an agent',
    ),
    true,
  );
  assert.equal(isModelUnconfiguredError('model_unconfigured'), true);
  assert.equal(isModelUnconfiguredError('model_timeout: candidate exceeded 45000 ms'), false);
  assert.equal(isModelUnconfiguredError(''), false);
  assert.equal(isModelUnconfiguredError(null), false);
  assert.equal(isModelUnconfiguredError(undefined), false);
});
