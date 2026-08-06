import type { DesktopRuntimeConfig } from '../../types';
import {
  exactNativeRouteIdentifier,
  isNativeRouteRecord,
  NativeRouteClientError,
  requestNativeRouteJson,
  requireRuntimeAuthority,
} from './nativeRouteHttpClient';

export type TemplatesRouteScope = Readonly<{
  authority: DesktopRuntimeConfig['mode'];
  tenantId: string;
}>;

export type TemplatesRouteQuery = Readonly<{
  page?: number;
  pageSize?: number;
  category?: string;
  search?: string;
}>;

export type TemplatesRouteSummary = Readonly<{
  id: string;
  tenant_id: string;
  name: string;
  version: string;
  display_name: string | null;
  description: string | null;
  category: string;
  tags: readonly string[];
  author: string | null;
  is_builtin: boolean;
  is_published: boolean;
  install_count: number;
  rating: number;
  created_at: string | null;
  updated_at: string | null;
}>;

export type TemplatesRouteDetail = TemplatesRouteSummary &
  Readonly<{
    system_prompt: string;
    trigger_description: string;
    trigger_keywords: readonly string[];
    trigger_examples: readonly string[];
    model: string;
    max_tokens: number;
    temperature: number;
    max_iterations: number;
    allowed_tools: readonly string[];
    metadata: Readonly<Record<string, unknown>> | null;
  }>;

export type TemplatesRouteObservation = Readonly<{
  scope: TemplatesRouteScope;
  authority: DesktopRuntimeConfig['mode'];
  availability: 'available';
  reasonCode: null;
  allowedActions: readonly string[];
  itemCount: number;
  templates: readonly TemplatesRouteSummary[];
  categories: readonly string[];
  total: number;
  page: number;
  pageSize: number;
}>;

export type TemplatesRouteClient = Readonly<{
  observe(
    scope: TemplatesRouteScope,
    query?: TemplatesRouteQuery,
    signal?: AbortSignal,
  ): Promise<TemplatesRouteObservation>;
  get(
    scope: TemplatesRouteScope,
    templateId: string,
    signal?: AbortSignal,
  ): Promise<TemplatesRouteDetail>;
  install(scope: TemplatesRouteScope, templateId: string, signal?: AbortSignal): Promise<void>;
  seed(scope: TemplatesRouteScope, signal?: AbortSignal): Promise<number>;
}>;

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

export function createTemplatesRouteClient(config: DesktopRuntimeConfig): TemplatesRouteClient {
  const runtime = Object.freeze({ ...config });
  return Object.freeze({
    async observe(scope, query = {}, signal) {
      const current = requireScope(runtime, scope);
      const normalized = normalizeQuery(query);
      const params = new URLSearchParams({
        tenant_id: current.tenantId,
        limit: String(normalized.pageSize),
        offset: String((normalized.page - 1) * normalized.pageSize),
      });
      if (normalized.category) params.set('category', normalized.category);
      if (normalized.search) params.set('query', normalized.search);
      const listPath = `/api/v1/subagents/templates/list?${params.toString()}`;
      if (runtime.mode === 'local') {
        await requestNativeRouteJson(runtime, listPath, { signal });
        throw new NativeRouteClientError(
          'local_template_marketplace_authority_contract_invalid',
          502,
        );
      }
      const [listPayload, categoryPayload] = await Promise.all([
        requestNativeRouteJson(runtime, listPath, { signal }),
        requestNativeRouteJson(
          runtime,
          `/api/v1/subagents/templates/categories?tenant_id=${encodeURIComponent(current.tenantId)}`,
          { signal },
        ),
      ]);
      const list = parseList(listPayload);
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
        page: normalized.page,
        pageSize: normalized.pageSize,
      });
    },
    async get(scope, templateId, signal) {
      const current = requireScope(runtime, scope);
      const id = exactNativeRouteIdentifier(templateId, 'template_marketplace_template_id_invalid');
      const payload = await requestNativeRouteJson(
        runtime,
        `/api/v1/subagents/templates/${encodeURIComponent(id)}?tenant_id=${encodeURIComponent(current.tenantId)}`,
        { signal },
      );
      return parseDetail(payload);
    },
    async install(scope, templateId, signal) {
      const current = requireScope(runtime, scope);
      const id = exactNativeRouteIdentifier(templateId, 'template_marketplace_template_id_invalid');
      await requestNativeRouteJson(
        runtime,
        `/api/v1/subagents/templates/${encodeURIComponent(id)}/install?tenant_id=${encodeURIComponent(current.tenantId)}`,
        { method: 'POST', signal },
      );
    },
    async seed(scope, signal) {
      const current = requireScope(runtime, scope);
      const payload = await requestNativeRouteJson(
        runtime,
        `/api/v1/subagents/templates/seed?tenant_id=${encodeURIComponent(current.tenantId)}`,
        { method: 'POST', signal },
      );
      if (
        !isNativeRouteRecord(payload) ||
        !Number.isSafeInteger(payload.created) ||
        (payload.created as number) < 0
      ) {
        throw new NativeRouteClientError(
          'template_marketplace_seed_contract_invalid',
          502,
          payload,
        );
      }
      return payload.created as number;
    },
  });
}

function requireScope(
  config: DesktopRuntimeConfig,
  scope: TemplatesRouteScope,
): TemplatesRouteScope {
  requireRuntimeAuthority(config, scope.authority, 'template_marketplace_runtime_scope_mismatch');
  const tenantId = exactNativeRouteIdentifier(
    scope.tenantId,
    'template_marketplace_tenant_scope_invalid',
  );
  if (tenantId !== config.tenantId) {
    throw new NativeRouteClientError('template_marketplace_runtime_scope_mismatch', 409);
  }
  return Object.freeze({ authority: scope.authority, tenantId });
}

function normalizeQuery(query: TemplatesRouteQuery): Required<TemplatesRouteQuery> {
  const page = Number.isSafeInteger(query.page) && (query.page ?? 0) > 0 ? query.page! : 1;
  const pageSize =
    Number.isSafeInteger(query.pageSize) &&
    (query.pageSize ?? 0) > 0 &&
    (query.pageSize ?? 0) <= 100
      ? query.pageSize!
      : 12;
  return {
    page,
    pageSize,
    category: cleanOptional(query.category),
    search: cleanOptional(query.search),
  };
}

function parseList(
  payload: unknown,
): Readonly<{ templates: readonly TemplatesRouteSummary[]; total: number }> {
  if (
    !isNativeRouteRecord(payload) ||
    !Array.isArray(payload.templates) ||
    !Number.isSafeInteger(payload.total)
  ) {
    throw new NativeRouteClientError('template_marketplace_list_contract_invalid', 502, payload);
  }
  const templates = payload.templates.map(parseSummary);
  return Object.freeze({
    templates: Object.freeze(templates),
    total: payload.total as number,
  });
}

function parseCategories(payload: unknown): readonly string[] {
  if (
    !isNativeRouteRecord(payload) ||
    !Array.isArray(payload.categories) ||
    payload.categories.some((value) => typeof value !== 'string')
  ) {
    throw new NativeRouteClientError(
      'template_marketplace_categories_contract_invalid',
      502,
      payload,
    );
  }
  return Object.freeze(payload.categories.map((value) => (value as string).trim()).filter(Boolean));
}

function parseSummary(payload: unknown): TemplatesRouteSummary {
  if (!isNativeRouteRecord(payload)) {
    throw new NativeRouteClientError(
      'template_marketplace_template_contract_invalid',
      502,
      payload,
    );
  }
  const id = requiredText(payload.id);
  const tenantId = requiredText(payload.tenant_id);
  const name = requiredText(payload.name);
  const version = requiredText(payload.version);
  const category = requiredText(payload.category);
  if (
    !id ||
    !tenantId ||
    !name ||
    !version ||
    !category ||
    !Array.isArray(payload.tags) ||
    payload.tags.some((value) => typeof value !== 'string') ||
    typeof payload.is_builtin !== 'boolean' ||
    typeof payload.is_published !== 'boolean' ||
    typeof payload.install_count !== 'number' ||
    typeof payload.rating !== 'number'
  ) {
    throw new NativeRouteClientError(
      'template_marketplace_template_contract_invalid',
      502,
      payload,
    );
  }
  return Object.freeze({
    id,
    tenant_id: tenantId,
    name,
    version,
    display_name: optionalText(payload.display_name),
    description: optionalText(payload.description),
    category,
    tags: Object.freeze(payload.tags.map((value) => value as string)),
    author: optionalText(payload.author),
    is_builtin: payload.is_builtin,
    is_published: payload.is_published,
    install_count: payload.install_count,
    rating: payload.rating,
    created_at: optionalText(payload.created_at),
    updated_at: optionalText(payload.updated_at),
  });
}

function parseDetail(payload: unknown): TemplatesRouteDetail {
  const summary = parseSummary(payload);
  if (
    !isNativeRouteRecord(payload) ||
    typeof payload.system_prompt !== 'string' ||
    typeof payload.trigger_description !== 'string' ||
    !Array.isArray(payload.trigger_keywords) ||
    !Array.isArray(payload.trigger_examples) ||
    typeof payload.model !== 'string' ||
    typeof payload.max_tokens !== 'number' ||
    typeof payload.temperature !== 'number' ||
    typeof payload.max_iterations !== 'number' ||
    !Array.isArray(payload.allowed_tools)
  ) {
    throw new NativeRouteClientError('template_marketplace_detail_contract_invalid', 502, payload);
  }
  return Object.freeze({
    ...summary,
    system_prompt: payload.system_prompt,
    trigger_description: payload.trigger_description,
    trigger_keywords: Object.freeze(payload.trigger_keywords.map(String)),
    trigger_examples: Object.freeze(payload.trigger_examples.map(String)),
    model: payload.model,
    max_tokens: payload.max_tokens,
    temperature: payload.temperature,
    max_iterations: payload.max_iterations,
    allowed_tools: Object.freeze(payload.allowed_tools.map(String)),
    metadata: isNativeRouteRecord(payload.metadata) ? Object.freeze({ ...payload.metadata }) : null,
  });
}

function requiredText(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}

function optionalText(value: unknown): string | null {
  return value === null || value === undefined ? null : requiredText(value);
}

function cleanOptional(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}
