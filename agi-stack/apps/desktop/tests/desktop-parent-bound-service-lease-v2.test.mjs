import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';
const require = createRequire(import.meta.url);
const ROOT = '/tmp/agistack-desktop-test-dist';
const runtime = require('@agistack/plugin-runtime');
const { acquireDesktopRendererServiceOperationLeaseV2: admit } = require(
  `${ROOT}/src/plugins/desktopRendererServiceOperationLeaseV2.js`,
);
const request = {
  service: 'service:desktop-renderer.session-projection-authority',
  version: '1.0.0',
  scope: {
    kind: 'session',
    tenant_id: 'tenant-1',
    project_id: 'project-1',
    session_id: 'session-1',
  },
};
function definitions() {
  return [
    ...runtime.createDesktopRendererDefinitionsV2(),
    ...readdirSync(`${ROOT}/src/plugins`)
      .filter((name) => /AuthorityModules?V2\.js$/u.test(name))
      .flatMap((name) =>
        Object.values(require(`${ROOT}/src/plugins/${name}`)).filter(
          (value) => value?.moduleRef && typeof value.apply === 'function',
        ),
      ),
  ];
}
function profile() {
  return JSON.parse(
    readFileSync(
      new URL('../../../../shared/profiles/memstack-default-bootstrap.v2.json', import.meta.url),
      'utf8',
    ),
  );
}
test('parent-bound lease keeps old generation usable after actual renderer HMR commit', async () => {
  const renderer = new runtime.RendererPluginRuntimeV2('desktop-renderer', definitions());
  const store = new runtime.RendererGenerationLeaseStoreV2(renderer);
  store.activateRoot();
  try {
    const baseline = profile();
    await renderer.bootstrap(baseline);
    const old = renderer.getSnapshot();
    const parent = await admit(old, request, (g) => store.acquireGeneration(g));
    assert.equal(parent.status, 'accepted');
    assert.equal(typeof parent.acquireChildServiceLease, 'function');
    const nextProfile = structuredClone(baseline);
    nextProfile.entries.find(
      (entry) => entry.entry_id === 'builtin-desktop-session-projection-authority',
    ).enabled = false;
    const { digest: _digest, ...digestPayload } = nextProfile;
    nextProfile.digest = await runtime.digestV2(digestPayload);
    await renderer.replaceBaseline(nextProfile);
    await store.commit(store.getSnapshot());
    assert.throws(
      () => store.acquireGeneration(old),
      (e) => e.code === 'renderer_generation_not_renderable',
    );
    assert.equal(old.disposed, false);
    const child = await parent.acquireChildServiceLease(request);
    assert.equal(child.status, 'accepted');
    assert.equal(child.digest, parent.digest);
    assert.equal(typeof child.useService((service) => service.bindOperation), 'function');
    const release = parent.release();
    const denied = await parent.acquireChildServiceLease(request);
    assert.equal(denied.status, 'rejected');
    await release;
    assert.equal(old.disposed, false);
    assert.equal(typeof child.useService((service) => service.bindOperation), 'function');
    await child.release();
    assert.equal(old.disposed, true);
  } finally {
    await store.deactivateRoot();
    await renderer.close();
  }
});
test('GenerationLeaseV2 fork is exact generation and rejects synchronously after parent release', async () => {
  const manager = new runtime.GenerationManagerV2();
  const generation = await new runtime.LoaderV2(definitions(), 'desktop-renderer').stage(profile());
  await manager.publish(generation);
  const parent = manager.acquire();
  const child = parent.fork();
  assert.equal(child.generation, generation);
  assert.equal(generation.leaseCount, 2);
  const release = parent.release();
  assert.throws(
    () => parent.fork(),
    (e) => e.code === 'generation_lease_released',
  );
  await release;
  await manager.close();
  assert.equal(generation.disposed, false);
  await child.release();
  assert.equal(generation.disposed, true);
});
test('release-only admission remains compatible and cannot advertise parent-bound acquisition', async () => {
  const generation = { snapshot: { digest: 'sha256:compat' }, resolve: () => ({}) };
  let releases = 0;
  const parent = await admit(generation, request, () => ({
    async release() {
      releases++;
    },
  }));
  assert.equal(parent.status, 'accepted');
  assert.equal(parent.acquireChildServiceLease, undefined);
  await parent.release();
  assert.equal(releases, 1);
});
test('child admission retains request validation version isolation and resolution-failure cleanup', async () => {
  const manager = new runtime.GenerationManagerV2();
  const generation = await new runtime.LoaderV2(definitions(), 'desktop-renderer').stage(profile());
  await manager.publish(generation);
  const parent = await admit(generation, request, (g) => manager.acquire(g));
  try {
    assert.equal(generation.leaseCount, 1);
    for (const invalid of [
      { ...request, scope: { kind: 'workspace' } },
      { ...request, extra: true },
      { ...request, scope: { kind: 'project', tenant_id: '', project_id: 'project-1' } },
    ]) {
      const result = await parent.acquireChildServiceLease(invalid);
      assert.equal(result.reasonCode, 'desktop_renderer_service_request_invalid');
      assert.equal(generation.leaseCount, 1);
    }
    for (const unresolved of [
      { ...request, version: '9.0.0' },
      { ...request, isolation: 'other-provider' },
      { ...request, service: 'service:desktop-renderer.missing' },
    ]) {
      const result = await parent.acquireChildServiceLease(unresolved);
      assert.equal(result.reasonCode, 'desktop_renderer_service_resolve_failed');
      assert.equal(generation.leaseCount, 1);
    }
    const child = await parent.acquireChildServiceLease(request);
    assert.equal(child.status, 'accepted');
    assert.equal(generation.leaseCount, 2);
    await child.release();
    assert.equal(generation.leaseCount, 1);
  } finally {
    await parent.release();
    await manager.close();
  }
});
test('fork-shaped lease from a different generation cannot advertise child admission', async () => {
  const generation = { snapshot: { digest: 'sha256:expected' }, resolve: () => ({}) };
  let forks = 0;
  const parent = await admit(generation, request, () => ({
    generation: {},
    fork() {
      forks++;
      throw new Error('wrong generation');
    },
    async release() {},
  }));
  assert.equal(parent.acquireChildServiceLease, undefined);
  assert.equal(forks, 0);
  await parent.release();
});
