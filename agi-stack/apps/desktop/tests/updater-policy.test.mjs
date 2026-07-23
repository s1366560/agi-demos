import assert from 'node:assert/strict';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';

import updatePolicyModule from '/tmp/agistack-desktop-test-dist/electron/main/updatePolicy.js';

const { releaseUpdateFeedIsEnabled } = updatePolicyModule;

function withResources(run) {
  const resourcesPath = mkdtempSync(join(tmpdir(), 'agistack-update-policy-'));
  try {
    run(resourcesPath);
  } finally {
    rmSync(resourcesPath, { recursive: true, force: true });
  }
}

test('development and local packaged builds cannot enable production updates', () => {
  withResources((resourcesPath) => {
    assert.equal(releaseUpdateFeedIsEnabled(false, resourcesPath), false);
    assert.equal(releaseUpdateFeedIsEnabled(true, resourcesPath), false);
  });
});

test('only the structured production GitHub feed enables updates', () => {
  withResources((resourcesPath) => {
    const configPath = join(resourcesPath, 'app-update.yml');
    writeFileSync(
      configPath,
      ['provider: github', 'owner: s1366560', 'repo: agi-demos', ''].join('\n'),
    );
    assert.equal(releaseUpdateFeedIsEnabled(true, resourcesPath), true);

    writeFileSync(
      configPath,
      ['provider: generic', 'url: https://updates.invalid', ''].join('\n'),
    );
    assert.equal(releaseUpdateFeedIsEnabled(true, resourcesPath), false);

    writeFileSync(
      configPath,
      ['provider: github', 'owner: attacker', 'repo: agi-demos', ''].join('\n'),
    );
    assert.equal(releaseUpdateFeedIsEnabled(true, resourcesPath), false);

    writeFileSync(configPath, 'provider: [invalid\n');
    assert.equal(releaseUpdateFeedIsEnabled(true, resourcesPath), false);
  });
});
