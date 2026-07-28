import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

const testsDirectory = dirname(fileURLToPath(import.meta.url));
const desktopRoot = dirname(testsDirectory);
const tscEntrypoint = join(desktopRoot, 'node_modules', 'typescript', 'bin', 'tsc');
const compile = spawnSync(
  process.execPath,
  [tscEntrypoint, '-p', 'tsconfig.native-bridge-test.json'],
  {
    cwd: desktopRoot,
    encoding: 'utf8',
  },
);
assert.equal(compile.status, 0, compile.stderr || compile.stdout);

const require = createRequire(import.meta.url);
const {
  DisplayCaptureAuthorizationGate,
  MAX_CAPTURE_DIMENSION,
  MAX_CAPTURE_PNG_BYTES,
  assertPngCaptureWithinLimit,
  captureThumbnailSize,
  selectExactDisplaySource,
} = require(
  '/tmp/agistack-desktop-native-bridge-test-dist/electron/main/displayCapturePolicy.js',
);
const {
  SIGNED_WEB_CONTROL_PLANE_ORIGIN,
  WEB_CONTROL_PLANE_DESTINATIONS,
  buildWebControlPlaneUrl,
  resolveWebControlPlaneConfiguration,
} = require(
  '/tmp/agistack-desktop-native-bridge-test-dist/electron/main/webControlPlanePolicy.js',
);

const mainSource = readFileSync(new URL('../electron/main/index.ts', import.meta.url), 'utf8');
const preloadSource = readFileSync(
  new URL('../electron/preload/index.ts', import.meta.url),
  'utf8',
);
const rendererTypes = readFileSync(new URL('../src/vite-env.d.ts', import.meta.url), 'utf8');

const pngSignature = Uint8Array.from([137, 80, 78, 71, 13, 10, 26, 10]);

test('display capture selects one exact display source and otherwise fails closed', () => {
  const expected = { displayId: '42', value: 'application-display' };
  assert.equal(
    selectExactDisplaySource(
      [
        { displayId: '7', value: 'other-display' },
        expected,
      ],
      '42',
    ),
    expected,
  );
  assert.throws(
    () => selectExactDisplaySource([{ displayId: '7', value: 'other-display' }], '42'),
    /exact display capture source is unavailable/u,
  );
  assert.throws(
    () =>
      selectExactDisplaySource(
        [
          expected,
          { displayId: '42', value: 'ambiguous-display' },
        ],
        '42',
      ),
    /exact display capture source is unavailable/u,
  );
});

test('display capture accepts only non-empty PNG data within the fixed byte limit', () => {
  assert.equal(assertPngCaptureWithinLimit(pngSignature), pngSignature.byteLength);
  assert.throws(
    () => assertPngCaptureWithinLimit(new Uint8Array()),
    /capture is not a PNG/u,
  );
  assert.throws(
    () => assertPngCaptureWithinLimit(Uint8Array.from([1, 2, 3, 4, 5, 6, 7, 8])),
    /capture is not a PNG/u,
  );
  assert.throws(
    () => assertPngCaptureWithinLimit(pngSignature, pngSignature.byteLength - 1),
    /PNG exceeds/u,
  );
  assert.equal(MAX_CAPTURE_PNG_BYTES, 8 * 1024 * 1024);
  assert.equal(MAX_CAPTURE_DIMENSION, 2560);
  assert.deepEqual(captureThumbnailSize(3840, 2160, 2), {
    width: 2560,
    height: 1440,
  });
  assert.deepEqual(captureThumbnailSize(1440, 900, 2), {
    width: 2560,
    height: 1600,
  });
});

test('display capture authorization is main-owned, explicit, expiring, and single-use', async () => {
  const gate = new DisplayCaptureAuthorizationGate({ grantLifetimeMs: 5_000 });
  let now = 1_000;

  await assert.rejects(
    gate.authorize(async () => false, () => now),
    /display capture was not authorized/u,
  );

  const granted = await gate.authorize(async () => true, () => now);
  assert.doesNotThrow(() => gate.consume(granted, () => now + 1));
  assert.throws(
    () => gate.consume(granted, () => now + 2),
    /authorization is invalid or already used/u,
  );

  const expired = await gate.authorize(async () => true, () => now);
  now += 5_001;
  assert.throws(
    () => gate.consume(expired, () => now),
    /authorization has expired/u,
  );
});

test('web control-plane URLs come from a static destination enum and main-owned origin', () => {
  assert.deepEqual(WEB_CONTROL_PLANE_DESTINATIONS, [
    'tenant-overview',
    'agent-workspace',
    'project-overview',
    'project-memories',
    'project-graph',
    'project-settings',
  ]);
  assert.equal(Object.isFrozen(WEB_CONTROL_PLANE_DESTINATIONS), true);
  assert.equal(
    buildWebControlPlaneUrl('https://app.memstack.example', {
      destination: 'project-graph',
      tenantId: 'tenant/a',
      projectId: 'project?b',
    }),
    'https://app.memstack.example/tenant/tenant%2Fa/project/project%3Fb/graph',
  );
  assert.equal(
    buildWebControlPlaneUrl('http://127.0.0.1:3000', {
      destination: 'agent-workspace',
      tenantId: 'tenant-1',
      projectId: 'project-1',
    }),
    'http://127.0.0.1:3000/tenant/tenant-1/agent-workspace?projectId=project-1',
  );
  assert.equal(
    buildWebControlPlaneUrl('https://app.memstack.example', {
      destination: 'project-overview',
      tenantId: 'tenant-1',
      projectId: 'project-1',
      url: 'https://attacker.example/private',
    }),
    'https://app.memstack.example/tenant/tenant-1/project/project-1',
  );
  assert.throws(
    () =>
      buildWebControlPlaneUrl('https://app.memstack.example', {
        destination: 'arbitrary-url',
        tenantId: 'tenant-1',
        projectId: 'project-1',
        url: 'https://attacker.example',
      }),
    /destination is not supported/u,
  );
  assert.throws(
    () =>
      buildWebControlPlaneUrl('http://remote.example', {
        destination: 'project-overview',
        tenantId: 'tenant-1',
        projectId: 'project-1',
      }),
    /origin must use HTTPS or loopback HTTP/u,
  );
  assert.throws(
    () =>
      buildWebControlPlaneUrl('https://user:secret@app.memstack.example/path?token=secret', {
        destination: 'project-overview',
        tenantId: 'tenant-1',
        projectId: 'project-1',
      }),
    /origin must not contain/u,
  );
});

test('web control-plane capability is sourced from signed build config and fails closed', () => {
  assert.equal(SIGNED_WEB_CONTROL_PLANE_ORIGIN, 'https://app.memstack.ai');

  const packaged = resolveWebControlPlaneConfiguration({
    developmentOrigin: 'https://attacker.example',
    isPackaged: true,
    signedOrigin: SIGNED_WEB_CONTROL_PLANE_ORIGIN,
  });
  assert.deepEqual(packaged, {
    capability: {
      availability: 'available',
      contractVersion: 1,
      reasonCode: 'web_control_plane_configured',
      source: 'signed_build',
    },
    origin: 'https://app.memstack.ai',
  });

  assert.deepEqual(
    resolveWebControlPlaneConfiguration({
      isPackaged: true,
      signedOrigin: null,
    }),
    {
      capability: {
        availability: 'unavailable',
        contractVersion: 1,
        reasonCode: 'web_control_plane_origin_unconfigured',
        source: 'none',
      },
      origin: null,
    },
  );

  assert.deepEqual(
    resolveWebControlPlaneConfiguration({
      developmentOrigin: 'http://127.0.0.1:3000',
      isPackaged: false,
      signedOrigin: null,
    }),
    {
      capability: {
        availability: 'available',
        contractVersion: 1,
        reasonCode: 'web_control_plane_configured',
        source: 'development_override',
      },
      origin: 'http://127.0.0.1:3000',
    },
  );

  assert.deepEqual(
    resolveWebControlPlaneConfiguration({
      developmentOrigin: 'http://remote.example',
      isPackaged: false,
      signedOrigin: null,
    }),
    {
      capability: {
        availability: 'unavailable',
        contractVersion: 1,
        reasonCode: 'web_control_plane_origin_invalid',
        source: 'none',
      },
      origin: null,
    },
  );
});

test('Electron exposes named safe bridge methods without a renderer URL parameter', () => {
  assert.match(mainSource, /async function captureCurrentDisplay\(\)/u);
  assert.match(mainSource, /dialog\.showMessageBox\(captureWindow/u);
  assert.match(mainSource, /captureAuthorizationGate\.authorize/u);
  assert.match(mainSource, /captureAuthorizationGate\.consume/u);
  assert.match(mainSource, /screen\.getDisplayMatching\(captureWindow\.getBounds\(\)\)/u);
  assert.match(mainSource, /selectExactDisplaySource/u);
  assert.match(mainSource, /assertPngCaptureWithinLimit/u);
  assert.match(mainSource, /resolveWebControlPlaneConfiguration/u);
  assert.match(mainSource, /get_desktop_capabilities/u);
  assert.match(mainSource, /async function openWebControlPlane/u);
  assert.match(mainSource, /buildWebControlPlaneUrl/u);

  assert.match(preloadSource, /captureCurrentDisplay/u);
  assert.match(preloadSource, /getCapabilities/u);
  assert.match(preloadSource, /openWebControlPlane/u);
  assert.match(preloadSource, /destination,\s*tenantId,\s*projectId/u);
  assert.doesNotMatch(preloadSource, /openWebControlPlane[\s\S]{0,240}\burl\b/u);

  assert.match(rendererTypes, /type WebControlPlaneDestination/u);
  assert.match(rendererTypes, /captureCurrentDisplay/u);
  assert.match(rendererTypes, /getCapabilities/u);
  assert.match(rendererTypes, /openWebControlPlane/u);
});
