import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  copyProviderPublicConfigV2,
  declaredProviderAudioModelsV2,
  providerAudioProtocolSupportedV2,
} = require('/tmp/agistack-desktop-test-dist/src/plugins/desktopProviderPublicConfigV2.js');

test('public provider configuration preserves documented tuning and creates independent nested values', () => {
  const source = {
    temperature: 0.4,
    max_tokens: 1000,
    top_p: 0.8,
    timeout: 10,
    timeout_seconds: 12,
    request_timeout_seconds: 120,
    connect_timeout_seconds: 5,
    frequency_penalty: 0,
    presence_penalty: -0.1,
    seed: 7,
    max_retries: 2,
    region: 'cn-beijing',
    audio_input_models: ['opaque'],
    retries: { max_attempts: 2, base_delay: 0.5, max_delay: 10, backoff_factor: 2 },
    transport: {
      connect_timeout_seconds: 5,
      request_timeout_seconds: 120,
      idle_timeout_seconds: 30,
    },
    embedding: {
      model: 'opaque-embedding',
      dimensions: 1024,
      encoding_format: 'float',
      user: 'fixture-owner',
      timeout: 10,
      provider_options: { batch_size: 8, input_type: 'search_query', truncate: 'END' },
    },
  };
  const copy = copyProviderPublicConfigV2(source, true);
  assert.deepEqual(copy, source);
  source.audio_input_models.push('another');
  source.retries.max_attempts = 9;
  source.embedding.provider_options.batch_size = 99;
  assert.deepEqual(copy.audio_input_models, ['opaque']);
  assert.equal(copy.retries.max_attempts, 2);
  assert.equal(copy.embedding.provider_options.batch_size, 8);
  assert.deepEqual(copyProviderPublicConfigV2({}), {});
  assert.deepEqual(copyProviderPublicConfigV2({ embedding: { encoding_format: 'base64' } }), {
    embedding: { encoding_format: 'base64' },
  });
});

test('response projection drops non-public fields and request validation rejects them', () => {
  const source = {
    temperature: 0.4,
    api_key: 'private-fixture',
    headers: { authorization: 'private-fixture' },
    retries: { max_attempts: 2, callback: 'private-fixture' },
    transport: { request_timeout_seconds: 120, base_url: 'private-fixture' },
    embedding: {
      model: 'opaque',
      token: 'private-fixture',
      provider_options: { batch_size: 8, headers: { authorization: 'private-fixture' } },
    },
  };
  const copy = copyProviderPublicConfigV2(source);
  assert.equal(JSON.stringify(copy).includes('private-fixture'), false);
  assert.equal(copy.embedding.provider_options.batch_size, 8);
  for (const config of [
    source,
    { retries: { callback: '' } },
    { transport: { base_url: '' } },
    { embedding: { token: '' } },
    { embedding: { provider_options: { headers: {} } } },
  ])
    assert.throws(() => copyProviderPublicConfigV2(config, true), /public_config_invalid/);
});

test('malformed numeric, region and nested configuration fails without coercion', () => {
  for (const value of [null, [], 'config', true])
    assert.throws(() => copyProviderPublicConfigV2(value), /public_config_invalid/);
  for (const temperature of ['0.4', null, true, NaN, Infinity])
    assert.throws(() => copyProviderPublicConfigV2({ temperature }), /public_config_invalid/);
  for (const region of ['', 'cn beijing', '北京', 'a'.repeat(65), 3])
    assert.throws(() => copyProviderPublicConfigV2({ region }), /public_config_invalid/);
  for (const config of [
    { retries: [] },
    { transport: null },
    { embedding: [] },
    { retries: { max_attempts: '2' } },
    { transport: { request_timeout_seconds: true } },
  ])
    assert.throws(() => copyProviderPublicConfigV2(config), /public_config_invalid/);
});

test('embedding options preserve only supported scalar forms and enum values', () => {
  for (const config of [
    { model: '' },
    { model: 'x'.repeat(513) },
    { model: 'bad\n' },
    { user: 3 },
    { encoding_format: 'arbitrary' },
    { provider_options: [] },
    ...[0, 2049, 1.5, '8'].map((batch_size) => ({ provider_options: { batch_size } })),
    { provider_options: { input_type: 'arbitrary' } },
    { provider_options: { truncate: 'arbitrary' } },
  ])
    assert.throws(() => copyProviderPublicConfigV2({ embedding: config }), /public_config_invalid/);
  for (const input_type of ['search_document', 'search_query', 'classification', 'clustering'])
    for (const truncate of ['NONE', 'START', 'END'])
      assert.deepEqual(
        copyProviderPublicConfigV2({ embedding: { provider_options: { input_type, truncate } } })
          .embedding.provider_options,
        { input_type, truncate },
      );
});

test('audio model declarations remain bounded exact unique identifiers', () => {
  const input = ['opaque', 'ep-fixture'];
  assert.deepEqual(declaredProviderAudioModelsV2(input), input);
  assert.notEqual(declaredProviderAudioModelsV2(input), input);
  for (const value of [
    undefined,
    null,
    'opaque',
    [3],
    [''],
    [' opaque'],
    ['bad\n'],
    ['a'.repeat(257)],
    ['opaque', 'opaque'],
    Array(101).fill('opaque'),
  ])
    assert.throws(() => declaredProviderAudioModelsV2(value), /public_config_invalid/);
});

test('audio protocol support comes from exact provider metadata', () => {
  assert.equal(providerAudioProtocolSupportedV2('openai_compatible', 'local'), true);
  assert.equal(providerAudioProtocolSupportedV2('volcengine', 'local'), false);
  for (const provider of ['openai', 'openrouter', 'lmstudio', 'kimi', 'volcengine'])
    assert.equal(providerAudioProtocolSupportedV2(provider, 'cloud'), true);
  for (const provider of ['anthropic', 'audio-model', 'VOLCENGINE', 'volcengine_custom'])
    assert.equal(providerAudioProtocolSupportedV2(provider, 'cloud'), false);
});
