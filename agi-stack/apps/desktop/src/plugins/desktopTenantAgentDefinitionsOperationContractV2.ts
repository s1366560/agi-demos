import { RuntimeV2Error } from '@agistack/plugin-runtime';

import type {
  DesktopRuntimeConfig,
  ManagedAgentDefinition,
  ManagedAgentDefinitionMutation,
  ManagedExternalAcpAgent,
} from '../types';
import type { ManagementRouteScope } from '../features/settings-routes/managementRouteTypes';

export type DesktopTenantAgentDefinitionsScopeV2 = ManagementRouteScope;

export type DesktopTenantAgentDefinitionsLoadInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  scope: DesktopTenantAgentDefinitionsScopeV2;
  signal?: AbortSignal;
}>;

export type DesktopTenantAgentDefinitionsMutationInputV2 =
  DesktopTenantAgentDefinitionsLoadInputV2 &
  Readonly<{ input: ManagedAgentDefinitionMutation }>;

export type DesktopTenantAgentDefinitionsItemInputV2 =
  DesktopTenantAgentDefinitionsLoadInputV2 &
  Readonly<{
    definitionId: string;
    expectedRevision?: number;
  }>;

export type DesktopTenantAgentDefinitionsUpdateInputV2 =
  DesktopTenantAgentDefinitionsItemInputV2 &
  Readonly<{ input: ManagedAgentDefinitionMutation }>;

export type DesktopTenantAgentDefinitionsEnabledInputV2 =
  DesktopTenantAgentDefinitionsItemInputV2 &
  Readonly<{ enabled: boolean }>;

export interface DesktopTenantAgentDefinitionsAuthorityV2 {
  load(
    scope: DesktopTenantAgentDefinitionsScopeV2,
    signal?: AbortSignal,
  ): Promise<readonly ManagedAgentDefinition[]>;
  listExternal(
    scope: DesktopTenantAgentDefinitionsScopeV2,
    signal?: AbortSignal,
  ): Promise<readonly ManagedExternalAcpAgent[]>;
  create(
    scope: DesktopTenantAgentDefinitionsScopeV2,
    input: ManagedAgentDefinitionMutation,
    signal?: AbortSignal,
  ): Promise<ManagedAgentDefinition>;
  update(
    scope: DesktopTenantAgentDefinitionsScopeV2,
    definitionId: string,
    input: ManagedAgentDefinitionMutation,
    expectedRevision?: number,
    signal?: AbortSignal,
  ): Promise<ManagedAgentDefinition>;
  setEnabled(
    scope: DesktopTenantAgentDefinitionsScopeV2,
    definitionId: string,
    enabled: boolean,
    expectedRevision?: number,
    signal?: AbortSignal,
  ): Promise<ManagedAgentDefinition>;
  delete(
    scope: DesktopTenantAgentDefinitionsScopeV2,
    definitionId: string,
    expectedRevision?: number,
    signal?: AbortSignal,
  ): Promise<Readonly<{ deleted: true; id: string }>>;
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
  'temperature',
  'max_tokens',
  'max_iterations',
  'allowed_tools',
  'allowed_skills',
  'allowed_mcp_servers',
  'can_spawn',
  'max_spawn_depth',
  'agent_to_agent_enabled',
  'agent_to_agent_allowlist',
  'discoverable',
  'max_retries',
  'fallback_models',
  'spawn_policy',
  'tool_policy',
  'session_policy',
  'delegate_config',
  'execution_backend',
  'workspace_config',
]);
const REQUIRED_MUTATION_KEYS = Object.freeze([
  'name',
  'display_name',
  'system_prompt',
  'project_id',
  'trigger_description',
  'trigger_examples',
  'trigger_keywords',
  'model',
  'temperature',
  'max_tokens',
  'max_iterations',
  'allowed_tools',
  'allowed_skills',
  'allowed_mcp_servers',
  'can_spawn',
  'max_spawn_depth',
  'agent_to_agent_enabled',
  'agent_to_agent_allowlist',
  'discoverable',
  'max_retries',
  'fallback_models',
  'execution_backend',
  'workspace_config',
]);

export function prepareDesktopTenantAgentDefinitionsLoadV2(
  input: DesktopTenantAgentDefinitionsLoadInputV2,
): DesktopTenantAgentDefinitionsLoadInputV2 {
  return Object.freeze(prepareCommon(input, ['config', 'scope', 'signal']));
}

export function prepareDesktopTenantAgentDefinitionsExternalV2(
  input: DesktopTenantAgentDefinitionsLoadInputV2,
): DesktopTenantAgentDefinitionsLoadInputV2 {
  const prepared = prepareDesktopTenantAgentDefinitionsLoadV2(input);
  if (prepared.scope.projectId !== null) throw invalidInput();
  return prepared;
}

export function prepareDesktopTenantAgentDefinitionsCreateV2(
  input: DesktopTenantAgentDefinitionsMutationInputV2,
): DesktopTenantAgentDefinitionsMutationInputV2 {
  const common = prepareCommon(input, ['config', 'scope', 'input', 'signal']);
  const mutation = freezeMutation(input.input);
  requireMutationScope(common.scope, mutation.project_id);
  return Object.freeze({ ...common, input: mutation });
}

export function prepareDesktopTenantAgentDefinitionsUpdateV2(
  input: DesktopTenantAgentDefinitionsUpdateInputV2,
): DesktopTenantAgentDefinitionsUpdateInputV2 {
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

export function prepareDesktopTenantAgentDefinitionsEnabledV2(
  input: DesktopTenantAgentDefinitionsEnabledInputV2,
): DesktopTenantAgentDefinitionsEnabledInputV2 {
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

export function prepareDesktopTenantAgentDefinitionsDeleteV2(
  input: DesktopTenantAgentDefinitionsItemInputV2,
): DesktopTenantAgentDefinitionsItemInputV2 {
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

export function freezeDesktopTenantAgentDefinitionsConfigV2(
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
  identifier(config.tenantId);
  return Object.freeze({ ...config });
}

export function requireDesktopTenantAgentDefinitionsV2(
  value: unknown,
  scope: DesktopTenantAgentDefinitionsScopeV2,
): readonly ManagedAgentDefinition[] {
  if (!Array.isArray(value) || value.length > 100) throw invalidResponse();
  return Object.freeze(value.map((item) => requireDesktopTenantAgentDefinitionV2(item, scope)));
}

export function requireDesktopTenantAgentDefinitionV2(
  value: unknown,
  scope: DesktopTenantAgentDefinitionsScopeV2,
): ManagedAgentDefinition {
  if (!record(value) || !cleanText(value.id) || !cleanText(value.name)) {
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
    (value.status !== undefined && !cleanText(value.status)) ||
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
    return freezeJson(value, new WeakSet(), 0) as ManagedAgentDefinition;
  } catch {
    throw invalidResponse();
  }
}

export function requireDesktopTenantAgentDefinitionExternalAcpAgentsV2(
  value: unknown,
): readonly ManagedExternalAcpAgent[] {
  if (!Array.isArray(value) || value.length > 100) throw invalidResponse();
  return Object.freeze(
    value.map((item) => {
      if (
        !record(item) ||
        !exactKeys(item, ['id', 'agentKey', 'name', 'enabled', 'available']) ||
        !cleanText(item.id) ||
        !cleanText(item.agentKey) ||
        !cleanText(item.name) ||
        typeof item.enabled !== 'boolean' ||
        typeof item.available !== 'boolean'
      ) {
        throw invalidResponse();
      }
      return Object.freeze({
        id: item.id,
        agentKey: item.agentKey,
        name: item.name,
        enabled: item.enabled,
        available: item.available,
      });
    }),
  );
}

export function requireDesktopTenantAgentDefinitionDeleteV2(
  value: unknown,
  definitionId: string,
): Readonly<{ deleted: true; id: string }> {
  if (!record(value) || value.deleted !== true || value.id !== definitionId) {
    throw invalidResponse();
  }
  return Object.freeze({ deleted: true, id: definitionId });
}

function prepareCommon(
  input: DesktopTenantAgentDefinitionsLoadInputV2,
  allowedKeys: readonly string[],
): DesktopTenantAgentDefinitionsLoadInputV2 {
  if (!record(input) || !allowedOnly(input, allowedKeys)) throw invalidInput();
  const config = freezeDesktopTenantAgentDefinitionsConfigV2(input.config);
  if (
    !record(input.scope) ||
    !exactKeys(input.scope, ['authority', 'tenantId', 'projectId']) ||
    input.scope.authority !== config.mode ||
    identifier(input.scope.tenantId) !== config.tenantId ||
    !(input.scope.projectId === null || identifier(input.scope.projectId)) ||
    (input.scope.projectId !== null && input.scope.projectId !== config.projectId)
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

function freezeMutation(value: unknown): ManagedAgentDefinitionMutation {
  if (
    !record(value) ||
    !allowedOnly(value, MUTATION_KEYS) ||
    REQUIRED_MUTATION_KEYS.some((key) => !Object.hasOwn(value, key)) ||
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
    typeof value.can_spawn !== 'boolean' ||
    !nonnegativeInteger(value.max_spawn_depth) ||
    typeof value.agent_to_agent_enabled !== 'boolean' ||
    !(value.agent_to_agent_allowlist === null || stringArray(value.agent_to_agent_allowlist)) ||
    typeof value.discoverable !== 'boolean' ||
    !nonnegativeInteger(value.max_retries) ||
    !stringArray(value.fallback_models) ||
    !record(value.execution_backend) ||
    (value.execution_backend.type !== 'memstack' &&
      value.execution_backend.type !== 'acp_external') ||
    !record(value.workspace_config)
  ) {
    throw invalidInput();
  }
  for (const optional of ['spawn_policy', 'tool_policy', 'session_policy', 'delegate_config']) {
    const candidate = value[optional];
    if (candidate !== undefined && candidate !== null && !record(candidate)) throw invalidInput();
  }
  try {
    return freezeJson(value, new WeakSet(), 0) as ManagedAgentDefinitionMutation;
  } catch {
    throw invalidInput();
  }
}

function requireMutationScope(
  scope: DesktopTenantAgentDefinitionsScopeV2,
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
    Object.keys(value).length === keys.length &&
    keys.every((key) => Object.hasOwn(value, key))
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
    'desktop_tenant_agent_definitions_operation_input_invalid',
    'desktop tenant Agent definitions operation input invalid',
  );
}

function invalidResponse(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_tenant_agent_definitions_operation_response_invalid',
    'desktop tenant Agent definitions operation response invalid',
  );
}
