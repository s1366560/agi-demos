import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdtempSync, readFileSync, realpathSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { test } from 'node:test';

const enabled = process.env.AGISTACK_MCP_APP_GUEST_ELECTRON_TESTS === '1';
test(
  'real Electron SDK guest isolation, callback, safety controls and retained instance',
  {
    skip: !enabled,
    timeout: 45_000,
  },
  async () => {
    const require = createRequire(import.meta.url);
    const output = mkdtempSync(join(tmpdir(), 'memstack-mcp-guest-sdk-'));
    const environment = { ...process.env, AGISTACK_MCP_APP_GUEST_TEST_OUTPUT: output };
    delete environment.ELECTRON_RUN_AS_NODE;
    const executable = realpathSync(require('electron'));
    const fixture = fileURLToPath(
      new URL('./fixtures/mcp-app-guest-electron.cjs', import.meta.url),
    );
    const child = spawn(executable, [fixture], {
      env: environment,
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    let log = '';
    child.stdout.on('data', (chunk) => {
      log += chunk;
    });
    child.stderr.on('data', (chunk) => {
      log += chunk;
    });
    const timer = setTimeout(() => child.kill('SIGTERM'), 35_000);
    const status = await new Promise((resolve, reject) => {
      child.once('error', reject);
      child.once('exit', resolve);
    }).finally(() => clearTimeout(timer));
    writeFileSync(join(output, 'electron.log'), log);
    const report = JSON.parse(readFileSync(join(output, 'report.json'), 'utf8'));
    assert.equal(status, 0, `Electron fixture failed; report: ${join(output, 'report.json')}`);
    assert.equal(report.ok, true);
    assert.ok(report.checks.length >= 12);
    assert.ok(report.checks.every((check) => check.result));
    console.log(`Guest SDK fixture artifacts: ${output}`);
  },
);
