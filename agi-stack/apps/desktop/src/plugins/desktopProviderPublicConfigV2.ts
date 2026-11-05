import type { LlmProviderPublicConfig } from '../types';

const numericFields = [
  'temperature',
  'max_tokens',
  'top_p',
  'timeout',
  'timeout_seconds',
  'request_timeout_seconds',
  'connect_timeout_seconds',
  'frequency_penalty',
  'presence_penalty',
  'seed',
  'max_retries',
] as const;
const retryFields = ['max_attempts', 'base_delay', 'max_delay', 'backoff_factor'] as const;
const transportFields = [
  'connect_timeout_seconds',
  'request_timeout_seconds',
  'idle_timeout_seconds',
] as const;

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
function invalid(): never {
  throw new TypeError('provider_public_config_invalid');
}
function knownKeys(value: Record<string, unknown>, keys: readonly string[], strict: boolean) {
  if (strict && Object.keys(value).some((key) => !keys.includes(key))) invalid();
}
function numbers(value: Record<string, unknown>, keys: readonly string[]) {
  const result: Record<string, number> = {};
  for (const key of keys) {
    const number = value[key];
    if (number === undefined) continue;
    if (typeof number !== 'number' || !Number.isFinite(number)) invalid();
    result[key] = number;
  }
  return result;
}

export function declaredProviderAudioModelsV2(value: unknown, maximum = 100): string[] {
  if (
    !Array.isArray(value) ||
    value.length > maximum ||
    value.some(
      (model) =>
        typeof model !== 'string' ||
        !model ||
        model !== model.trim() ||
        model.length > 256 ||
        /[\u0000-\u001f\u007f-\u009f]/u.test(model)
    )
  )
    invalid();
  if (new Set(value).size !== value.length) invalid();
  return [...value];
}

/** Preserve the ordinary provider response schema; credentials and arbitrary options stay out. */
export function copyProviderPublicConfigV2(
  value: unknown,
  strict = false
): LlmProviderPublicConfig {
  if (!record(value)) invalid();
  knownKeys(
    value,
    [...numericFields, 'region', 'audio_input_models', 'retries', 'transport', 'embedding'],
    strict
  );
  const result: Record<string, unknown> = numbers(value, numericFields);
  if (value.region !== undefined) {
    if (typeof value.region !== 'string' || !/^[A-Za-z0-9-]{1,64}$/u.test(value.region)) invalid();
    result.region = value.region;
  }
  if (value.audio_input_models !== undefined)
    result.audio_input_models = declaredProviderAudioModelsV2(value.audio_input_models);
  for (const [key, fields] of [
    ['retries', retryFields],
    ['transport', transportFields],
  ] as const) {
    const nested = value[key];
    if (nested === undefined) continue;
    if (!record(nested)) invalid();
    knownKeys(nested, fields, strict);
    result[key] = numbers(nested, fields);
  }
  if (value.embedding !== undefined) {
    if (!record(value.embedding)) invalid();
    const input = value.embedding;
    knownKeys(
      input,
      ['model', 'dimensions', 'encoding_format', 'user', 'timeout', 'provider_options'],
      strict
    );
    const embedding: Record<string, unknown> = numbers(input, ['dimensions', 'timeout']);
    for (const key of ['model', 'user']) {
      const text = input[key];
      if (text === undefined) continue;
      if (
        typeof text !== 'string' ||
        !text ||
        text.length > 512 ||
        /[\u0000-\u001f\u007f-\u009f]/u.test(text)
      )
        invalid();
      embedding[key] = text;
    }
    if (input.encoding_format !== undefined) {
      if (input.encoding_format !== 'float' && input.encoding_format !== 'base64') invalid();
      embedding.encoding_format = input.encoding_format;
    }
    if (input.provider_options !== undefined) {
      if (!record(input.provider_options)) invalid();
      const options = input.provider_options;
      knownKeys(options, ['batch_size', 'input_type', 'truncate'], strict);
      const output: Record<string, unknown> = {};
      if (options.batch_size !== undefined) {
        if (
          !Number.isSafeInteger(options.batch_size) ||
          Number(options.batch_size) < 1 ||
          Number(options.batch_size) > 2048
        )
          invalid();
        output.batch_size = options.batch_size;
      }
      if (options.input_type !== undefined) {
        if (
          !['search_document', 'search_query', 'classification', 'clustering'].includes(
            String(options.input_type)
          )
        )
          invalid();
        output.input_type = options.input_type;
      }
      if (options.truncate !== undefined) {
        if (!['NONE', 'START', 'END'].includes(String(options.truncate))) invalid();
        output.truncate = options.truncate;
      }
      embedding.provider_options = output;
    }
    result.embedding = embedding;
  }
  return result as LlmProviderPublicConfig;
}

export function providerAudioProtocolSupportedV2(
  provider: string,
  mode: 'local' | 'cloud'
): boolean {
  return mode === 'local'
    ? ['openai', 'openai_compatible'].includes(provider)
    : ['openai', 'openrouter', 'lmstudio', 'kimi', 'volcengine'].includes(provider);
}
