import { RuntimeV2Error } from '@agistack/plugin-runtime';

import type {
  TemplatesRouteDetail,
  TemplatesRouteObservation,
  TemplatesRouteQuery,
  TemplatesRouteScope,
} from '../features/settings-routes/templatesRouteClient';
import type {
  DesktopRuntimeConfig,
  ManagedSubAgent,
  ManagedSubAgentTemplate,
} from '../types';

export type DesktopTenantTemplatesSnapshotV2 = Omit<
  TemplatesRouteObservation,
  'templates'
> &
  Readonly<{ templates: readonly ManagedSubAgentTemplate[] }>;

export type DesktopTenantTemplatesLoadInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  scope: TemplatesRouteScope;
  query?: TemplatesRouteQuery;
  signal?: AbortSignal;
}>;

export type PreparedDesktopTenantTemplatesLoadInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  scope: TemplatesRouteScope;
  query: Required<TemplatesRouteQuery>;
  signal?: AbortSignal;
}>;

export type DesktopTenantTemplatesItemInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  scope: TemplatesRouteScope;
  templateId: string;
  signal?: AbortSignal;
}>;

export type DesktopTenantTemplatesSeedInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  scope: TemplatesRouteScope;
  signal?: AbortSignal;
}>;

export interface DesktopTenantTemplatesAuthorityV2 {
  load(
    scope: TemplatesRouteScope,
    query: Required<TemplatesRouteQuery>,
    signal?: AbortSignal,
  ): Promise<DesktopTenantTemplatesSnapshotV2>;
  get(
    scope: TemplatesRouteScope,
    templateId: string,
    signal?: AbortSignal,
  ): Promise<TemplatesRouteDetail>;
  install(
    scope: TemplatesRouteScope,
    templateId: string,
    signal?: AbortSignal,
  ): Promise<ManagedSubAgent>;
  seed(scope: TemplatesRouteScope, signal?: AbortSignal): Promise<number>;
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
const QUERY_KEYS = Object.freeze(['page', 'pageSize', 'category', 'search']);
const SNAPSHOT_KEYS = Object.freeze([
  'scope',
  'authority',
  'availability',
  'reasonCode',
  'allowedActions',
  'itemCount',
  'templates',
  'categories',
  'total',
  'page',
  'pageSize',
]);
const TEMPLATE_KEYS = Object.freeze([
  'id',
  'tenant_id',
  'name',
  'version',
  'display_name',
  'description',
  'category',
  'tags',
  'system_prompt',
  'trigger_description',
  'trigger_keywords',
  'trigger_examples',
  'model',
  'max_tokens',
  'temperature',
  'max_iterations',
  'allowed_tools',
  'author',
  'is_builtin',
  'is_published',
  'install_count',
  'rating',
  'metadata',
  'created_at',
  'updated_at',
]);
const SUMMARY_KEYS = Object.freeze([
  'id',
  'tenant_id',
  'name',
  'version',
  'display_name',
  'description',
  'category',
  'tags',
  'author',
  'is_builtin',
  'is_published',
  'install_count',
  'rating',
  'created_at',
  'updated_at',
]);
const DETAIL_KEYS = Object.freeze([
  ...SUMMARY_KEYS,
  'system_prompt',
  'trigger_description',
  'trigger_keywords',
  'trigger_examples',
  'model',
  'max_tokens',
  'temperature',
  'max_iterations',
  'allowed_tools',
  'metadata',
]);
const ACTIONS = Object.freeze([
  'view',
  'list',
  'search',
  'filter',
  'view-detail',
  'install',
  'seed',
  'retry',
]);

export function prepareDesktopTenantTemplatesLoadV2(
  input: DesktopTenantTemplatesLoadInputV2,
): PreparedDesktopTenantTemplatesLoadInputV2 {
  const common = prepareCommon(input, ['config', 'scope', 'query', 'signal']);
  return Object.freeze({
    ...common,
    query: freezeQuery(input.query),
  });
}

export function prepareDesktopTenantTemplatesItemV2(
  input: DesktopTenantTemplatesItemInputV2,
): DesktopTenantTemplatesItemInputV2 {
  const common = prepareCommon(input, ['config', 'scope', 'templateId', 'signal']);
  return Object.freeze({ ...common, templateId: identifier(input.templateId) });
}

export function prepareDesktopTenantTemplatesSeedV2(
  input: DesktopTenantTemplatesSeedInputV2,
): DesktopTenantTemplatesSeedInputV2 {
  return Object.freeze(prepareCommon(input, ['config', 'scope', 'signal']));
}

export function freezeDesktopTenantTemplatesConfigV2(
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

export function requireDesktopTenantTemplatesSnapshotV2(
  value: unknown,
  scope: TemplatesRouteScope,
  query: Required<TemplatesRouteQuery>,
): DesktopTenantTemplatesSnapshotV2 {
  if (
    !record(value) ||
    !exactKeys(value, SNAPSHOT_KEYS) ||
    !sameScope(value.scope, scope) ||
    value.authority !== scope.authority ||
    value.availability !== 'available' ||
    value.reasonCode !== null ||
    !sameStringArray(value.allowedActions, ACTIONS) ||
    !Array.isArray(value.templates) ||
    !Array.isArray(value.categories) ||
    !nonnegativeInteger(value.itemCount) ||
    !nonnegativeInteger(value.total) ||
    value.itemCount !== value.templates.length ||
    value.page !== query.page ||
    value.pageSize !== query.pageSize ||
    value.categories.some((item) => !cleanText(item))
  ) {
    throw invalidResponse();
  }
  const templates = value.templates.map((item) => requireTemplate(item, scope.tenantId));
  return Object.freeze({
    scope: Object.freeze({ authority: scope.authority, tenantId: scope.tenantId }),
    authority: scope.authority,
    availability: 'available',
    reasonCode: null,
    allowedActions: ACTIONS,
    itemCount: templates.length,
    templates: Object.freeze(templates),
    categories: Object.freeze(value.categories.map((item) => String(item))),
    total: value.total,
    page: query.page,
    pageSize: query.pageSize,
  });
}

export function requireDesktopTenantTemplateDetailV2(
  value: unknown,
  tenantId: string,
): TemplatesRouteDetail {
  if (!record(value) || !exactKeys(value, DETAIL_KEYS)) throw invalidResponse();
  const summary = requireSummary(value, tenantId);
  if (
    typeof value.system_prompt !== 'string' ||
    typeof value.trigger_description !== 'string' ||
    !stringArray(value.trigger_keywords) ||
    !stringArray(value.trigger_examples) ||
    !cleanText(value.model) ||
    !nonnegativeInteger(value.max_tokens) ||
    !finite(value.temperature) ||
    !nonnegativeInteger(value.max_iterations) ||
    !stringArray(value.allowed_tools) ||
    !(value.metadata === null || record(value.metadata))
  ) {
    throw invalidResponse();
  }
  return Object.freeze({
    ...summary,
    system_prompt: value.system_prompt,
    trigger_description: value.trigger_description,
    trigger_keywords: freezeStrings(value.trigger_keywords),
    trigger_examples: freezeStrings(value.trigger_examples),
    model: value.model,
    max_tokens: value.max_tokens,
    temperature: value.temperature,
    max_iterations: value.max_iterations,
    allowed_tools: freezeStrings(value.allowed_tools),
    metadata:
      value.metadata === null
        ? null
        : (freezeJson(value.metadata, new WeakSet(), 0) as Readonly<Record<string, unknown>>),
  });
}

export function requireDesktopTenantTemplateInstallV2(
  value: unknown,
  tenantId: string,
): ManagedSubAgent {
  if (
    !record(value) ||
    !cleanText(value.id) ||
    value.tenant_id !== tenantId ||
    !cleanText(value.name) ||
    typeof value.enabled !== 'boolean' ||
    (value.revision !== undefined && !nonnegativeInteger(value.revision)) ||
    (value.project_id !== undefined && value.project_id !== null && !cleanText(value.project_id)) ||
    (value.source !== undefined && value.source !== 'filesystem' && value.source !== 'database')
  ) {
    throw invalidResponse();
  }
  return freezeJson(value, new WeakSet(), 0) as ManagedSubAgent;
}

export function requireDesktopTenantTemplateSeedV2(value: unknown): number {
  if (!nonnegativeInteger(value)) throw invalidResponse();
  return value;
}

function prepareCommon(
  input: DesktopTenantTemplatesSeedInputV2,
  allowedKeys: readonly string[],
): DesktopTenantTemplatesSeedInputV2 {
  if (!record(input) || !allowedOnly(input, allowedKeys)) throw invalidInput();
  const config = freezeDesktopTenantTemplatesConfigV2(input.config);
  if (
    !record(input.scope) ||
    !exactKeys(input.scope, ['authority', 'tenantId']) ||
    input.scope.authority !== config.mode ||
    identifier(input.scope.tenantId) !== config.tenantId
  ) {
    throw invalidInput();
  }
  if (input.signal !== undefined && !abortSignal(input.signal)) throw invalidInput();
  return {
    config,
    scope: Object.freeze({ authority: input.scope.authority, tenantId: input.scope.tenantId }),
    ...(input.signal === undefined ? {} : { signal: input.signal }),
  };
}

function freezeQuery(query: TemplatesRouteQuery | undefined): Required<TemplatesRouteQuery> {
  if (query !== undefined && (!record(query) || !allowedOnly(query, QUERY_KEYS))) {
    throw invalidInput();
  }
  const value = query ?? {};
  const page = value.page ?? 1;
  const pageSize = value.pageSize ?? 12;
  if (
    !Number.isSafeInteger(page) ||
    page < 1 ||
    !Number.isSafeInteger(pageSize) ||
    pageSize < 1 ||
    pageSize > 100
  ) {
    throw invalidInput();
  }
  return Object.freeze({
    page,
    pageSize,
    category: optionalInputText(value.category),
    search: optionalInputText(value.search),
  });
}

function requireTemplate(value: unknown, tenantId: string): ManagedSubAgentTemplate {
  if (
    !record(value) ||
    !exactKeys(value, TEMPLATE_KEYS) ||
    !cleanText(value.id) ||
    value.tenant_id !== tenantId ||
    !cleanText(value.name) ||
    !cleanText(value.version) ||
    !cleanText(value.category) ||
    !stringArray(value.tags) ||
    typeof value.system_prompt !== 'string' ||
    !(value.trigger_description === null || typeof value.trigger_description === 'string') ||
    !stringArray(value.trigger_keywords) ||
    !stringArray(value.trigger_examples) ||
    !cleanText(value.model) ||
    !nonnegativeInteger(value.max_tokens) ||
    !finite(value.temperature) ||
    !nonnegativeInteger(value.max_iterations) ||
    !stringArray(value.allowed_tools) ||
    typeof value.is_builtin !== 'boolean' ||
    typeof value.is_published !== 'boolean' ||
    !nonnegativeInteger(value.install_count) ||
    !finite(value.rating) ||
    !(value.metadata === null || record(value.metadata)) ||
    !nullableText(value.display_name) ||
    !nullableText(value.description) ||
    !nullableText(value.author) ||
    !nullableText(value.created_at) ||
    !nullableText(value.updated_at)
  ) {
    throw invalidResponse();
  }
  return Object.freeze({
    id: value.id,
    tenant_id: tenantId,
    name: value.name,
    version: value.version,
    display_name: value.display_name,
    description: value.description,
    category: value.category,
    tags: freezeStrings(value.tags),
    system_prompt: value.system_prompt,
    trigger_description: value.trigger_description,
    trigger_keywords: freezeStrings(value.trigger_keywords),
    trigger_examples: freezeStrings(value.trigger_examples),
    model: value.model,
    max_tokens: value.max_tokens,
    temperature: value.temperature,
    max_iterations: value.max_iterations,
    allowed_tools: freezeStrings(value.allowed_tools),
    author: value.author,
    is_builtin: value.is_builtin,
    is_published: value.is_published,
    install_count: value.install_count,
    rating: value.rating,
    metadata:
      value.metadata === null
        ? null
        : (freezeJson(value.metadata, new WeakSet(), 0) as Record<string, unknown>),
    created_at: value.created_at,
    updated_at: value.updated_at,
  });
}

function requireSummary(value: Record<string, unknown>, tenantId: string) {
  if (
    !SUMMARY_KEYS.every((key) => Object.hasOwn(value, key)) ||
    !cleanText(value.id) ||
    value.tenant_id !== tenantId ||
    !cleanText(value.name) ||
    !cleanText(value.version) ||
    !cleanText(value.category) ||
    !stringArray(value.tags) ||
    typeof value.is_builtin !== 'boolean' ||
    typeof value.is_published !== 'boolean' ||
    !nonnegativeInteger(value.install_count) ||
    !finite(value.rating) ||
    !nullableText(value.display_name) ||
    !nullableText(value.description) ||
    !nullableText(value.author) ||
    !nullableText(value.created_at) ||
    !nullableText(value.updated_at)
  ) {
    throw invalidResponse();
  }
  return Object.freeze({
    id: value.id,
    tenant_id: tenantId,
    name: value.name,
    version: value.version,
    display_name: value.display_name,
    description: value.description,
    category: value.category,
    tags: freezeStrings(value.tags),
    author: value.author,
    is_builtin: value.is_builtin,
    is_published: value.is_published,
    install_count: value.install_count,
    rating: value.rating,
    created_at: value.created_at,
    updated_at: value.updated_at,
  });
}

function freezeJson(value: unknown, seen: WeakSet<object>, depth: number): unknown {
  if (depth > 24) throw invalidResponse();
  if (value === null || typeof value === 'string' || typeof value === 'boolean') return value;
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) throw invalidResponse();
    return value;
  }
  if (typeof value !== 'object') throw invalidResponse();
  if (seen.has(value)) throw invalidResponse();
  seen.add(value);
  if (Array.isArray(value)) {
    return Object.freeze(value.map((item) => freezeJson(item, seen, depth + 1)));
  }
  const source = value as Record<string, unknown>;
  const copy: Record<string, unknown> = {};
  for (const [key, item] of Object.entries(source)) {
    if (key === '__proto__' || key === 'prototype' || key === 'constructor') {
      throw invalidResponse();
    }
    copy[key] = freezeJson(item, seen, depth + 1);
  }
  return Object.freeze(copy);
}

function sameScope(value: unknown, expected: TemplatesRouteScope): boolean {
  return (
    record(value) &&
    exactKeys(value, ['authority', 'tenantId']) &&
    value.authority === expected.authority &&
    value.tenantId === expected.tenantId
  );
}

function abortSignal(value: unknown): value is AbortSignal {
  return (
    record(value) &&
    typeof value.aborted === 'boolean' &&
    typeof value.addEventListener === 'function'
  );
}

function allowedOnly(value: Record<string, unknown>, keys: readonly string[]): boolean {
  return Object.keys(value).every((key) => keys.includes(key));
}

function exactKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  return Object.keys(value).length === keys.length && keys.every((key) => Object.hasOwn(value, key));
}

function identifier(value: unknown): string {
  if (!cleanText(value) || value !== value.trim()) throw invalidInput();
  return value;
}

function optionalInputText(value: unknown): string {
  if (value === undefined) return '';
  if (typeof value !== 'string' || value !== value.trim()) throw invalidInput();
  return value;
}

function cleanText(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && value === value.trim();
}

function nullableText(value: unknown): value is string | null {
  return value === null || cleanText(value);
}

function stringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === 'string');
}

function freezeStrings(value: unknown[]): string[] {
  return Object.freeze(value.map((item) => String(item))) as string[];
}

function sameStringArray(value: unknown, expected: readonly string[]): boolean {
  return (
    Array.isArray(value) &&
    value.length === expected.length &&
    value.every((item, index) => item === expected[index])
  );
}

function nonnegativeInteger(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) >= 0;
}

function finite(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function invalidInput(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_tenant_templates_operation_input_invalid',
    'desktop tenant templates operation input invalid',
  );
}

function invalidResponse(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_tenant_templates_operation_response_invalid',
    'desktop tenant templates operation response invalid',
  );
}
