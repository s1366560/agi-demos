import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  buildSessionRuntimeInfrastructure,
  isSessionRuntimeInfrastructureEvent,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/session/sessionRuntimeInfrastructureModel.js'
);

const event = (id, type, payload, counter) => ({
  id,
  type,
  payload,
  eventTimeUs: 1_900_000_000 + counter,
  eventCounter: counter,
});

test('projects sandbox, desktop, terminal, and HTTP service lifecycle into inspectable resources', () => {
  const model = buildSessionRuntimeInfrastructure([
    event(
      'sandbox-created',
      'sandbox_created',
      {
        sandbox_id: 'sandbox-1',
        project_id: 'project-1',
        status: 'running',
        endpoint: 'https://sandbox.example',
        websocket_url: 'wss://sandbox.example/ws',
      },
      1
    ),
    event(
      'desktop-started',
      'desktop_started',
      {
        sandbox_id: 'sandbox-1',
        url: '/desktop/vnc.html',
        display: ':1',
        resolution: '1440x900',
        port: 6080,
      },
      2
    ),
    event(
      'terminal-started',
      'terminal_started',
      {
        sandbox_id: 'sandbox-1',
        url: 'wss://sandbox.example/terminal',
        port: 7681,
        session_id: 'terminal-1',
        pid: 42,
      },
      3
    ),
    event(
      'service-started',
      'http_service_started',
      {
        sandbox_id: 'sandbox-1',
        service_id: 'preview-1',
        service_name: 'Vite preview',
        source_type: 'sandbox_internal',
        service_url: 'http://172.17.0.2:5173',
        proxy_url: '/preview/preview-1',
        ws_proxy_url: '/preview/preview-1/ws',
        auto_open: true,
        restart_token: 'restart-1',
      },
      4
    ),
    event(
      'service-updated',
      'http_service_updated',
      {
        sandbox_id: 'sandbox-1',
        service_id: 'preview-1',
        service_name: 'Vite preview',
        source_type: 'sandbox_internal',
        service_url: 'http://172.17.0.2:4173',
        proxy_url: '/preview/preview-1',
        auto_open: false,
        status: 'running',
      },
      5
    ),
    event(
      'terminal-stopped',
      'terminal_status',
      {
        sandbox_id: 'sandbox-1',
        running: false,
        session_id: 'terminal-1',
      },
      6
    ),
    event(
      'sandbox-error',
      'sandbox_status',
      {
        sandbox_id: 'sandbox-1',
        status: 'error',
        error_message: 'Runtime health probe failed',
      },
      7
    ),
    event(
      'service-error',
      'http_service_error',
      {
        sandbox_id: 'sandbox-1',
        service_id: 'preview-1',
        service_name: 'Vite preview',
        status: 'error',
        error_message: 'Preview port is not reachable',
      },
      8
    ),
  ]);

  assert.deepEqual(model.summary, {
    events: 8,
    resources: 4,
    running: 1,
    errors: 2,
  });
  assert.equal(model.activeSandbox?.id, 'sandbox-1');
  assert.equal(model.activeSandbox?.status, 'error');
  assert.equal(model.activeSandbox?.errorMessage, 'Runtime health probe failed');

  const resources = new Map(model.resources.map((resource) => [resource.key, resource]));
  assert.deepEqual(
    {
      status: resources.get('desktop:sandbox-1')?.status,
      display: resources.get('desktop:sandbox-1')?.display,
      resolution: resources.get('desktop:sandbox-1')?.resolution,
      port: resources.get('desktop:sandbox-1')?.port,
    },
    { status: 'running', display: ':1', resolution: '1440x900', port: 6080 }
  );
  assert.deepEqual(
    {
      status: resources.get('terminal:sandbox-1')?.status,
      sessionId: resources.get('terminal:sandbox-1')?.sessionId,
      pid: resources.get('terminal:sandbox-1')?.pid,
    },
    { status: 'stopped', sessionId: 'terminal-1', pid: 42 }
  );
  assert.deepEqual(
    {
      status: resources.get('httpService:preview-1')?.status,
      url: resources.get('httpService:preview-1')?.url,
      proxyUrl: resources.get('httpService:preview-1')?.proxyUrl,
      autoOpen: resources.get('httpService:preview-1')?.autoOpen,
      errorMessage: resources.get('httpService:preview-1')?.errorMessage,
    },
    {
      status: 'error',
      url: 'http://172.17.0.2:4173',
      proxyUrl: '/preview/preview-1',
      autoOpen: false,
      errorMessage: 'Preview port is not reachable',
    }
  );
  assert.equal(model.events.at(-1)?.snapshot.url, 'http://172.17.0.2:4173');
});

test('sandbox termination stops every attached runtime resource without losing evidence', () => {
  const model = buildSessionRuntimeInfrastructure([
    event('sandbox', 'sandbox_created', { sandbox_id: 'sandbox-1', status: 'running' }, 1),
    event('desktop', 'desktop_started', { sandbox_id: 'sandbox-1', port: 6080 }, 2),
    event(
      'terminal',
      'terminal_started',
      { sandbox_id: 'sandbox-1', session_id: 'terminal-1', port: 7681 },
      3
    ),
    event(
      'service',
      'http_service_started',
      {
        sandbox_id: 'sandbox-1',
        service_id: 'preview-1',
        service_name: 'Preview',
        source_type: 'sandbox_internal',
        service_url: 'http://172.17.0.2:5173',
      },
      4
    ),
    event('terminated', 'sandbox_terminated', { sandbox_id: 'sandbox-1' }, 5),
  ]);

  assert.equal(model.activeSandbox?.status, 'terminated');
  assert.deepEqual(
    model.resources.map((resource) => [resource.key, resource.status]),
    [
      ['sandbox:sandbox-1', 'terminated'],
      ['desktop:sandbox-1', 'stopped'],
      ['terminal:sandbox-1', 'stopped'],
      ['httpService:preview-1', 'stopped'],
    ]
  );
  assert.equal(model.summary.running, 0);
});

test('keeps multiple HTTP services distinct and orders events by cursor', () => {
  const model = buildSessionRuntimeInfrastructure([
    event(
      'service-b',
      'http_service_started',
      {
        service_id: 'service-b',
        service_name: 'Docs',
        source_type: 'external_url',
        service_url: 'https://docs.example',
      },
      2
    ),
    event(
      'service-a',
      'http_service_started',
      {
        service_id: 'service-a',
        service_name: 'Preview',
        source_type: 'sandbox_internal',
        service_url: 'http://127.0.0.1:4173',
      },
      1
    ),
  ]);

  assert.deepEqual(model.events.map((item) => item.id), ['service-a', 'service-b']);
  assert.deepEqual(
    model.resources.map((resource) => resource.key),
    ['httpService:service-a', 'httpService:service-b']
  );
});

test('fails closed for malformed, duplicate, and unrelated runtime events', () => {
  const model = buildSessionRuntimeInfrastructure([
    event('bad-sandbox', 'sandbox_created', { status: 'running' }, 1),
    event(
      'valid-service',
      'http_service_started',
      {
        service_id: 'preview-1',
        service_name: 'Preview',
        source_type: 'sandbox_internal',
        service_url: 'http://127.0.0.1:4173',
      },
      2
    ),
    event(
      'valid-service',
      'http_service_error',
      {
        service_id: 'preview-1',
        service_name: 'Preview',
        error_message: 'Duplicate must not win',
      },
      3
    ),
    event('bad-status', 'desktop_status', { sandbox_id: 'sandbox-1', running: 'yes' }, 4),
    event('unrelated', 'cost_update', { input_tokens: 10 }, 5),
  ]);

  assert.equal(model.events.length, 1);
  assert.equal(model.resources.length, 1);
  assert.equal(model.resources[0]?.status, 'running');
  assert.equal(model.resources[0]?.errorMessage, null);
});

test('recognizes only the exact runtime infrastructure event protocol', () => {
  assert.equal(isSessionRuntimeInfrastructureEvent({ type: 'sandbox_created' }), true);
  assert.equal(isSessionRuntimeInfrastructureEvent({ event_type: 'http_service_error' }), true);
  assert.equal(isSessionRuntimeInfrastructureEvent({ type: 'sandbox_create' }), false);
  assert.equal(isSessionRuntimeInfrastructureEvent({ type: 'terminal_started_extra' }), false);
});

test('Desktop exposes a dynamic Runtime canvas with selectable resources and event history', () => {
  const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
  const canvasSource = readFileSync(
    new URL('../src/features/session/SessionRuntimeInfrastructureCanvas.tsx', import.meta.url),
    'utf8'
  );
  const qaSource = readFileSync(new URL('../src/qa/SessionSteeringQa.tsx', import.meta.url), 'utf8');

  assert.match(appSource, /buildSessionRuntimeInfrastructure\(timelineItems\)/);
  assert.match(appSource, /tab: 'runtime'/);
  assert.match(appSource, /activeTab === 'runtime'/);
  assert.match(canvasSource, /session-runtime-infrastructure-canvas/);
  assert.match(canvasSource, /aria-pressed=\{selected\}/);
  assert.match(canvasSource, /model\.resources\.map/);
  assert.match(canvasSource, /historyEvents\.map/);
  assert.match(qaSource, /runtime-infrastructure-canvas/);
});
