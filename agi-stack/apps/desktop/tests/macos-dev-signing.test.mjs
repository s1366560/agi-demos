import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { chmodSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';

const macosConfigUrl = new URL('../src-tauri/tauri.macos.conf.json', import.meta.url);
const cargoRunnerUrl = new URL('../../../scripts/run-macos-tauri-cargo.sh', import.meta.url);

test('direct Tauri development uses the stable macOS signing runner', () => {
  const config = JSON.parse(readFileSync(macosConfigUrl, 'utf8'));

  assert.deepEqual(config.build?.runner, {
    cmd: '../../../scripts/run-macos-tauri-cargo.sh',
  });
});

test('the Tauri cargo wrapper preserves arguments and injects both macOS runners', {
  skip: process.platform === 'win32',
}, () => {
  const fixtureRoot = mkdtempSync(join(tmpdir(), 'agistack-tauri-cargo-runner-'));
  const fakeCargo = join(fixtureRoot, 'cargo');
  writeFileSync(
    fakeCargo,
    `#!/bin/sh
printf '%s\n' "$CARGO_TARGET_AARCH64_APPLE_DARWIN_RUNNER"
printf '%s\n' "$CARGO_TARGET_X86_64_APPLE_DARWIN_RUNNER"
printf '%s\n' "$*"
`,
  );
  chmodSync(fakeCargo, 0o755);

  try {
    const result = spawnSync('/bin/sh', [cargoRunnerUrl.pathname, 'run', '--features', 'fixture'], {
      encoding: 'utf8',
      env: {
        ...process.env,
        CARGO: fakeCargo,
      },
    });

    assert.equal(result.status, 0, result.stderr);
    const [armRunner, intelRunner, argumentsLine] = result.stdout.trim().split('\n');
    assert.match(armRunner, /scripts\/run-macos-dev-signed\.sh$/);
    assert.equal(intelRunner, armRunner);
    assert.equal(argumentsLine, 'run --features fixture');
  } finally {
    rmSync(fixtureRoot, { recursive: true, force: true });
  }
});
