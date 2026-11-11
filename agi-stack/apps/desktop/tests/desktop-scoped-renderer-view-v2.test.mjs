import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
import { test } from 'node:test';
const require = createRequire(import.meta.url);
require.extensions['.css'] = () => {};
const webRequire = createRequire(new URL('../../../../web/package.json', import.meta.url));
const { Window } = await import(pathToFileURL(webRequire.resolve('happy-dom')).href);
const window = new Window({ url: 'http://localhost/' });
for (const key of ['window', 'document', 'navigator', 'HTMLElement', 'Event']) Object.defineProperty(globalThis, key, { configurable: true, value: key === 'window' ? window : window[key] });
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const React = require('react');
const { act } = React;
const { createRoot } = require('react-dom/client');
const runtime = require('@agistack/plugin-runtime');
const { useDesktopPluginGenerationV2, activateDesktopPluginGenerationRootV2, deactivateDesktopPluginGenerationRootV2 } = require('/tmp/agistack-desktop-test-dist/src/plugins/useDesktopPluginGenerationV2.js');
const { projectDesktopRendererAuthorityV2 } = require('/tmp/agistack-desktop-test-dist/src/plugins/desktopRendererAuthorityProjectionV2.js');
const profile = JSON.parse(readFileSync(new URL('../../../../shared/profiles/memstack-default-bootstrap.v2.json', import.meta.url), 'utf8'));
const baseConfig = { mode: 'local', apiBaseUrl: 'http://127.0.0.1:46123', apiKey: 'fixture-session', localApiToken: 'fixture-launch', tenantId: 'tenant-a', projectId: 'project-a', deviceAuthorizationBaseUrl: '', workspaceId: '', workspaceRoot: '' };
const response = (value) => new Response(JSON.stringify(value), { headers: { 'Content-Type': 'application/json' } });

test('scope change hides the old generation, discards late views and refreshes after instance apply', async () => {
  const originalFetch = globalThis.fetch;
  const pending = [];
  const receipts = [];
  const observations = [];
  let latest;
  globalThis.fetch = async (url, options) => {
    if (String(url).includes('renderer-receipt')) { receipts.push(JSON.parse(options.body)); return response({ status: 'ack' }); }
    return new Promise((resolve) => pending.push({ url: new URL(String(url)), options, resolve }));
  };
  window.__MEMSTACK_DESKTOP__ = { core: { invoke: async () => undefined } };
  const host = document.createElement('div'); document.body.append(host);
  const root = createRoot(host);
  function Harness({ config, account }) {
    const state = useDesktopPluginGenerationV2(config, true, account);
    latest = state;
    observations.push({ project: config.projectId, status: state.status, generation: state.generation });
    return React.createElement('span', null, state.status);
  }
  const flush = async () => { await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); }); };
  const waitFor = async (predicate) => { for (const deadline = Date.now() + 5000; Date.now() < deadline && !predicate();) await flush(); assert.ok(predicate(), JSON.stringify({ status: latest?.status, error: latest?.error?.message, receipts, pending: pending.length })); };
  activateDesktopPluginGenerationRootV2();
  try {
    await act(async () => root.render(React.createElement(Harness, { config: baseConfig, account: 'user-a' })));
    await waitFor(() => pending.length === 1);
    const first = pending.shift();
    assert.equal(first.url.pathname, '/api/v1/local-plugins/v2/renderer-view');
    assert.equal(first.url.searchParams.get('project_id'), 'project-a');
    assert.equal(new Headers(first.options.headers).get('Authorization'), 'Bearer fixture-session');
    const nextConfig = { ...baseConfig, projectId: 'project-b' };
    await act(async () => root.render(React.createElement(Harness, { config: nextConfig, account: 'user-a' })));
    assert.equal(latest.generation, undefined);
    await waitFor(() => pending.length === 1);
    const second = pending.shift();
    assert.equal(second.url.searchParams.get('project_id'), 'project-b');
    await act(async () => second.resolve(response({ source: 'local', snapshot: profile })));
    await waitFor(() => latest.status === 'ready' && receipts.length === 1);
    const current = latest.generation;
    await act(async () => first.resolve(response({ source: 'local', snapshot: profile })));
    await flush();
    assert.equal(latest.generation, current);
    assert.equal(receipts.length, 1);
    assert.equal(receipts[0].project_id, 'project-b');
    assert.equal(receipts[0].status, 'ack');
    assert.equal(first.options.signal.aborted, true);
    const changed = structuredClone(profile);
    changed.entries.find((entry) => entry.config?.contributions?.some((contribution) => contribution.payload.artifact_refs.includes('desktop.settings.models.v1'))).enabled = false;
    const { digest, ...unsigned } = changed; changed.digest = await runtime.digestV2(unsigned);
    await act(async () => window.dispatchEvent(new Event('memstack:plugin-configuration-changed-v2')));
    await waitFor(() => pending.length === 1);
    assert.equal(latest.generation, current);
    await act(async () => pending.shift().resolve(response({ source: 'local', snapshot: changed })));
    await waitFor(() => latest.generation !== current && receipts.length === 2);
    assert.equal(projectDesktopRendererAuthorityV2(latest.generation).settingsSectionIds.includes('models'), false);
    assert.equal(observations.some((item) => item.project === 'project-b' && item.status === 'ready' && item.generation === undefined), false);
  } finally {
    await act(async () => root.unmount());
    await deactivateDesktopPluginGenerationRootV2();
    await new Promise((resolve) => setTimeout(resolve, 5));
    globalThis.fetch = originalFetch;
    host.remove();
  }
});

test('cloud receipt delay still publishes the generation before the receipt returns', async () => {
  const originalFetch = globalThis.fetch;
  let releaseReceipt;
  const receipt = new Promise((resolve) => { releaseReceipt = resolve; });
  let deliveries = 0;
  const observations = [];
  let latest;
  globalThis.fetch = async () => { throw new Error('cloud generation must use ipc'); };
  window.__MEMSTACK_DESKTOP__ = { core: { invoke: async (command) => {
    if (command === 'platform_plugin_renderer_delivery_current_v2') {
      deliveries += 1;
      return {
        source: 'cloud',
        authority_id: 'authority-1',
        delivery_token: 'delivery-1',
        distribution: {
          schema_version: 2,
          descriptor: { profile_id: profile.profile_id, generation: profile.generation, digest: profile.digest },
          snapshot: profile,
          envelope: {
            version: 1,
            nonce: 'nonce-1',
            snapshot_digest: profile.digest,
            type_url: 'types.memstack.ai/plugin.profile.v2',
          },
        },
      };
    }
    if (command === 'platform_plugin_renderer_receipt_submit_v2') return receipt;
    return undefined;
  } } };
  const host = document.createElement('div'); document.body.append(host);
  const root = createRoot(host);
  const cloudConfig = { ...baseConfig, mode: 'cloud', apiKey: '', localApiToken: '' };
  function Harness({ config }) {
    const state = useDesktopPluginGenerationV2(config, true, 'user-a');
    latest = state;
    observations.push({ status: state.status, digest: state.generation?.snapshot.digest });
    return React.createElement('span', null, state.status);
  }
  const flush = async () => { await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); }); };
  const waitFor = async (predicate) => { for (const deadline = Date.now() + 5000; Date.now() < deadline && !predicate();) await flush(); assert.ok(predicate(), JSON.stringify({ status: latest?.status, error: latest?.error?.message, deliveries })); };
  activateDesktopPluginGenerationRootV2();
  try {
    await act(async () => root.render(React.createElement(Harness, { config: cloudConfig })));
    await waitFor(() => latest.status === 'ready' && latest.generation?.snapshot.digest === profile.digest);
    assert.equal(deliveries, 1);
    assert.equal(observations.some((item) => item.status === 'ready' && item.digest === undefined), false);
    const switched = { ...cloudConfig, projectId: 'project-b' };
    await act(async () => root.render(React.createElement(Harness, { config: switched })));
    assert.equal(latest.generation, undefined);
    assert.equal(latest.status, 'loading');
    releaseReceipt(undefined);
    await flush();
  } finally {
    await act(async () => root.unmount());
    await deactivateDesktopPluginGenerationRootV2();
    await new Promise((resolve) => setTimeout(resolve, 5));
    globalThis.fetch = originalFetch;
    host.remove();
  }
});
