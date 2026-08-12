import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const mainSource = readFileSync(new URL('../electron/main/index.ts', import.meta.url), 'utf8');
const preloadSource = readFileSync(new URL('../electron/preload/index.ts', import.meta.url), 'utf8');
const typesSource = readFileSync(new URL('../src/vite-env.d.ts', import.meta.url), 'utf8');
const viteConfigSource = readFileSync(new URL('../electron.vite.config.ts', import.meta.url), 'utf8');
const recoveryProcessSource = readFileSync(
  new URL('../electron/main/updateRecoveryProcess.ts', import.meta.url),
  'utf8',
);

test('updates use dedicated allowlisted IPC and never widen the generic desktop command bridge', () => {
  for (const channel of [
    'agistack:update-state',
    'agistack:update-check',
    'agistack:update-restart-to-apply',
    'agistack:update-state-changed',
  ]) {
    assert.equal(mainSource.includes(channel), true);
    assert.equal(preloadSource.includes(channel), true);
  }
  assert.doesNotMatch(preloadSource, /allowedCommands[\s\S]*update_/u);
  assert.match(preloadSource, /updates:\s*updateBridge/u);
  assert.match(preloadSource, /restartToApply:\s*restartToApplyUpdate/u);
  assert.match(preloadSource, /subscribe:\s*subscribeToUpdateState/u);
  assert.doesNotMatch(preloadSource, /install:\s*installUpdate/u);
  assert.match(typesSource, /updates\?:\s*Readonly/u);
  assert.match(typesSource, /restartToApply\(\)/u);
  assert.match(typesSource, /subscribe\(listener/u);
});

test('Electron main owns the update journal, lifecycle controller, and renderer subscription', () => {
  assert.match(mainSource, /createUpdateRecoveryJournal/u);
  assert.match(mainSource, /app\.getPath\('userData'\)[\s\S]*recovery-journal\.v2\.json/u);
  assert.match(mainSource, /ipcMain\.handle\(UPDATE_STATE_CHANNEL/u);
  assert.match(mainSource, /automaticUpdates\.subscribe/u);
  assert.match(mainSource, /automaticUpdates\.confirmHealthy\(\)/u);
  assert.match(mainSource, /automaticUpdates\?\.stop\(\)/u);
});

test('the recovery helper uses the copied signed sidecar without nonce argv exposure', () => {
  assert.doesNotMatch(viteConfigSource, /update-recovery-helper/u);
  assert.match(recoveryProcessSource, /\['--update-recovery-prepare'\]/u);
  assert.match(recoveryProcessSource, /\['--update-recovery-helper'\]/u);
  assert.match(recoveryProcessSource, /AGISTACK_UPDATE_RECOVERY_REQUEST/u);
  assert.doesNotMatch(recoveryProcessSource, /spawn\([^\n]+,\s*\[[^\]]*nonce/u);
  assert.match(mainSource, /recoveryHelperBinaryPath:\s*sidecarBinaryPath\(\)/u);
});
