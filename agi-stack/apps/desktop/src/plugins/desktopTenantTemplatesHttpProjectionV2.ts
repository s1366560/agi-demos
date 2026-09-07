import type {
  TemplatesRouteDetail,
  TemplatesRouteQuery,
  TemplatesRouteScope,
} from '../features/settings-routes/templatesRouteClient';
import {
  exactNativeRouteIdentifier,
  isNativeRouteRecord,
  NativeRouteClientError,
  requestNativeRouteJson,
  requireRuntimeAuthority,
} from '../features/settings-routes/nativeRouteHttpClient';
import type {
  DesktopRuntimeConfig,
  ManagedSubAgent,
  ManagedSubAgentTemplate,
} from '../types';
import type {
  DesktopTenantTemplatesAuthorityV2,
  DesktopTenantTemplatesSnapshotV2,
} from './desktopTenantTemplatesOperationContractV2';

export const DESKTOP_TENANT_TEMPLATES_LOCAL_REASON_V2 =
  'local_subagent_registry_unavailable';

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

export function createDesktopTenantTemplatesHttpProjectionV2(
  config: DesktopRuntimeConfig,
): DesktopTenantTemplatesAuthorityV2 {
  const runtime = Object.freeze({ ...config });
  const authority: DesktopTenantTemplatesAuthorityV2 = {
    async load(scope, query, signal): Promise<DesktopTenantTemplatesSnapshotV2> {
      const current = requireScope(runtime, scope);
      const params = listParams(current, query);
      const listPath = `/api/v1/subagents/templates/list?${params.toString()}`;
      if (runtime.mode === 'local') {
        return localUnavailable(() => requestNativeRouteJson(runtime, listPath, { signal }));
      }
      const [listPayload, categoryPayload] = await Promise.all([
        requestNativeRouteJson(runtime, listPath, { signal }),
        requestNativeRouteJson(
          runtime,
          `/api/v1/subagents/templates/categories?tenant_id=${encodeURIComponent(
            current.tenantId,
          )}`,
          { signal },
        ),
      ]);
      const list = parseList(listPayload, current.tenantId);
      const categories = parseCategories(categoryPayload);
      return Object.freeze({
        scope: current,
        authority: current.authority,
        availability: 'available',
        reasonCode: null,
        allowedActions: ACTIONS,
        itemCount: list.templates.length,
        templates: list.templates,
        categories,
        total: list.total,
        page: query.page,
        pageSize: query.pageSize,
      }) satisfies DesktopTenantTemplatesSnapshotV2;
    },
    async get(scope, templateId, signal): Promise<TemplatesRouteDetail> {
      const current = requireScope(runtime, scope);
      const id = exactNativeRouteIdentifier(
        templateId,
        'template_marketplace_template_id_invalid',
      );
      const path =
        `/api/v1/subagents/templates/${encodeURIComponent(id)}` +
        `?tenant_id=${encodeURIComponent(current.tenantId)}`;
      if (runtime.mode === 'local') {
        return localUnavailable(() => requestNativeRouteJson(runtime, path, { signal }));
      }
      return parseDetail(await requestNativeRouteJson(runtime, path, { signal }), current.tenantId);
    },
    async install(scope, templateId, signal): Promise<ManagedSubAgent> {
      const current = requireScope(runtime, scope);
      const id = exactNativeRouteIdentifier(
        templateId,
        'template_marketplace_template_id_invalid',
      );
      const path =
        `/api/v1/subagents/templates/${encodeURIComponent(id)}/install` +
        `?tenant_id=${encodeURIComponent(current.tenantId)}`;
      if (runtime.mode === 'local') {
        return localUnavailable(() =>
          requestNativeRouteJson(runtime, path, { method: 'POST', signal }),
        );
      }
      return parseInstalled(
        await requestNativeRouteJson(runtime, path, { method: 'POST', signal }),
        current.tenantId,
      );
    },
    async seed(scope, signal): Promise<number> {
      const current = requireScope(runtime, scope);
      const path =
        '/api/v1/subagents/templates/seed' +
        `?tenant_id=${encodeURIComponent(current.tenantId)}`;
      if (runtime.mode === 'local') {
        return localUnavailable(() =>
          requestNativeRouteJson(runtime, path, { method: 'POST', signal }),
        );
      }
      const payload = await requestNativeRouteJson(runtime, path, {
        method: 'POST',
        signal,
      });
      if (
        !isNativeRouteRecord(payload) ||
        !Number.isSafeInteger(payload.created) ||
        Number(payload.created) < 0
      ) {
        throw contractError('template_marketplace_seed_contract_invalid', payload);
      }
      return payload.created as number;
    },
  };
  return Object.freeze(authority);
}

function listParams(
  scope: TemplatesRouteScope,
  query: Required<TemplatesRouteQuery>,
): URLSearchParams {
  const params = new URLSearchParams({
    tenant_id: scope.tenantId,
    limit: String(query.pageSize),
    offset: String((query.page - 1) * query.pageSize),
  });
  if (query.category) params.set('category', query.category);
  if (query.search) params.set('query', query.search);
  return params;
}

function requireScope(
  config: DesktopRuntimeConfig,
  scope: TemplatesRouteScope,
): TemplatesRouteScope {
  requireRuntimeAuthority(
    config,
    scope.authority,
    'template_marketplace_runtime_scope_mismatch',
  );
  const tenantId = exactNativeRouteIdentifier(
    scope.tenantId,
    'template_marketplace_tenant_scope_invalid',
  );
  if (tenantId !== config.tenantId) {
    throw new NativeRouteClientError('template_marketplace_runtime_scope_mismatch', 409);
  }
  return Object.freeze({ authority: scope.authority, tenantId });
}

async function localUnavailable<T>(request: () => Promise<unknown>): Promise<T> {
  try {
    await request();
  } catch (error) {
    if (
      error instanceof NativeRouteClientError &&
      (error.status === 404 || error.status === 501)
    ) {
      throw new NativeRouteClientError(
        DESKTOP_TENANT_TEMPLATES_LOCAL_REASON_V2,
        error.status,
        error.payload,
      );
    }
    throw error;
  }
  throw new NativeRouteClientError(
    'local_template_marketplace_authority_contract_invalid',
    502,
  );
}

function parseList(
  payload: unknown,
  tenantId: string,
): Readonly<{ templates: readonly ManagedSubAgentTemplate[]; total: number }> {
  if (
    !isNativeRouteRecord(payload) ||
    !Array.isArray(payload.templates) ||
    !Number.isSafeInteger(payload.total) ||
    Number(payload.total) < 0
  ) {
    throw contractError('template_marketplace_list_contract_invalid', payload);
  }
  return Object.freeze({
    templates: Object.freeze(
      payload.templates.map((template) => parseTemplate(template, tenantId)),
    ),
    total: payload.total as number,
  });
}

function parseCategories(payload: unknown): readonly string[] {
  if (
    !isNativeRouteRecord(payload) ||
    !Array.isArray(payload.categories) ||
    payload.categories.some((category) => !cleanText(category))
  ) {
    throw contractError('template_marketplace_categories_contract_invalid', payload);
  }
  return Object.freeze(payload.categories.map((category) => category as string));
}

function parseTemplate(payload: unknown, tenantId: string): ManagedSubAgentTemplate {
  if (
    !isNativeRouteRecord(payload) ||
    !cleanText(payload.id) ||
    payload.tenant_id !== tenantId ||
    !cleanText(payload.name) ||
    !cleanText(payload.version) ||
    !cleanText(payload.category) ||
    !stringArray(payload.tags) ||
    typeof payload.system_prompt !== 'string' ||
    !(payload.trigger_description === null || typeof payload.trigger_description === 'string') ||
    !stringArray(payload.trigger_keywords) ||
    !stringArray(payload.trigger_examples) ||
    !cleanText(payload.model) ||
    !nonnegativeInteger(payload.max_tokens) ||
    !finite(payload.temperature) ||
    !nonnegativeInteger(payload.max_iterations) ||
    !stringArray(payload.allowed_tools) ||
    typeof payload.is_builtin !== 'boolean' ||
    typeof payload.is_published !== 'boolean' ||
    !nonnegativeInteger(payload.install_count) ||
    !finite(payload.rating) ||
    !(payload.metadata === null || isNativeRouteRecord(payload.metadata)) ||
    !nullableText(payload.display_name) ||
    !nullableText(payload.description) ||
    !nullableText(payload.author) ||
    !nullableText(payload.created_at) ||
    !nullableText(payload.updated_at)
  ) {
    throw contractError('template_marketplace_template_contract_invalid', payload);
  }
  return Object.freeze({
    id: payload.id,
    tenant_id: tenantId,
    name: payload.name,
    version: payload.version,
    display_name: payload.display_name,
    description: payload.description,
    category: payload.category,
    tags: freezeStrings(payload.tags),
    system_prompt: payload.system_prompt,
    trigger_description: payload.trigger_description,
    trigger_keywords: freezeStrings(payload.trigger_keywords),
    trigger_examples: freezeStrings(payload.trigger_examples),
    model: payload.model,
    max_tokens: payload.max_tokens,
    temperature: payload.temperature,
    max_iterations: payload.max_iterations,
    allowed_tools: freezeStrings(payload.allowed_tools),
    author: payload.author,
    is_builtin: payload.is_builtin,
    is_published: payload.is_published,
    install_count: payload.install_count,
    rating: payload.rating,
    metadata:
      payload.metadata === null
        ? null
        : (freezeJson(payload.metadata, new WeakSet(), 0) as Record<string, unknown>),
    created_at: payload.created_at,
    updated_at: payload.updated_at,
  });
}

function parseDetail(payload: unknown, tenantId: string): TemplatesRouteDetail {
  if (!isNativeRouteRecord(payload)) {
    throw contractError('template_marketplace_detail_contract_invalid', payload);
  }
  const summary = parseSummary(payload, tenantId);
  if (
    typeof payload.system_prompt !== 'string' ||
    typeof payload.trigger_description !== 'string' ||
    !stringArray(payload.trigger_keywords) ||
    !stringArray(payload.trigger_examples) ||
    !cleanText(payload.model) ||
    !nonnegativeInteger(payload.max_tokens) ||
    !finite(payload.temperature) ||
    !nonnegativeInteger(payload.max_iterations) ||
    !stringArray(payload.allowed_tools) ||
    !(payload.metadata === null || isNativeRouteRecord(payload.metadata))
  ) {
    throw contractError('template_marketplace_detail_contract_invalid', payload);
  }
  return Object.freeze({
    ...summary,
    system_prompt: payload.system_prompt,
    trigger_description: payload.trigger_description,
    trigger_keywords: freezeStrings(payload.trigger_keywords),
    trigger_examples: freezeStrings(payload.trigger_examples),
    model: payload.model,
    max_tokens: payload.max_tokens,
    temperature: payload.temperature,
    max_iterations: payload.max_iterations,
    allowed_tools: freezeStrings(payload.allowed_tools),
    metadata:
      payload.metadata === null
        ? null
        : (freezeJson(payload.metadata, new WeakSet(), 0) as Readonly<
            Record<string, unknown>
          >),
  });
}

function parseSummary(payload: Record<string, unknown>, tenantId: string) {
  if (
    !cleanText(payload.id) ||
    payload.tenant_id !== tenantId ||
    !cleanText(payload.name) ||
    !cleanText(payload.version) ||
    !cleanText(payload.category) ||
    !stringArray(payload.tags) ||
    typeof payload.is_builtin !== 'boolean' ||
    typeof payload.is_published !== 'boolean' ||
    !nonnegativeInteger(payload.install_count) ||
    !finite(payload.rating) ||
    !nullableText(payload.display_name) ||
    !nullableText(payload.description) ||
    !nullableText(payload.author) ||
    !nullableText(payload.created_at) ||
    !nullableText(payload.updated_at)
  ) {
    throw contractError('template_marketplace_template_contract_invalid', payload);
  }
  return Object.freeze({
    id: payload.id,
    tenant_id: tenantId,
    name: payload.name,
    version: payload.version,
    display_name: payload.display_name,
    description: payload.description,
    category: payload.category,
    tags: freezeStrings(payload.tags),
    author: payload.author,
    is_builtin: payload.is_builtin,
    is_published: payload.is_published,
    install_count: payload.install_count,
    rating: payload.rating,
    created_at: payload.created_at,
    updated_at: payload.updated_at,
  });
}

function parseInstalled(payload: unknown, tenantId: string): ManagedSubAgent {
  if (
    !isNativeRouteRecord(payload) ||
    !cleanText(payload.id) ||
    payload.tenant_id !== tenantId ||
    !cleanText(payload.name) ||
    typeof payload.enabled !== 'boolean' ||
    (payload.source !== undefined &&
      payload.source !== 'filesystem' &&
      payload.source !== 'database')
  ) {
    throw contractError('template_marketplace_install_contract_invalid', payload);
  }
  return freezeJson(payload, new WeakSet(), 0) as ManagedSubAgent;
}

function freezeJson(value: unknown, seen: WeakSet<object>, depth: number): unknown {
  if (depth > 24) throw contractError('template_marketplace_response_contract_invalid');
  if (value === null || typeof value === 'string' || typeof value === 'boolean') return value;
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) {
      throw contractError('template_marketplace_response_contract_invalid', value);
    }
    return value;
  }
  if (typeof value !== 'object') {
    throw contractError('template_marketplace_response_contract_invalid', value);
  }
  if (seen.has(value)) throw contractError('template_marketplace_response_contract_invalid');
  seen.add(value);
  if (Array.isArray(value)) {
    return Object.freeze(value.map((item) => freezeJson(item, seen, depth + 1)));
  }
  const source = value as Record<string, unknown>;
  const copy: Record<string, unknown> = {};
  for (const [key, item] of Object.entries(source)) {
    if (key === '__proto__' || key === 'prototype' || key === 'constructor') {
      throw contractError('template_marketplace_response_contract_invalid');
    }
    copy[key] = freezeJson(item, seen, depth + 1);
  }
  return Object.freeze(copy);
}

function freezeStrings(values: string[]): string[] {
  return Object.freeze([...values]) as string[];
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

function nonnegativeInteger(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) >= 0;
}

function finite(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function contractError(reasonCode: string, payload: unknown = null): NativeRouteClientError {
  return new NativeRouteClientError(reasonCode, 502, payload);
}
