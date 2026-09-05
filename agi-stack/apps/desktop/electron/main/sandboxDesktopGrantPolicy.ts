/** Pure policy only. Frame observations must come from Electron main, never renderer IPC. */
export type SandboxDesktopDescriptor = Readonly<{
  contract_version: 1;
  project_id: string;
  protocol: 'kasmvnc-1';
  auth_mode: 'scoped_http_only_cookie';
  proxy_url: string;
}>;
export type SandboxDesktopGrantOpen = Readonly<{
  requestId: string;
  tenantId: string;
  projectId: string;
  descriptor: SandboxDesktopDescriptor;
}>;
export type SandboxDesktopGrantClose = Readonly<{ requestId: string; grantId?: string }>;
export type SandboxDesktopGrantPolicy = Readonly<{
  requestId: string;
  grantId: string;
  tenantId: string;
  projectId: string;
  ownerId: number;
  mainFrameTreeNodeId: number;
  frameName: string;
  frameUrl: string;
  origin: string;
  websocketOrigin: string;
  proxyPrefix: string;
}>;
export type SandboxDesktopGrantFrame = Readonly<{
  frameTreeNodeId: number;
  parentFrameTreeNodeId: number | null;
  name: string;
}>;
export type SandboxDesktopGrantRequestDetails = Readonly<{
  url: string;
  method: string;
  resourceType: string;
  webContentsId?: number;
  frame: SandboxDesktopGrantFrame | null;
}>;
export type SandboxDesktopGrantRequestAdmission = Readonly<{
  frameTreeNodeId: number;
  kind: 'document' | 'resource' | 'websocket';
}>;
export type SandboxDesktopGrantReply = Readonly<{
  grantId: string;
  frameName: string;
  frameUrl: string;
}>;
const OPAQUE_ID = /^[A-Za-z0-9_-]{16,128}$/u;
const HTTP_RESOURCE_TYPES = new Set([
  'stylesheet',
  'script',
  'image',
  'font',
  'xhr',
  'media',
  'other',
]);
const AUTH_QUERY_KEYS = new Set(['token', 'access_token', 'api_key', 'authorization']);

export function parseSandboxDesktopGrantOpen(input: unknown): SandboxDesktopGrantOpen {
  const raw = record(input, ['requestId', 'tenantId', 'projectId', 'descriptor']);
  const requestId = opaqueId(raw.requestId);
  const tenantId = identifier(raw.tenantId);
  const projectId = identifier(raw.projectId);
  const descriptor = record(raw.descriptor, [
    'contract_version',
    'project_id',
    'protocol',
    'auth_mode',
    'proxy_url',
  ]);
  const proxyUrl = `/api/v1/projects/${encodeURIComponent(projectId)}/sandbox/desktop/proxy/vnc.html`;
  if (
    descriptor.contract_version !== 1 ||
    descriptor.project_id !== projectId ||
    descriptor.protocol !== 'kasmvnc-1' ||
    descriptor.auth_mode !== 'scoped_http_only_cookie' ||
    descriptor.proxy_url !== proxyUrl
  )
    fail('descriptor_invalid');
  return Object.freeze({
    requestId,
    tenantId,
    projectId,
    descriptor: Object.freeze({
      contract_version: 1,
      project_id: projectId,
      protocol: 'kasmvnc-1',
      auth_mode: 'scoped_http_only_cookie',
      proxy_url: proxyUrl,
    }),
  });
}
export function parseSandboxDesktopGrantClose(input: unknown): SandboxDesktopGrantClose {
  if (!input || typeof input !== 'object' || Array.isArray(input)) fail('input_invalid');
  const keys = Object.keys(input);
  const raw = record(input, keys.includes('grantId') ? ['requestId', 'grantId'] : ['requestId']);
  return Object.freeze({
    requestId: opaqueId(raw.requestId),
    ...(keys.includes('grantId') ? { grantId: opaqueId(raw.grantId) } : {}),
  });
}
export function createSandboxDesktopGrantPolicy(
  input: SandboxDesktopGrantOpen,
  options: Readonly<{
    ownerId: number;
    mainFrameTreeNodeId: number;
    apiBaseUrl: string;
    grantId: string;
  }>,
): SandboxDesktopGrantPolicy {
  const request = parseSandboxDesktopGrantOpen(input);
  if (!positiveInteger(options.ownerId) || !positiveInteger(options.mainFrameTreeNodeId))
    fail('owner_invalid');
  const grantId = opaqueId(options.grantId);
  const base = parseUrl(options.apiBaseUrl);
  if (!['http:', 'https:'].includes(base.protocol) || base.search || base.hash)
    fail('origin_invalid');
  const websocket = new URL(base.origin);
  websocket.protocol = base.protocol === 'https:' ? 'wss:' : 'ws:';
  return Object.freeze({
    requestId: request.requestId,
    grantId,
    tenantId: request.tenantId,
    projectId: request.projectId,
    ownerId: options.ownerId,
    mainFrameTreeNodeId: options.mainFrameTreeNodeId,
    frameName: `memstack-kasm-${grantId}`,
    frameUrl: base.origin + request.descriptor.proxy_url,
    origin: base.origin,
    websocketOrigin: websocket.origin,
    proxyPrefix: `/api/v1/projects/${encodeURIComponent(request.projectId)}/sandbox/desktop/proxy/`,
  });
}
export function sandboxDesktopGrantReply(
  policy: SandboxDesktopGrantPolicy,
): SandboxDesktopGrantReply {
  return Object.freeze({
    grantId: policy.grantId,
    frameName: policy.frameName,
    frameUrl: policy.frameUrl,
  });
}
export function authorizeSandboxDesktopGrantRequest(
  policy: SandboxDesktopGrantPolicy,
  boundFrameTreeNodeId: number | null,
  details: SandboxDesktopGrantRequestDetails,
): SandboxDesktopGrantRequestAdmission {
  const frame = details.frame;
  if (
    details.webContentsId !== policy.ownerId ||
    !frame ||
    !positiveInteger(frame.frameTreeNodeId) ||
    frame.frameTreeNodeId === policy.mainFrameTreeNodeId ||
    frame.parentFrameTreeNodeId !== policy.mainFrameTreeNodeId ||
    frame.name !== policy.frameName ||
    details.method !== 'GET'
  )
    fail('frame_mismatch');
  if (boundFrameTreeNodeId !== null && frame.frameTreeNodeId !== boundFrameTreeNodeId)
    fail('frame_mismatch');
  const url = parseUrl(details.url);
  if (url.hash || url.href !== details.url) fail('url_invalid');
  if (boundFrameTreeNodeId === null) {
    if (details.resourceType !== 'subFrame' || details.url !== policy.frameUrl)
      fail('initial_document_invalid');
    return Object.freeze({ frameTreeNodeId: frame.frameTreeNodeId, kind: 'document' });
  }
  const websocket = details.resourceType === 'webSocket';
  if (
    url.origin !== (websocket ? policy.websocketOrigin : policy.origin) ||
    !url.pathname.startsWith(policy.proxyPrefix)
  )
    fail('path_mismatch');
  const suffix = url.pathname.slice(policy.proxyPrefix.length);
  requireResourcePath(suffix);
  if (websocket) {
    if (suffix !== 'websockify' || url.search) fail('websocket_invalid');
    return Object.freeze({ frameTreeNodeId: frame.frameTreeNodeId, kind: 'websocket' });
  }
  if (suffix === 'websockify') fail('resource_invalid');
  if (details.resourceType === 'subFrame') {
    if (details.url !== policy.frameUrl) fail('document_invalid');
    return Object.freeze({ frameTreeNodeId: frame.frameTreeNodeId, kind: 'document' });
  }
  if (!HTTP_RESOURCE_TYPES.has(details.resourceType)) fail('resource_invalid');
  for (const key of url.searchParams.keys())
    if (AUTH_QUERY_KEYS.has(key.toLowerCase())) fail('query_invalid');
  return Object.freeze({ frameTreeNodeId: frame.frameTreeNodeId, kind: 'resource' });
}
function requireResourcePath(path: string): void {
  if (!path || path.includes('\\')) fail('path_invalid');
  for (const segment of path.split('/')) {
    let decoded: string;
    try {
      decoded = decodeURIComponent(segment);
    } catch {
      fail('path_invalid');
    }
    if (
      !decoded ||
      decoded === '.' ||
      decoded === '..' ||
      /[%/\\\u0000-\u001f\u007f]/u.test(decoded)
    )
      fail('path_invalid');
  }
}
function parseUrl(value: unknown): URL {
  if (typeof value !== 'string' || value !== value.trim() || /[\\\u0000-\u001f\u007f]/u.test(value))
    fail('url_invalid');
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    fail('url_invalid');
  }
  if (url.username || url.password) fail('url_invalid');
  return url;
}
function identifier(value: unknown): string {
  if (
    typeof value !== 'string' ||
    !value ||
    value.length > 256 ||
    value !== value.trim() ||
    value === '.' ||
    value === '..' ||
    /[%/\\?#\u0000-\u001f\u007f]/u.test(value)
  )
    fail('scope_invalid');
  return value;
}
function opaqueId(value: unknown): string {
  if (typeof value !== 'string' || !OPAQUE_ID.test(value)) fail('id_invalid');
  return value;
}
function positiveInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value > 0;
}
function record(value: unknown, keys: readonly string[]): Record<string, unknown> {
  if (
    !value ||
    typeof value !== 'object' ||
    Array.isArray(value) ||
    Object.keys(value).length !== keys.length ||
    keys.some((key) => !Object.hasOwn(value, key))
  )
    fail('input_invalid');
  return value as Record<string, unknown>;
}
function fail(reason: string): never {
  throw new Error('sandbox_desktop_grant_' + reason);
}
