import type { ChannelConfig, CreateChannelConfig, UpdateChannelConfig } from '@/types/channel';

export const SECRET_UNCHANGED_SENTINEL = '__MEMSTACK_SECRET_UNCHANGED__';

export const CHANNEL_SETTING_FIELDS = new Set([
  'app_id',
  'app_secret',
  'encrypt_key',
  'verification_token',
  'connection_mode',
  'webhook_url',
  'webhook_port',
  'webhook_path',
  'domain',
]);

const LEGACY_SECRET_FIELDS = new Set(['app_secret', 'encrypt_key', 'verification_token']);

export const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null;

const removeUndefinedValues = (record: Record<string, unknown>): Record<string, unknown> =>
  Object.fromEntries(Object.entries(record).filter(([, value]) => value !== undefined));

const removeEmptySecretValues = (
  record: Record<string, unknown>,
  secretPaths: Set<string>,
  isSecretKey: (key: string) => boolean
): Record<string, unknown> =>
  Object.fromEntries(
    Object.entries(record).filter(
      ([key, value]) =>
        !(secretPaths.has(key) && isSecretKey(key) && (value === undefined || value === ''))
    )
  );

const removeSecretSentinelValues = (
  record: Record<string, unknown> | undefined
): Record<string, unknown> | undefined => {
  if (!record) return undefined;
  const sanitized = Object.fromEntries(
    Object.entries(record).filter(([, value]) => value !== SECRET_UNCHANGED_SENTINEL)
  );
  return Object.keys(sanitized).length > 0 ? sanitized : undefined;
};

const sanitizeExtraSettingsForSubmit = (
  extraSettings: Record<string, unknown> | undefined,
  secretPaths: Set<string>,
  editingConfig: ChannelConfig | null
): Record<string, unknown> | undefined => {
  if (!extraSettings) return undefined;

  const sanitized = Object.fromEntries(
    Object.entries(extraSettings).filter(([key, value]) => {
      if (value === undefined || value === SECRET_UNCHANGED_SENTINEL) {
        return false;
      }
      return !(editingConfig && secretPaths.has(key) && value === '');
    })
  );

  return Object.keys(sanitized).length > 0 ? sanitized : undefined;
};

export const getChannelConfigEditValues = (config: ChannelConfig): Record<string, unknown> => ({
  ...config,
  app_secret: undefined,
  encrypt_key: undefined,
  verification_token: undefined,
  extra_settings: removeSecretSentinelValues(
    isRecord(config.extra_settings) ? config.extra_settings : undefined
  ),
});

export const getChannelConfigSubmitValues = (
  values: CreateChannelConfig | UpdateChannelConfig,
  options: {
    editingConfig: ChannelConfig | null;
    schemaSecretPaths?: string[] | undefined;
    schemaSupported?: boolean | undefined;
  }
): Partial<CreateChannelConfig & UpdateChannelConfig> => {
  let mutablePayload: Record<string, unknown> = { ...values };
  const schemaSecretPaths = new Set(options.schemaSecretPaths ?? []);
  let extraSettings = isRecord(mutablePayload.extra_settings)
    ? { ...mutablePayload.extra_settings }
    : undefined;

  if (options.schemaSupported) {
    mutablePayload = options.editingConfig
      ? removeEmptySecretValues(mutablePayload, schemaSecretPaths, (key) =>
          CHANNEL_SETTING_FIELDS.has(key)
        )
      : mutablePayload;
  } else if (options.editingConfig) {
    mutablePayload = removeEmptySecretValues(mutablePayload, LEGACY_SECRET_FIELDS, () => true);
  }

  extraSettings = sanitizeExtraSettingsForSubmit(
    extraSettings,
    schemaSecretPaths,
    options.editingConfig
  );

  return removeUndefinedValues({
    ...mutablePayload,
    extra_settings: extraSettings,
  }) as Partial<CreateChannelConfig & UpdateChannelConfig>;
};
