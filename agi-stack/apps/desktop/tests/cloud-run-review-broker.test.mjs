import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';
const require = createRequire(import.meta.url);
const {
  executeVaultBoundCloudRequest,
} = require('/tmp/agistack-desktop-test-dist/electron/main/cloudRequestPolicy.js');
const summaryPath = '/api/v1/agent/runs/run-one/summary';
const changesPath = '/api/v1/agent/runs/run-one/changes';
function fixture(options = {}) {
  const calls = [];
  const summary = {
    run_id: 'run-one',
    tenant_id: 'tenant-one',
    project_id: 'project-one',
    conversation_id: 'conversation-one',
    revision: 1,
    summary_state: 'partial',
    ...options.summary,
  };
  const dependencies = {
    signal: options.signal,
    loadTrustedSession: async () => ({
      version: 1,
      api_base_url: 'https://cloud.example',
      runtime_mode: 'cloud',
      credential_kind: 'cloud_bearer',
      credential: 'synthetic-test-token',
      expires_at: null,
    }),
    fetch: async (url, init) => {
      const target = new URL(url);
      calls.push(target.pathname + target.search);
      assert.equal(init.method, 'GET');
      let body;
      let status = 200;
      if (target.pathname === '/api/v1/workspace-context')
        body = {
          context: {
            tenant_id: 'tenant-one',
            project_id: 'project-one',
            workspace_id: 'workspace-one',
            revision: 1,
          },
        };
      else if (target.pathname === summaryPath) {
        body = summary;
        status = options.summaryStatus ?? 200;
        options.onSummary?.();
      } else {
        assert.equal(target.pathname, changesPath);
        status = options.changesStatus ?? 200;
        body = {
          run_id: 'run-one',
          conversation_id: 'conversation-one',
          run_revision: 3,
          scope: target.searchParams.get('scope'),
          turn_id: target.searchParams.get('turn_id'),
          ...options.changes,
        };
      }
      return new Response(JSON.stringify(body), {
        status,
        headers: { 'content-type': 'application/json' },
      });
    },
  };
  return {
    calls,
    request: (path, extra = {}) =>
      executeVaultBoundCloudRequest({ path, method: 'GET', ...extra }, dependencies),
  };
}
test('native summary accepts actual partial summary scoped to observed project', async () => {
  const f = fixture();
  const result = await f.request(summaryPath);
  assert.equal(result.status, 200);
  assert.equal(result.body.summary_state, 'partial');
  assert.deepEqual(f.calls, ['/api/v1/workspace-context', summaryPath]);
});
for (const scope of ['turn', 'run', 'session']) {
  test(`native ${scope} changes bind summary identity before requested CAS read`, async () => {
    const f = fixture();
    const path = `${changesPath}?scope=${scope}&expected_revision=3${scope === 'turn' ? '&turn_id=turn-one' : ''}`;
    const result = await f.request(path);
    assert.equal(result.status, 200);
    assert.equal(result.body.run_revision, 3);
    assert.deepEqual(f.calls, ['/api/v1/workspace-context', summaryPath, path]);
  });
}
for (const [label, summary] of [
  ['tenant', { tenant_id: 'other' }],
  ['project', { project_id: 'other' }],
  ['run', { run_id: 'other' }],
  ['missing conversation', { conversation_id: null }],
]) {
  test(`native run review rejects ${label} identity before changes`, async () => {
    const f = fixture({ summary });
    await assert.rejects(
      f.request(`${changesPath}?scope=run&expected_revision=3`),
      /summary scope/,
    );
    assert.deepEqual(f.calls, ['/api/v1/workspace-context', summaryPath]);
    await assert.rejects(f.request(summaryPath), /summary scope/);
  });
}
for (const [label, changes] of [
  ['conversation', { conversation_id: 'other' }],
  ['run', { run_id: 'other' }],
  ['revision', { run_revision: 2 }],
  ['scope', { scope: 'session' }],
  ['turn', { turn_id: 'other' }],
]) {
  test(`native changes reject mismatched ${label} response`, async () => {
    const f = fixture({ changes });
    await assert.rejects(
      f.request(`${changesPath}?scope=run&expected_revision=3`),
      /changes scope/,
    );
  });
}
test('native run review rejects invalid query/method/body before network', async () => {
  for (const [path, extra] of [
    [`${changesPath}?expected_revision=3`, {}],
    [`${changesPath}?scope=run&expected_revision=0`, {}],
    [`${changesPath}?scope=run&expected_revision=1.5`, {}],
    [`${changesPath}?scope=run&expected_revision=3&scope=run`, {}],
    [`${changesPath}?scope=turn&expected_revision=3`, {}],
    [`${changesPath}?scope=run&expected_revision=3&turn_id=turn-one`, {}],
    [`${summaryPath}?project_id=project-one`, {}],
    [summaryPath, { method: 'POST' }],
    [summaryPath, { body: {} }],
    [summaryPath, { response: { kind: 'binary', max_bytes: 1000 } }],
  ]) {
    const f = fixture();
    await assert.rejects(f.request(path, extra));
    assert.equal(f.calls.length, 0, path);
  }
});
test('native changes preserve CAS failure and stop on summary failure', async () => {
  const conflict = fixture({ changesStatus: 409 });
  assert.equal(
    (await conflict.request(`${changesPath}?scope=run&expected_revision=3`)).status,
    409,
  );
  const missing = fixture({ summaryStatus: 404 });
  assert.equal((await missing.request(`${changesPath}?scope=run&expected_revision=3`)).status, 404);
  assert.deepEqual(missing.calls, ['/api/v1/workspace-context', summaryPath]);
});
test('native cancellation between summary and changes sends no changes request', async () => {
  const controller = new AbortController();
  const f = fixture({ signal: controller.signal, onSummary: () => controller.abort() });
  await assert.rejects(f.request(`${changesPath}?scope=run&expected_revision=3`), {
    name: 'AbortError',
  });
  assert.deepEqual(f.calls, ['/api/v1/workspace-context', summaryPath]);
});
