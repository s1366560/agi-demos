import type {
  CreateManagedChannelConfigRequest,
  ManagedChannelConfig,
  ManagedChannelPluginConfigSchema,
  PluginConfigSchemaProperty,
  UpdateManagedChannelConfigRequest,
} from '../../types';

export const CHANNEL_SECRET_UNCHANGED = '__MEMSTACK_SECRET_UNCHANGED__';

const CHANNEL_SETTING_FIELDS = new Set([
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

export type ChannelConnectionFieldKind =
  | 'text'
  | 'secret'
  | 'boolean'
  | 'integer'
  | 'number'
  | 'select';

export type ChannelConnectionField = {
  name: string;
  label: string;
  kind: ChannelConnectionFieldKind;
  required: boolean;
  placeholder: string;
  help: string;
  options: Array<string | number | boolean>;
  minimum: number | null;
  maximum: number | null;
};

export type ChannelConnectionDraft = {
  channelType: string;
  name: string;
  enabled: boolean;
  description: string;
  values: Record<string, unknown>;
};

export type ChannelConnectionErrorCode =
  | 'required'
  | 'minimum'
  | 'maximum'
  | 'invalid_number'
  | 'invalid_option';
export type ChannelConnectionErrors = Record<string, ChannelConnectionErrorCode>;

export function legacyChannelConfigSchema(
  channelType: string,
): ManagedChannelPluginConfigSchema {
  return {
    channel_type: channelType,
    plugin_name: channelType,
    source: 'legacy',
    schema_supported: false,
    config_schema: {
      type: 'object',
      properties: {
        connection_mode: { type: 'string', enum: ['websocket', 'webhook'] },
        app_id: { type: 'string' },
        app_secret: { type: 'string' },
        encrypt_key: { type: 'string' },
        verification_token: { type: 'string' },
        webhook_url: { type: 'string' },
        webhook_port: { type: 'integer', minimum: 1, maximum: 65535 },
        webhook_path: { type: 'string' },
        domain: { type: 'string' },
      },
    },
    config_ui_hints: {
      app_secret: { sensitive: true },
      encrypt_key: { sensitive: true },
      verification_token: { sensitive: true },
    },
    defaults: { connection_mode: 'websocket' },
    secret_paths: ['app_secret', 'encrypt_key', 'verification_token'],
  };
}

export function channelConnectionFields(
  schema: ManagedChannelPluginConfigSchema,
): ChannelConnectionField[] {
  const properties = schema.config_schema?.properties ?? {};
  const required = new Set(schema.config_schema?.required ?? []);
  const secrets = new Set(schema.secret_paths);
  const hints = schema.config_ui_hints ?? {};
  return Object.entries(properties)
    .filter(([name]) => !['channel_type', 'name', 'enabled', 'description'].includes(name))
    .map(([name, property]) => {
      const hint = hints[name] ?? {};
      const sensitive = hint.sensitive === true || secrets.has(name);
      return {
        name,
        label: cleanText(hint.label) || cleanText(property.title) || name,
        kind: fieldKind(property, sensitive),
        required: required.has(name),
        placeholder: cleanText(hint.placeholder) || cleanText(property.description),
        help: cleanText(hint.help),
        options: Array.isArray(property.enum) ? [...property.enum] : [],
        minimum: finiteNumber(property.minimum),
        maximum: finiteNumber(property.maximum),
      };
    });
}

export function channelConnectionDraftFrom(
  schema: ManagedChannelPluginConfigSchema,
  config: ManagedChannelConfig | null,
): ChannelConnectionDraft {
  const topLevel = config ? (config as unknown as Record<string, unknown>) : {};
  const source = { ...schema.defaults, ...topLevel, ...config?.extra_settings };
  const secrets = new Set(schema.secret_paths);
  return {
    channelType: config?.channel_type ?? schema.channel_type,
    name: config?.name ?? '',
    enabled: config?.enabled ?? true,
    description: config?.description ?? '',
    values: Object.fromEntries(
      channelConnectionFields(schema).map((field) => {
        const value = source[field.name];
        return [
          field.name,
          secrets.has(field.name)
            ? ''
            : value === undefined || value === CHANNEL_SECRET_UNCHANGED
              ? defaultValue(field.kind)
              : value,
        ];
      }),
    ),
  };
}

export function validateChannelConnectionDraft(
  schema: ManagedChannelPluginConfigSchema,
  draft: ChannelConnectionDraft,
  editing: boolean,
): ChannelConnectionErrors {
  const errors: ChannelConnectionErrors = {};
  if (!draft.name.trim()) errors.name = 'required';
  if (!draft.channelType.trim()) errors.channelType = 'required';
  const secrets = new Set(schema.secret_paths);
  for (const field of channelConnectionFields(schema)) {
    const value = draft.values[field.name];
    if (field.required && isBlank(value) && !(editing && secrets.has(field.name))) {
      errors[field.name] = 'required';
      continue;
    }
    if (isBlank(value)) continue;
    if (field.kind === 'number' || field.kind === 'integer') {
      const number = typeof value === 'number' ? value : Number(value);
      if (!Number.isFinite(number) || (field.kind === 'integer' && !Number.isInteger(number))) {
        errors[field.name] = 'invalid_number';
      } else if (field.minimum !== null && number < field.minimum) {
        errors[field.name] = 'minimum';
      } else if (field.maximum !== null && number > field.maximum) {
        errors[field.name] = 'maximum';
      }
    } else if (
      field.kind === 'select' &&
      !field.options.some((option) => option === value)
    ) {
      errors[field.name] = 'invalid_option';
    }
  }
  return errors;
}

export function channelConnectionMutationFromDraft(
  schema: ManagedChannelPluginConfigSchema,
  draft: ChannelConnectionDraft,
  editing: boolean,
): CreateManagedChannelConfigRequest | UpdateManagedChannelConfigRequest {
  const payload: Record<string, unknown> = {
    ...(editing ? {} : { channel_type: draft.channelType.trim() }),
    name: draft.name.trim(),
    enabled: draft.enabled,
    description: draft.description.trim(),
  };
  const extraSettings: Record<string, unknown> = {};
  const secrets = new Set(schema.secret_paths);
  for (const field of channelConnectionFields(schema)) {
    const value = draft.values[field.name];
    if (value === undefined || value === CHANNEL_SECRET_UNCHANGED) continue;
    if (editing && secrets.has(field.name) && isBlank(value)) continue;
    const normalized = normalizeValue(field, value);
    if (CHANNEL_SETTING_FIELDS.has(field.name)) payload[field.name] = normalized;
    else extraSettings[field.name] = normalized;
  }
  if (Object.keys(extraSettings).length > 0) payload.extra_settings = extraSettings;
  return payload as CreateManagedChannelConfigRequest | UpdateManagedChannelConfigRequest;
}

function fieldKind(
  property: PluginConfigSchemaProperty,
  sensitive: boolean,
): ChannelConnectionFieldKind {
  if (sensitive) return 'secret';
  if (Array.isArray(property.enum) && property.enum.length > 0) return 'select';
  if (property.type === 'boolean') return 'boolean';
  if (property.type === 'integer') return 'integer';
  if (property.type === 'number') return 'number';
  return 'text';
}

function normalizeValue(field: ChannelConnectionField, value: unknown): unknown {
  if (field.kind === 'text' || field.kind === 'secret') {
    return typeof value === 'string' ? value.trim() : value;
  }
  if (field.kind === 'number' || field.kind === 'integer') {
    return typeof value === 'number' ? value : Number(value);
  }
  return value;
}

function defaultValue(kind: ChannelConnectionFieldKind): unknown {
  return kind === 'boolean' ? false : '';
}

function isBlank(value: unknown): boolean {
  return value === null || value === undefined || (typeof value === 'string' && !value.trim());
}

function cleanText(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

function finiteNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}
