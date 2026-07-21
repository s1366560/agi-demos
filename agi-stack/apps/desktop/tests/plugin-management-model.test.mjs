import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  pluginConfigDraftFrom,
  pluginConfigFields,
  pluginConfigMutationFromDraft,
  validatePluginConfigDraft,
  validatePluginRequirement,
} = require('/tmp/agistack-desktop-test-dist/src/features/settings/pluginManagementModel.js');

const schema = {
  plugin_name: 'release-notifier',
  providers: [],
  skills: [],
  enabled: true,
  discovered: true,
  schema_supported: true,
  config_schema: {
    type: 'object',
    required: ['endpoint', 'token'],
    properties: {
      endpoint: {
        type: 'string',
        title: 'Webhook endpoint',
        description: 'Destination URL',
      },
      token: { type: 'string' },
      retries: { type: 'integer', minimum: 0, maximum: 10 },
      enabled: { type: 'boolean' },
      mode: { type: 'string', enum: ['safe', 'fast'] },
    },
  },
  config_ui_hints: {
    token: { label: 'Access token', sensitive: true },
    retries: { label: 'Retry count' },
  },
  defaults: { retries: 3, enabled: true, mode: 'safe' },
  secret_paths: ['token'],
};

test('plugin config fields follow the server schema and UI hints without guessing fields', () => {
  assert.deepEqual(pluginConfigFields(schema), [
    {
      name: 'endpoint',
      label: 'Webhook endpoint',
      kind: 'text',
      required: true,
      placeholder: 'Destination URL',
      help: '',
      options: [],
      minimum: null,
      maximum: null,
    },
    {
      name: 'token',
      label: 'Access token',
      kind: 'secret',
      required: false,
      placeholder: '',
      help: '',
      options: [],
      minimum: null,
      maximum: null,
    },
    {
      name: 'retries',
      label: 'Retry count',
      kind: 'integer',
      required: false,
      placeholder: '',
      help: '',
      options: [],
      minimum: 0,
      maximum: 10,
    },
    {
      name: 'enabled',
      label: 'enabled',
      kind: 'boolean',
      required: false,
      placeholder: '',
      help: '',
      options: [],
      minimum: null,
      maximum: null,
    },
    {
      name: 'mode',
      label: 'mode',
      kind: 'select',
      required: false,
      placeholder: '',
      help: '',
      options: ['safe', 'fast'],
      minimum: null,
      maximum: null,
    },
  ]);
});

test('plugin config drafts merge defaults and persisted values while blanking secret sentinels', () => {
  assert.deepEqual(
    pluginConfigDraftFrom(schema, {
      tenant_id: 'tenant-a',
      plugin_name: 'release-notifier',
      config: {
        endpoint: 'https://hooks.example.test/release',
        token: '__MEMSTACK_SECRET_UNCHANGED__',
        retries: 5,
      },
    }),
    {
      endpoint: 'https://hooks.example.test/release',
      token: '',
      retries: 5,
      enabled: true,
      mode: 'safe',
    },
  );

  assert.equal(
    pluginConfigDraftFrom(schema, {
      tenant_id: 'tenant-a',
      plugin_name: 'release-notifier',
      config: { token: 'server-must-not-expose-this-value' },
    }).token,
    '',
  );
});

test('plugin config mutations allow only schema fields and never overwrite unchanged secrets', () => {
  assert.deepEqual(
    pluginConfigMutationFromDraft(schema, {
      endpoint: ' https://hooks.example.test/release ',
      token: '',
      retries: 0,
      enabled: false,
      mode: 'fast',
      injected: 'must-not-leave-the-client',
    }),
    {
      config: {
        endpoint: 'https://hooks.example.test/release',
        retries: 0,
        enabled: false,
        mode: 'fast',
      },
    },
  );
});

test('plugin validation covers required values, number bounds, enums, and install requirements', () => {
  assert.deepEqual(
    validatePluginConfigDraft(schema, {
      endpoint: ' ',
      token: '',
      retries: 11,
      enabled: true,
      mode: 'unsupported',
    }),
    { endpoint: 'required', retries: 'maximum', mode: 'invalid_option' },
  );
  assert.equal(validatePluginRequirement('  memstack-plugin-github>=2.0  '), null);
  assert.equal(validatePluginRequirement('   '), 'required');
});
