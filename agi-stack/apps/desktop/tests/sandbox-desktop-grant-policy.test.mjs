import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';
const require = createRequire(import.meta.url);
const {
  parseSandboxDesktopGrantOpen: parseOpen,
  parseSandboxDesktopGrantClose: parseClose,
  createSandboxDesktopGrantPolicy: createPolicy,
  sandboxDesktopGrantReply: reply,
  authorizeSandboxDesktopGrantRequest: authorize,
} = require('/tmp/agistack-desktop-test-dist/electron/main/sandboxDesktopGrantPolicy.js');
const requestId = 'request_0123456789abcdef',
  grantId = 'grant_0123456789abcdef';
const request = () => ({
  requestId,
  tenantId: 'tenant-1',
  projectId: 'project-1',
  descriptor: {
    contract_version: 1,
    project_id: 'project-1',
    protocol: 'kasmvnc-1',
    auth_mode: 'scoped_http_only_cookie',
    proxy_url: '/api/v1/projects/project-1/sandbox/desktop/proxy/vnc.html',
  },
});
const options = () => ({
  ownerId: 7,
  mainFrameTreeNodeId: 11,
  apiBaseUrl: 'https://cloud.example.invalid',
  grantId,
});
const policy = () => createPolicy(parseOpen(request()), options());
const details = () => ({
  url: policy().frameUrl,
  method: 'GET',
  resourceType: 'subFrame',
  webContentsId: 7,
  frame: { frameTreeNodeId: 12, parentFrameTreeNodeId: 11, name: policy().frameName },
});
test('grant input and reply are exact immutable credential-free protocol objects', () => {
  const raw = request(),
    parsed = parseOpen(raw);
  raw.descriptor.project_id = 'changed';
  assert.equal(parsed.descriptor.project_id, 'project-1');
  assert.ok(Object.isFrozen(parsed.descriptor));
  assert.deepEqual(reply(createPolicy(parsed, options())), {
    grantId,
    frameName: `memstack-kasm-${grantId}`,
    frameUrl: details().url,
  });
});
test('malformed IDs extra secrets and descriptor drift reject without echo', () => {
  for (const mutate of [
    (r) => (r.requestId = 'short'),
    (r) => (r.tenantId = ''),
    (r) => (r.projectId = '../other'),
    (r) => (r.credential = 'secret-value'),
    (r) => (r.descriptor.project_id = 'other'),
    (r) => (r.descriptor.contract_version = 2),
    (r) => (r.descriptor.protocol = 'other'),
    (r) => (r.descriptor.auth_mode = 'bearer'),
    (r) => (r.descriptor.proxy_url += '?token=secret-value'),
    (r) => (r.descriptor.proxy_url = 'https://other.invalid/vnc.html'),
    (r) => (r.descriptor.extra = true),
  ]) {
    const raw = request();
    mutate(raw);
    assert.throws(
      () => parseOpen(raw),
      (e) => !String(e).includes('secret-value'),
    );
  }
});
test('pending close identifies request and optional exact grant ID', () => {
  assert.deepEqual(parseClose({ requestId }), { requestId });
  assert.deepEqual(parseClose({ requestId, grantId }), { requestId, grantId });
  for (const raw of [
    { grantId },
    { requestId, grantId: null },
    { requestId, grantId: 'bad' },
    { requestId, extra: true },
  ])
    assert.throws(() => parseClose(raw));
});
test('policy accepts only a credential-free HTTP origin and actual positive owner/frame IDs', () => {
  for (const apiBaseUrl of [
    'file:///tmp/test',
    'https://user:pass@cloud.example.invalid',
    'https://cloud.example.invalid?token=x',
    'https://cloud.example.invalid/#x',
  ])
    assert.throws(() => createPolicy(parseOpen(request()), { ...options(), apiBaseUrl }));
  for (const invalid of [{ ownerId: 0 }, { mainFrameTreeNodeId: -1 }, { grantId: 'bad' }])
    assert.throws(() => createPolicy(parseOpen(request()), { ...options(), ...invalid }));
});
test('initial document requires owner exact name and direct main-frame parent', () => {
  assert.deepEqual(authorize(policy(), null, details()), { frameTreeNodeId: 12, kind: 'document' });
  for (const mutate of [
    (d) => (d.webContentsId = 8),
    (d) => (d.frame = null),
    (d) => (d.frame.name = 'other'),
    (d) => (d.frame.parentFrameTreeNodeId = 13),
    (d) => (d.frame.frameTreeNodeId = 11),
    (d) => (d.resourceType = 'mainFrame'),
    (d) => (d.resourceType = 'script'),
    (d) => (d.method = 'POST'),
    (d) => (d.url += '?cache=1'),
    (d) => (d.url = d.url.replace('vnc.html', 'app.js')),
  ]) {
    const d = details();
    mutate(d);
    assert.throws(() => authorize(policy(), null, d));
  }
});
test('bound frame authorizes proxy resources and exact websocket endpoint', () => {
  const d = details();
  d.resourceType = 'script';
  d.url = d.url.replace('vnc.html', 'dist/main.js?v=1');
  assert.equal(authorize(policy(), 12, d).kind, 'resource');
  d.resourceType = 'webSocket';
  d.url = 'wss://cloud.example.invalid/api/v1/projects/project-1/sandbox/desktop/proxy/websockify';
  assert.equal(authorize(policy(), 12, d).kind, 'websocket');
  d.url += '?token=secret';
  assert.throws(() => authorize(policy(), 12, d));
});
test('bound frame cannot lend grant to sibling descendant or missing frame', () => {
  for (const frame of [
    null,
    { ...details().frame, frameTreeNodeId: 13 },
    { ...details().frame, parentFrameTreeNodeId: 12 },
  ])
    assert.throws(() => authorize(policy(), 12, { ...details(), frame }));
});
test('cross origin project prefix encoded traversal and secret query reject', () => {
  const p = 'https://cloud.example.invalid/api/v1/projects/project-1/sandbox/desktop/proxy/';
  for (const url of [
    p + '../other',
    p + '%2e%2e/other',
    p + '%2Fother',
    p + '%252e%252e/other',
    p + 'a\\b',
    p + 'a%00b',
    p.replace('project-1', 'project-2') + 'vnc.html',
    p.replace('cloud.example.invalid', 'evil.invalid') + 'vnc.html',
    p.replace('/proxy/', '/proxy-evil/') + 'vnc.html',
    p + 'a.js?Authorization=secret',
    p + 'a.js?token=x',
    p + 'a.js#fragment',
    p.replace('https://', 'https://user:pass@') + 'a.js',
  ])
    assert.throws(() => authorize(policy(), 12, { ...details(), resourceType: 'script', url }));
});
test('WebSocket path transport and resource type do not widen the grant', () => {
  const p = 'wss://cloud.example.invalid/api/v1/projects/project-1/sandbox/desktop/proxy/';
  for (const [url, resourceType] of [
    [p + 'other', 'webSocket'],
    [p + 'websockify?x=1', 'webSocket'],
    [p.replace('wss:', 'https:') + 'websockify', 'xhr'],
    [p.replace('wss:', 'ws:') + 'websockify', 'webSocket'],
    [details().url, 'object'],
    [details().url, 'ping'],
  ])
    assert.throws(() => authorize(policy(), 12, { ...details(), url, resourceType }));
});
