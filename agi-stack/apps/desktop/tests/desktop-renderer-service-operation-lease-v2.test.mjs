import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import test from 'node:test';

const COMPILED_ROOT = '/tmp/agistack-desktop-test-dist';
const require = createRequire(import.meta.url);
const {
  acquireDesktopRendererServiceOperationLeaseV2,
} = require(`${COMPILED_ROOT}/src/plugins/desktopRendererServiceOperationLeaseV2.js`);
const { RuntimeV2Error } = require('@agistack/plugin-runtime');

const ROOT_SERVICE_REQUEST = Object.freeze({
  service: 'service:desktop-renderer.workspace-context-authority',
  scope: Object.freeze({ kind: 'root' }),
  version: '1.0.0',
});

function generation({ digest, lifecycle, service, resolveError }) {
  return {
    snapshot: { digest },
    resolve(requestedService, scope, options) {
      lifecycle?.push('resolve');
      if (resolveError !== undefined) throw resolveError;
      assert.equal(requestedService, ROOT_SERVICE_REQUEST.service);
      assert.deepEqual(scope, ROOT_SERVICE_REQUEST.scope);
      assert.deepEqual(options, { isolation: undefined, version: '1.0.0' });
      return service;
    },
  };
}

test('service operation admission pins one generation for resolution and use', async () => {
  const lifecycle = [];
  let releases = 0;
  const oldService = Object.freeze({ generation: 'old' });
  const oldGeneration = generation({
    digest: ' sha256:old-generation ',
    lifecycle,
    service: oldService,
  });
  const admission = await acquireDesktopRendererServiceOperationLeaseV2(
    oldGeneration,
    ROOT_SERVICE_REQUEST,
    (requestedGeneration) => {
      lifecycle.push('acquire');
      assert.equal(requestedGeneration, oldGeneration);
      return {
        release: async () => {
          lifecycle.push('release');
          releases += 1;
        },
      };
    },
  );

  assert.equal(admission.status, 'accepted');
  assert.equal(admission.digest, 'sha256:old-generation');
  assert.equal(
    admission.useService((service) => {
      lifecycle.push('use');
      return service;
    }),
    oldService,
  );
  const firstRelease = admission.release();
  const secondRelease = admission.release();
  const thirdRelease = admission.release();
  assert.equal(firstRelease, secondRelease);
  assert.equal(secondRelease, thirdRelease);
  await Promise.all([firstRelease, secondRelease, thirdRelease]);

  assert.equal(releases, 1);
  assert.deepEqual(lifecycle, ['acquire', 'resolve', 'use', 'release']);
  assert.throws(
    () => admission.useService(() => 'late-use'),
    /desktop_renderer_service_generation_lease_released/u,
  );
});

test('release failure is shared while use is rejected as soon as release starts', async () => {
  let releases = 0;
  const admission = await acquireDesktopRendererServiceOperationLeaseV2(
    generation({
      digest: 'sha256:release-failure',
      service: Object.freeze({ generation: 'release-failure' }),
    }),
    ROOT_SERVICE_REQUEST,
    () => ({
      release: async () => {
        releases += 1;
        throw new Error('expected release failure');
      },
    }),
  );

  assert.equal(admission.status, 'accepted');
  const firstRelease = admission.release();
  const secondRelease = admission.release();
  assert.equal(firstRelease, secondRelease);
  assert.throws(
    () => admission.useService((service) => service),
    /desktop_renderer_service_generation_lease_released/u,
  );
  await assert.rejects(firstRelease, /expected release failure/u);
  await assert.rejects(secondRelease, /expected release failure/u);
  assert.equal(releases, 1);
});

test('operation callback failure does not implicitly release the admitted service', async () => {
  let releases = 0;
  const service = Object.freeze({ generation: 'callback-failure' });
  const admission = await acquireDesktopRendererServiceOperationLeaseV2(
    generation({ digest: 'sha256:callback-failure', service }),
    ROOT_SERVICE_REQUEST,
    () => ({
      release: async () => {
        releases += 1;
      },
    }),
  );

  assert.equal(admission.status, 'accepted');
  assert.throws(
    () =>
      admission.useService(() => {
        throw new Error('operation failure');
      }),
    /operation failure/u,
  );
  assert.equal(releases, 0);
  assert.equal(admission.useService((value) => value), service);
  await admission.release();
  assert.equal(releases, 1);
});

test('an admitted operation keeps the old service across publication replacement', async () => {
  const oldService = Object.freeze({ generation: 'old' });
  const nextService = Object.freeze({ generation: 'next' });
  let currentGeneration = generation({
    digest: 'sha256:old-generation',
    service: oldService,
  });
  const acquireCurrent = () =>
    acquireDesktopRendererServiceOperationLeaseV2(
      currentGeneration,
      ROOT_SERVICE_REQUEST,
      () => ({ release: async () => undefined }),
    );

  const oldAdmission = await acquireCurrent();
  currentGeneration = generation({
    digest: 'sha256:next-generation',
    service: nextService,
  });
  const nextAdmission = await acquireCurrent();

  assert.equal(oldAdmission.status, 'accepted');
  assert.equal(nextAdmission.status, 'accepted');
  assert.equal(oldAdmission.useService((service) => service), oldService);
  assert.equal(nextAdmission.useService((service) => service), nextService);
  await Promise.all([oldAdmission.release(), nextAdmission.release()]);
});

test('request is cloned and frozen before lease acquisition and resolution', async () => {
  const request = {
    service: ROOT_SERVICE_REQUEST.service,
    scope: { kind: 'project', tenant_id: 'tenant-a', project_id: 'project-a' },
    version: '1.0.0',
    isolation: 'renderer-root',
  };
  const service = Object.freeze({ authority: 'workspace-context' });
  const observed = [];
  const requestedGeneration = {
    snapshot: { digest: 'sha256:immutable-request' },
    resolve(serviceKey, scope, options) {
      observed.push({ serviceKey, scope, options });
      assert.equal(Object.isFrozen(scope), true);
      return service;
    },
  };

  const admission = await acquireDesktopRendererServiceOperationLeaseV2(
    requestedGeneration,
    request,
    () => {
      request.service = 'service:mutated';
      request.scope.project_id = 'project-mutated';
      request.version = '9.9.9';
      request.isolation = 'mutated';
      return { release: async () => undefined };
    },
  );

  assert.equal(admission.status, 'accepted');
  assert.equal(admission.useService((value) => value), service);
  assert.deepEqual(observed, [
    {
      serviceKey: ROOT_SERVICE_REQUEST.service,
      scope: { kind: 'project', tenant_id: 'tenant-a', project_id: 'project-a' },
      options: { isolation: 'renderer-root', version: '1.0.0' },
    },
  ]);
  await admission.release();
});

test('invalid requests fail before generation lease acquisition', async () => {
  const validGeneration = generation({
    digest: 'sha256:request-validation',
    service: Object.freeze({}),
  });
  let acquisitions = 0;
  const acquire = () => {
    acquisitions += 1;
    return { release: async () => undefined };
  };
  const invalidRequests = [
    undefined,
    null,
    {},
    { ...ROOT_SERVICE_REQUEST, service: '   ' },
    { ...ROOT_SERVICE_REQUEST, service: ` ${ROOT_SERVICE_REQUEST.service}` },
    { ...ROOT_SERVICE_REQUEST, version: '' },
    { ...ROOT_SERVICE_REQUEST, version: ' 1.0.0' },
    { ...ROOT_SERVICE_REQUEST, isolation: '   ' },
    { ...ROOT_SERVICE_REQUEST, isolation: 'renderer-root ' },
    { ...ROOT_SERVICE_REQUEST, scope: undefined },
    { ...ROOT_SERVICE_REQUEST, scope: { kind: 'operation' } },
    { ...ROOT_SERVICE_REQUEST, scope: { kind: 'tenant', tenant_id: '' } },
    {
      ...ROOT_SERVICE_REQUEST,
      scope: {
        kind: 'session',
        project_id: 42,
        session_id: 'session-a',
        tenant_id: 'tenant-a',
      },
    },
    { ...ROOT_SERVICE_REQUEST, unexpected: true },
    { ...ROOT_SERVICE_REQUEST, scope: { kind: 'root', unexpected: true } },
  ];

  for (const request of invalidRequests) {
    assert.deepEqual(
      await acquireDesktopRendererServiceOperationLeaseV2(validGeneration, request, acquire),
      {
        status: 'rejected',
        reasonCode: 'desktop_renderer_service_request_invalid',
      },
    );
  }
  assert.equal(acquisitions, 0);
});

test('invalid generation lease values reject before service resolution', async () => {
  let resolutions = 0;
  const validGeneration = {
    snapshot: { digest: 'sha256:invalid-lease' },
    resolve() {
      resolutions += 1;
      return Object.freeze({});
    },
  };

  for (const lease of [undefined, null, {}, { release: 'not-a-function' }]) {
    assert.deepEqual(
      await acquireDesktopRendererServiceOperationLeaseV2(
        validGeneration,
        ROOT_SERVICE_REQUEST,
        () => lease,
      ),
      {
        status: 'rejected',
        reasonCode: 'desktop_renderer_service_generation_lease_acquire_failed',
      },
    );
  }
  assert.equal(resolutions, 0);
});

test('missing generation and digest reject without acquiring a lease', async () => {
  let acquisitions = 0;
  const acquire = () => {
    acquisitions += 1;
    return { release: async () => undefined };
  };

  assert.deepEqual(
    await acquireDesktopRendererServiceOperationLeaseV2(
      undefined,
      ROOT_SERVICE_REQUEST,
      acquire,
    ),
    {
      status: 'rejected',
      reasonCode: 'desktop_renderer_service_generation_required',
    },
  );
  assert.deepEqual(
    await acquireDesktopRendererServiceOperationLeaseV2(
      generation({ digest: '   ', service: Object.freeze({}) }),
      ROOT_SERVICE_REQUEST,
      acquire,
    ),
    {
      status: 'rejected',
      reasonCode: 'desktop_renderer_service_generation_digest_missing',
    },
  );
  assert.equal(acquisitions, 0);
});

test('lease acquisition failure preserves only RuntimeV2Error codes', async () => {
  const validGeneration = generation({
    digest: 'sha256:lease-acquisition',
    service: Object.freeze({}),
  });

  assert.deepEqual(
    await acquireDesktopRendererServiceOperationLeaseV2(
      validGeneration,
      ROOT_SERVICE_REQUEST,
      () => {
        throw new RuntimeV2Error(
          'renderer_generation_not_renderable',
          'generation not retained',
        );
      },
    ),
    {
      status: 'rejected',
      reasonCode: 'desktop_renderer_service_generation_lease_acquire_failed',
      runtimeCode: 'renderer_generation_not_renderable',
    },
  );
  assert.deepEqual(
    await acquireDesktopRendererServiceOperationLeaseV2(
      validGeneration,
      ROOT_SERVICE_REQUEST,
      () => {
        const error = new Error('generic acquisition failure');
        error.code = 'must_not_escape';
        throw error;
      },
    ),
    {
      status: 'rejected',
      reasonCode: 'desktop_renderer_service_generation_lease_acquire_failed',
    },
  );
});

test('resolve failure awaits exact lease cleanup and preserves RuntimeV2Error code', async () => {
  let releaseResolve;
  let releases = 0;
  let settled = false;
  const releaseBarrier = new Promise((resolve) => {
    releaseResolve = resolve;
  });
  const requestedGeneration = generation({
    digest: 'sha256:resolve-failure',
    resolveError: new RuntimeV2Error('missing_service', 'service is unavailable'),
  });
  const pending = acquireDesktopRendererServiceOperationLeaseV2(
    requestedGeneration,
    ROOT_SERVICE_REQUEST,
    () => ({
      release: async () => {
        releases += 1;
        await releaseBarrier;
        throw new Error('cleanup failure must not replace primary rejection');
      },
    }),
  ).then((value) => {
    settled = true;
    return value;
  });

  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(releases, 1);
  assert.equal(settled, false);
  releaseResolve();
  assert.deepEqual(await pending, {
    status: 'rejected',
    reasonCode: 'desktop_renderer_service_resolve_failed',
    runtimeCode: 'missing_service',
  });
});

test(
  'generic resolve errors omit runtimeCode and synchronous cleanup errors are consumed',
  async () => {
    const resolveError = new Error('generic resolve failure');
    resolveError.code = 'must_not_escape';
    const requestedGeneration = generation({
      digest: 'sha256:generic-resolve-failure',
      resolveError,
    });

    assert.deepEqual(
      await acquireDesktopRendererServiceOperationLeaseV2(
        requestedGeneration,
        ROOT_SERVICE_REQUEST,
        () => ({
          release: () => {
            throw new Error('synchronous cleanup failure');
          },
        }),
      ),
      {
        status: 'rejected',
        reasonCode: 'desktop_renderer_service_resolve_failed',
      },
    );
  },
);
