import type { CloudProductEndpoint, CloudProductRequestMethod } from './cloudProductEndpointPolicy';

/** Read-only catalog contracts not supplied by the scoped session aggregate. */
export function authorizeCloudJourneyReadEndpoint(
  request: Readonly<{ method?: CloudProductRequestMethod; body?: unknown; mutation?: unknown }>,
  target: URL,
): CloudProductEndpoint | null {
  if (request.method !== 'GET' || request.body !== undefined || request.mutation !== undefined) return null;
  const entries = [...target.searchParams];
  if (target.pathname === '/api/v1/system/features' && entries.length === 0) {
    return { kind: 'identity-catalog', tenantId: null, projectId: null, workspaceId: null };
  }
  if (target.pathname === '/api/v1/artifacts' && entries.length === 2 &&
      target.searchParams.getAll('limit').length === 1 && target.searchParams.get('limit') === '100' &&
      target.searchParams.getAll('project_id').length === 1) {
    const projectId = exactIdentifier(target.searchParams.get('project_id'));
    if (projectId) return { kind: 'project', tenantId: null, projectId, workspaceId: null };
  }
  if (target.pathname === '/api/v1/attachments' && entries.length === 1 &&
      target.searchParams.getAll('conversation_id').length === 1) {
    const conversationId = exactIdentifier(target.searchParams.get('conversation_id'));
    if (conversationId) return { kind: 'project', tenantId: null, projectId: null, workspaceId: null, conversationId };
  }
  return null;
}

function exactIdentifier(value: string | null): string | null {
  return value && value === value.trim() && !/[\u0000-\u0020\u007f/\\?#]/u.test(value) &&
    !['.', '..'].includes(value) ? value : null;
}
