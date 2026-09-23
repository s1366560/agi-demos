import { RuntimeV2Error } from '@agistack/plugin-runtime';
import type {
  DesktopRuntimeConfig,
  ManagedSkill,
  ManagedSkillContent,
  ManagedSkillCreateMutation,
  ManagedSkillMutation,
} from '../types';

export type DesktopTenantSkillDefinitionsScopeV2 = Readonly<{
  authority: DesktopRuntimeConfig['mode'];
  tenantId: string;
  projectId: string | null;
}>;
export type DesktopTenantSkillDefinitionsInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  scope: DesktopTenantSkillDefinitionsScopeV2;
  signal?: AbortSignal;
}>;
export type DesktopTenantSkillDefinitionsItemInputV2 = DesktopTenantSkillDefinitionsInputV2 &
  Readonly<{
    skillId: string;
    expectedRevision?: number;
  }>;
export type DesktopTenantSkillDefinitionsCreateInputV2 = DesktopTenantSkillDefinitionsInputV2 &
  Readonly<{ input: ManagedSkillCreateMutation }>;
export type DesktopTenantSkillDefinitionsUpdateInputV2 = DesktopTenantSkillDefinitionsItemInputV2 &
  Readonly<{ input: Omit<ManagedSkillMutation, 'full_content'> }>;
export type DesktopTenantSkillDefinitionsContentInputV2 = DesktopTenantSkillDefinitionsItemInputV2 &
  Readonly<{ fullContent: string }>;
export type DesktopTenantSkillDefinitionsStatusV2 = 'active' | 'disabled' | 'deprecated';
export type DesktopTenantSkillDefinitionsStatusInputV2 = DesktopTenantSkillDefinitionsItemInputV2 &
  Readonly<{ status: DesktopTenantSkillDefinitionsStatusV2 }>;
export interface DesktopTenantSkillDefinitionsAuthorityV2 {
  load(
    scope: DesktopTenantSkillDefinitionsScopeV2,
    signal?: AbortSignal,
  ): Promise<readonly ManagedSkill[]>;
  create(
    scope: DesktopTenantSkillDefinitionsScopeV2,
    input: ManagedSkillCreateMutation,
    signal?: AbortSignal,
  ): Promise<ManagedSkill>;
  getContent(
    scope: DesktopTenantSkillDefinitionsScopeV2,
    id: string,
    signal?: AbortSignal,
  ): Promise<ManagedSkillContent>;
  update(
    scope: DesktopTenantSkillDefinitionsScopeV2,
    id: string,
    input: Omit<ManagedSkillMutation, 'full_content'>,
    revision?: number,
    signal?: AbortSignal,
  ): Promise<ManagedSkill>;
  updateContent(
    scope: DesktopTenantSkillDefinitionsScopeV2,
    id: string,
    content: string,
    revision?: number,
    signal?: AbortSignal,
  ): Promise<ManagedSkill>;
  setStatus(
    scope: DesktopTenantSkillDefinitionsScopeV2,
    id: string,
    status: DesktopTenantSkillDefinitionsStatusV2,
    revision?: number,
    signal?: AbortSignal,
  ): Promise<ManagedSkill>;
  delete(
    scope: DesktopTenantSkillDefinitionsScopeV2,
    id: string,
    revision?: number,
    signal?: AbortSignal,
  ): Promise<void>;
}
const CONFIG_KEYS = [
  'apiBaseUrl',
  'deviceAuthorizationBaseUrl',
  'apiKey',
  'localApiToken',
  'tenantId',
  'projectId',
  'workspaceId',
  'mode',
  'workspaceRoot',
] as const;
const MUTATION_KEYS = [
  'name',
  'description',
  'tools',
  'metadata',
  'license',
  'compatibility',
  'allowed_tools_raw',
  'spec_version',
] as const;

export function freezeDesktopTenantSkillDefinitionsConfigV2(
  config: DesktopRuntimeConfig,
): DesktopRuntimeConfig {
  if (
    !record(config) ||
    !exactKeys(config, CONFIG_KEYS) ||
    (config.mode !== 'cloud' && config.mode !== 'local') ||
    CONFIG_KEYS.some((key) => typeof config[key] !== 'string')
  )
    throw invalidInput();
  return Object.freeze({ ...config });
}
export function prepareDesktopTenantSkillDefinitionsLoadV2(
  input: DesktopTenantSkillDefinitionsInputV2,
): DesktopTenantSkillDefinitionsInputV2 {
  return prepareCommon(input, ['config', 'scope', 'signal']);
}
export function prepareDesktopTenantSkillDefinitionsItemV2(
  input: DesktopTenantSkillDefinitionsItemInputV2,
): DesktopTenantSkillDefinitionsItemInputV2 {
  return prepareItem(input, ['config', 'scope', 'signal', 'skillId', 'expectedRevision']);
}
export function prepareDesktopTenantSkillDefinitionsCreateV2(
  input: DesktopTenantSkillDefinitionsCreateInputV2,
): DesktopTenantSkillDefinitionsCreateInputV2 {
  const common = prepareCommon(input, ['config', 'scope', 'signal', 'input']);
  const value = input.input;
  requireMutation(value, true);
  if (
    (value.scope !== 'tenant' && value.scope !== 'project') ||
    (value.scope === 'tenant'
      ? value.project_id !== null || common.scope.projectId !== null
      : identifier(value.project_id) !== common.scope.projectId)
  )
    throw invalidInput();
  return Object.freeze({
    ...common,
    input: freezeJson(value, new WeakSet(), 0) as ManagedSkillCreateMutation,
  });
}
export function prepareDesktopTenantSkillDefinitionsUpdateV2(
  input: DesktopTenantSkillDefinitionsUpdateInputV2,
): DesktopTenantSkillDefinitionsUpdateInputV2 {
  const common = prepareItem(input, [
    'config',
    'scope',
    'signal',
    'skillId',
    'expectedRevision',
    'input',
  ]);
  requireMutation(input.input, false);
  return Object.freeze({
    ...common,
    input: freezeJson(input.input, new WeakSet(), 0) as Omit<ManagedSkillMutation, 'full_content'>,
  });
}
export function prepareDesktopTenantSkillDefinitionsContentV2(
  input: DesktopTenantSkillDefinitionsContentInputV2,
): DesktopTenantSkillDefinitionsContentInputV2 {
  const common = prepareItem(input, [
    'config',
    'scope',
    'signal',
    'skillId',
    'expectedRevision',
    'fullContent',
  ]);
  if (typeof input.fullContent !== 'string') throw invalidInput();
  return Object.freeze({ ...common, fullContent: input.fullContent });
}
export function prepareDesktopTenantSkillDefinitionsStatusV2(
  input: DesktopTenantSkillDefinitionsStatusInputV2,
): DesktopTenantSkillDefinitionsStatusInputV2 {
  const common = prepareItem(input, [
    'config',
    'scope',
    'signal',
    'skillId',
    'expectedRevision',
    'status',
  ]);
  if (!skillStatus(input.status)) throw invalidInput();
  return Object.freeze({ ...common, status: input.status });
}
export function requireDesktopTenantSkillDefinitionsV2(
  value: unknown,
  scope: DesktopTenantSkillDefinitionsScopeV2,
): readonly ManagedSkill[] {
  if (!Array.isArray(value) || (scope.authority === 'cloud' && value.length > 500))
    throw invalidResponse();
  const result = value.map((item) => requireDesktopTenantSkillDefinitionV2(item, scope));
  const ids = result.map((item) => JSON.stringify([item.scope, item.project_id ?? null, item.id]));
  if (new Set(ids).size !== ids.length) throw invalidResponse();
  return Object.freeze(result);
}
export function requireDesktopTenantSkillDefinitionV2(
  value: unknown,
  scope: DesktopTenantSkillDefinitionsScopeV2,
  expectedId?: string,
  expectedScope?: 'tenant' | 'project',
): ManagedSkill {
  if (
    !record(value) ||
    !cleanText(value.id) ||
    (expectedId !== undefined && value.id !== expectedId) ||
    !cleanText(value.name) ||
    typeof value.description !== 'string' ||
    !stringArray(value.tools) ||
    !skillStatus(value.status) ||
    !skillScope(value.scope)
  )
    throw invalidResponse();
  const system = value.scope === 'system' && value.is_system_skill === true;
  if (
    (!system && value.tenant_id !== scope.tenantId) ||
    (system && typeof value.tenant_id !== 'string') ||
    (value.project_id !== undefined && value.project_id !== null && !cleanText(value.project_id)) ||
    (expectedScope !== undefined && value.scope !== expectedScope) ||
    (expectedScope === 'project' &&
      (!cleanText(value.project_id) ||
        (scope.projectId !== null && value.project_id !== scope.projectId))) ||
    (value.revision !== undefined && !unsigned(value.revision)) ||
    (value.current_version !== undefined && !unsigned(value.current_version)) ||
    (value.is_system_skill !== undefined && typeof value.is_system_skill !== 'boolean') ||
    (value.full_content !== undefined && !nullableString(value.full_content)) ||
    (value.metadata !== undefined && value.metadata !== null && !record(value.metadata)) ||
    ['license', 'compatibility', 'allowed_tools_raw', 'file_path', 'updated_at'].some(
      (key) => value[key] !== undefined && !nullableString(value[key]),
    )
  )
    throw invalidResponse();
  try {
    return freezeJson(value, new WeakSet(), 0) as ManagedSkill;
  } catch {
    throw invalidResponse();
  }
}
export function requireDesktopTenantSkillContentV2(
  value: unknown,
  expectedId: string,
): ManagedSkillContent {
  if (
    !record(value) ||
    value.skill_id !== expectedId ||
    !cleanText(value.name) ||
    !nullableString(value.full_content) ||
    !skillScope(value.scope) ||
    typeof value.is_system_skill !== 'boolean'
  )
    throw invalidResponse();
  return Object.freeze({
    skill_id: expectedId,
    name: value.name,
    full_content: value.full_content,
    scope: value.scope,
    is_system_skill: value.is_system_skill,
  });
}
export function requireDesktopTenantSkillDeletionV2(value: unknown): void {
  if (value !== undefined) throw invalidResponse();
}
function prepareCommon(
  input: DesktopTenantSkillDefinitionsInputV2,
  allowed: readonly string[],
): DesktopTenantSkillDefinitionsInputV2 {
  if (!record(input) || !allowedOnly(input, allowed)) throw invalidInput();
  const config = freezeDesktopTenantSkillDefinitionsConfigV2(input.config);
  if (
    !record(input.scope) ||
    !exactKeys(input.scope, ['authority', 'tenantId', 'projectId']) ||
    input.scope.authority !== config.mode ||
    identifier(input.scope.tenantId) !== config.tenantId ||
    !(input.scope.projectId === null || cleanText(input.scope.projectId)) ||
    (config.mode === 'local' &&
      input.scope.projectId !== null &&
      input.scope.projectId !== config.projectId) ||
    (input.signal !== undefined && !abortSignal(input.signal))
  )
    throw invalidInput();
  return Object.freeze({
    config,
    scope: Object.freeze({ ...input.scope }),
    ...(input.signal === undefined ? {} : { signal: input.signal }),
  });
}
function prepareItem(
  input: DesktopTenantSkillDefinitionsItemInputV2,
  allowed: readonly string[],
): DesktopTenantSkillDefinitionsItemInputV2 {
  const common = prepareCommon(input, allowed);
  if (
    common.scope.projectId !== null ||
    (input.expectedRevision !== undefined && !unsigned(input.expectedRevision))
  )
    throw invalidInput();
  return Object.freeze({
    ...common,
    skillId: identifier(input.skillId),
    ...(input.expectedRevision === undefined ? {} : { expectedRevision: input.expectedRevision }),
  });
}
function requireMutation(
  value: unknown,
  create: boolean,
): asserts value is ManagedSkillCreateMutation {
  if (
    !record(value) ||
    !allowedOnly(
      value,
      create ? [...MUTATION_KEYS, 'full_content', 'scope', 'project_id'] : MUTATION_KEYS,
    ) ||
    MUTATION_KEYS.some((key) => !Object.hasOwn(value, key)) ||
    !cleanText(value.name) ||
    typeof value.description !== 'string' ||
    !stringArray(value.tools) ||
    !record(value.metadata) ||
    !nullableString(value.license) ||
    !nullableString(value.compatibility) ||
    !nullableString(value.allowed_tools_raw) ||
    typeof value.spec_version !== 'string' ||
    (value.full_content !== undefined && typeof value.full_content !== 'string')
  )
    throw invalidInput();
}
function skillStatus(value: unknown): value is DesktopTenantSkillDefinitionsStatusV2 {
  return value === 'active' || value === 'disabled' || value === 'deprecated';
}
function skillScope(value: unknown): value is string {
  return value === 'system' || value === 'tenant' || value === 'project';
}
function identifier(value: unknown): string {
  if (!cleanText(value)) throw invalidInput();
  return value;
}
function cleanText(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && value === value.trim();
}
function unsigned(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) >= 0;
}
function nullableString(value: unknown): value is string | null {
  return value === null || typeof value === 'string';
}
function stringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === 'string');
}
function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
function allowedOnly(value: Record<string, unknown>, keys: readonly string[]): boolean {
  return Object.keys(value).every((key) => keys.includes(key));
}
function exactKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  return (
    Object.keys(value).length === keys.length && keys.every((key) => Object.hasOwn(value, key))
  );
}
function abortSignal(value: unknown): value is AbortSignal {
  return (
    record(value) &&
    typeof value.aborted === 'boolean' &&
    typeof value.addEventListener === 'function' &&
    typeof value.removeEventListener === 'function'
  );
}
function freezeJson(value: unknown, seen: WeakSet<object>, depth: number): unknown {
  if (depth > 24) throw invalidInput();
  if (value === null || typeof value === 'string' || typeof value === 'boolean') return value;
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value !== 'object' || value === null || seen.has(value) || abortSignal(value))
    throw invalidInput();
  seen.add(value);
  if (Array.isArray(value))
    return Object.freeze(value.map((item) => freezeJson(item, seen, depth + 1)));
  const result: Record<string, unknown> = {};
  for (const [key, item] of Object.entries(value)) {
    if (key === '__proto__' || key === 'constructor' || key === 'prototype') throw invalidInput();
    result[key] = freezeJson(item, seen, depth + 1);
  }
  return Object.freeze(result);
}
function invalidInput(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_tenant_skill_definitions_operation_input_invalid',
    'desktop tenant skill definitions operation input invalid',
  );
}
function invalidResponse(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_tenant_skill_definitions_operation_response_invalid',
    'desktop tenant skill definitions operation response invalid',
  );
}
