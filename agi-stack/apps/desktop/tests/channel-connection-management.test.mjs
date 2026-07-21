import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  channelConnectionDraftFrom,
  channelConnectionFields,
  channelConnectionMutationFromDraft,
  validateChannelConnectionDraft,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/settings/channelConnectionModel.js'
);
const { DesktopApiClient } = require('/tmp/agistack-desktop-test-dist/src/api/client.js');
const { DEFAULT_CONFIG } = require('/tmp/agistack-desktop-test-dist/src/types.js');

const schema = {
  channel_type: 'slack',
  plugin_name: 'slack',
  source: 'entrypoint',
  schema_supported: true,
  config_schema: {
    type: 'object',
    required: ['bot_token', 'connection_mode'],
    properties: {
      bot_token: { type: 'string', title: 'Bot token' },
      connection_mode: { type: 'string', enum: ['websocket', 'webhook'] },
      mention_required: { type: 'boolean', title: 'Require mention' },
      retry_limit: { type: 'integer', minimum: 0, maximum: 8 },
    },
  },
  config_ui_hints: {
    bot_token: { label: 'Bot token', sensitive: true },
    retry_limit: { label: 'Retry limit' },
  },
  defaults: { connection_mode: 'websocket', mention_required: true, retry_limit: 3 },
  secret_paths: ['bot_token'],
};

test('channel connection fields preserve dynamic schema types and create requirements', () => {
  assert.deepEqual(channelConnectionFields(schema), [
    {
      name: 'bot_token',
      label: 'Bot token',
      kind: 'secret',
      required: true,
      placeholder: '',
      help: '',
      options: [],
      minimum: null,
      maximum: null,
    },
    {
      name: 'connection_mode',
      label: 'connection_mode',
      kind: 'select',
      required: true,
      placeholder: '',
      help: '',
      options: ['websocket', 'webhook'],
      minimum: null,
      maximum: null,
    },
    {
      name: 'mention_required',
      label: 'Require mention',
      kind: 'boolean',
      required: false,
      placeholder: '',
      help: '',
      options: [],
      minimum: null,
      maximum: null,
    },
    {
      name: 'retry_limit',
      label: 'Retry limit',
      kind: 'integer',
      required: false,
      placeholder: '',
      help: '',
      options: [],
      minimum: 0,
      maximum: 8,
    },
  ]);
});

test('channel connection drafts merge defaults and persisted custom settings without secrets', () => {
  assert.deepEqual(
    channelConnectionDraftFrom(schema, {
      id: 'channel-1',
      project_id: 'project-1',
      channel_type: 'slack',
      name: 'Incident room',
      enabled: true,
      connection_mode: 'webhook',
      extra_settings: {
        bot_token: '__MEMSTACK_SECRET_UNCHANGED__',
        mention_required: false,
        retry_limit: 5,
      },
      dm_policy: 'open',
      group_policy: 'open',
      rate_limit_per_minute: 60,
      status: 'connected',
      created_at: '2026-07-21T00:00:00Z',
    }),
    {
      channelType: 'slack',
      name: 'Incident room',
      enabled: true,
      description: '',
      values: {
        bot_token: '',
        connection_mode: 'webhook',
        mention_required: false,
        retry_limit: 5,
      },
    },
  );
});

test('channel mutations split model fields from extra settings and preserve unchanged edit secrets', () => {
  const draft = {
    channelType: 'slack',
    name: ' Incident room ',
    enabled: false,
    description: ' Alert routing ',
    values: {
      bot_token: ' xoxb-new ',
      connection_mode: 'websocket',
      mention_required: true,
      retry_limit: '4',
      injected: 'must-not-leave-client',
    },
  };
  assert.deepEqual(channelConnectionMutationFromDraft(schema, draft, false), {
    channel_type: 'slack',
    name: 'Incident room',
    enabled: false,
    description: 'Alert routing',
    connection_mode: 'websocket',
    extra_settings: { bot_token: 'xoxb-new', mention_required: true, retry_limit: 4 },
  });
  assert.deepEqual(
    channelConnectionMutationFromDraft(
      schema,
      { ...draft, values: { ...draft.values, bot_token: '' } },
      true,
    ),
    {
      name: 'Incident room',
      enabled: false,
      description: 'Alert routing',
      connection_mode: 'websocket',
      extra_settings: { mention_required: true, retry_limit: 4 },
    },
  );
});

test('channel validation requires create secrets but permits unchanged edit secrets', () => {
  const draft = {
    channelType: 'slack',
    name: '',
    enabled: true,
    description: '',
    values: {
      bot_token: '',
      connection_mode: 'unsupported',
      retry_limit: 9,
    },
  };
  assert.deepEqual(validateChannelConnectionDraft(schema, draft, false), {
    name: 'required',
    bot_token: 'required',
    connection_mode: 'invalid_option',
    retry_limit: 'maximum',
  });
  assert.deepEqual(validateChannelConnectionDraft(schema, { ...draft, name: 'Alerts' }, true), {
    connection_mode: 'invalid_option',
    retry_limit: 'maximum',
  });
});

test('desktop channel API uses tenant catalog and project config contracts', async () => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (input, init) => {
    calls.push([String(input), init?.method, init?.body]);
    const url = String(input);
    if (url.endsWith('/channel-catalog')) return Response.json({ items: [] });
    if (url.endsWith('/schema')) return Response.json(schema);
    if (url.endsWith('/configs')) return Response.json({ items: [], total: 0 });
    if (init?.method === 'DELETE') return new Response(null, { status: 204 });
    return Response.json({ success: true, message: 'ok' });
  };

  try {
    const client = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      mode: 'cloud',
      apiBaseUrl: 'http://127.0.0.1:8088',
      tenantId: 'tenant 1',
      projectId: 'project 1',
    });
    await client.listManagedChannelCatalog();
    await client.getManagedChannelSchema('slack/events');
    await client.listManagedChannelConfigs();
    await client.createManagedChannelConfig({ channel_type: 'slack', name: 'Alerts' });
    await client.updateManagedChannelConfig('channel/1', { enabled: false });
    await client.testManagedChannelConfig('channel/1');
    await client.deleteManagedChannelConfig('channel/1');

    assert.deepEqual(calls, [
      ['http://127.0.0.1:8088/api/v1/channels/tenants/tenant%201/plugins/channel-catalog', 'GET', undefined],
      ['http://127.0.0.1:8088/api/v1/channels/tenants/tenant%201/plugins/channel-catalog/slack%2Fevents/schema', 'GET', undefined],
      ['http://127.0.0.1:8088/api/v1/channels/projects/project%201/configs', 'GET', undefined],
      ['http://127.0.0.1:8088/api/v1/channels/projects/project%201/configs', 'POST', JSON.stringify({ channel_type: 'slack', name: 'Alerts' })],
      ['http://127.0.0.1:8088/api/v1/channels/configs/channel%2F1', 'PUT', JSON.stringify({ enabled: false })],
      ['http://127.0.0.1:8088/api/v1/channels/configs/channel%2F1/test', 'POST', undefined],
      ['http://127.0.0.1:8088/api/v1/channels/configs/channel%2F1', 'DELETE', undefined],
    ]);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
