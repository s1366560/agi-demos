import { RuntimeV2Error } from '@agistack/plugin-runtime';

import type { DesktopRuntimeConfig, ManagedSubAgent, ManagedSubAgentMutation } from '../types';
import type { ManagementRouteScope } from '../features/settings-routes/managementRouteTypes';

export type DesktopTenantSubAgentDefinitionsScopeV2 = ManagementRouteScope;

export type DesktopTenantSubAgentDefinitionsLoadInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  scope: DesktopTenantSubAgentDefinitionsScopeV2;
  signal?: AbortSignal;
}>;

export type DesktopTenantSubAgentDefinitionsMutationInputV2 =
  DesktopTenantSubAgentDefinitionsLoadInputV2 & Readonly<{ input: ManagedSubAgentMutation }>;

export type DesktopTenantSubAgentDefinitionsItemInputV2 =
  DesktopTenantSubAgentDefinitionsLoadInputV2 &
    Readonly<{
      definitionId: string;
      expectedRevision?: number;
    }>;

export type DesktopTenantSubAgentDefinitionsUpdateInputV2 =
  DesktopTenantSubAgentDefinitionsItemInputV2 & Readonly<{ input: ManagedSubAgentMutation }>;

export type DesktopTenantSubAgentDefinitionsEnabledInputV2 =
  DesktopTenantSubAgentDefinitionsItemInputV2 & Readonly<{ enabled: boolean }>;

export interface DesktopTenantSubAgentDefinitionsAuthorityV2 {
  load(
    scope: DesktopTenantSubAgentDefinitionsScopeV2,
    signal?: AbortSignal,
  ): Promise<readonly ManagedSubAgent[]>;
  importFilesystem(
    scope: DesktopTenantSubAgentDefinitionsScopeV2,
    name: string,
    signal?: AbortSignal,
  ): Promise<ManagedSubAgent>;
  create(
    scope: DesktopTenantSubAgentDefinitionsScopeV2,
    input: ManagedSubAgentMutation,
    signal?: AbortSignal,
  ): Promise<ManagedSubAgent>;
  update(
    scope: DesktopTenantSubAgentDefinitionsScopeV2,
    definitionId: string,
    input: ManagedSubAgentMutation,
    expectedRevision?: number,
    signal?: AbortSignal,
  ): Promise<ManagedSubAgent>;
  setEnabled(
    scope: DesktopTenantSubAgentDefinitionsScopeV2,
    definitionId: string,
    enabled: boolean,
    expectedRevision?: number,
    signal?: AbortSignal,
  ): Promise<ManagedSubAgent>;
  delete(
    scope: DesktopTenantSubAgentDefinitionsScopeV2,
    definitionId: string,
    expectedRevision?: number,
    signal?: AbortSignal,
  ): Promise<void>;
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
const MUTATION_KEYS = Object.freeze([
  'name',
  'display_name',
  'system_prompt',
  'project_id',
  'trigger_description',
  'trigger_examples',
  'trigger_keywords',
  'model',
  'color',
  'temperature',
  'max_tokens',
  'max_iterations',
  'allowed_tools',
  'allowed_skills',
  'allowed_mcp_servers',
  'metadata',
]);

export type DesktopTenantSubAgentDefinitionsImportInputV2 =
  DesktopTenantSubAgentDefinitionsLoadInputV2 & Readonly<{ name: string }>;

export function prepareDesktopTenantSubAgentDefinitionsLoadV2(
  input: DesktopTenantSubAgentDefinitionsLoadInputV2,
): DesktopTenantSubAgentDefinitionsLoadInputV2 {
  const common = prepareCommon(input, ['config', 'scope', 'signal']);
  if (common.scope.projectId !== null) throw invalidInput();
  return Object.freeze(common);
}

export function prepareDesktopTenantSubAgentDefinitionsImportV2(
  input: DesktopTenantSubAgentDefinitionsImportInputV2,
): DesktopTenantSubAgentDefinitionsImportInputV2 {
  const common = prepareCommon(input, ['config', 'scope', 'name', 'signal']);
  return Object.freeze({ ...common, name: identifier(input.name) });
}

export function prepareDesktopTenantSubAgentDefinitionsCreateV2(
  input: DesktopTenantSubAgentDefinitionsMutationInputV2,
): DesktopTenantSubAgentDefinitionsMutationInputV2 {
  const common = prepareCommon(input, ['config', 'scope', 'input', 'signal']);
  const mutation = freezeMutation(input.input);
  requireMutationScope(common.scope, mutation.project_id);
  return Object.freeze({ ...common, input: mutation });
}

export function prepareDesktopTenantSubAgentDefinitionsUpdateV2(
  input: DesktopTenantSubAgentDefinitionsUpdateInputV2,
): DesktopTenantSubAgentDefinitionsUpdateInputV2 {
  const common = prepareCommon(input, [
    'config',
    'scope',
    'definitionId',
    'input',
    'expectedRevision',
    'signal',
  ]);
  const mutation = freezeMutation(input.input);
  requireMutationScope(common.scope, mutation.project_id);
  return Object.freeze({
    ...common,
    definitionId: identifier(input.definitionId),
    input: mutation,
    ...(input.expectedRevision === undefined
      ? {}
      : { expectedRevision: revision(input.expectedRevision) }),
  });
}

export function prepareDesktopTenantSubAgentDefinitionsEnabledV2(
  input: DesktopTenantSubAgentDefinitionsEnabledInputV2,
): DesktopTenantSubAgentDefinitionsEnabledInputV2 {
  const common = prepareCommon(input, [
    'config',
    'scope',
    'definitionId',
    'enabled',
    'expectedRevision',
    'signal',
  ]);
  if (typeof input.enabled !== 'boolean') throw invalidInput();
  return Object.freeze({
    ...common,
    definitionId: identifier(input.definitionId),
    enabled: input.enabled,
    ...(input.expectedRevision === undefined
      ? {}
      : { expectedRevision: revision(input.expectedRevision) }),
  });
}

export function prepareDesktopTenantSubAgentDefinitionsDeleteV2(
  input: DesktopTenantSubAgentDefinitionsItemInputV2,
): DesktopTenantSubAgentDefinitionsItemInputV2 {
  const common = prepareCommon(input, [
    'config',
    'scope',
    'definitionId',
    'expectedRevision',
    'signal',
  ]);
  return Object.freeze({
    ...common,
    definitionId: identifier(input.definitionId),
    ...(input.expectedRevision === undefined
      ? {}
      : { expectedRevision: revision(input.expectedRevision) }),
  });
}

export function freezeDesktopTenantSubAgentDefinitionsConfigV2(
  config: DesktopRuntimeConfig,
): DesktopRuntimeConfig {
  if (
    !record(config) ||
    !exactKeys(config, CONFIG_KEYS) ||
    (config.mode !== 'cloud' && config.mode !== 'local')
  ) {
    throw invalidInput();
  }
  for (const key of CONFIG_KEYS) {
    if (key !== 'mode' && typeof config[key as keyof DesktopRuntimeConfig] !== 'string') {
      throw invalidInput();
    }
  }
  return Object.freeze({ ...config });
}

export function requireDesktopTenantSubAgentDefinitionsV2(
  value: unknown,
  scope: DesktopTenantSubAgentDefinitionsScopeV2,
): readonly ManagedSubAgent[] {
  if (!Array.isArray(value) || (scope.authority === 'cloud' && value.length > 100))
    throw invalidResponse();
  const items = value.map((item) => requireDesktopTenantSubAgentDefinitionV2(item, scope));
  if (new Set(items.map((item) => item.id)).size !== items.length) throw invalidResponse();
  return Object.freeze(items);
}

export function requireDesktopTenantSubAgentDefinitionV2(
  value: unknown,
  scope: DesktopTenantSubAgentDefinitionsScopeV2,
  expectedId?: string,
): ManagedSubAgent {
  if (
    !record(value) ||
    !cleanText(value.id) ||
    !cleanText(value.name) ||
    value.tenant_id !== scope.tenantId ||
    typeof value.enabled !== 'boolean' ||
    (expectedId !== undefined && value.id !== expectedId)
  ) {
    throw invalidResponse();
  }
  if (
    (value.tenant_id !== undefined &&
      value.tenant_id !== null &&
      value.tenant_id !== scope.tenantId) ||
    (value.project_id !== undefined &&
      value.project_id !== null &&
      (!cleanText(value.project_id) ||
        (scope.projectId !== null && value.project_id !== scope.projectId))) ||
    (value.revision !== undefined && !nonnegativeInteger(value.revision)) ||
    (value.enabled !== undefined && typeof value.enabled !== 'boolean') ||
    (expectedId !== undefined && value.id !== expectedId) ||
    (value.source !== undefined && value.source !== 'database' && value.source !== 'filesystem') ||
    (value.display_name !== undefined && !nullableString(value.display_name)) ||
    (value.system_prompt !== undefined && !nullableString(value.system_prompt)) ||
    (value.updated_at !== undefined && !nullableString(value.updated_at)) ||
    (value.allowed_tools !== undefined && !stringArray(value.allowed_tools)) ||
    (value.allowed_skills !== undefined && !stringArray(value.allowed_skills)) ||
    (value.allowed_mcp_servers !== undefined && !stringArray(value.allowed_mcp_servers))
  ) {
    throw invalidResponse();
  }
  try {
    return freezeJson(value, new WeakSet(), 0) as ManagedSubAgent;
  } catch {
    throw invalidResponse();
  }
}

export function requireDesktopTenantSubAgentDefinitionDeleteV2(value: unknown): void {
  if (value !== undefined) throw invalidResponse();
}

function prepareCommon(
  input: DesktopTenantSubAgentDefinitionsLoadInputV2,
  allowedKeys: readonly string[],
): DesktopTenantSubAgentDefinitionsLoadInputV2 {
  if (!record(input) || !allowedOnly(input, allowedKeys)) throw invalidInput();
  const config = freezeDesktopTenantSubAgentDefinitionsConfigV2(input.config);
  if (
    !record(input.scope) ||
    !exactKeys(input.scope, ['authority', 'tenantId', 'projectId']) ||
    input.scope.authority !== config.mode ||
    identifier(input.scope.tenantId) !== config.tenantId ||
    !(input.scope.projectId === null || identifier(input.scope.projectId)) ||
    (config.mode === 'local' &&
      input.scope.projectId !== null &&
      input.scope.projectId !== config.projectId)
  ) {
    throw invalidInput();
  }
  if (input.signal !== undefined && !abortSignal(input.signal)) throw invalidInput();
  return Object.freeze({
    config,
    scope: Object.freeze({
      authority: input.scope.authority,
      tenantId: input.scope.tenantId,
      projectId: input.scope.projectId,
    }),
    ...(input.signal === undefined ? {} : { signal: input.signal }),
  });
}

function freezeMutation(value: unknown): ManagedSubAgentMutation {
  if (
    !record(value) ||
    !exactKeys(value, MUTATION_KEYS) ||
    !cleanText(value.name) ||
    typeof value.display_name !== 'string' ||
    typeof value.system_prompt !== 'string' ||
    !(value.project_id === null || cleanText(value.project_id)) ||
    typeof value.trigger_description !== 'string' ||
    !stringArray(value.trigger_examples) ||
    !stringArray(value.trigger_keywords) ||
    !cleanText(value.model) ||
    !finite(value.temperature) ||
    !nonnegativeInteger(value.max_tokens) ||
    !nonnegativeInteger(value.max_iterations) ||
    !stringArray(value.allowed_tools) ||
    !stringArray(value.allowed_skills) ||
    !stringArray(value.allowed_mcp_servers) ||
    typeof value.color !== 'string' ||
    !(value.metadata === null || record(value.metadata))
  ) {
    throw invalidInput();
  }
  try {
    return freezeJson(value, new WeakSet(), 0) as ManagedSubAgentMutation;
  } catch {
    throw invalidInput();
  }
}

function requireMutationScope(
  scope: DesktopTenantSubAgentDefinitionsScopeV2,
  projectId: string | null,
): void {
  if (scope.projectId !== projectId) throw invalidInput();
}

function freezeJson(value: unknown, seen: WeakSet<object>, depth: number): unknown {
  if (depth > 24) throw invalidInput();
  if (value === null || typeof value === 'string' || typeof value === 'boolean') return value;
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) throw invalidInput();
    return value;
  }
  if (typeof value !== 'object' || abortSignal(value)) throw invalidInput();
  if (seen.has(value)) throw invalidInput();
  seen.add(value);
  if (Array.isArray(value)) {
    return Object.freeze(value.map((item) => freezeJson(item, seen, depth + 1)));
  }
  const source = value as Record<string, unknown>;
  const copy: Record<string, unknown> = {};
  for (const [key, item] of Object.entries(source)) {
    if (key === '__proto__' || key === 'prototype' || key === 'constructor') throw invalidInput();
    copy[key] = freezeJson(item, seen, depth + 1);
  }
  return Object.freeze(copy);
}

function identifier(value: unknown): string {
  if (!cleanText(value)) throw invalidInput();
  return value;
}

function revision(value: unknown): number {
  if (!nonnegativeInteger(value)) throw invalidInput();
  return value;
}

function allowedOnly(value: Record<string, unknown>, keys: readonly string[]): boolean {
  return Object.keys(value).every((key) => keys.includes(key));
}

function exactKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  return (
    Object.keys(value).length === keys.length && keys.every((key) => Object.hasOwn(value, key))
  );
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function cleanText(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && value === value.trim();
}

function nullableString(value: unknown): value is string | null {
  return value === null || typeof value === 'string';
}

function stringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === 'string');
}

function finite(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function nonnegativeInteger(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) >= 0;
}

function abortSignal(value: unknown): value is AbortSignal {
  return (
    record(value) &&
    typeof value.aborted === 'boolean' &&
    typeof value.addEventListener === 'function' &&
    typeof value.removeEventListener === 'function'
  );
}

function invalidInput(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_tenant_subagent_definitions_operation_input_invalid',
    'desktop tenant SubAgent definitions operation input invalid',
  );
}

function invalidResponse(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_tenant_subagent_definitions_operation_response_invalid',
    'desktop tenant SubAgent definitions operation response invalid',
  );
}
