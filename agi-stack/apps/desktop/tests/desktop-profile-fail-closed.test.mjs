import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

test('compat does not set the full desktop flag and a missing flag stays closed', () => {
  const profile = readFileSync(new URL('../scripts/legacyRendererProfile.ts', import.meta.url), 'utf8');
  const vite = readFileSync(new URL('../electron.vite.config.ts', import.meta.url), 'utf8');
  const makefile = readFileSync(new URL('../../../Makefile', import.meta.url), 'utf8');
  assert.match(profile, /fullDesktopProfile = profile === 'full'/);
  assert.match(profile, /legacyBusinessProfile = false/);
  assert.doesNotMatch(vite, /@business/);
  assert.match(vite, /__AGISTACK_FULL_DESKTOP__: JSON\.stringify\(fullDesktopProfile\)/);
  assert.doesNotMatch(makefile, /AGISTACK_DESKTOP_PROFILE \?= .*\bthin\b/);
  const result = spawnSync(
    process.execPath,
    [
      '-e',
      `const profile = require('/tmp/agistack-desktop-test-dist/electron/desktopProfile.js');
       if (profile.fullDesktop !== false) process.exit(2);
       if (profile.sidecarRuntimeProfile !== 'package-host') process.exit(3);`,
    ],
    { encoding: 'utf8' },
  );
  assert.equal(result.status, 0, result.stderr || result.stdout);
});
