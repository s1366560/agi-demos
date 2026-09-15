import type { CloudProductEndpoint, CloudProductRequestMethod } from './cloudProductEndpointPolicy';

type Request = Readonly<{
  method?: CloudProductRequestMethod;
  body?: Readonly<Record<string, unknown>>;
  mutation?: unknown;
}>;

/** Exact read contracts emitted by the desktop capability projections. */
export function authorizeCloudCapabilityProbeEndpoint(
  request: Request,
  target: URL,
): CloudProductEndpoint | null {
  if (request.mutation !== undefined) return null;
  const segments = target.pathname.split('/');
  const project = (projectId: string | null, tenantId: string | null = null) =>
    projectId === null
      ? null
      : Object.freeze({
          kind: 'project' as const,
          tenantId,
          projectId,
          workspaceId: null,
        });
  if (request.method === 'GET' && request.body === undefined) {
    if (target.pathname === '/api/v1/agent/definitions' &&
        exactQuery(target, { tenant_id: null, scope: ['tenant'], enabled_only: ['true'], limit: ['100'] })) {
      const tenantId = identifier(target.searchParams.get('tenant_id'));
      return tenantId === null ? null : Object.freeze({ kind: 'identity-catalog', tenantId, projectId: null, workspaceId: null });
    }
    if (segments.length === 7 && segments.slice(0, 4).join('/') === '/api/v1/projects' &&
        segments[5] === 'schema' && ['entities', 'edges', 'mappings'].includes(segments[6]!) && exactQuery(target, {})) {
      return project(identifier(segments[4]));
    }
    if (['/api/v1/maintenance/status', '/api/v1/data/stats', '/api/v1/maintenance/embeddings/status'].includes(target.pathname) &&
        exactQuery(target, { tenant_id: null, project_id: null })) {
      const tenantId = identifier(target.searchParams.get('tenant_id'));
      return tenantId === null ? null : project(identifier(target.searchParams.get('project_id')), tenantId);
    }
    if (segments.length === 6 && segments.slice(0, 4).join('/') === '/api/v1/projects' &&
        segments[5] === 'members' && exactQuery(target, { tenant_id: null })) {
      const tenantId = identifier(target.searchParams.get('tenant_id'));
      const catalogProjectId = identifier(segments[4]);
      return tenantId === null || catalogProjectId === null ? null : Object.freeze({
        kind: 'identity-catalog', tenantId, projectId: null, workspaceId: null, catalogProjectId,
      });
    }
    if (segments.slice(0, 7).join('/') === '/api/v1/agent/trace/runs/project') {
      const list = segments.length === 8 && exactQuery(target, { limit: ['8', '100'] });
      const count =
        segments.length === 10 &&
        segments[8] === 'active' &&
        segments[9] === 'count' &&
        exactQuery(target, {});
      if (list || count) return project(identifier(segments[7]));
    }
    if (
      segments.length === 8 &&
      segments.slice(0, 7).join('/') === '/api/v1/agent/workflows/patterns/project' &&
      exactQuery(target, { page: ['1'], page_size: ['100'] })
    ) {
      return project(identifier(segments[7]));
    }
    if (
      target.pathname === '/api/v1/agent/definitions' &&
      exactQuery(target, {
        include_total: ['true'],
        limit: ['50'],
        offset: ['0'],
        tenant_id: null,
        project_id: null,
      })
    ) {
      const tenantId = identifier(target.searchParams.get('tenant_id'));
      return tenantId === null
        ? null
        : project(identifier(target.searchParams.get('project_id')), tenantId);
    }
  }
  if (
    target.pathname === '/api/v1/mcp/apps/resources/list' &&
    request.method === 'POST' &&
    exactQuery(target, {}) &&
    request.body &&
    Object.keys(request.body).every((key) => ['project_id', 'server_name'].includes(key)) &&
    (request.body.server_name === undefined ||
      (typeof request.body.server_name === 'string' && request.body.server_name.trim().length > 0))
  ) {
    return project(identifier(request.body.project_id));
  }
  return null;
}

function exactQuery(
  target: URL,
  fields: Readonly<Record<string, readonly string[] | null>>,
): boolean {
  const entries = [...target.searchParams];
  return (
    entries.length === Object.keys(fields).length &&
    Object.entries(fields).every(([key, values]) => {
      const found = target.searchParams.getAll(key);
      return found.length === 1 && (values === null || values.includes(found[0]!));
    })
  );
}

function identifier(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  try {
    const decoded = decodeURIComponent(value);
    return decoded &&
      decoded === decoded.trim() &&
      !/[\u0000-\u001f\u007f/\\?#]/u.test(decoded) &&
      !['.', '..'].includes(decoded)
      ? decoded
      : null;
  } catch {
    return null;
  }
}
