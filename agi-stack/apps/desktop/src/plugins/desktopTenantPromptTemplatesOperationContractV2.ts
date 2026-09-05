import { RuntimeV2Error } from '@agistack/plugin-runtime';

import type {
  DesktopRuntimeConfig,
  PromptTemplateCreateInput,
  PromptTemplateRecord,
  PromptTemplateVariable,
} from '../types';

export type DesktopTenantPromptTemplatesScopeV2 = Readonly<{
  authority: DesktopRuntimeConfig['mode'];
  tenantId: string;
}>;

export type DesktopTenantPromptTemplatesLoadInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  scope: DesktopTenantPromptTemplatesScopeV2;
  signal?: AbortSignal;
}>;

export type DesktopTenantPromptTemplatesCreateInputV2 =
  DesktopTenantPromptTemplatesLoadInputV2 &
    Readonly<{ input: PromptTemplateCreateInput }>;

export type DesktopTenantPromptTemplatesDeleteInputV2 =
  DesktopTenantPromptTemplatesLoadInputV2 &
    Readonly<{ templateId: string; expectedRevision?: number }>;

export interface DesktopTenantPromptTemplatesAuthorityV2 {
  list(
    scope: DesktopTenantPromptTemplatesScopeV2,
    signal?: AbortSignal,
  ): Promise<readonly PromptTemplateRecord[]>;
  create(
    scope: DesktopTenantPromptTemplatesScopeV2,
    input: PromptTemplateCreateInput,
    signal?: AbortSignal,
  ): Promise<PromptTemplateRecord>;
  delete(
    scope: DesktopTenantPromptTemplatesScopeV2,
    templateId: string,
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

export function prepareDesktopTenantPromptTemplatesLoadV2(
  input: DesktopTenantPromptTemplatesLoadInputV2,
): DesktopTenantPromptTemplatesLoadInputV2 {
  return Object.freeze(prepareCommon(input, ['config', 'scope', 'signal']));
}

export function prepareDesktopTenantPromptTemplatesCreateV2(
  input: DesktopTenantPromptTemplatesCreateInputV2,
): DesktopTenantPromptTemplatesCreateInputV2 {
  const common = prepareCommon(input, ['config', 'scope', 'input', 'signal']);
  if (!record(input.input) || !exactKeys(input.input, ['title', 'content', 'category'])) {
    throw invalidInput();
  }
  const mutation = Object.freeze({
    title: normalizedDraftText(input.input.title),
    content: normalizedDraftText(input.input.content),
    category: normalizedDraftText(input.input.category),
  });
  return Object.freeze({ ...common, input: mutation });
}

export function prepareDesktopTenantPromptTemplatesDeleteV2(
  input: DesktopTenantPromptTemplatesDeleteInputV2,
): DesktopTenantPromptTemplatesDeleteInputV2 {
  const common = prepareCommon(input, [
    'config',
    'scope',
    'templateId',
    'expectedRevision',
    'signal',
  ]);
  return Object.freeze({
    ...common,
    templateId: cleanRequired(input.templateId),
    ...(input.expectedRevision === undefined
      ? {}
      : { expectedRevision: revision(input.expectedRevision) }),
  });
}

export function freezeDesktopTenantPromptTemplatesConfigV2(
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
  cleanRequired(config.tenantId);
  return Object.freeze({ ...config });
}

export function requireDesktopTenantPromptTemplatesV2(
  value: unknown,
  tenantId: string,
): readonly PromptTemplateRecord[] {
  if (!Array.isArray(value) || value.length > 100) throw invalidResponse();
  const seen = new Set<string>();
  const templates = value.map((item) => requireDesktopTenantPromptTemplateV2(item, tenantId));
  if (templates.some((template) => seen.has(template.id) || !seen.add(template.id))) {
    throw invalidResponse();
  }
  return Object.freeze(templates);
}

export function requireDesktopTenantPromptTemplateV2(
  value: unknown,
  tenantId: string,
  expected?: PromptTemplateCreateInput,
): PromptTemplateRecord {
  if (
    !record(value) ||
    !cleanText(value.id) ||
    value.tenant_id !== tenantId ||
    !(value.project_id === null || cleanText(value.project_id)) ||
    !cleanText(value.created_by) ||
    !cleanText(value.title) ||
    typeof value.content !== 'string' ||
    !cleanText(value.category) ||
    !Array.isArray(value.variables) ||
    value.variables.length > 100 ||
    typeof value.is_system !== 'boolean' ||
    !unsigned(value.usage_count) ||
    !cleanText(value.created_at) ||
    !cleanText(value.updated_at) ||
    (value.revision !== undefined && !unsigned(value.revision)) ||
    (expected !== undefined &&
      (value.title !== expected.title ||
        value.content !== expected.content ||
        value.category !== expected.category ||
        value.is_system ||
        value.project_id !== null ||
        value.variables.length !== 0))
  ) {
    throw invalidResponse();
  }
  return Object.freeze({
    id: value.id,
    ...(value.revision === undefined ? {} : { revision: value.revision }),
    tenant_id: tenantId,
    project_id: value.project_id,
    created_by: value.created_by,
    title: value.title,
    content: value.content,
    category: value.category,
    variables: Object.freeze(value.variables.map(requireVariable)),
    is_system: value.is_system,
    usage_count: value.usage_count,
    created_at: value.created_at,
    updated_at: value.updated_at,
  }) as unknown as PromptTemplateRecord;
}

export function requireDesktopTenantPromptTemplateDeleteV2(value: unknown): void {
  if (value !== undefined) throw invalidResponse();
}

function prepareCommon(
  input: DesktopTenantPromptTemplatesLoadInputV2,
  allowedKeys: readonly string[],
): DesktopTenantPromptTemplatesLoadInputV2 {
  if (!record(input) || !allowedOnly(input, allowedKeys)) throw invalidInput();
  const config = freezeDesktopTenantPromptTemplatesConfigV2(input.config);
  if (
    !record(input.scope) ||
    !exactKeys(input.scope, ['authority', 'tenantId']) ||
    input.scope.authority !== config.mode ||
    cleanRequired(input.scope.tenantId) !== config.tenantId
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

function requireVariable(value: unknown): PromptTemplateVariable {
  if (
    !record(value) ||
    !exactKeys(value, ['name', 'description', 'default_value', 'required']) ||
    !cleanText(value.name) ||
    typeof value.description !== 'string' ||
    typeof value.default_value !== 'string' ||
    typeof value.required !== 'boolean'
  ) {
    throw invalidResponse();
  }
  return Object.freeze({
    name: value.name,
    description: value.description,
    default_value: value.default_value,
    required: value.required,
  });
}

function normalizedDraftText(value: unknown): string {
  if (typeof value !== 'string') throw invalidInput();
  return cleanRequired(value.trim());
}

function cleanRequired(value: unknown): string {
  if (!cleanText(value)) throw invalidInput();
  return value;
}

function revision(value: unknown): number {
  if (!unsigned(value)) throw invalidInput();
  return value;
}

function abortSignal(value: unknown): value is AbortSignal {
  return record(value) && typeof value.aborted === 'boolean' && typeof value.addEventListener === 'function';
}

function cleanText(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && value === value.trim();
}

function unsigned(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) >= 0;
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function exactKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  const actual = Object.keys(value).sort();
  const expected = [...keys].sort();
  return actual.length === expected.length && actual.every((key, index) => key === expected[index]);
}

function allowedOnly(value: Record<string, unknown>, keys: readonly string[]): boolean {
  return Object.keys(value).every((key) => keys.includes(key));
}

function invalidInput(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_tenant_prompt_templates_operation_input_invalid',
    'desktop tenant prompt templates operation input invalid',
  );
}

function invalidResponse(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_tenant_prompt_templates_operation_response_invalid',
    'desktop tenant prompt templates operation response invalid',
  );
}
