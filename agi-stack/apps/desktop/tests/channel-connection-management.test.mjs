import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
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

test('settings channel management has one mandatory V2 authority and no guessed schema fallback', () => {
  const source = readFileSync(
    new URL('../src/features/settings/useChannelConnectionManagement.ts', import.meta.url),
    'utf8',
  );
  const model = readFileSync(
    new URL('../src/features/settings/channelConnectionModel.ts', import.meta.url),
    'utf8',
  );
  assert.match(source, /projectChannelsOperationsV2/u);
  assert.match(source, /createDesktopProjectChannelsClientV2/u);
  assert.doesNotMatch(source, /DesktopApiClient|legacyChannelConfigSchema/u);
  assert.doesNotMatch(model, /legacyChannelConfigSchema/u);
});
