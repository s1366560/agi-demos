import assert from 'node:assert/strict';
import {
  chmodSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createRequire } from 'node:module';
import test from 'node:test';

const require = createRequire(import.meta.url);
const dist = process.env.AGISTACK_ACCEPTANCE_TEST_DIST ?? '/tmp/agistack-desktop-test-dist';
const { qualifyLocalKnowledgeAcceptance } = require(`${dist}/electron/main/qaProfilePolicy.js`);
const { SidecarSupervisor } = require(`${dist}/electron/main/sidecarSupervisor.js`);
function fixture(t) {
  const profile = mkdtempSync(join(tmpdir(), 'agistack-desktop-qa-profile-'));
  const workspace = mkdtempSync(join(tmpdir(), 'agistack-desktop-qa-workspace-'));
  t.after(() => {
    rmSync(profile, { recursive: true, force: true });
    rmSync(workspace, { recursive: true, force: true });
  });
  return {
    isPackaged: false,
    qaProfileDirectory: profile,
    dataDirectory: join(profile, 'runtime'),
    workspaceRoot: workspace,
  };
}

test('ordinary desktop initialization has no acceptance qualification or filesystem changes', () => {
  assert.equal(
    qualifyLocalKnowledgeAcceptance({
      isPackaged: false,
      qaProfileDirectory: null,
      dataDirectory: '/normal/data',
      workspaceRoot: '/normal/workspace',
    }),
    undefined,
  );
});

test('host derives only the fixed purpose from independent private QA directories', (t) => {
  const input = fixture(t);
  const qualification = qualifyLocalKnowledgeAcceptance(input);
  assert.deepEqual(qualification, {
    purpose: 'local-knowledge-acceptance-v1',
    userDataDirectory: input.qaProfileDirectory,
  });
  assert.equal(Object.isFrozen(qualification), true);
  assert.equal(
    readFileSync(new URL('../electron/main/index.ts', import.meta.url), 'utf8').includes(
      'qualifyLocalKnowledgeAcceptance({',
    ),
    true,
  );
});

test('packaged, normal workspace, identical root and foreign data directory are refused', (t) => {
  const input = fixture(t);
  for (const change of [
    { isPackaged: true },
    { workspaceRoot: '/Users/example/project' },
    { workspaceRoot: input.qaProfileDirectory },
    { dataDirectory: join(input.workspaceRoot, 'runtime') },
  ]) {
    assert.throws(() => qualifyLocalKnowledgeAcceptance({ ...input, ...change }));
  }
});

test('runtime and workspace symlinks cannot acquire host qualification', (t) => {
  const input = fixture(t);
  symlinkSync(input.workspaceRoot, input.dataDirectory, 'dir');
  assert.throws(() => qualifyLocalKnowledgeAcceptance(input));
  rmSync(input.dataDirectory);
  const target = join(input.qaProfileDirectory, 'outside-workspace');
  mkdirSync(target);
  rmSync(input.workspaceRoot, { recursive: true });
  symlinkSync(target, input.workspaceRoot, 'dir');
  assert.throws(() => qualifyLocalKnowledgeAcceptance(input));
});

test('qualified purpose crosses the authenticated initialization pipe without an alternate profile or actions', async (t) => {
  const input = fixture(t);
  const qualification = qualifyLocalKnowledgeAcceptance(input);
  const marker = join(input.qaProfileDirectory, 'observed-initialize.json');
  const binaryPath = join(input.qaProfileDirectory, 'sidecar.cjs');
  writeFileSync(
    binaryPath,
    `#!/usr/bin/env node
const { createHmac } = require('node:crypto');
const { writeFileSync } = require('node:fs');
const input = require('node:readline').createInterface({ input: process.stdin });
input.once('line', line => {
  const init = JSON.parse(line);
  writeFileSync(${JSON.stringify(marker)}, JSON.stringify({ acceptance:init.localKnowledgeAcceptance, data:init.dataDirectory, workspace:init.workspaceRoot, legacy:init.legacyDataDirectories }));
  const apiBaseUrl = 'http://127.0.0.1:41123';
  const apiToken = 'test-local-acceptance-token';
  const proof = createHmac('sha256',Buffer.from(init.secret,'base64url')).update([init.protocolVersion,init.nonce,process.pid,apiBaseUrl,apiToken].join('\\n')).digest('base64url');
  process.stdout.write(JSON.stringify({type:'ready',protocolVersion:init.protocolVersion,nonce:init.nonce,pid:process.pid,apiBaseUrl,apiToken,proof})+'\\n');
});
`,
  );
  chmodSync(binaryPath, 0o700);
  const supervisor = new SidecarSupervisor({
    binaryPath,
    workspaceCoreBinaryPath: binaryPath,
    dataDirectory: input.dataDirectory,
    workspaceRoot: input.workspaceRoot,
    legacyDataDirectories: [],
    localKnowledgeAcceptance: qualification,
  });
  try {
    await supervisor.start();
    assert.deepEqual(JSON.parse(readFileSync(marker, 'utf8')), {
      acceptance: qualification,
      data: input.dataDirectory,
      workspace: input.workspaceRoot,
      legacy: [],
    });
  } finally {
    await supervisor.stop();
  }
});
