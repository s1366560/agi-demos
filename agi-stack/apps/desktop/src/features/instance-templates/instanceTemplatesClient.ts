import {
  absoluteUrl,
  DesktopApiError,
  desktopApiCredential,
  desktopLaunchCapability,
} from '../../api/client';
import { desktopApiFetch } from '../../api/cloudRequestBroker';
import type { DesktopRuntimeConfig } from '../../types';
import type {
  InstanceTemplateCreateInput,
  InstanceTemplateItem,
  InstanceTemplateSummary,
  InstanceTemplatesClient,
  InstanceTemplatesPage,
  InstanceTemplatesQuery,
  InstanceTemplatesScope,
} from './instanceTemplatesTypes';

type Fetch = typeof globalThis.fetch;
type FetchPath = (path: string, init: RequestInit) => Promise<Response>;

export type InstanceTemplatesClientDependencies = Readonly<{
  fetch?: Fetch;
}>;

export class InstanceTemplatesUnavailableError extends Error {
  readonly reasonCode: string;

  constructor(reasonCode: string) {
    super(reasonCode);
    this.name = 'InstanceTemplatesUnavailableError';
    this.reasonCode = reasonCode;
  }
}

export function createInstanceTemplatesClient(
  config: DesktopRuntimeConfig,
  dependencies: InstanceTemplatesClientDependencies = {},
): InstanceTemplatesClient {
  const runtimeConfig = Object.freeze({ ...config });
  const fetchPath: FetchPath = dependencies.fetch
    ? (path, init) => dependencies.fetch!(absoluteUrl(runtimeConfig.apiBaseUrl, path), init)
    : (path, init) => desktopApiFetch(runtimeConfig, path, init);
  return Object.freeze({
    async list(scope, query = {}, options) {
      requireCloudScope(runtimeConfig, scope);
      const page = positiveInteger(query.page, 1);
      const pageSize = positiveInteger(query.pageSize, 20);
      const params = new URLSearchParams({
        page: String(page),
        page_size: String(pageSize),
      });
      const isPublished =
        query.isPublished ??
        (query.status === 'published'
          ? true
          : query.status === 'draft'
            ? false
            : undefined);
      if (isPublished !== undefined) {
        params.set('is_published', String(isPublished));
      }
      const payload = await request(
        runtimeConfig,
        `/api/v1/instance-templates/?${params.toString()}`,
        fetchPath,
        { method: 'GET', signal: options?.signal },
      );
      return parsePage(payload, scope);
    },
    async get(scope, templateId, options) {
      requireCloudScope(runtimeConfig, scope);
      const payload = await request(
        runtimeConfig,
        `/api/v1/instance-templates/${encodeURIComponent(identifier(templateId))}`,
        fetchPath,
        { method: 'GET', signal: options?.signal },
      );
      return parseTemplate(payload, scope);
    },
    async listItems(scope, templateId, options) {
      requireCloudScope(runtimeConfig, scope);
      const payload = await request(
        runtimeConfig,
        `/api/v1/instance-templates/${encodeURIComponent(identifier(templateId))}/items`,
        fetchPath,
        { method: 'GET', signal: options?.signal },
      );
      if (!Array.isArray(payload)) throw contractError();
      return Object.freeze(payload.map(parseItem));
    },
    async create(scope, input, options) {
      requireCloudScope(runtimeConfig, scope);
      const payload = await request(
        runtimeConfig,
        '/api/v1/instance-templates/',
        fetchPath,
        {
          method: 'POST',
          signal: options?.signal,
          body: {
            name: identifier(input.name),
            slug: identifier(input.slug),
            tenant_id: scope.tenantId,
            description: nullableString(input.description),
            default_config: jsonObject(input.defaultConfig),
          },
        },
      );
      return parseTemplate(payload, scope);
    },
    async delete(scope, templateId, options) {
      requireCloudScope(runtimeConfig, scope);
      await request(
        runtimeConfig,
        `/api/v1/instance-templates/${encodeURIComponent(identifier(templateId))}`,
        fetchPath,
        {
          method: 'DELETE',
          signal: options?.signal,
          expectsJson: false,
        },
      );
    },
    async publish(scope, templateId, options) {
      requireCloudScope(runtimeConfig, scope);
      const payload = await request(
        runtimeConfig,
        `/api/v1/instance-templates/${encodeURIComponent(identifier(templateId))}/publish`,
        fetchPath,
        { method: 'POST', signal: options?.signal },
      );
      return parseTemplate(payload, scope);
    },
    async clone(scope, templateId, newName, options) {
      requireCloudScope(runtimeConfig, scope);
      const payload = await request(
        runtimeConfig,
        `/api/v1/instance-templates/${encodeURIComponent(identifier(templateId))}/clone`,
        fetchPath,
        {
          method: 'POST',
          signal: options?.signal,
          body: { new_name: identifier(newName) },
        },
      );
      return parseTemplate(payload, scope);
    },
  });
}

function requireCloudScope(
  config: DesktopRuntimeConfig,
  scope: InstanceTemplatesScope,
): void {
  if (
    config.mode !== scope.authority ||
    identifier(config.tenantId) !== identifier(scope.tenantId)
  ) {
    throw new InstanceTemplatesUnavailableError(
      'instance_templates_runtime_scope_mismatch',
    );
  }
  if (scope.authority !== 'cloud') {
    throw new InstanceTemplatesUnavailableError(
      'local_instance_template_authority_unavailable',
    );
  }
}

async function request(
  config: DesktopRuntimeConfig,
  path: string,
  fetchPath: FetchPath,
  options: Readonly<{
    method: 'GET' | 'POST' | 'DELETE';
    signal?: AbortSignal;
    body?: Readonly<Record<string, unknown>>;
    expectsJson?: boolean;
  }>,
): Promise<unknown> {
  const headers = requestHeaders(config);
  if (options.body) headers.set('Content-Type', 'application/json');
  const response = await fetchPath(path, {
    method: options.method,
    headers,
    signal: options.signal,
    ...(options.body ? { body: JSON.stringify(options.body) } : {}),
  });
  if (options.expectsJson === false && response.ok) return null;
  const contentType = response.headers.get('content-type') ?? '';
  const isJson = contentType.toLowerCase().includes('application/json');
  const payload = isJson
    ? await response.json().catch(() => null)
    : await response.text().catch(() => '');
  if (!response.ok) {
    throw new DesktopApiError(
      errorMessage(response.status, payload),
      response.status,
      payload,
    );
  }
  if (!isJson || payload === null) throw contractError();
  return payload;
}

function requestHeaders(config: DesktopRuntimeConfig): Headers {
  const headers = new Headers({ Accept: 'application/json' });
  const credential = desktopApiCredential(config);
  if (credential) headers.set('Authorization', `Bearer ${credential}`);
  const launchCapability = desktopLaunchCapability(config);
  if (launchCapability) headers.set('X-Agistack-Launch', launchCapability);
  return headers;
}

function parsePage(
  payload: unknown,
  scope: InstanceTemplatesScope,
): InstanceTemplatesPage {
  if (
    !isRecord(payload) ||
    !Array.isArray(payload.templates) ||
    !isNonnegativeInteger(payload.total) ||
    !isPositiveInteger(payload.page) ||
    !isPositiveInteger(payload.page_size)
  ) {
    throw contractError();
  }
  return Object.freeze({
    templates: Object.freeze(
      payload.templates.map((template) => parseTemplate(template, scope)),
    ),
    total: payload.total,
    page: payload.page,
    pageSize: payload.page_size,
  });
}

function parseTemplate(
  payload: unknown,
  scope: InstanceTemplatesScope,
): InstanceTemplateSummary {
  if (
    !isRecord(payload) ||
    !isExactString(payload.id) ||
    !isExactString(payload.name) ||
    !isExactString(payload.slug) ||
    !isNullableExactString(payload.tenant_id) ||
    !isNullableString(payload.description) ||
    !isNullableString(payload.icon) ||
    !isNullableString(payload.image_version) ||
    !isRecord(payload.default_config) ||
    typeof payload.is_published !== 'boolean' ||
    typeof payload.is_featured !== 'boolean' ||
    !isNonnegativeInteger(payload.install_count) ||
    !isExactString(payload.created_at) ||
    !isNullableExactString(payload.updated_at)
  ) {
    throw contractError();
  }
  if (payload.tenant_id !== null && payload.tenant_id !== scope.tenantId) {
    throw new InstanceTemplatesUnavailableError(
      'instance_templates_tenant_scope_mismatch',
    );
  }
  return Object.freeze({
    id: payload.id,
    name: payload.name,
    slug: payload.slug,
    tenantId: payload.tenant_id,
    description: payload.description,
    icon: payload.icon,
    imageVersion: payload.image_version,
    defaultConfig: Object.freeze({ ...payload.default_config }),
    isPublished: payload.is_published,
    isFeatured: payload.is_featured,
    installCount: payload.install_count,
    createdAt: payload.created_at,
    updatedAt: payload.updated_at,
  });
}

function parseItem(payload: unknown): InstanceTemplateItem {
  if (
    !isRecord(payload) ||
    !isExactString(payload.id) ||
    !isExactString(payload.template_id) ||
    !isExactString(payload.item_type) ||
    !isExactString(payload.item_slug) ||
    typeof payload.display_order !== 'number' ||
    !Number.isSafeInteger(payload.display_order) ||
    !isExactString(payload.created_at)
  ) {
    throw contractError();
  }
  return Object.freeze({
    id: payload.id,
    templateId: payload.template_id,
    itemType: payload.item_type,
    itemSlug: payload.item_slug,
    displayOrder: payload.display_order,
    createdAt: payload.created_at,
  });
}

function positiveInteger(value: number | undefined, fallback: number): number {
  return value === undefined || !isPositiveInteger(value) ? fallback : value;
}

function identifier(value: string): string {
  if (!isExactString(value)) {
    throw new InstanceTemplatesUnavailableError(
      'instance_templates_identifier_invalid',
    );
  }
  return value;
}

function nullableString(value: string | null): string | null {
  if (!isNullableString(value)) throw contractError();
  return value;
}

function jsonObject(
  value: Readonly<Record<string, unknown>>,
): Readonly<Record<string, unknown>> {
  if (!isRecord(value)) throw contractError();
  return value;
}

function errorMessage(status: number, payload: unknown): string {
  if (isRecord(payload) && typeof payload.detail === 'string') {
    return payload.detail;
  }
  return `instance_templates_request_failed:${status}`;
}

function contractError(): InstanceTemplatesUnavailableError {
  return new InstanceTemplatesUnavailableError(
    'instance_templates_contract_invalid',
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isExactString(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && value === value.trim();
}

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === 'string';
}

function isNullableExactString(value: unknown): value is string | null {
  return value === null || isExactString(value);
}

function isPositiveInteger(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) > 0;
}

function isNonnegativeInteger(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) >= 0;
}
