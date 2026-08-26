import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import test from 'node:test';

const require = createRequire(import.meta.url);
const {
  acquireAgentSocketGenerationLeaseV2,
} = require('/tmp/agistack-desktop-test-dist/src/hooks/agentSocketGenerationLeaseV2.js');

test('generation admission retains the exact socket generation until release', async () => {
  let releases = 0;
  let acquisitions = 0;
  const lifecycle = [];
  const admission = acquireAgentSocketGenerationLeaseV2(() => {
    acquisitions += 1;
    lifecycle.push('acquire');
    return {
      digest: ' sha256:agent-socket-generation ',
      kind: 'generation',
      release: async () => {
        releases += 1;
      },
    };
  });

  assert.equal(admission.status, 'accepted');
  assert.equal(admission.digest, 'sha256:agent-socket-generation');
  assert.equal(
    admission.constructSocket(() => {
      lifecycle.push('construct-initial');
      return 'initial-socket';
    }),
    'initial-socket',
  );
  assert.throws(
    () =>
      admission.constructSocket(() => {
        lifecycle.push('construct-failed');
        throw new Error('constructor failure');
      }),
    /constructor failure/u,
  );
  assert.equal(
    admission.constructSocket(() => {
      lifecycle.push('construct-reconnect');
      return 'reconnected-socket';
    }),
    'reconnected-socket',
  );
  assert.equal(acquisitions, 1);
  assert.deepEqual(lifecycle, [
    'acquire',
    'construct-initial',
    'construct-failed',
    'construct-reconnect',
  ]);

  await Promise.all([admission.release(), admission.release()]);
  assert.equal(releases, 1);
  assert.throws(
    () => admission.constructSocket(() => 'late-socket'),
    /desktop_agent_socket_generation_lease_released/u,
  );
});

test('generation admission rejects the authentication kernel and consumes release failure', async () => {
  let releases = 0;
  const admission = acquireAgentSocketGenerationLeaseV2(() => ({
    digest: undefined,
    kind: 'authentication-kernel',
    release: async () => {
      releases += 1;
      throw new Error('expected release rejection');
    },
  }));

  assert.deepEqual(admission, {
    status: 'rejected',
    reasonCode: 'desktop_agent_socket_generation_required',
  });
  assert.equal('constructSocket' in admission, false);
  assert.equal(releases, 1);
  await new Promise((resolve) => setImmediate(resolve));
});

test('generation admission rejects missing digests and acquisition failures', async () => {
  let missingDigestReleases = 0;
  const missingDigest = acquireAgentSocketGenerationLeaseV2(() => ({
    digest: '   ',
    kind: 'generation',
    release: async () => {
      missingDigestReleases += 1;
    },
  }));
  assert.deepEqual(missingDigest, {
    status: 'rejected',
    reasonCode: 'desktop_agent_socket_generation_digest_missing',
  });
  assert.equal(missingDigestReleases, 1);

  assert.deepEqual(
    acquireAgentSocketGenerationLeaseV2(() => {
      throw new Error('generation unavailable');
    }),
    {
      status: 'rejected',
      reasonCode: 'desktop_agent_socket_generation_lease_acquire_failed',
    },
  );
  assert.deepEqual(
    acquireAgentSocketGenerationLeaseV2(() => undefined),
    {
      status: 'rejected',
      reasonCode: 'desktop_agent_socket_generation_lease_invalid',
    },
  );
  assert.deepEqual(
    acquireAgentSocketGenerationLeaseV2(() => ({
      digest: 42,
      kind: 'generation',
      release: async () => undefined,
    })),
    {
      status: 'rejected',
      reasonCode: 'desktop_agent_socket_generation_lease_invalid',
    },
  );

  await new Promise((resolve) => setImmediate(resolve));
});

test('generation replacement releases the old socket boundary before the next', async () => {
  const releases = new Map();
  const acquire = (digest) =>
    acquireAgentSocketGenerationLeaseV2(() => ({
      digest,
      kind: 'generation',
      release: () => {
        releases.set(digest, (releases.get(digest) ?? 0) + 1);
        if (digest === 'sha256:old-generation') {
          throw new Error('expected synchronous release failure');
        }
        return Promise.resolve();
      },
    }));

  const oldGeneration = acquire('sha256:old-generation');
  assert.equal(oldGeneration.status, 'accepted');
  assert.equal(oldGeneration.constructSocket(() => 'old-socket'), 'old-socket');
  await oldGeneration.release();

  const nextGeneration = acquire('sha256:next-generation');
  assert.equal(nextGeneration.status, 'accepted');
  assert.equal(nextGeneration.constructSocket(() => 'next-socket'), 'next-socket');
  await Promise.all([nextGeneration.release(), nextGeneration.release()]);

  assert.deepEqual(
    Object.fromEntries(releases),
    {
      'sha256:old-generation': 1,
      'sha256:next-generation': 1,
    },
  );
  await new Promise((resolve) => setImmediate(resolve));
});
