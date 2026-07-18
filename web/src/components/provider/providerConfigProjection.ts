const TOP_LEVEL_NUMBER_KEYS = [
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

const RETRY_NUMBER_KEYS = ['max_attempts', 'base_delay', 'max_delay', 'backoff_factor'] as const;

const TRANSPORT_NUMBER_KEYS = [
  'connect_timeout_seconds',
  'request_timeout_seconds',
  'idle_timeout_seconds',
] as const;

const SAFE_EMBEDDING_INPUT_TYPES = new Set([
  'search_document',
  'search_query',
  'classification',
  'clustering',
]);

const SAFE_EMBEDDING_TRUNCATE_VALUES = new Set(['NONE', 'START', 'END']);

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

const projectFiniteNumbers = (
  source: Record<string, unknown>,
  keys: readonly string[]
): Record<string, number> => {
  const projected: Record<string, number> = {};
  for (const key of keys) {
    const value = source[key];
    if (typeof value === 'number' && Number.isFinite(value)) {
      projected[key] = value;
    }
  }
  return projected;
};

export const projectSafeEmbeddingProviderOptions = (value: unknown): Record<string, unknown> => {
  if (!isRecord(value)) return {};

  const projected: Record<string, unknown> = {};
  if (
    typeof value.batch_size === 'number' &&
    Number.isInteger(value.batch_size) &&
    value.batch_size >= 1 &&
    value.batch_size <= 2048
  ) {
    projected.batch_size = value.batch_size;
  }
  if (typeof value.input_type === 'string' && SAFE_EMBEDDING_INPUT_TYPES.has(value.input_type)) {
    projected.input_type = value.input_type;
  }
  if (typeof value.truncate === 'string' && SAFE_EMBEDDING_TRUNCATE_VALUES.has(value.truncate)) {
    projected.truncate = value.truncate;
  }
  return projected;
};

export const projectSafeEmbeddingConfig = (value: unknown): Record<string, unknown> => {
  if (!isRecord(value)) return {};

  const projected: Record<string, unknown> = {};
  if (typeof value.dimensions === 'number' && Number.isFinite(value.dimensions)) {
    projected.dimensions = value.dimensions;
  }
  if (typeof value.timeout === 'number' && Number.isFinite(value.timeout)) {
    projected.timeout = value.timeout;
  }
  if (typeof value.model === 'string' && value.model.trim()) {
    projected.model = value.model.trim();
  }
  if (typeof value.user === 'string' && value.user.trim()) {
    projected.user = value.user.trim();
  }
  if (value.encoding_format === 'float' || value.encoding_format === 'base64') {
    projected.encoding_format = value.encoding_format;
  }
  const providerOptions = projectSafeEmbeddingProviderOptions(value.provider_options);
  if (Object.keys(providerOptions).length > 0) {
    projected.provider_options = providerOptions;
  }
  return projected;
};

/**
 * Projects provider configuration onto the backend's public, non-secret schema.
 * Unknown keys are intentionally dropped so UI state can never become a credential side channel.
 */
export const projectSafeProviderConfig = (value: unknown): Record<string, unknown> => {
  if (!isRecord(value)) return {};

  const projected: Record<string, unknown> = projectFiniteNumbers(value, TOP_LEVEL_NUMBER_KEYS);
  if (typeof value.region === 'string' && /^[A-Za-z0-9-]+$/.test(value.region)) {
    projected.region = value.region;
  }

  if (isRecord(value.retries)) {
    const retries = projectFiniteNumbers(value.retries, RETRY_NUMBER_KEYS);
    if (Object.keys(retries).length > 0) projected.retries = retries;
  }

  if (isRecord(value.transport)) {
    const transport = projectFiniteNumbers(value.transport, TRANSPORT_NUMBER_KEYS);
    if (Object.keys(transport).length > 0) projected.transport = transport;
  }

  const embedding = projectSafeEmbeddingConfig(value.embedding);
  if (Object.keys(embedding).length > 0) projected.embedding = embedding;

  return projected;
};
