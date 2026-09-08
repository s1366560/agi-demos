import { requireCloudMemoryMutation } from '../../src/api/cloudMemoryCommandContract';
import type { CloudProductEndpoint } from './cloudProductEndpointPolicy';

type MemoryRequest = Readonly<{
  method?: string;
  body?: Readonly<Record<string, unknown>>;
  mutation?: unknown;
  form?: unknown;
  response?: unknown;
}>;
const CREATE_FIELDS = new Set([
  'project_id',
  'title',
  'content',
  'content_type',
  'tags',
  'metadata',
]);
const PATCH_FIELDS = new Set(['version', 'title', 'content', 'tags', 'metadata']);

export function authorizeCloudMemoryEndpoint(
  request: MemoryRequest,
  target: URL,
): CloudProductEndpoint | null {
  if (request.form !== undefined || request.response !== undefined) return null;
  const collection = target.pathname === '/api/v1/memories/';
  const segments = target.pathname.split('/');
  const detail = segments.length === 5 && segments[3] === 'memories' && pathIdentifier(segments[4]);
  if (!collection && !detail) return null;
  if (
    detail &&
    request.method === 'GET' &&
    request.body === undefined &&
    request.mutation === undefined
  ) {
    return endpoint(scopedProject(target));
  }
  if (!record(request.mutation) || request.mutation.kind !== 'memory-command') return null;
  const mutation = requireCloudMemoryMutation(request.mutation);
  if (collection && request.method === 'POST' && [...target.searchParams].length === 0) {
    const body = request.body;
    if (
      !body ||
      !validFields(body, CREATE_FIELDS) ||
      mutation.expected_revision !== 0 ||
      typeof body.title !== 'string' ||
      typeof body.content !== 'string' ||
      (body.content_type !== undefined && typeof body.content_type !== 'string')
    )
      return null;
    return endpoint(identifier(body.project_id));
  }
  if (!detail || mutation.expected_revision < 1) return null;
  const projectId = scopedProject(target);
  if (request.method === 'DELETE' && request.body === undefined) return endpoint(projectId);
  if (
    request.method === 'PATCH' &&
    request.body &&
    request.body.version === mutation.expected_revision &&
    validFields(request.body, PATCH_FIELDS) &&
    Object.keys(request.body).length > 1
  ) {
    return endpoint(projectId);
  }
  return null;
}

function validFields(
  body: Readonly<Record<string, unknown>>,
  allowed: ReadonlySet<string>,
): boolean {
  return (
    Object.keys(body).every((key) => allowed.has(key)) &&
    (body.title === undefined || typeof body.title === 'string') &&
    (body.content === undefined || typeof body.content === 'string') &&
    (body.tags === undefined ||
      (Array.isArray(body.tags) && body.tags.every((tag) => typeof tag === 'string'))) &&
    (body.metadata === undefined || record(body.metadata))
  );
}
function scopedProject(target: URL): string {
  const pairs = [...target.searchParams];
  if (pairs.length !== 1 || pairs[0]?.[0] !== 'project_id') throw invalid();
  return identifier(pairs[0][1]);
}
function identifier(value: unknown): string {
  if (
    typeof value !== 'string' ||
    value.length === 0 ||
    value.length > 512 ||
    value !== value.trim() ||
    /[\u0000-\u001f\u007f]/u.test(value)
  )
    throw invalid();
  return value;
}
function pathIdentifier(value: string | undefined): boolean {
  if (!value) return false;
  try {
    const decoded = identifier(decodeURIComponent(value));
    return !decoded.includes('/') && !decoded.includes('\\') && decoded !== '.' && decoded !== '..';
  } catch {
    return false;
  }
}
function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
function endpoint(projectId: string): CloudProductEndpoint {
  return Object.freeze({
    kind: 'project',
    tenantId: null,
    projectId,
    workspaceId: null,
  });
}
function invalid(): Error {
  return new Error('cloud request memory endpoint is not allowed');
}
