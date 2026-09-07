import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';
const require = createRequire(import.meta.url);
const ROOT = '/tmp/agistack-desktop-test-dist/src';
const runtime = require('@agistack/plugin-runtime');
const core = require(`${ROOT}/plugins/desktopBrowserBridgeManagementAuthorityModuleV2.js`);
const { acquireDesktopRendererServiceOperationLeaseV2 } = require(
  `${ROOT}/plugins/desktopRendererServiceOperationLeaseV2.js`,
);
const { DEFAULT_CONFIG } = require(`${ROOT}/types.js`);
test('real Loader bridge management service executes native operation with root lease and disabled next generation emits no IPC', async () => {
  const definitions = readdirSync(`${ROOT}/plugins`)
    .filter((n) => /AuthorityModules?V2\.js$/u.test(n))
    .flatMap((n) =>
      Object.values(require(`${ROOT}/plugins/${n}`)).filter(
        (v) => v?.moduleRef && typeof v.apply === 'function',
      ),
    );
  const profile = JSON.parse(
    readFileSync(
      new URL('../../../../shared/profiles/memstack-default-bootstrap.v2.json', import.meta.url),
      'utf8',
    ),
  );
  const loader = new runtime.LoaderV2(
    [...runtime.createDesktopRendererDefinitionsV2(), ...definitions],
    'desktop-renderer',
  );
  const manager = new runtime.GenerationManagerV2();
  let calls = 0;
  let observed;
  global.window = {
    __MEMSTACK_DESKTOP__: {
      runtime: 'electron',
      core: {
        async invoke(command) {
          calls++;
          assert.equal(command, 'browser_bridge_uninstall');
          assert.equal(observed.leaseCount, 1);
          return { removed: ['Chrome'] };
        },
      },
    },
  };
  const clientFor = (generation) =>
    core.createDesktopBrowserBridgeManagementClientV2(
      core.createDesktopBrowserBridgeManagementOperationsV2(() => ({
        acquireServiceOperationLease: (request) =>
          acquireDesktopRendererServiceOperationLeaseV2(generation, request, (g) =>
            manager.acquire(g),
          ),
      })),
      DEFAULT_CONFIG,
    );
  const active = await loader.stage(profile);
  await manager.publish(active);
  observed = active;
  try {
    assert.deepEqual(await clientFor(active).uninstall(), { removed: ['Chrome'] });
    assert.equal(active.leaseCount, 0);
    const disabled = structuredClone(profile);
    const entry = disabled.entries.find(
      (e) => e.module_ref === core.DESKTOP_BROWSER_BRIDGE_MANAGEMENT_AUTHORITY_MODULE_REF_V2,
    );
    assert.ok(entry);
    entry.enabled = false;
    const next = await loader.stage(disabled);
    await manager.publish(next);
    try {
      assert.throws(
        () =>
          next.resolve(
            core.DESKTOP_BROWSER_BRIDGE_MANAGEMENT_AUTHORITY_SERVICE_V2,
            { kind: 'root' },
            { version: '1.0.0' },
          ),
        (error) => error.code === 'missing_service',
      );
      await assert.rejects(clientFor(next).uninstall(), /desktop_renderer_service_resolve_failed/);
      assert.equal(calls, 1);
      assert.equal(next.leaseCount, 0);
    } finally {
      await next.dispose();
    }
  } finally {
    await active.dispose();
    delete global.window;
  }
});
