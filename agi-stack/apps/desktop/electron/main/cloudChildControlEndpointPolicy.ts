import type { CloudProductEndpoint, CloudProductRequestMethod } from './cloudProductEndpointPolicy';

export function authorizeCloudChildControlEndpoint(
  request: Readonly<{ method?: CloudProductRequestMethod; body?: Readonly<Record<string, unknown>>; mutation?: unknown }>,
  target: URL,
): CloudProductEndpoint | null {
  if (request.mutation !== undefined) return null;
  const segments = target.pathname.split('/');
  if (segments.slice(0, 5).join('/') !== '/api/v1/agent/conversations') return null;
  const query = [...target.searchParams];
  if (query.length !== 2 || target.searchParams.getAll('tenant_id').length !== 1 ||
      target.searchParams.getAll('project_id').length !== 1) return null;
  const tenantId = identifier(target.searchParams.get('tenant_id'));
  const projectId = identifier(target.searchParams.get('project_id'));
  const conversationId = identifier(segments[5]);
  if (!tenantId || !projectId || !conversationId) return null;
  const endpoint: CloudProductEndpoint = { kind: 'project', tenantId, projectId, workspaceId: null, conversationId };
  if (segments.length === 7 && segments[6] === 'subagent-controls' && request.method === 'GET' && request.body === undefined) return endpoint;
  const body = request.body;
  if (segments.length !== 9 || segments[6] !== 'subagents' || segments[8] !== 'control' ||
      !identifier(segments[7]) || request.method !== 'POST' || !body ||
      !Object.keys(body).every((key) => ['action', 'expected_control_revision', 'idempotency_key', 'instruction'].includes(key)) ||
      typeof body.expected_control_revision !== 'number' || !Number.isSafeInteger(body.expected_control_revision) || body.expected_control_revision < 0 ||
      typeof body.idempotency_key !== 'string' || !body.idempotency_key.trim() || body.idempotency_key.length > 200) return null;
  if (body.action === 'kill_run') return body.instruction === undefined ? endpoint : null;
  return body.action === 'steer' && typeof body.instruction === 'string' && body.instruction.trim().length > 0 && body.instruction.length <= 16000 ? endpoint : null;
}

function identifier(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  try {
    const decoded = decodeURIComponent(value);
    return decoded && decoded === decoded.trim() && !/[\u0000-\u001f\u007f/\\?#]/u.test(decoded) && !['.', '..'].includes(decoded) ? decoded : null;
  } catch { return null; }
}
