import { RuntimeV2Error } from '@agistack/plugin-runtime';

import type {
  ChannelsRouteObservation,
  ChannelsRouteScope,
} from '../features/settings-routes/channelsRouteClient';
import type {
  CreateManagedChannelConfigRequest,
  DesktopRuntimeConfig,
  ManagedChannelConfig,
  ManagedChannelPluginCatalogItem,
  ManagedChannelPluginConfigSchema,
  ManagedChannelTestResult,
  UpdateManagedChannelConfigRequest,
} from '../types';

export type DesktopProjectChannelsSnapshotV2 = ChannelsRouteObservation;

export type DesktopProjectChannelsLoadInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  scope: ChannelsRouteScope;
  signal?: AbortSignal;
}>;

export type DesktopProjectChannelsSchemaInputV2 = DesktopProjectChannelsLoadInputV2 &
  Readonly<{ channelType: string }>;

export type DesktopProjectChannelsCreateInputV2 = DesktopProjectChannelsLoadInputV2 &
  Readonly<{ input: CreateManagedChannelConfigRequest }>;

export type DesktopProjectChannelsUpdateInputV2 = DesktopProjectChannelsLoadInputV2 &
  Readonly<{ configId: string; input: UpdateManagedChannelConfigRequest }>;

export type DesktopProjectChannelsItemInputV2 = DesktopProjectChannelsLoadInputV2 &
  Readonly<{ configId: string }>;

export interface DesktopProjectChannelsAuthorityV2 {
  load(scope: ChannelsRouteScope, signal?: AbortSignal): Promise<DesktopProjectChannelsSnapshotV2>;
  schema(
    scope: ChannelsRouteScope,
    channelType: string,
    signal?: AbortSignal,
  ): Promise<ManagedChannelPluginConfigSchema>;
  create(
    scope: ChannelsRouteScope,
    input: CreateManagedChannelConfigRequest,
    signal?: AbortSignal,
  ): Promise<ManagedChannelConfig>;
  update(
    scope: ChannelsRouteScope,
    configId: string,
    input: UpdateManagedChannelConfigRequest,
    signal?: AbortSignal,
  ): Promise<ManagedChannelConfig>;
  test(
    scope: ChannelsRouteScope,
    configId: string,
    signal?: AbortSignal,
  ): Promise<ManagedChannelTestResult>;
  remove(scope: ChannelsRouteScope, configId: string, signal?: AbortSignal): Promise<void>;
}

const CONFIG_KEYS = Object.freeze([
  'apiBaseUrl',
  'deviceAuthorizationBaseUrl',
  'apiKey',
  'localApiToken',
  'tenantId',
  'projectId',
  'workspaceId',
  'mode',
  'workspaceRoot',
]);
const SCOPE_KEYS = Object.freeze(['authority', 'tenantId', 'projectId']);
const LOAD_KEYS = Object.freeze(['config', 'scope', 'signal']);
const SCHEMA_INPUT_KEYS = Object.freeze([...LOAD_KEYS, 'channelType']);
const CREATE_INPUT_KEYS = Object.freeze([...LOAD_KEYS, 'input']);
const UPDATE_INPUT_KEYS = Object.freeze([...LOAD_KEYS, 'configId', 'input']);
const ITEM_INPUT_KEYS = Object.freeze([...LOAD_KEYS, 'configId']);
const CREATE_KEYS = Object.freeze([
  'channel_type',
  'name',
  'enabled',
  'connection_mode',
  'app_id',
  'app_secret',
  'encrypt_key',
  'verification_token',
  'webhook_url',
  'webhook_port',
  'webhook_path',
  'domain',
  'extra_settings',
  'description',
]);
const UPDATE_KEYS = Object.freeze(CREATE_KEYS.filter((key) => key !== 'channel_type'));
const CATALOG_KEYS = Object.freeze([
  'channel_type',
  'plugin_name',
  'source',
  'package',
  'version',
  'enabled',
  'discovered',
  'schema_supported',
]);
const SCHEMA_KEYS = Object.freeze([
  'channel_type',
  'plugin_name',
  'source',
  'package',
  'version',
  'schema_supported',
  'config_schema',
  'config_ui_hints',
  'defaults',
  'secret_paths',
]);
const CONFIG_KEYS_RESPONSE = Object.freeze([
  'id',
  'project_id',
  'channel_type',
  'name',
  'enabled',
  'connection_mode',
  'app_id',
  'webhook_url',
  'webhook_port',
  'webhook_path',
  'domain',
  'extra_settings',
  'dm_policy',
  'group_policy',
  'allow_from',
  'group_allow_from',
  'rate_limit_per_minute',
  'status',
  'last_error',
  'description',
  'created_at',
  'updated_at',
]);
const SNAPSHOT_KEYS = Object.freeze([
  'scope',
  'authority',
  'availability',
  'reasonCode',
  'allowedActions',
  'itemCount',
  'catalog',
  'configs',
]);
const TEST_RESULT_KEYS = Object.freeze(['success', 'message']);
const ACTIONS = Object.freeze([
  'view',
  'view-channel-catalog',
  'view-channel-schema',
  'list-channel-configs',
  'create-channel-config',
  'update-channel-config',
  'delete-channel-config',
  'test-channel-config',
]);

export function prepareDesktopProjectChannelsLoadV2(
  input: DesktopProjectChannelsLoadInputV2,
): DesktopProjectChannelsLoadInputV2 {
  return prepareCommon(input, LOAD_KEYS);
}

export function prepareDesktopProjectChannelsSchemaV2(
  input: DesktopProjectChannelsSchemaInputV2,
): DesktopProjectChannelsSchemaInputV2 {
  const common = prepareCommon(input, SCHEMA_INPUT_KEYS);
  return Object.freeze({ ...common, channelType: identifier(input.channelType) });
}

export function prepareDesktopProjectChannelsCreateV2(
  value: DesktopProjectChannelsCreateInputV2,
): DesktopProjectChannelsCreateInputV2 {
  const common = prepareCommon(value, CREATE_INPUT_KEYS);
  return Object.freeze({ ...common, input: freezeCreateMutation(value.input) });
}

export function prepareDesktopProjectChannelsUpdateV2(
  value: DesktopProjectChannelsUpdateInputV2,
): DesktopProjectChannelsUpdateInputV2 {
  const common = prepareCommon(value, UPDATE_INPUT_KEYS);
  return Object.freeze({
    ...common,
    configId: identifier(value.configId),
    input: freezeUpdateMutation(value.input),
  });
}

export function prepareDesktopProjectChannelsItemV2(
  value: DesktopProjectChannelsItemInputV2,
): DesktopProjectChannelsItemInputV2 {
  const common = prepareCommon(value, ITEM_INPUT_KEYS);
  return Object.freeze({ ...common, configId: identifier(value.configId) });
}

export function freezeDesktopProjectChannelsConfigV2(
  value: DesktopRuntimeConfig,
): DesktopRuntimeConfig {
  if (!record(value) || !exactKeys(value, CONFIG_KEYS) || !['cloud', 'local'].includes(value.mode)) {
    throw invalidInput();
  }
  for (const key of CONFIG_KEYS) {
    if (key !== 'mode' && typeof value[key as keyof DesktopRuntimeConfig] !== 'string') {
      throw invalidInput();
    }
  }
  identifier(value.tenantId);
  identifier(value.projectId);
  return Object.freeze({ ...value });
}

export function requireDesktopProjectChannelsSnapshotV2(
  value: unknown,
  scope: ChannelsRouteScope,
): DesktopProjectChannelsSnapshotV2 {
  if (
    !record(value) ||
    !exactKeys(value, SNAPSHOT_KEYS) ||
    !sameScope(value.scope, scope) ||
    value.authority !== scope.authority ||
    value.availability !== 'available' ||
    value.reasonCode !== null ||
    !sameStringArray(value.allowedActions, ACTIONS) ||
    !Array.isArray(value.catalog) ||
    !Array.isArray(value.configs) ||
    value.itemCount !== value.configs.length ||
    value.catalog.some((item) => !validCatalogItem(item)) ||
    value.configs.some((item) => !validChannelConfig(item, scope.projectId))
  ) {
    throw invalidResponse();
  }
  return freezeJson(value) as DesktopProjectChannelsSnapshotV2;
}

export function requireDesktopProjectChannelSchemaV2(
  value: unknown,
  channelType: string,
): ManagedChannelPluginConfigSchema {
  if (!validSchema(value) || value.channel_type !== channelType) throw invalidResponse();
  return freezeJson(value) as ManagedChannelPluginConfigSchema;
}

export function requireDesktopProjectChannelConfigV2(
  value: unknown,
  projectId: string,
): ManagedChannelConfig {
  if (!validChannelConfig(value, projectId)) throw invalidResponse();
  return freezeJson(value) as ManagedChannelConfig;
}

export function requireDesktopProjectChannelTestResultV2(
  value: unknown,
): ManagedChannelTestResult {
  if (
    !record(value) ||
    !exactKeys(value, TEST_RESULT_KEYS) ||
    typeof value.success !== 'boolean' ||
    typeof value.message !== 'string'
  ) {
    throw invalidResponse();
  }
  return Object.freeze({ success: value.success, message: value.message });
}

function prepareCommon<T extends DesktopProjectChannelsLoadInputV2>(
  value: T,
  keys: readonly string[],
): T {
  if (
    !record(value) ||
    !allowedKeys(value, keys) ||
    !Object.hasOwn(value, 'config') ||
    !Object.hasOwn(value, 'scope') ||
    (value.signal !== undefined && !isAbortSignal(value.signal))
  ) {
    throw invalidInput();
  }
  const config = freezeDesktopProjectChannelsConfigV2(value.config);
  const scope = freezeScope(value.scope, config);
  return Object.freeze({
    ...value,
    config,
    scope,
    ...(value.signal === undefined ? {} : { signal: value.signal }),
  });
}

function freezeScope(scope: ChannelsRouteScope, config: DesktopRuntimeConfig): ChannelsRouteScope {
  if (
    !record(scope) ||
    !exactKeys(scope, SCOPE_KEYS) ||
    scope.authority !== config.mode ||
    identifier(scope.tenantId) !== config.tenantId ||
    identifier(scope.projectId) !== config.projectId
  ) {
    throw invalidInput();
  }
  return Object.freeze({
    authority: scope.authority,
    tenantId: scope.tenantId,
    projectId: scope.projectId,
  });
}

function freezeCreateMutation(
  value: CreateManagedChannelConfigRequest,
): CreateManagedChannelConfigRequest {
  return freezeMutation(value, false) as CreateManagedChannelConfigRequest;
}

function freezeUpdateMutation(
  value: UpdateManagedChannelConfigRequest,
): UpdateManagedChannelConfigRequest {
  return freezeMutation(value, true) as UpdateManagedChannelConfigRequest;
}

function freezeMutation(
  value: CreateManagedChannelConfigRequest | UpdateManagedChannelConfigRequest,
  updating: boolean,
): CreateManagedChannelConfigRequest | UpdateManagedChannelConfigRequest {
  const allowed = updating ? UPDATE_KEYS : CREATE_KEYS;
  if (!record(value) || !allowedKeys(value, allowed)) throw invalidInput();
  const fields = value as Record<string, unknown>;
  if (!updating && (!cleanText(fields.channel_type) || !cleanText(fields.name))) throw invalidInput();
  if (Object.hasOwn(value, 'name') && !cleanText(value.name)) throw invalidInput();
  for (const key of [
    'app_id',
    'app_secret',
    'encrypt_key',
    'verification_token',
    'webhook_url',
    'webhook_path',
    'domain',
    'description',
  ]) {
    if (Object.hasOwn(value, key) && typeof fields[key] !== 'string') throw invalidInput();
  }
  if (Object.hasOwn(value, 'enabled') && typeof value.enabled !== 'boolean') throw invalidInput();
  if (
    Object.hasOwn(value, 'connection_mode') &&
    value.connection_mode !== 'websocket' &&
    value.connection_mode !== 'webhook'
  ) {
    throw invalidInput();
  }
  if (
    Object.hasOwn(value, 'webhook_port') &&
    (!Number.isSafeInteger(value.webhook_port) || Number(value.webhook_port) < 1)
  ) {
    throw invalidInput();
  }
  if (Object.hasOwn(value, 'extra_settings') && !record(value.extra_settings)) throw invalidInput();
  return freezeJson(value) as CreateManagedChannelConfigRequest | UpdateManagedChannelConfigRequest;
}

function validCatalogItem(value: unknown): value is ManagedChannelPluginCatalogItem {
  return (
    record(value) &&
    allowedKeys(value, CATALOG_KEYS) &&
    cleanText(value.channel_type) &&
    cleanText(value.plugin_name) &&
    cleanText(value.source) &&
    optionalText(value.package) &&
    optionalText(value.version) &&
    typeof value.enabled === 'boolean' &&
    typeof value.discovered === 'boolean' &&
    typeof value.schema_supported === 'boolean'
  );
}

function validSchema(value: unknown): value is ManagedChannelPluginConfigSchema {
  if (
    !record(value) ||
    !allowedKeys(value, SCHEMA_KEYS) ||
    !cleanText(value.channel_type) ||
    !cleanText(value.plugin_name) ||
    !cleanText(value.source) ||
    !optionalText(value.package) ||
    !optionalText(value.version) ||
    typeof value.schema_supported !== 'boolean' ||
    !Array.isArray(value.secret_paths) ||
    value.secret_paths.some((item) => !cleanText(item))
  ) {
    return false;
  }
  if (value.config_schema !== undefined && !record(value.config_schema)) return false;
  if (value.config_ui_hints !== undefined && !record(value.config_ui_hints)) return false;
  if (value.defaults !== undefined && !record(value.defaults)) return false;
  return true;
}

function validChannelConfig(value: unknown, projectId: string): value is ManagedChannelConfig {
  return (
    record(value) &&
    allowedKeys(value, CONFIG_KEYS_RESPONSE) &&
    cleanText(value.id) &&
    value.project_id === projectId &&
    cleanText(value.channel_type) &&
    cleanText(value.name) &&
    typeof value.enabled === 'boolean' &&
    (value.connection_mode === 'websocket' || value.connection_mode === 'webhook') &&
    ['open', 'allowlist', 'disabled'].includes(String(value.dm_policy)) &&
    ['open', 'allowlist', 'disabled'].includes(String(value.group_policy)) &&
    Number.isFinite(value.rate_limit_per_minute) &&
    ['connected', 'disconnected', 'error', 'circuit_open'].includes(String(value.status)) &&
    cleanText(value.created_at) &&
    optionalText(value.updated_at) &&
    optionalText(value.description) &&
    optionalText(value.last_error) &&
    optionalText(value.app_id) &&
    optionalText(value.webhook_url) &&
    optionalText(value.webhook_path) &&
    optionalText(value.domain) &&
    (value.webhook_port === undefined || Number.isFinite(value.webhook_port)) &&
    (value.extra_settings === undefined || record(value.extra_settings)) &&
    optionalStringArray(value.allow_from) &&
    optionalStringArray(value.group_allow_from)
  );
}

function sameScope(value: unknown, expected: ChannelsRouteScope): boolean {
  return (
    record(value) &&
    exactKeys(value, SCOPE_KEYS) &&
    value.authority === expected.authority &&
    value.tenantId === expected.tenantId &&
    value.projectId === expected.projectId
  );
}

function sameStringArray(value: unknown, expected: readonly string[]): boolean {
  return Array.isArray(value) && value.length === expected.length &&
    value.every((item, index) => item === expected[index]);
}

function optionalStringArray(value: unknown): boolean {
  return value === undefined || (Array.isArray(value) && value.every((item) => typeof item === 'string'));
}

function optionalText(value: unknown): boolean {
  return value === undefined || typeof value === 'string';
}

function cleanText(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && value === value.trim();
}

function identifier(value: unknown): string {
  if (!cleanText(value)) throw invalidInput();
  return value;
}

function exactKeys(value: Record<string, unknown>, expected: readonly string[]): boolean {
  const keys = Object.keys(value);
  return keys.length === expected.length && keys.every((key) => expected.includes(key));
}

function allowedKeys(value: Record<string, unknown>, allowed: readonly string[]): boolean {
  return Object.keys(value).every((key) => allowed.includes(key));
}

function record(value: unknown): value is Record<string, any> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function isAbortSignal(value: unknown): value is AbortSignal {
  return (
    record(value) &&
    typeof value.aborted === 'boolean' &&
    typeof value.addEventListener === 'function' &&
    typeof value.removeEventListener === 'function'
  );
}

function freezeJson<T>(value: T): T {
  let copy: T;
  try {
    copy = structuredClone(value);
  } catch {
    throw invalidInput();
  }
  return freezeRecursive(copy, new WeakSet<object>(), 0);
}

function freezeRecursive<T>(value: T, seen: WeakSet<object>, depth: number): T {
  if (depth > 32) throw invalidInput();
  if (value === null || typeof value !== 'object') return value;
  const object = value as object;
  if (seen.has(object)) throw invalidInput();
  seen.add(object);
  for (const nested of Object.values(object)) freezeRecursive(nested, seen, depth + 1);
  return Object.freeze(value);
}

function invalidInput(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_project_channels_operation_input_invalid',
    'desktop project channels operation input invalid',
  );
}

function invalidResponse(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_project_channels_operation_response_invalid',
    'desktop project channels operation response invalid',
  );
}
