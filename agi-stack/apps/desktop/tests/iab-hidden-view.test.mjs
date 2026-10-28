import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { createRequire } from 'node:module';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
test('real Electron hidden IAB renders, preserves trusted input and rejects covered targets without showing a window', {
  skip: process.env.AGISTACK_IAB_HIDDEN_ELECTRON_TESTS !== '1', timeout: 45_000,
}, () => {
  const profile = mkdtempSync(join(tmpdir(), 'agistack-iab-hidden-test-'));
  const env = { ...process.env, AGISTACK_IAB_TEST_PROFILE: profile };
  delete env.ELECTRON_RUN_AS_NODE;
  try {
    const result = spawnSync(require('electron'), [fileURLToPath(new URL('./fixtures/iab-hidden-view.cjs', import.meta.url))], {
      env, encoding: 'utf8', timeout: 40_000, maxBuffer: 1024 * 1024,
    });
    assert.equal(result.error, undefined, result.error?.message);
    assert.equal(result.status, 0, result.stderr + result.stdout);
    const report = JSON.parse(result.stdout.trim().split('\n').at(-1));
    assert.equal(report.results.length, 6);
    assert.deepEqual(report.results.map(result => [result.viewport.width, result.viewport.height]), [
      [1200, 800], [1200, 800], [850, 620], [640, 480], [850, 620], [1200, 800],
    ]);
    console.log(JSON.stringify(report));
  } finally {
    rmSync(profile, { recursive: true, force: true });
  }
});
