import { isExactNpmVersion, isNpmPackageName, isNpmPackageReference } from '../../../../packages/plugin-marketplace-ui/src/npmPackageReference';
import type { CloudProductEndpoint, CloudProductRequestMethod } from './cloudProductEndpointPolicy';

type Request = Readonly<{
  method?: CloudProductRequestMethod;
  body?: Readonly<Record<string, unknown>>;
  mutation?: unknown;
}>;
type Body = Readonly<Record<string, unknown>>;
const SCOPE = ['tenant_id', 'project_id'];
const MARKETPLACE = '/api/v1/plugin-marketplace/v3';
const INSTANCES = '/api/v1/platform-plugins/v2/instances';

function releaseDigest(value: unknown): boolean {
  return typeof value === 'string' && /^sha256:[a-f0-9]{64}$/u.test(value);
}

function revision(value: unknown): boolean {
  return Number.isSafeInteger(value) && Number(value) >= 0;
}

function marketRead(url: URL, catalog: boolean, tenantOnly: boolean): CloudProductEndpoint | null {
  const entries = [...url.searchParams];
  const params = Object.fromEntries(entries);
  if (entries.length !== Object.keys(params).length || !validPackageScope(params, tenantOnly))
    return null;
  if (catalog) {
    if (!fields(params, [...SCOPE, 'q', 'view', 'offset', 'limit']) ||
        (params.q !== undefined && params.q.length > 160) ||
        (params.view !== undefined && !['all', 'installed', 'updates'].includes(params.view)) ||
        (params.offset !== undefined && (!/^\d+$/u.test(params.offset) || !revision(Number(params.offset)))) ||
        (params.limit !== undefined && (!/^\d+$/u.test(params.limit) || Number(params.limit) < 1 || Number(params.limit) > 100)))
      return null;
  } else if (!fields(params, [...SCOPE, 'plugin_id', 'package_name', 'version']) ||
      !/^[a-z0-9][a-z0-9._-]{0,127}$/u.test(params.plugin_id ?? '') ||
      (params.package_name !== undefined && !isNpmPackageName(params.package_name)) ||
      (params.version !== undefined && !isExactNpmVersion(params.version))) {
    return null;
  }
  return scoped(params);
}

function validPackageScope(body: Body, tenantOnly: boolean): boolean {
  return identifier(body.tenant_id) && (tenantOnly ? !Object.hasOwn(body, 'project_id') : identifier(body.project_id));
}

/** Scope-bound signed package lifecycle and capability invocation. */
export function authorizePackageEndpoint(
  request: Request,
  target: URL,
): CloudProductEndpoint | null {
  if (request.mutation !== undefined) return null;
  const path = target.pathname;
  const read = request.method === 'GET' && request.body === undefined;
  if (['/api/v1/project-packages/projects/', '/api/v1/tenant-packages/tenants'].includes(path) && read && noQuery(target))
    return { kind: 'identity-catalog', tenantId: null, projectId: null, workspaceId: null };
  const tenantOnly = path.startsWith('/api/v1/tenant-packages/');
  const prefix = tenantOnly ? '/api/v1/tenant-packages/' : '/api/v1/platform-plugins/v2/optional-business/';
  if (!path.startsWith(prefix)) return null;
  const operation = path.slice(prefix.length);
  if (read && (path === prefix + 'npm/catalog' || path === prefix + 'npm/detail'))
    return marketRead(target, path === prefix + 'npm/catalog', tenantOnly);
  if (path.startsWith(prefix) && request.method === 'POST' && noQuery(target)) {
    const body = request.body;
    if (body && validPackageScope(body, tenantOnly)) {
      if (!tenantOnly && operation === 'npm/resolve' && fields(body, [...SCOPE, 'package_name', 'version']) &&
          isNpmPackageReference(body.package_name, body.version)) return scoped(body);
      if (operation === 'npm/apply' &&
          fields(body, [...SCOPE, 'package_name', 'version', 'expected_revision', 'expected_digest', 'approved_permissions']) &&
          isNpmPackageReference(body.package_name, body.version) && revision(body.expected_revision) &&
          releaseDigest(body.expected_digest) && stringList(body.approved_permissions)) return scoped(body);
      if (operation === 'inspect' || operation === 'install') {
        const keys = [...SCOPE, 'archive_base64', ...(operation === 'install' ? ['approved_permissions', 'expected_revision', 'expected_digest'] : [])];
        if (fields(body, keys) && (body.expected_revision === undefined || revision(body.expected_revision)) &&
            (body.expected_digest === undefined || releaseDigest(body.expected_digest)) && typeof body.archive_base64 === 'string' && body.archive_base64.length > 0 &&
            body.archive_base64.length <= 16 * 1024 * 1024 && (operation === 'inspect' || stringList(body.approved_permissions)))
          return scoped(body);
      }
      if (/^[a-z0-9][a-z0-9._-]{0,127}\/(enable|disable|rollback|uninstall)$/u.test(operation) &&
          fields(body, [...SCOPE, 'expected_revision']) && Number.isSafeInteger(body.expected_revision) &&
          Number(body.expected_revision) >= 0) return scoped(body);
    }
  }
  if (read && (operation === '' || (tenantOnly && /^[a-z0-9][a-z0-9._-]{0,127}$/u.test(operation)))) {
    return validPackageScope(Object.fromEntries(target.searchParams), tenantOnly) ? queryScope(target) : null;
  }
  const business = /^([a-z0-9][a-z0-9._-]{0,127})\/(ui|commands)$/u.exec(operation);
  if (business) {
    if (business[2] === 'ui' && read) {
      const entries = [...target.searchParams];
      const data = Object.fromEntries(entries);
      if (
        (entries.length !== (tenantOnly ? 3 : 4) + Number(data.page_id !== undefined)) ||
        Object.keys(data).length !== entries.length ||
        entries.some(([key]) => ![...SCOPE, 'target', 'expected_digest', 'page_id'].includes(key)) ||
        (data.page_id !== undefined && !/^[a-z0-9][a-z0-9._-]{0,127}$/u.test(data.page_id)) ||
        !validPackageScope(data, tenantOnly) ||
        data.target !== 'desktop-renderer' ||
        !releaseDigest(data.expected_digest)
      )
        return null;
      return scoped(data);
    }
    const body = request.body;
    return business[2] === 'commands' &&
      request.method === 'POST' &&
      (noQuery(target) || target.search === '?stream=true') &&
      fields(body, [...SCOPE, 'command_id', 'expected_digest', 'payload']) &&
      (body.payload === undefined || record(body.payload)) &&
      validPackageScope(body, tenantOnly) &&
      identifier(body.command_id) &&
      releaseDigest(body.expected_digest)
      ? scoped(body)
      : null;
  }
  return null;
}

function queryScope(target: URL) {
    const entries = [...target.searchParams];
    if (
      entries.some(([key]) => !SCOPE.includes(key)) ||
      new Set(entries.map(([key]) => key)).size !== entries.length
    )
      return null;
    return scoped(Object.fromEntries(entries));
}

/** Plugin center settings. Business pages use the signed contribution surface. */
export function authorizeCloudPluginSettingsEndpoint(request: Request, target: URL): CloudProductEndpoint | null {
  const release = authorizePackageEndpoint(request, target);
  if (release || request.mutation !== undefined) return release;
  const path = target.pathname;
  const read = request.method === 'GET' && request.body === undefined;
  if (path === INSTANCES && read) return queryScope(target);
  if (path === `${INSTANCES}/apply`) {
    const body = request.body;
    return request.method === 'POST' &&
      noQuery(target) &&
      fields(body, [...SCOPE, 'expected_revision', 'changes']) &&
      Number.isSafeInteger(body.expected_revision) &&
      Number(body.expected_revision) >= 1 &&
      Array.isArray(body.changes) &&
      body.changes.length > 0 &&
      body.changes.length <= 500 &&
      body.changes.every(instanceChange)
      ? scoped(body)
      : null;
  }
  if (!path.startsWith(`${MARKETPLACE}/`)) return null;
  const tail = path.slice(MARKETPLACE.length + 1).split('/');
  if (read && ['catalog/scoped', 'sources', 'installations', 'cache'].includes(tail.join('/')))
    return queryScope(target);
  if (
    tail.length === 2 &&
    tail[0] === 'sources' &&
    segment(tail[1]) &&
    request.method === 'DELETE' &&
    request.body === undefined
  )
    return queryScope(target);
  const oauth =
    tail.length === 5 &&
    tail[0] === 'installations' &&
    segment(tail[1]) &&
    tail[2] === 'oauth' &&
    segment(tail[3]);
  if (oauth && tail[4] === 'status' && read) return queryScope(target);
  if (request.method !== 'POST' || !noQuery(target)) return null;
  const body = request.body;
  if (!body || !scoped(body)) return null;
  if (tail.length === 1 && tail[0] === 'sources')
    return fields(body, [...SCOPE, 'name', 'kind', 'location', 'trusted']) &&
      text(body.name, 200) &&
      ['https', 'git'].includes(String(body.kind)) &&
      text(body.location, 2048) &&
      typeof body.trusted === 'boolean'
      ? scoped(body)
      : null;
  if (tail.length === 1 && tail[0] === 'preflight')
    return fields(body, [...SCOPE, 'source_id', 'plugin_id', 'version']) &&
      identifier(body.source_id) &&
      identifier(body.plugin_id) &&
      identifier(body.version)
      ? scoped(body)
      : null;
  if (!text(body.idempotency_key, 128)) return null;
  const mutation = [...SCOPE, 'idempotency_key'];
  if (tail.length === 1 && tail[0] === 'installations')
    return fields(body, [...mutation, 'preflight_id', 'approved_permissions']) &&
      identifier(body.preflight_id) &&
      stringList(body.approved_permissions)
      ? scoped(body)
      : null;
  if (tail.join('/') === 'cache/cleanup') return fields(body, mutation) ? scoped(body) : null;
  if (oauth && ['start', 'cancel', 'disconnect'].includes(tail[4]!)) {
    const allowed =
      tail[4] === 'start' ? [...mutation, 'client_id', 'client_metadata_url'] : mutation;
    return fields(body, allowed) &&
      (body.client_id === undefined || text(body.client_id, 2048)) &&
      (body.client_metadata_url === undefined || text(body.client_metadata_url, 2048))
      ? scoped(body)
      : null;
  }
  if (tail.length !== 3 || tail[0] !== 'installations' || !segment(tail[1])) return null;
  if (['enable', 'disable', 'uninstall', 'verify'].includes(tail[2]!))
    return fields(body, mutation) ? scoped(body) : null;
  if (tail[2] === 'update')
    return fields(body, [...mutation, 'preflight_id', 'approved_permissions']) &&
      identifier(body.preflight_id) &&
      stringList(body.approved_permissions)
      ? scoped(body)
      : null;
  if (tail[2] === 'configure')
    return fields(body, [...mutation, 'credentials']) &&
      record(body.credentials) &&
      Object.keys(body.credentials).length <= 100 &&
      Object.entries(body.credentials).every(
        ([key, value]) => identifier(key) && typeof value === 'string',
      )
      ? scoped(body)
      : null;
  return null;
}

function instanceChange(value: unknown): boolean {
  if (
    !record(value) ||
    !fields(value, ['entry_id', 'enabled', 'config', 'replacement']) ||
    !identifier(value.entry_id) ||
    (value.enabled === undefined && value.config === undefined && value.replacement === undefined)
  )
    return false;
  if (value.enabled !== undefined && typeof value.enabled !== 'boolean') return false;
  if (value.config !== undefined && !record(value.config)) return false;
  if (
    value.replacement !== undefined &&
    (!record(value.replacement) ||
      !fields(value.replacement, ['plugin_id', 'module_ref']) ||
      !identifier(value.replacement.plugin_id) ||
      !text(value.replacement.module_ref, 2048))
  )
    return false;
  return true;
}
function scoped(body: Body): CloudProductEndpoint | null {
  if (
    !identifier(body.tenant_id) ||
    (body.project_id !== undefined && body.project_id !== null && !identifier(body.project_id))
  )
    return null;
  const projectId = typeof body.project_id === 'string' ? body.project_id : null;
  return Object.freeze({
    kind: projectId === null ? 'tenant-admin' : 'project',
    tenantId: body.tenant_id,
    projectId,
    workspaceId: null,
  });
}
function fields(body: Body | undefined, allowed: readonly string[]): body is Body {
  return body !== undefined && Object.keys(body).every((key) => allowed.includes(key));
}
function record(value: unknown): value is Body {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
function text(value: unknown, max: number): value is string {
  return (
    typeof value === 'string' &&
    value.length > 0 &&
    value.length <= max &&
    value === value.trim() &&
    !/[\u0000-\u001f\u007f]/u.test(value)
  );
}
function identifier(value: unknown): value is string {
  return text(value, 256);
}
function segment(value: string | undefined): boolean {
  if (!value) return false;
  try {
    const decoded = decodeURIComponent(value);
    return (
      identifier(decoded) && !/[\/\\?#%]/u.test(decoded) && decoded !== '.' && decoded !== '..'
    );
  } catch {
    return false;
  }
}
function stringList(value: unknown): boolean {
  return Array.isArray(value) && value.length <= 100 && value.every(identifier);
}
function noQuery(target: URL): boolean {
  return [...target.searchParams].length === 0;
}
