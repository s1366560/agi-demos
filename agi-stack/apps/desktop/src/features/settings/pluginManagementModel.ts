import type {
  PluginActionDetails,
  PluginActionResponse,
  PluginCapabilityCounts,
  PluginConfigRecord,
  PluginConfigSchema,
  PluginConfigSchemaProperty,
  UpdatePluginConfigRequest,
} from '../../types';

export const PLUGIN_SECRET_UNCHANGED = '__MEMSTACK_SECRET_UNCHANGED__';

export type PluginConfigFieldKind =
  | 'text'
  | 'secret'
  | 'boolean'
  | 'integer'
  | 'number'
  | 'select';

export type PluginConfigField = {
  name: string;
  label: string;
  kind: PluginConfigFieldKind;
  required: boolean;
  placeholder: string;
  help: string;
  options: Array<string | number | boolean>;
  minimum: number | null;
  maximum: number | null;
};

export type PluginConfigDraft = Record<string, unknown>;
export type PluginConfigErrorCode =
  | 'required'
  | 'minimum'
  | 'maximum'
  | 'invalid_number'
  | 'invalid_option';
export type PluginConfigErrors = Record<string, PluginConfigErrorCode>;

export type PluginActionTimelineEntry = {
  id: string;
  action: string;
  message: string;
  success: boolean;
  timestamp: string;
  details: PluginActionDetails | null;
};

export type PluginCapabilityCountEntry = readonly [keyof PluginCapabilityCounts, number];

export function pluginActionTimelineEntry(
  response: PluginActionResponse,
  fallbackAction: string,
  now = new Date().toISOString(),
): PluginActionTimelineEntry {
  const details = response.details ?? null;
  const trace = details?.control_plane_trace;
  return {
    id: trace?.trace_id || `${now}:${fallbackAction}`,
    action: trace?.action || fallbackAction,
    message: response.message,
    success: response.success,
    timestamp: trace?.timestamp || now,
    details,
  };
}

export function prependPluginActionTimeline(
  current: PluginActionTimelineEntry[],
  response: PluginActionResponse,
  fallbackAction: string,
  now = new Date().toISOString(),
): PluginActionTimelineEntry[] {
  const entry = pluginActionTimelineEntry(response, fallbackAction, now);
  return [entry, ...current.filter((item) => item.id !== entry.id)].slice(0, 10);
}

export function pluginCapabilityCountEntries(
  counts: PluginCapabilityCounts,
): PluginCapabilityCountEntry[] {
  return [
    ['channel_types', counts.channel_types],
    ['tool_factories', counts.tool_factories],
    ['registered_tool_factories', counts.registered_tool_factories],
    ['hooks', counts.hooks],
    ['commands', counts.commands],
    ['services', counts.services],
    ['providers', counts.providers],
  ];
}

export function validatePluginRequirement(requirement: string): 'required' | null {
  return requirement.trim() ? null : 'required';
}

export function pluginConfigFields(schema: PluginConfigSchema): PluginConfigField[] {
  const properties = schema.config_schema?.properties ?? {};
  const required = new Set(schema.config_schema?.required ?? []);
  const secretPaths = new Set(schema.secret_paths);
  const hints = schema.config_ui_hints ?? {};

  return Object.entries(properties).map(([name, property]) => {
    const hint = hints[name] ?? {};
    const sensitive = hint.sensitive === true || secretPaths.has(name);
    const options = Array.isArray(property.enum) ? [...property.enum] : [];
    return {
      name,
      label: cleanText(hint.label) || cleanText(property.title) || name,
      kind: fieldKind(property, sensitive),
      required: required.has(name) && !sensitive,
      placeholder: cleanText(hint.placeholder) || cleanText(property.description),
      help: cleanText(hint.help),
      options,
      minimum: finiteNumber(property.minimum),
      maximum: finiteNumber(property.maximum),
    };
  });
}

export function pluginConfigDraftFrom(
  schema: PluginConfigSchema,
  record: PluginConfigRecord | null,
): PluginConfigDraft {
  const source = { ...(schema.defaults ?? {}), ...(record?.config ?? {}) };
  const secrets = new Set(schema.secret_paths);
  return Object.fromEntries(
    pluginConfigFields(schema).map((field) => {
      const value = source[field.name];
      return [
        field.name,
        secrets.has(field.name)
          ? ''
          : value === undefined
            ? defaultValue(field.kind)
            : value,
      ];
    }),
  );
}

export function validatePluginConfigDraft(
  schema: PluginConfigSchema,
  draft: PluginConfigDraft,
): PluginConfigErrors {
  const errors: PluginConfigErrors = {};
  for (const field of pluginConfigFields(schema)) {
    const value = draft[field.name];
    if (field.required && isBlank(value)) {
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
      continue;
    }
    if (field.kind === 'select' && !field.options.some((option) => option === value)) {
      errors[field.name] = 'invalid_option';
    }
  }
  return errors;
}

export function pluginConfigMutationFromDraft(
  schema: PluginConfigSchema,
  draft: PluginConfigDraft,
): UpdatePluginConfigRequest {
  const secrets = new Set(schema.secret_paths);
  const config: Record<string, unknown> = {};
  for (const field of pluginConfigFields(schema)) {
    const raw = draft[field.name];
    if (raw === undefined || raw === PLUGIN_SECRET_UNCHANGED) continue;
    if (secrets.has(field.name) && isBlank(raw)) continue;
    config[field.name] = normalizeValue(field, raw);
  }
  return { config };
}

function fieldKind(
  property: PluginConfigSchemaProperty,
  sensitive: boolean,
): PluginConfigFieldKind {
  if (sensitive) return 'secret';
  if (Array.isArray(property.enum) && property.enum.length > 0) return 'select';
  if (property.type === 'boolean') return 'boolean';
  if (property.type === 'integer') return 'integer';
  if (property.type === 'number') return 'number';
  return 'text';
}

function normalizeValue(field: PluginConfigField, value: unknown): unknown {
  if (field.kind === 'text' || field.kind === 'secret') {
    return typeof value === 'string' ? value.trim() : value;
  }
  if (field.kind === 'number' || field.kind === 'integer') {
    return typeof value === 'number' ? value : Number(value);
  }
  return value;
}

function defaultValue(kind: PluginConfigFieldKind): unknown {
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
